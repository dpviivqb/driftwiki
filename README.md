# driftwiki

**driftwiki** = [deepwiki-skill](https://github.com/natsu1211/deepwiki-skill) (wiki generation) + **a drift detection layer** (new). A Claude Code agent skill that both **generates** wiki docs **and detects** drift between docs and code.

> Forked from deepwiki-skill (MIT), adding Phase 7 `drift-check` to its 6-phase generation workflow.

## Why (deepwiki-skill's gaps + our patch)

deepwiki-skill generates good docs, but two hard gaps:

- It **only generates, never detects drift** — docs go stale after generation, it doesn't notice.
- Its **citations can hallucinate** — even its own self-generated docs have line numbers that don't match the code.

driftwiki adds the detection layer:

- **Endpoint drift** — `ast`-extract FastAPI endpoints vs doc endpoint tables; report missing / extra (each with `file:line`).
- **Citation line check** — validate GitHub `blob#L<line>` refs in docs; file exists + line in range (catches hallucination).

## Install

```
/plugin marketplace add https://github.com/dpviivqb/driftwiki
/plugin install driftwiki@driftwiki-marketplace
```

## Usage

```
/driftwiki:gen                     # generate wiki (inherited from deepwiki-skill)
/driftwiki:check                   # detect doc/code drift (driftwiki's addition)
/driftwiki:check --output docs/drift-report.md
/driftwiki:check --docs README.md,docs/api.md
```

`/driftwiki:check` runs `scripts/drift_check.py`, auto-discovering FastAPI endpoints and all `.md` docs in the repo, then emits a drift report (Markdown + JSON).

## Real example (on this repo)

```
Repo: .../job_outreach  Code endpoints: 18 (prefix /api/v1)
REPOWIKI.md: Doc endpoints 15 | Missing 3 | Extra 0
  Missing (in code, not in doc):
    GET /extension-auth/diagnostics  <- routers/extension_auth.py:56
    GET /orders/list                 <- routers/orders.py:33
    POST /auth/access-token          <- routers/auth.py:77
docs/wiki/07_backend-api.md: Doc 18 | Missing 0 | Extra 0
Citation check: 25 citations, 0 anomalous
```

Catches 3 endpoints that the repowiki-generated REPOWIKI missed. This is what deepwiki-skill / repowiki do not do.

## Relationship to deepwiki-skill

- Forked from [natsu1211/deepwiki-skill](https://github.com/natsu1211/deepwiki-skill) (MIT).
- Keeps all its generation power (repo-scan -> toc-design -> doc-write -> validate-docs -> doc-summary -> incremental-sync).
- Adds Phase 7 `drift-check` + `scripts/drift_check.py` + `commands/check.md`.
- Thanks to upstream.

## Constraints

- **Generation** (inherited from deepwiki-skill) may hang in headless mode in some environments (a subagent-spawn issue). **Drift detection** (added) is a pure-Python stdlib script, stable.
- MVP detection: FastAPI endpoint drift + citation line check. Future: more frameworks (Express / Django / Spring) and detection types (model fields, pricing).

## License

MIT (inherited from deepwiki-skill).
