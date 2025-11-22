"""OpenConfig full YANG ETL (initial lightweight implementation).

Parses .yang files under a provided repository directory (env OPENCONFIG_DIR or --path)
and indexes module + leaf definitions into the existing `openconfig-schema` index.

This is a regex-based fast extractor (not a full YANG parser). For production,
replace with a proper YANG parser (pyang) and include typedef, grouping, container paths.

Document format:
  {
    _index: "openconfig-schema",
    _id: "<module>:<leaf>",
    module: "openconfig-interfaces",
    leaf: "enabled",
    description: "Interface is enabled"
  }

Safety: deletes nothing, only adds documents; existing index must exist.
"""
from __future__ import annotations

import os
import re
import logging
from typing import Iterator, Dict, Any, List
from opensearchpy import OpenSearch, helpers

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

INDEX = "openconfig-schema"

LEAF_RE = re.compile(r"^\s*leaf\s+(?P<name>[a-zA-Z0-9_-]+)\s*{", re.MULTILINE)
MODULE_RE = re.compile(r"^\s*module\s+(?P<module>[a-zA-Z0-9_-]+)\s*{", re.MULTILINE)
DESCRIPTION_RE = re.compile(r"description\s+\"(?P<desc>.*?)\";", re.DOTALL)

def get_client() -> OpenSearch:
    url = os.getenv("OPENSEARCH_URL", "http://localhost:9200")
    return OpenSearch(hosts=[url], use_ssl=False, verify_certs=False)

def iter_yang_files(root: str) -> Iterator[str]:
    for dirpath, _, filenames in os.walk(root):
        for fn in filenames:
            if fn.endswith(".yang"):
                yield os.path.join(dirpath, fn)

def extract(file_path: str) -> List[Dict[str, Any]]:
    try:
        text = open(file_path, "r", encoding="utf-8", errors="ignore").read()
    except Exception as e:
        logger.warning(f"Skip {file_path}: {e}")
        return []
    module_match = MODULE_RE.search(text)
    if not module_match:
        return []
    module = module_match.group("module")
    leaves = LEAF_RE.findall(text)
    docs: List[Dict[str, Any]] = []
    for leaf in leaves:
        # Try to find closest description (naive: first description occurrence after leaf name)
        # For simplicity we use global description if single description present.
        desc_match = DESCRIPTION_RE.search(text)
        desc = desc_match.group("desc") if desc_match else ""
        docs.append({
            "_index": INDEX,
            "_id": f"{module}:{leaf}",
            "module": module,
            "leaf": leaf,
            "description": desc[:500],
            "source_file": os.path.basename(file_path),
        })
    return docs

def generate(root: str) -> Iterator[Dict[str, Any]]:
    count = 0
    for fp in iter_yang_files(root):
        docs = extract(fp)
        for d in docs:
            yield d
            count += 1
    logger.info(f"Prepared {count} YANG leaf documents")

def main() -> None:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--path", help="Path to OpenConfig YANG root (defaults OPENCONFIG_DIR)")
    args = parser.parse_args()
    yang_root = args.path or os.getenv("OPENCONFIG_DIR")
    if not yang_root or not os.path.isdir(yang_root):
        logger.error("Provide --path or set OPENCONFIG_DIR to a valid directory containing .yang files")
        return
    client = get_client()
    if not client.indices.exists(index=INDEX):
        logger.info(f"Creating index {INDEX}")
        client.indices.create(index=INDEX, body={
            "mappings": {
                "properties": {
                    "module": {"type": "keyword"},
                    "leaf": {"type": "keyword"},
                    "description": {"type": "text"},
                    "source_file": {"type": "keyword"},
                }
            }
        })
    logger.info(f"Indexing YANG leaves from {yang_root}")
    helpers.bulk(client, generate(yang_root))
    logger.info("YANG ETL completed")

if __name__ == "__main__":
    main()