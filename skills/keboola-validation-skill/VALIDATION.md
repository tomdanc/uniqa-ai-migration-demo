# VALIDATION — run a migrated flow against real pod data

How to validate a migrated dbt flow on the pod (reconcile new vs legacy + Elementary report).
The data isn't on the pod — it lives on **S3**, reached through two attached DuckDB DBs:
`kbc_in` (IN / raw inputs) and `kbc_stg` (STG / where `out.*` results land). Tables are **domain
views** (renamed by domain, not by Keboola project). Running example below: **00 Project A**.

> Work **one step at a time**. Do a step, check the result, then move on.

---

## Step 0 — Make sure the flow's project is ON the pod (upload it if missing)

Everything below assumes the migrated dbt project is on the pod. Normally it arrives via
`git clone` / `git pull` after the MR merges — but when validating a branch that **isn't pushed/merged
yet** (or the pod was reset / the flow was never cloned), the project won't be there. **Always check
first, and if it's missing, upload it from local** — don't assume it's present.

> **No local `*_TEST` / `TESTING_FOLDER` dirs — the validation "test folder" is on the POD.** The pod dir
> `/app/kbc/<flow>_val` (uploaded below) IS your scratch project for validation; local file prep goes in the
> session scratchpad. **NEVER** create `TESTING_FOLDER/`, `DBT_TEST/`, or `<flow>_TEST/` in the repo working
> tree — those are the deprecated old harness: git-ignored, ship nothing, and just clutter the tree / `git
> status`. `rm -rf` any you find. See [[clean-branch-no-test-folders]] and [[dbt-project-root-level-structure]].

`$KEBOOLA_POD` / `$KEBOOLA_POD_NAMESPACE` below come from the repo-root `.env-skill` (currently `pod-01`
/ `bi`; `source .env-skill` first, or substitute the values directly).

Check (a single `dbt_project.yml` anywhere under `/app` is enough):
```bash
kubectl exec "$KEBOOLA_POD" -n "$KEBOOLA_POD_NAMESPACE" -- /bin/bash -c 'find /app -maxdepth 5 -name dbt_project.yml 2>/dev/null' 2>&1
```

If nothing comes back, **upload the project** — run from your **LOCAL repo root** (NOT inside the pod).
This `tar | kubectl exec` ships only what dbt needs and skips junk (`.git`, `target`, `dbt_packages`,
the `*.duckdb`, `input/`, `retrieve_keboola/`, `HELP/`, …):
```bash
kubectl exec "$KEBOOLA_POD" -n "$KEBOOLA_POD_NAMESPACE" -- mkdir -p /app/kbc/<flow_slug>
COPYFILE_DISABLE=1 tar czf - \
  dbt_project.yml profiles.yml packages.yml package-lock.yml \
  models macros tests analyses seeds snapshots \
  | kubectl exec "$KEBOOLA_POD" -n "$KEBOOLA_POD_NAMESPACE" -i -- tar xzf - -C /app/kbc/<flow_slug>
```
(`-i` must come **after** `"$KEBOOLA_POD" -n "$KEBOOLA_POD_NAMESPACE"` so it matches the
`kubectl exec <pod> -n <namespace>:*` allow rule.) Then `cd /app/kbc/<flow_slug>` and run every dbt
command below with **`--profiles-dir .`**
so dbt uses the uploaded `profiles.yml`. This uploaded copy is the **pod scratch copy** — repoint its
`sources.yml` and adjust its model SQL freely for the pod (the repoints in Step 3 below are
**pod-validation-only**; never commit these pod edits back to the branch).

---

## Step 0b — BEFORE the first build: size the pod, set `memory_limit`, pre-build Elementary

Three things that cost 75 wasted minutes on an earlier flow (2026-08-12) because they were only discovered **after**
the first OOM. `Operating rule #0` ("on any error check FIXES first") fires too late here — the first
error arrives ~20 minutes into a build. Do all three **before** `dbt run`.

**1 — Read the pod's REAL size, then tune the `dev` target to it. Never assume either.**
`memory.max` differs per pod, changes over time, and since 2026-08-27 is a **launch parameter** — so
measuring is the only way to know what you actually got:
```bash
kubectl exec "$KEBOOLA_POD" -n "$KEBOOLA_POD_NAMESPACE" -- /bin/bash -c \
  'nproc; awk "{print \$1/1073741824\" GiB\"}" /sys/fs/cgroup/memory.max; grep oom_kill /sys/fs/cgroup/memory.events'
```
Note the `oom_kill` counter **now** — it is cumulative, so only a *change* proves your run was killed.
The committed `profiles.yml` comment (*"stay under the pod's 8 GiB cgroup"*) and its `threads: 1` /
`memory_limit: '5GB'` defaults are a **floor**, not the value to run with.

**Capacities, the auto-start sizes, the data owner's 16 Gi / 32 Gi conditions and the reason POD RAM and
`memory_limit` are two separate decisions all live in ONE place: `FIXES.md` → Problem T-UUUU addendum
(`DEC-061`).** This step does not restate them — that duplication is what left four locations quoting
sizes that were stale within two weeks.

Then set `threads` on the **`dev`** target of the pod's scratch `profiles.yml` from the measured `nproc`
— and drop it to `1` for a heavy build regardless, because each DuckDB thread holds its own
hash-aggregate arena and `threads` multiplies peak memory. Leave `prod` exactly as committed.

⚠ **This edit NEVER reaches git (`DEC-060`).** `profiles.yml` is pod-local scratch config: it is
re-applied after every pod restart, so a modified `profiles.yml` in `git status` is the expected steady
state, not something to tidy up by committing. `keboola-pushing-skill`'s targeted `git add` already
excludes it.

**2 — Pick `memory_limit` from the UPSTREAM flows, and remember LOWER is often the fix.**
> Since rule #0d (Step 1c), upstream models are read from S3 (gate2-passed) or from staged copies and are
> not built here, so this only concerns an upstream the operator chose to **build on the pod** (Step 1c,
> 2.3). Otherwise size for this flow's own models only.

⚠ **`+tag:<flow>` drags in every upstream model, and the memory recipe you need may be filed under
*their* flow, not yours.** On an earlier flow the three heaviest nodes (`model_x`, `model_y`,
`model_z`) belong to **an upstream flow**, whose `DATA_ACCESS.md` entry already said *"memory_limit **4GB**
(NOT 6 — Problem T-EE), elementary models built first"*. So:
```bash
dbt ls -s +tag:<flow_slug> --resource-type model --profiles-dir .   # which flows do we actually build?
```
then grep `HELP/DATA_ACCESS.md` + `HELP/FIXES.md` for **each** of those flows before choosing a value.
**`memory_limit` is NOT monotonic — raising it can break a model that a lower value builds** (FIXES
Problem T-EE, re-proven on that flow: `model_w` built fine at 3GB and OOM'd at 9GB, while `model_x`
OOM'd at 3GB and built at 9GB). DuckDB picks a memory-hungrier plan at a higher budget and then has
nowhere to spill. Absent a flow-specific note, start at **4–5GB with `threads=1`** (`DEC-008`: that `1` is the heavy-build floor, not a blanket rule — raise it off `nproc` once the flow is known to be light) and treat a bigger
number as a last resort, not the first knob.

**3 — Pre-build Elementary on every fresh scratch** (FIXES Problem **T-FF**) — otherwise its
artifacts-upload breaks the first build of any *changed* model with `Parser Error … order by metadata_hash`:
```bash
dbt run --select elementary --profiles-dir .        # 32 models, ~1 min
```

**Also: give the scratch its OWN DuckDB file.** The committed `profiles.yml` points at the shared
`/app/kbc/keboola_migration.db`; a pod can host several validations at once and DuckDB is single-writer.
Follow the convention the other scratches use — `path: /app/kbc/<flow_slug>_val/<short>.db`.

**And build incrementally across restarts.** A `table` model rebuilds from scratch on every `dbt run`, so a
re-run after a mid-way failure repeats hours of work. Exclude what already stands:
`dbt run -s tag:<flow> --exclude <already_built_models> --vars '{upstream_from_s3: false, publish_to_s3: false}'`
(`+tag` only on the pod-build path the operator chose, rule #0d step 2.3; verify with `duckdb <scratch>.db -c "select
table_name, estimated_size from duckdb_tables() where schema_name='main'"`).

---

## Step 1 — Find where the flow's data lives on S3

**First check `HELP/DATA_ACCESS.md`** (repo root, local-only) — its per-flow data map may already list this
flow's input + legacy-output tables and the exact attach command. If so, just re-confirm they still exist
(the S3 DBs refresh daily) and skip to the repoint. Otherwise, discover it:

We need the data, and we need to get to it. First list every loaded domain/schema in the two
attached DBs, so we can spot the one belonging to our project:

```bash
duckdb -c "ATTACH 's3://dwh-in/dwh-conf/keboola_in.db' AS kbc_in (READ_ONLY); ATTACH 's3://dwh-in/dwh-conf/keboola_stg.db' AS kbc_stg (READ_ONLY); SELECT database_name, schema_name, count(*) cnt FROM duckdb_views() WHERE database_name IN ('kbc_in','kbc_stg') GROUP BY 1,2 ORDER BY 1,2;"
```

This prints each `database.schema` and its view count. **Guess** your project's schema from the
names — e.g. `00 Project A` → `in_src_a` / `stg_src_a` (`src_a` = Project A). It's only a guess here; we
confirm it against the actual tables in Step 2.

---

## Step 1b — Check DATA RECENCY (ALWAYS report the age of the data)

Before/while validating, **check how fresh the source data is and ALWAYS tell the operator the age.**
Find the flow's date-ish column and get its range:

```bash
kubectl exec "$KEBOOLA_POD" -n "$KEBOOLA_POD_NAMESPACE" -- duckdb -c "ATTACH 's3://dwh-in/dwh-conf/keboola_in.db' AS kbc_in (READ_ONLY); SELECT min(\"<date_col>\") AS oldest, max(\"<date_col>\") AS newest, date_diff('day', max(\"<date_col>\"), current_date) AS days_old FROM kbc_in.<schema>.<table>;" 2>&1
```

Report the **newest-data age** in the validation summary, in plain terms:
- **recent** — newest is today / this week → live flow, normal.
- **months old** — newest a few months back → may be slowing/seasonal; note it.
- **≥ 1 YEAR old → FLAG PROMINENTLY.** The flow is **stale / frozen** (very likely `ONE_TIME` / no longer updated — cross-check the data owner's CSV note). On stale data:
  - a thorough recon adds little value (nothing new will ever arrive), so don't over-invest;
  - **report the staleness to the reviewer (the senior reviewer) / in the Productive comment** — they need to know the flow is dead before merging (it changes priority / whether it's even worth shipping);
  - still record the age with exact dates (e.g. *"newest 2024-06-30 = 2.0 years old"*).

Never silently validate stale data as if it were live — the operator + reviewer must know the data's age every time.

> **Two different clocks — don't confuse them:**
> - **DATA age** = the newest *business date* in the rows (`max("<date_col>")` on the pod). This is what "stale" means for validation.
> - **JOB recency** = when the Keboola transformation last *ran* (Keboola UI → "Last Use", e.g. "Job Succeeded 3 months ago"). This is execution time, NOT data age.
>
> They can diverge: a scheduled job can keep running on a **frozen upstream** — the job "succeeded 3 months ago" while the data still ends 2 years back, because each run just re-processes the same stale dataset. So a recent job run does **not** mean fresh data. Report the DATA age from the rows; mention the JOB recency if the operator has it. (Also: our pod copy is an S3 snapshot — if in doubt whether the *data* is truly frozen vs the copy being old, check `max(date)` in the live Keboola table.)
> Example (an earlier dashboard flow, 2026-07-01): data 2016-12-17 → **2024-06-30 = 2.0 yr old**; Keboola job last ran ~3 months ago; last schedule run also ~3 months ago → **retired/frozen flow**.

---

## Step 1c — Gate 1 upstream: CHECK → CHOOSE (S3 gate2-passed / STAGED same-run / ask) → VALIDATE (rule #0d, `DEC-082`)

Gate 1 validates **only the logic of this flow**. Upstream tables are inputs, chosen to be as close as
possible to what the legacy flow read. **Nothing is published here** (`DEC-083`): every command below runs
`publish_to_s3: false`.

**1 — Check (always show this table to the operator):**
```bash
cp <local repo>/claude/skills/keboola-validation-skill/upstream_s3_check.py /app/kbc/<flow_slug>_val/   # or ship it in the Step 0 tar
dbt parse --profiles-dir .
python upstream_s3_check.py --flow <flow_slug>
```
```
┌────────────────┬─────────────────────┬─────────────┬────────┬─────────────────────────────────────────────────────┬───────────┬─────────────────────┐
│ upstream model │ project/flow        │ needed by   │ status │ s3 path                                             │ rows      │ last modified       │
├────────────────┼─────────────────────┼─────────────┼────────┼─────────────────────────────────────────────────────┼───────────┼─────────────────────┤
│ upstream_x     │ 00_Project_C/Flow_D │ tmp_model_y │ ON_S3  │ s3://dwh-out/00_Project_C/Flow_D/upstream_x.parquet │ 1,563,887 │ 2026-09-18 13:38:08 │
└────────────────┴─────────────────────┴─────────────┴────────┴─────────────────────────────────────────────────────┴───────────┴─────────────────────┘
```

**2 — Choose each upstream, in this order:**
1. **`ON_S3` AND its producer's Productive task carries the tag `gate2-passed`** → a local view over its
   parquet: `create or replace view main.<model> as select * from read_parquet('<s3 path from the table>');`.
   `ON_S3` without the tag is NOT usable — a file proves nothing.
2. **Otherwise the STAGED legacy copy from the same legacy run as the recon references:**
```bash
# (a) WHICH RUN: Keboola lastImportDate of every staged table AND every recon reference (Storage API, per-project token)
curl -s -H "X-StorageApi-Token: $TOKEN" https://connection.keboola.example/v2/storage/tables/<bucket.table> | jq .lastImportDate
#     producers that finished BEFORE the flow's own night run = the state that run consumed → same run
#     a producer that ran AFTER it → one run newer: allowed, disclose it
# (b) REFRESH IN ONE WINDOW (after that night's run, before the next): the operator sets one GRP on the DWH-KBC rows of
#     the references AND the staged copies (never a row whose GRP starts INIT_SAP — disclose that one as another run's copy);
#     worker_run_grp <GRP> on the pod (HELP/RECON_REFRESH.md §2b); revert GRP to its previous value
# (c) STAND IN, pod-only — a local view the ref() falls back to:
duckdb <scratch>.db -c "attach 's3://dwh-in/dwh-conf/keboola_stg.db' as kbc_stg (read_only);
  create or replace view main.<producer_model> as select * from kbc_stg.<stg_schema>.<TABLE>;"
#     a split stage reassembled: "(select * from read_parquet('…_OUT.parquet') union select * from read_parquet('…_IN.parquet'))"
#     producer NOBODY has migrated: also a pod-only models/<…>/<producer_model>.sql (select * from kbc_stg.…) so ref() parses
```
   - Measure a split stage's coverage of the keys the model reads before trusting it.
   - Cast to the producer model's contract where types differ (FIXES T-AAAAB / CH).
   - Never pulled back to the branch.
3. **No staged copy (no DWH-KBC row) → STOP, ask the operator:** a data-owner ask for the stage, or building
   the upstream on the pod (`publish_to_s3: false`). Do not choose yourself.

Record each row as `S3 (gate2-passed)`, `STAGED (<table>, Keboola run <date time>)` or `BUILT ON POD`.

**3 — Validate:**
```bash
dbt build -s tag:<flow_slug> --profiles-dir . --vars '{upstream_from_s3: false, publish_to_s3: false}'
```
`upstream_from_s3: false` is deliberate: under `true`, `macros/ref.sql` would read every `ON_S3` file
directly — including producers that have not passed Gate 2 — and bypass the local views. Every upstream
must resolve to its local view; anything else means a view is missing.

**4 — Disclose:** the list goes into the WARN summary and the STATE table (`Upstream` row), and the pushing
skill carries it into the MR and Productive and adds the `gate2-pending` tag.
