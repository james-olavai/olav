# olav-ent — OLAV Enterprise Features

Enterprise extension package for [OLAV](https://github.com/admin/olav-core), providing audit dataset export pipelines, Tink AEAD encryption, and one-time token control for secure training-data workflows.

## Requirements

- OLAV core (`olav >= 0.11`)
- Python >= 3.11

## Installation

```bash
pip install olav-ent
# or, from monorepo:
uv pip install -e olav-ent
```

## Features

### 1. Audit Dataset Export (`olav log export`)

Convert OLAV audit logs into training datasets for fine-tuning LLMs.

| Sub-command | Format | Description |
|---|---|---|
| `log export sft` | SFT Chat JSONL | System/user/assistant chat turns with 3-layer redaction |
| `log export trajectory` | Tool Trajectory | Tool-call step sequences with dedup fingerprinting |
| `log export atif` | ATIF Trace | Annotated trace spans for RLHF/HITL workflows |
| `log export grant-local-train` | One-time token | JWT-gated single-use access for local training runs |

**Quality gate**: All export commands support `--min-score` to filter by computed quality score (completeness, query specificity, analysis value, tool consistency).

**Encryption**: All export commands support `--encrypt` / `--no-encrypt` / `--key-ref` for Tink AEAD encryption of output files.

```bash
# Export SFT training data with quality filter and encryption
olav log export sft --output runs.jsonl --min-score 0.7 --encrypt

# Export tool trajectories
olav log export trajectory --output trajectories.jsonl

# Export ATIF spans
olav log export atif --output traces.jsonl

# Issue a one-time training token (TTL: 60 minutes)
olav log export grant-local-train --export-id run-001 --ttl-minutes 60
```

### 2. Dataset Encryption (`olav.enterprise.dataset_encryption`)

Tink AEAD encryption for exported dataset files.

```python
from olav.enterprise import DatasetEncryptor, EncryptionMode, build_associated_data

encryptor = DatasetEncryptor(key_ref="path/to/keyset.json")
associated_data = build_associated_data(export_id="run-001", user_id="alice")
encryptor.encrypt_file("output.jsonl", associated_data=associated_data)
```

Supports KMS key references: `gcp-kms://`, `aws-kms://`, `hcvault://`, `azure-kms://`.

### 3. One-Time Token Control (`OneTimeTokenManager`)

JWT-signed, DuckDB-backed single-use tokens for controlled access to exported training data.

```python
from olav.enterprise import OneTimeTokenManager

mgr = OneTimeTokenManager(db_path=".olav/databases/audit.duckdb")
token = mgr.issue(export_id="run-001", ttl_minutes=60)
# Token can only be consumed once — subsequent uses are rejected
mgr.consume(token)
```

### 4. Quality Scoring

Programmatic quality assessment for audit runs before export.

```python
from olav.enterprise import compute_quality_score, quality_gate, register_llm_scorer

# Rule-based scoring (no LLM required)
score = compute_quality_score(run)

# Register optional LLM scorer for semantic quality evaluation
register_llm_scorer(my_llm_scorer_fn)

# Filter a list of runs by quality threshold
passed, stats = quality_gate(runs, min_score=0.6)
```

## Package Structure

```
olav-ent/
  pyproject.toml       # Package metadata + entry points
  README.md            # This file

# Source (in monorepo: src/olav/enterprise/)
olav/enterprise/
  __init__.py          # Public API surface (20+ exports)
  cli_bridge.py        # CLI dispatch bridge (olav.enterprise_commands entry point)
  audit_dataset_export.py   # SFT / Trajectory / ATIF export pipelines
  dataset_encryption.py     # Tink AEAD + OneTimeTokenManager
```

## Entry Points

`olav-ent` registers an `olav.enterprise_commands` entry point so OLAV core can discover enterprise CLI commands without a hard import dependency:

```toml
[project.entry-points."olav.enterprise_commands"]
log_export = "olav.enterprise.cli_bridge:dispatch_log_export"
```

## Design Documents

- `dev_docs/ent_features.md` — Full enterprise feature roadmap
- `dev_docs/audit_dataset_export.md` — Audit-to-training export design (Phases 1–4)
- `dev_docs/encrypted_dataset_control.md` — Tink AEAD encryption design (Phases 1–4)

## License

MIT
