# Drift Check

Detect documentation drift (API endpoint drift + citation line check). This is driftwiki's differentiator over the original deepwiki-skill.

## Usage

```
/driftwiki:check                                # check current repo (auto-discover FastAPI + docs)
/driftwiki:check --output docs/drift-report.md  # specify report output
/driftwiki:check --docs README.md,docs/api.md   # specify docs (default: auto-discover all .md)
```

## Arguments

| Arg | Required | Default | Description |
|-----|----------|---------|-------------|
| `--output <path>` | no | stdout | report output path (Markdown); JSON is also printed to stdout |
| `--docs <paths>` | no | auto-discover | comma-separated doc paths; default scans all `.md` in repo (excludes .venv/node_modules etc.) |

## Workflow

Parse args, run `scripts/drift_check.py --repo-path <repo> [--output ...] [--docs ...]`, produce a drift report.

### What it detects

1. **Endpoint drift**: `ast`-extract FastAPI endpoints (`@router.method(path)` + `include_router` prefixes + `config.py`'s `api_v1_prefix`), reconcile against doc endpoint tables, report:
   - **Missing** (in code, not in doc): each with `file:line`
   - **Extra** (in doc, not in code)
2. **Citation line check**: parse GitHub `blob/<hash>/<path>#L<line>` refs in docs; verify file exists + line in range (catches "citation hallucination").

### Output

- Markdown report (human): drift items + citation anomalies
- stdout JSON (machine): structured drift data

> Path normalization: strip `api_v1_prefix`, `{xxx}` -> `{}`, for cross-doc comparison. Doc endpoint tables are supported in two layouts: `| path | METHOD |` or `| METHOD | path |`.
