#!/usr/bin/env python3
"""drift_check — detect documentation drift. Generic, stdlib-only.

Usage:
  python3 drift_check.py --repo-path /path/to/repo [--output report.md] [--docs a.md,b.md]

Detects two kinds of drift:
  1. API endpoint drift: ast-extract FastAPI endpoints vs doc endpoint tables
  2. Citation line check: validate GitHub blob#L<line> refs in docs
     (file exists + line in range)
"""
import ast
import json
import re
import sys
import argparse
from pathlib import Path

METHODS = {"get", "post", "put", "delete", "patch"}
EXCLUDE_DIRS = {".venv", "venv", "node_modules", ".git", "site-packages",
                "__pycache__", "dist", "build", ".next", ".cache", "drift-skill"}


def is_excluded(p):
    return any(part in EXCLUDE_DIRS for part in p.parts)


def norm_path(p, prefix=""):
    p = p.strip().strip("`")
    if prefix and p.startswith(prefix):
        p = p[len(prefix):]
    return re.sub(r"\{[^}]+\}", "{}", p)


def find_fastapi_apps(repo):
    """Return [(main_path, app_dir)] for each FastAPI main.py found."""
    apps = []
    for main in repo.rglob("main.py"):
        if is_excluded(main):
            continue
        try:
            text = main.read_text(errors="ignore")
        except OSError:
            continue
        if "FastAPI(" in text:
            apps.append((main, main.parent))
    return apps


def read_prefix(app_dir):
    cfg = app_dir / "config.py"
    if not cfg.exists():
        for c in app_dir.rglob("config.py"):
            if not is_excluded(c):
                cfg = c
                break
    if cfg.exists():
        m = re.search(r'api_v1_prefix[^=]*=\s*"([^"]+)"', cfg.read_text(errors="ignore"))
        if m:
            return m.group(1)
    return "/api/v1"


def read_router_prefixes(main_path):
    main = main_path.read_text(errors="ignore")
    rp = {}
    for m in re.finditer(r"include_router\(\s*(\w+)\.router,\s*prefix=([^,\)]+)", main):
        sm = re.search(r'"(/[\w-]+)"', m.group(2))
        rp[m.group(1)] = sm.group(1) if sm else ""
    return rp


def find_routers_dir(app_dir):
    for cand in (app_dir / "routers", app_dir / "app" / "routers"):
        if cand.is_dir():
            return cand
    return app_dir / "routers"


def extract_code_endpoints(repo):
    endpoints = []
    for main, app_dir in find_fastapi_apps(repo):
        prefix = read_prefix(app_dir)
        rp_map = read_router_prefixes(main)
        routers_dir = find_routers_dir(app_dir)
        if routers_dir.is_dir():
            for rf in sorted(routers_dir.glob("*.py")):
                if rf.name == "__init__.py":
                    continue
                rp = rp_map.get(rf.stem, "")
                try:
                    tree = ast.parse(rf.read_text(errors="ignore"))
                except SyntaxError:
                    continue
                for node in ast.walk(tree):
                    if (isinstance(node, ast.Call)
                            and isinstance(node.func, ast.Attribute)
                            and node.func.attr in METHODS
                            and isinstance(node.func.value, ast.Name)
                            and node.func.value.id in ("router", "api")
                            and node.args and isinstance(node.args[0], ast.Constant)):
                        ep = node.args[0].value
                        full = prefix + rp + ep
                        endpoints.append({
                            "method": node.func.attr.upper(), "path": full,
                            "norm": norm_path(full, prefix),
                            "file": str(rf.relative_to(repo)), "line": node.lineno,
                        })
        try:
            for node in ast.walk(ast.parse(main.read_text(errors="ignore"))):
                if (isinstance(node, ast.Call)
                        and isinstance(node.func, ast.Attribute)
                        and node.func.attr in METHODS
                        and isinstance(node.func.value, ast.Name)
                        and node.func.value.id == "app"
                        and node.args and isinstance(node.args[0], ast.Constant)):
                    ep = node.args[0].value
                    endpoints.append({
                        "method": node.func.attr.upper(), "path": ep,
                        "norm": norm_path(ep, prefix),
                        "file": str(main.relative_to(repo)), "line": node.lineno,
                    })
        except SyntaxError:
            pass
    return endpoints


def discover_docs(repo, docs_arg=None):
    if docs_arg:
        return [Path(d) for d in docs_arg.split(",")]
    docs = []
    for md in repo.rglob("*.md"):
        if is_excluded(md):
            continue
        docs.append(md)
    return docs


def extract_doc_endpoints(text, prefix):
    found = {}
    for m in re.finditer(r"\|\s*`?([/\w{}.-]+)`?\s*\|\s*(GET|POST|PUT|DELETE|PATCH)\s*\|", text):
        if "/" in m.group(1):
            found[(m.group(2), norm_path(m.group(1), prefix))] = m.group(1)
    for m in re.finditer(r"\|\s*(GET|POST|PUT|DELETE|PATCH)\s*\|\s*`?([/\w{}.-]+)`?\s*\|", text):
        if "/" in m.group(2):
            found[(m.group(1), norm_path(m.group(2), prefix))] = m.group(2)
    return found


CITE_RE = re.compile(r"\]\(https?://[^)]*?/blob/[\w-]+/([^)#]+?)#L(\d+)(?:-L\d+)?\)")


def check_cites(text, md_rel, repo):
    out = []
    for m in CITE_RE.finditer(text):
        path, line = m.group(1), int(m.group(2))
        f = repo / path
        e = {"md": md_rel, "path": path, "line": line}
        if not f.exists():
            e["status"] = "missing_file"
        else:
            lines = f.read_text(errors="replace").splitlines()
            e["status"] = "ok" if 1 <= line <= len(lines) else "out_of_range"
            if e["status"] == "ok":
                e["content"] = lines[line - 1].strip()[:100]
        out.append(e)
    return out


def main():
    ap = argparse.ArgumentParser(description="Detect documentation drift")
    ap.add_argument("--repo-path", required=True)
    ap.add_argument("--output", help="report output path (default: stdout)")
    ap.add_argument("--docs", help="comma-separated doc paths (default: auto-discover all .md)")
    args = ap.parse_args()

    repo = Path(args.repo_path).resolve()
    code_eps = extract_code_endpoints(repo)
    apps = find_fastapi_apps(repo)
    prefix = read_prefix(apps[0][1]) if apps else "/api/v1"
    code_keys = {(e["method"], e["norm"]) for e in code_eps}
    by_key = {(e["method"], e["norm"]): e for e in code_eps}

    report = {"repo": str(repo), "code_endpoint_count": len(code_eps),
              "prefix": prefix, "docs": {}, "cite_check": []}
    md = ["# Drift Report", "",
          f"Repo: `{repo}`  Code endpoints: **{len(code_eps)}** (prefix `{prefix}`)", ""]

    for doc in discover_docs(repo, args.docs):
        if not doc.exists():
            continue
        text = doc.read_text(errors="ignore")
        try:
            rel = str(doc.relative_to(repo))
        except ValueError:
            rel = str(doc)
        doc_eps = extract_doc_endpoints(text, prefix)
        cites = check_cites(text, rel, repo)

        if not doc_eps:
            if cites:
                bad = [c for c in cites if c["status"] != "ok"]
                report["cite_check"].append({"doc": rel, "total": len(cites), "bad": bad})
                if bad:
                    md += [f"## {rel}", "",
                           f"**Citation check:** {len(cites)} citations, {len(bad)} anomalous", ""]
                    for c in bad:
                        md.append(f"- WARNING `{c['path']}:{c['line']}` {c['status']}")
                    md.append("")
            continue

        doc_keys = set(doc_eps)
        missing = code_keys - doc_keys
        extra = doc_keys - code_keys
        report["docs"][rel] = {
            "doc_count": len(doc_eps),
            "missing_in_doc": sorted([{"method": a, "path": b} for a, b in missing],
                                     key=lambda x: (x["method"], x["path"])),
            "extra_in_doc": sorted([{"method": a, "path": doc_eps[(a, b)]} for a, b in extra],
                                   key=lambda x: (x["method"], x["path"])),
        }
        md += [f"## {rel}", "",
               f"Doc endpoints **{len(doc_eps)}** | Code **{len(code_eps)}** | "
               f"Missing **{len(missing)}** | Extra **{len(extra)}**", ""]
        if missing:
            md.append("**Missing (in code, not in doc):**")
            for a, b in sorted(missing):
                src = by_key.get((a, b))
                loc = f"`{src['file']}:{src['line']}`" if src else "?"
                md.append(f"- `{a} {b}` <- {loc}")
            md.append("")
        if extra:
            md.append("**Extra (in doc, not in code):**")
            for a, b in sorted(extra):
                md.append(f"- `{a} {doc_eps[(a, b)]}`")
            md.append("")
        if cites:
            bad = [c for c in cites if c["status"] != "ok"]
            report["cite_check"].append({"doc": rel, "total": len(cites), "bad": bad})
            md += [f"**Citation check:** {len(cites)} citations, {len(bad)} anomalous", ""]
            for c in bad:
                md.append(f"- WARNING `{c['path']}:{c['line']}` {c['status']}")
            if bad:
                md.append("")

    out = "\n".join(md) + "\n"
    if args.output:
        Path(args.output).write_text(out)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        print(f"Report written: {args.output}", file=sys.stderr)
    else:
        print(out)


if __name__ == "__main__":
    main()
