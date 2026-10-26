#!/usr/bin/env python3
"""DEC-084 check: does the S3 publish hook sit on exactly this flow's OUTPUT models?

    python3 check_s3_publish.py models/<project_slug>/<flow_dir> --outputs <model>,<model>
    python3 check_s3_publish.py models/<project_slug>/<flow_dir>          # fallback, see below

Run from the dbt repo root. Read-only, no dbt needed — it reads the .sql/.yml files.

A model's ROLE comes from --outputs when given: the models whose tables are in the flow's
LIVE Storage output mapping (the list P1 / P3 already resolved). That is the authority.
Without --outputs it falls back to the yml, by the repo's own test rule (the senior reviewer, 2026-08-27):
an OUTPUT model carries data tests, an intermediate carries a bare column list. The
fallback misreads one legitimate case — an output with no ID/PK carries zero tests
(DEC-009 asks for none) — so pass --outputs whenever the list is known. With --outputs,
a model that has tests but is not listed is ⛔ (tests on an intermediate), and a listed
output with no tests is ⚠ (fine only with the yml's "no primary key" NOTE). So:

    OUTPUT        must carry copy_relation_to_s3() and must not be ephemeral
                  (an ephemeral model fires no post-hook — a silent no-op)
    INTERMEDIATE  must NOT carry it (it is not a Storage output; nothing reads it on S3)
    NO YML        no yml anywhere under the flow names it — fine without a hook (an
                  ephemeral helper), a STOP with one
    *_filtered    a filtered / windowed variant should NOT publish: no hook is ✅, a hook is
                  ⚠ (it lands a slice under the production name; the 8 versioned
                  models of one source project on qa do this, so it is reported, not failed)

The derived S3 path mirrors macros/copy_relation_to_s3.sql: the first two folder levels
under models/ plus the relation name (alias if set). A model passing s3_path= / s3_prefix=
shows as CUSTOM.

Exit 0 when no row is ⛔ (⚠ rows are reported, not failed), 1 otherwise. A ⛔ row is a STOP, never something to work
around: if an output legitimately has no tests (or an intermediate legitimately publishes),
that is the operator's call, recorded in the MR.
"""
import argparse
import os
import re
import sys

import yaml

HOOK = re.compile(r"copy_relation_to_s3\s*\(([^)]*)\)")
MAT = re.compile(r"materialized\s*=\s*['\"](\w+)['\"]")
ALIAS = re.compile(r"\balias\s*=\s*['\"]([^'\"]+)['\"]")
TEST_KEYS = ("data_tests", "tests")


def has_tests(node):
    """True if any data_tests/tests list under this yml node is non-empty."""
    if isinstance(node, dict):
        for k, v in node.items():
            if k in TEST_KEYS and v:
                return True
            if has_tests(v):
                return True
    elif isinstance(node, list):
        return any(has_tests(x) for x in node)
    return False


def index_ymls(top):
    """file stem -> (model yml node, alias from yml or None), across every .yml under `top`.

    A versioned model is defined in several files (`defined_in:`, else `<name>_v<v>`), all
    under one yml node; its alias comes from the version's config, not the .sql."""
    idx = {}
    for root, _, files in os.walk(top):
        for fn in files:
            if not fn.endswith((".yml", ".yaml")):
                continue
            with open(os.path.join(root, fn), encoding="utf-8") as f:
                doc = yaml.safe_load(f) or {}
            for m in doc.get("models") or []:
                name = m.get("name")
                if not name:
                    continue
                idx.setdefault(name, (m, (m.get("config") or {}).get("alias")))
                for v in m.get("versions") or []:
                    stem = v.get("defined_in") or f"{name}_v{v.get('v')}"
                    idx[stem] = (m, (v.get("config") or {}).get("alias") or name)
    return idx


def role_of(stem, idx, outputs):
    """(role, alias, has_tests). Role from --outputs when given, else from the yml's tests."""
    if stem not in idx:
        return ("OUTPUT" if outputs and stem in outputs else "NO YML"), None, False
    node, alias = idx[stem]
    tested = has_tests(node)
    if outputs is not None:
        return ("OUTPUT" if stem in outputs else "INTERMEDIATE"), alias, tested
    return ("OUTPUT" if tested else "INTERMEDIATE"), alias, tested


def s3_path(sql_path, relation, hook_args):
    if hook_args.strip():
        return "CUSTOM (" + hook_args.strip()[:40] + ")"
    parts = os.path.normpath(sql_path).split(os.sep)
    if "models" not in parts:
        return "?"
    under = parts[parts.index("models") + 1:-1]
    if len(under) < 2:
        return "⛔ fewer than 2 folder levels — the macro refuses this"
    return f"s3://dwh-out/{under[0]}/{under[1]}/{relation}.parquet"


def main():
    ap = argparse.ArgumentParser(description="DEC-084: S3 publish hook on exactly the flow's outputs")
    ap.add_argument("flow_dir", help="models/<project_slug>/<flow_dir>")
    ap.add_argument("--outputs", help="comma-separated model names of the live Storage outputs")
    a = ap.parse_args()
    if not os.path.isdir(a.flow_dir):
        sys.exit(f"not a directory: {a.flow_dir}")
    outputs = {o.strip().lower() for o in a.outputs.split(",") if o.strip()} if a.outputs else None
    rows, bad = [], 0
    idx = index_ymls(a.flow_dir)
    for root, _, files in os.walk(a.flow_dir):
        for fn in sorted(files):
            if not fn.endswith(".sql"):
                continue
            path = os.path.join(root, fn)
            name = fn[:-4]
            with open(path, encoding="utf-8") as f:
                sql = f.read()
            hook = HOOK.search(sql)
            mat = (MAT.search(sql) or [None, "view (default)"])[1]
            alias = ALIAS.search(sql)
            role, yml_alias, tested = role_of(name.lower(), idx, outputs)
            relation = alias[1] if alias else (yml_alias or name)
            filtered = "filtered" in name and "nonfiltered" not in name
            if filtered and hook:
                verdict = "⚠ filtered variant publishes to the production path"
            elif filtered:
                verdict = "✅"  # a slice must not publish; its production twin carries the hook
            elif role == "OUTPUT" and not hook:
                verdict = "⛔ output without the publish hook"
            elif role == "OUTPUT" and mat == "ephemeral":
                verdict = "⛔ ephemeral output never publishes"
            elif role == "INTERMEDIATE" and hook:
                verdict = "⛔ intermediate carries the publish hook"
            elif outputs is not None and role == "INTERMEDIATE" and tested:
                verdict = "⛔ not a listed output, but carries data tests"
            elif outputs is not None and role == "OUTPUT" and not tested:
                verdict = "⚠ output without data tests — needs the no-PK NOTE"
            elif role == "NO YML" and hook:
                verdict = "⛔ publishes, but no yml says it is an output"
            elif role == "NO YML":
                verdict = "⚠ no yml — not an output, no hook"
            else:
                verdict = "✅"
            bad += verdict.startswith("⛔")
            dest = s3_path(path, relation, hook[1]) if hook else "—"
            rows.append((name, role, mat, "yes" if hook else "no", dest, verdict))

    if not rows:
        sys.exit(f"no .sql under {a.flow_dir}")
    if outputs is not None:
        missing = outputs - {r[0].lower() for r in rows}
        for m in sorted(missing):
            rows.append((m, "OUTPUT", "—", "no", "—", "⛔ listed output has no model"))
            bad += 1
    head = ("Model", "Role", "Materialized", "Hook", "S3 path", "Verdict")
    w = [max(len(str(r[i])) for r in rows + [head]) for i in range(len(head))]
    line = lambda l, m, r: l + m.join("─" * (x + 2) for x in w) + r
    fmt = lambda r: "│" + "│".join(f" {str(c):<{w[i]}} " for i, c in enumerate(r)) + "│"
    print(line("┌", "┬", "┐")); print(fmt(head)); print(line("├", "┼", "┤"))
    for r in rows:
        print(fmt(r))
    print(line("└", "┴", "┘"))
    outs = sum(r[1] == "OUTPUT" for r in rows)
    print(f"{outs} output(s), {len(rows) - outs} other model(s), {bad} problem(s)")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
