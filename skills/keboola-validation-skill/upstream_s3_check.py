#!/usr/bin/env python3
"""Pre-validation check: is every upstream table the flow needs already on S3?

Reads target/manifest.json (run `dbt parse --profiles-dir .` first), walks the flow's cross-flow
ref() chain and prints one table row per upstream model:

  ON_S3        published parquet exists in dwh-out -> read from S3 under upstream_from_s3, no build
  RUN+PUBLISH  wired with copy_relation_to_s3() but the parquet is missing
  LOCAL        another flow's intermediate (no publish hook) -> Gate 1: a local view over its staged copy,
               or a pod build only if the operator chooses it (rule #0d step 2.3)
  CUSTOM_PATH  publish hook with a non-literal path -> ref.sql can't resolve it, treat as LOCAL

Path derivation mirrors macros/ref.sql + macros/copy_relation_to_s3.sql exactly. The walk stops at
an ON_S3 model (its own parents are not needed); it continues through RUN+PUBLISH / LOCAL models,
because building those needs their parents too.

Usage (pod scratch dir):
  python upstream_s3_check.py --flow <flow_tag> [--manifest target/manifest.json] [--no-s3]
Exit code 0 = every row ON_S3 (go straight to validation), 1 = something must be run first,
2 = --no-s3 (existence not checked).
Docs: docs/VALIDATION_UPSTREAM_FROM_S3.md, docs/S3_EXPORT_TEMP.md.
"""
import argparse
import json
import re
import sys

LIT = re.compile(r"(s3_path|s3_prefix|s3_bucket)\s*=\s*['\"]([^'\"]+)['\"]")
NONLIT = re.compile(r"(s3_path|s3_prefix|s3_bucket)\s*=\s*[^'\"\s]")


def dirs(node):
    return node["original_file_path"].replace("\\", "/").split("/")[1:-1]


def s3_path(node, bucket_var):
    """Return (path, None) or (None, reason) — same precedence as ref.sql."""
    hooks = node["config"].get("post-hook") or node["config"].get("post_hook") or []
    sql = next((h["sql"] if isinstance(h, dict) else str(h) for h in hooks
                if "copy_relation_to_s3" in (h["sql"] if isinstance(h, dict) else str(h))), None)
    if sql is None:
        return None, "no_hook"
    if NONLIT.search(sql):
        return None, "custom"
    args = dict(LIT.findall(sql))
    if args.get("s3_path"):
        return args["s3_path"], None
    if args.get("s3_prefix"):
        return args["s3_prefix"].rstrip("/") + "/" + node["alias"] + ".parquet", None
    d = dirs(node)
    if len(d) < 2:
        return None, "custom"
    bucket = bucket_var or args.get("s3_bucket", "s3://dwh-out")
    return "/".join([bucket.rstrip("/"), d[0], d[1], node["alias"] + ".parquet"]), None


def s3_stat(con, path):
    """(rows, last_modified) or None when the object does not exist."""
    parent = path.rsplit("/", 1)[0]
    hit = con.execute(f"select count(*) from glob('{parent}/*') where file = ?", [path]).fetchone()[0]
    if not hit:
        return None
    rows = con.execute(f"select count(*) from read_parquet('{path}')").fetchone()[0]
    mod = con.execute(f"select last_modified from read_blob('{path}')").fetchone()[0]
    return rows, mod


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--flow", required=True, help="flow tag (the flow's folder name, e.g. Flow_A)")
    ap.add_argument("--manifest", default="target/manifest.json")
    ap.add_argument("--s3-bucket", default=None, help="same as --vars s3_bucket, if the run uses one")
    ap.add_argument("--no-s3", action="store_true", help="skip the S3 lookups (classification only)")
    a = ap.parse_args()

    nodes = json.load(open(a.manifest))["nodes"]
    models = {k: v for k, v in nodes.items() if v["resource_type"] == "model" and v["config"].get("enabled", True)}
    own = {k for k, v in models.items() if a.flow in v.get("tags", [])}
    if not own:
        sys.exit(f"no enabled model tagged '{a.flow}' in {a.manifest} — run `dbt parse` / check the tag")
    own_flow = {tuple(dirs(models[k])[:2]) for k in own}

    con = None
    if not a.no_s3:
        import duckdb
        con = duckdb.connect()

    rows, seen = [], set()
    todo = [(p, models[k]["name"]) for k in own for p in models[k]["depends_on"]["nodes"]]
    while todo:
        uid, child = todo.pop()
        if uid in seen or uid not in models or uid in own:
            continue
        seen.add(uid)
        n = models[uid]
        if tuple(dirs(n)[:2]) in own_flow:          # same flow folder -> always local, like ref.sql
            continue
        path, why = s3_path(n, a.s3_bucket)
        stat = s3_stat(con, path) if path and con else None
        if path and con is None:
            status = "?(no-s3)"
        elif path and stat:
            status = "ON_S3"
        elif path:
            status = "RUN+PUBLISH"
        else:
            status = "CUSTOM_PATH" if why == "custom" else "LOCAL"
        rows.append((n["name"], "/".join(dirs(n)[:2]), child, status, path or "-",
                     f"{stat[0]:,}" if stat else "-", str(stat[1])[:19] if stat else "-"))
        if status != "ON_S3":
            todo += [(p, n["name"]) for p in n["depends_on"]["nodes"]]

    hdr = ("upstream model", "project/flow", "needed by", "status", "s3 path", "rows", "last modified")
    rows.sort(key=lambda r: (r[3] != "RUN+PUBLISH", r[3] != "LOCAL", r[1], r[0]))
    w = [max(len(str(x)) for x in col) for col in zip(hdr, *rows)] if rows else [len(h) for h in hdr]
    line = lambda r: "│ " + " │ ".join(str(x).ljust(w[i]) for i, x in enumerate(r)) + " │"
    print("┌─" + "─┬─".join("─" * x for x in w) + "─┐")
    print(line(hdr))
    print("├─" + "─┼─".join("─" * x for x in w) + "─┤")
    for r in rows:
        print(line(r))
    print("└─" + "─┴─".join("─" * x for x in w) + "─┘")
    if not rows:
        print(f"'{a.flow}' has no cross-flow upstream model — nothing to check.")

    missing = [r[0] for r in rows if r[3] == "RUN+PUBLISH"]
    local = [r[0] for r in rows if r[3] in ("LOCAL", "CUSTOM_PATH")]
    # Gate 1 (DEC-082/083): nothing is run or published here. Every upstream becomes a local view —
    # over its dwh-out parquet only if its producer's Productive task is tagged gate2-passed, else over
    # its same-run staged copy; with no staged copy, ask the operator (rule #0d step 2).
    print("\nGate 1: for EVERY row create a local view — dwh-out parquet if the producer is gate2-passed,"
          " else the same-run staged copy (rule #0d step 2). ON_S3 alone proves nothing (DEC-083).")
    unknown = any(r[3] == "?(no-s3)" for r in rows)
    sys.exit(1 if missing or local else 2 if unknown else 0)


if __name__ == "__main__":
    main()
