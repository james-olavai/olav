#!/usr/bin/env python3
"""
list_automations — Browse the automation library at .olav/automations/.

Returns scripts grouped by category with description and metadata.
Call this before generating a new script to check if one already exists.
"""
import json
import sys
from datetime import datetime
from pathlib import Path


def _find_project_root() -> Path:
    p = Path(__file__).resolve().parent
    while p != p.parent:
        if (p / "pyproject.toml").exists():
            return p
        p = p.parent
    return Path.cwd()


PROJECT_ROOT = _find_project_root()


def list_automations(category: str | None = None) -> dict:
    base = PROJECT_ROOT / ".olav" / "automations"
    if not base.exists():
        return {"status": "empty", "total": 0, "categories": {}}

    results: dict = {}
    for cat_dir in sorted(base.iterdir()):
        if not cat_dir.is_dir():
            continue
        if category and cat_dir.name != category:
            continue
        scripts = []
        for f in sorted(cat_dir.iterdir()):
            if f.suffix in (".py", ".sh", ".yaml", ".yml") and f.is_file():
                stat = f.stat()
                try:
                    lines = f.read_text(encoding="utf-8").splitlines()
                    desc = next(
                        (
                            ln.strip().strip('"""').strip("'''").strip("#").strip()
                            for ln in lines[1:10]
                            if ln.strip() and not ln.strip().startswith("#!")
                        ),
                        "",
                    )
                except Exception:
                    desc = ""
                scripts.append({
                    "name": f.name,
                    "path": str(f.relative_to(PROJECT_ROOT)),
                    "size_bytes": stat.st_size,
                    "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                    "description": desc[:120],
                })
        if scripts:
            results[cat_dir.name] = scripts

    total = sum(len(v) for v in results.values())
    return {"status": "ok", "total": total, "categories": results}


if __name__ == "__main__":
    args = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
    print(json.dumps(list_automations(**args), default=str))
