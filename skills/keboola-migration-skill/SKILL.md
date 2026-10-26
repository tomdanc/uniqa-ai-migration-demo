---
name: keboola-migration-skill
description: >-
  **P3 of the migration chain (HELP/CHAIN.md) — it does NOT run first.** Entry is P2 PASS for migration: keboola-status-skill (P0) has confirmed nobody else holds the flow, keboola-scope-skill (P1) has returned MIGRATE plus a type of source for every input, and keboola-readiness-skill (P2) has emitted its availability table with no row blocking migration. If the operator just says "migrate flow X" and those have not run, DO NOT START HERE — say so and run P0 first; the whole point of the phase order is that this skill never guesses the scope verdict or the input list. Migrate one Keboola flow (or one transformation within it) into a dbt+DuckDB project for the client's ecosystem. Creates a GitLab branch named after the operator-supplied Productive task, runs the Python downloader to pull the flow's raw legacy SQL from the right Keboola project by reading the LIVE flow (orchestrator task list — no manifest), maps dependencies into sources.yml, converts Snowflake-dialect SQL to dbt+DuckDB (CTEs, ref(), source(), TRY_CAST), generates the dbt model YAML (quote: true on every column, `view` materialization by default, no descriptions; data_tests go on OUTPUT models only — those in the flow's Storage output mapping — with unique+not_null on ID/PK columns and not_null on foreign-key `*_id` columns, while every intermediate DAG node gets a bare column-list yml with no tests), wires reconciliation tests (no_missing_rows_enhanced / no_additional_rows_enhanced / same_values_enhanced) on the output models against the legacy table, puts the S3 publish post-hook copy_relation_to_s3() on every output model and on no intermediate (DEC-084, checked by check_s3_publish.py), and moves the Productive task to Work in progress when it creates the branch (DEC-085, set_status.py). LOCAL authoring (2026-07-13, per the lead — pod-first reverted): the model + its tests are authored in the LOCAL repo on the flow's branch; the pod is touched only by the readiness gate at the end — confirm the pod is reachable and the flow's source/legacy data is loaded (via HELP/DATA_ACCESS.md) so validation can run — then STOP and recommend the separate keboola-validation-skill (it uploads the branch to the pod scratch, runs the validation loop + fixes, and when clean hands to keboola-pushing-skill for the commit, push, and MR — the branch itself is created here at Step 1). Use when migrating a Keboola flow as part of the client's Keboola→dbt migration. Triggers on "migrate this flow", "migrate transformation X", "convert Keboola SQL to dbt", "run the migration loop on X".
---

# keboola-migration-skill

Per-flow migration worker: **creates the flow's branch** (off a fresh `qa`, at the start), then takes one Keboola flow from raw Snowflake SQL to a dbt+DuckDB model set **authored locally on that branch**, and ends with a **readiness gate** that confirms the flow's data is ready for validation before handing off. Validation and pushing are the next skills in the chain ([[keboola-validation-skill]] → [[keboola-pushing-skill]]). Adapted from the manager's AIDER-driven workflow, restructured for Claude Code and the client's ecosystem.

**Scope of this version (LOCAL authoring, 2026-07-13 — per the lead; the 2026-07-02 pod-first experiment is REVERTED).** The model is **written in the local repo, on the flow's branch** — like before pod-first. The pod (where the real source/legacy data lives, S3 domain views via `kbc_in`/`kbc_stg`) is **validation's territory**: [[keboola-validation-skill]] uploads the branch to the pod scratch (its Step 0) and runs the build/test loop there. Migration itself only touches the pod at the very end, for the lightweight readiness gate (is the data there?). **The flow of control:**
> create the branch off a fresh `qa` (Step 1) → download raw SQL locally → **author the flow's models + YAML + reconciliation tests LOCALLY on the branch** (Steps 3–5c) → **readiness gate: confirm the pod + the flow's source/legacy data are ready for validation** (Step 5d) → **STOP and recommend [[keboola-validation-skill]]** (it uploads the branch to the pod scratch, runs the validation loop + fixes; when clean it syncs any pod-side fixes back to the branch and hands to [[keboola-pushing-skill]] to commit, push, and open the MR).

> **"0 unexplained WARNs" — the loop's terminal condition (decided 2026-07-02).** Iterate: a WARN that's a **migration bug** → fix the model and re-run; a WARN from an **invalid test** (e.g. `unique` on a genuinely non-unique upstream column, pod-verified) → drop that one test with an inline `# <test> removed — <justification + count>` per the ID-rule escape hatch and re-run; a WARN that's an **expected diff** (data recency, incremental-superset, upstream-source nulls — things you canNOT code to zero without weakening a real test) → **accept + document** it, don't suppress it. Terminal state = **build clean OR every remaining WARN individually justified**. Never weaken/drop a test purely to force a green count (that hides real issues) — one earlier flow hit literal 0 by dropping a genuinely-invalid `unique(ID)`; another legitimately ended with 14 documented recency/superset WARNs.

One flow per invocation. The only Python is `retrieve_keboola/main.py` (the downloader, validated); Storage-API reads (column schemas) are fine via `curl`/inline `python3`. Everything else is Claude reasoning + **local file edits** + `bash`/git + a local CSV breadcrumb; `kubectl exec` to the pod is used only for the Step 5d readiness gate (data-presence checks — full pod work belongs to [[keboola-validation-skill]]).

**Tenant note.** The client's ecosystem (~50 projects) lives at `connection.keboola.example`. The downloader authenticates per-project using `KEBOOLA_TOKEN_<PROJECT>` tokens in `.env`, picking the right one by **verifying each token against Keboola** (`owner.id` must equal the flow's project id — live, not a CSV column). Never hardcode a tenant or token.

## The loop (overview)

```
┌─ per flow (one invocation) ──────────────────────────────────────────┐
│ 0. entry: P1 scope verdict + P2 readiness pass (separate skills)      │
│ 1. resolve inputs + create branch off fresh qa (start)                │
│ 2. download SQL + task inventory     (main.py --flow-url — LIVE)      │
│ ── Steps 3–5c are authored LOCALLY on the flow's branch: ──           │
│ 3. merge deps → central per-project sources.yml                       │
│ 4. convert each SQL → dbt+DuckDB model                                │
│ 5. write the model YAML(s) + best-practice tests                      │
│ 5b. wire reconciliation tests onto each YAML (vs legacy)              │
│ 5c. register the flow's folders in dbt_project.yml                    │
│ 5d. re-run P2 over the model's ACTUAL source()/ref() calls            │
│     → STOP, recommend keboola-validation-skill                        │
└───────────────────────────────────────────────────────────────────────┘
```

## Folder layout & naming (manager-mandated)

**The dbt project lives at the REPO ROOT — there is NO `dbt_project/` wrapper dir** (manager directive, 2026-06-30; the old nested layout is deprecated — see [[dbt-project-root-level-structure]]). Every path below (`models/`, `dbt_project.yml`, `sources.yml`, `tests/`, `analyses/`, `packages.yml`, `profiles.yml`) is at the **root**.

Models nest **three levels** mirroring Keboola, derived entirely from **live Keboola** (all captured in `input/<flow>/_flow_tasks.json`): `<project>` = the token's `owner.name`, `<flow>` = the flow config `name`, `<transformation>` = each transformation config's `name`:

```
models/<project_slug>/<flow_dir>/<transformation_dir>/<output_table>.{sql,yml}
# e.g. models/00_Project_A/Scheduled_TABLE_A_90_DAYS/TABLE_A_90_DAYS/prod_table_a_l90d_csvbody.sql
```

Each model is placed under the transformation that **produces its output table** (the transformation whose live output mapping lists that table — `_flow_tasks.json` `output_tables`, or the config's `configuration.storage.output.tables`). One flow with several transformations → several `<transformation_dir>`s; one transformation emitting several output tables → several files in the same dir.

**Two distinct sanitization rules:**
- **`<project_slug>`** = the **same rule as the `source()` slug** (Step 3): each non-alphanumeric → one `_`, **no collapsing**, original case kept. So `00 Project A` → `00_Project_A`, `00 Project G` → `00_Project_G`, `15 Project E & F` → `15_Project_E___F`. Keeping this rule means **folder name == dbt_project.yml key == `source()` slug**, all identical — required for `+tags` to bind (Step 5c).
- **`<flow_dir>` / `<transformation_dir>`** = runs of non-alphanumeric → a **single** `_`, then **trim** leading/trailing `_` (these names carry brackets, parens, stray/leading/trailing spaces). `Scheduled TABLE_A_90_DAYS` → `Scheduled_TABLE_A_90_DAYS`; `[prod] Flow D orders (C1 only)` → `prod_Flow_D_orders_C1_only`; `Step A union` → `Step_A_union`.

> **Tags rule.** A project/model tag is **never** a top-level `tags:` property under a model in the `.yml` — Fusion rejects it (`Property tags is not allowed`). It's set in `dbt_project.yml` via `+tags` at the transformation level (Step 5c). Per-**test** `config: tags:` inside `data_tests` is unrelated and stays valid.

> **dbt_project.yml gotcha (verified — the manager's reference got this wrong).** Under `models:`, the **first key must be the project name `keboola_migration`**; the `<project_slug>/<flow>/<transformation>` hierarchy nests *under* it. Omitting `keboola_migration` (or letting the folder name drift from the key, e.g. `00_Project__A` folder vs `00_Project_A` key) makes dbt silently treat the block as an **unused config path** — `dbt1097` warning — and **no tag binds**. Verify with `dbt ls -s tag:<project_slug> --resource-type model`.

## Inputs the skill expects

**Invocation format.** The operator identifies the flow in **either** of two ways — a **Keboola flow URL** (preferred; added 2026-07-02, per the lead) **or** a `project:`+`flow:` name pair:

```
# Form A — Keboola flow URL (preferred). Task optional; auto-resolved if omitted.
/keboola-migration-skill flow: https://connection.keboola.example/admin/projects/<PID>/flows/<FID>
/keboola-migration-skill task: <task>, flow: https://connection.keboola.example/admin/projects/<PID>/flows/<FID>

# Form B — project + flow name pair (the original form; still fully supported)
/keboola-migration-skill task: <productive task #>, project: <project name>, flow: <flow name>
```

e.g. `/keboola-migration-skill task: <task>, project: 00 Project A, flow: Scheduled TABLE_A_90_DAYS`.

> **Resolving a Keboola URL → `CURRENT_FLOW` + project (Form A) — LIVE, no manifest (2026-07-13).** When `flow:` is a URL of the shape `…/admin/projects/<PID>/flows/<FID>` (spot it by the `http`/`connection.…keboola.com` prefix, or a bare `projects/<PID>/flows/<FID>`), **derive everything from LIVE Keboola — never a CSV.** The downloader does this for you: `python3 retrieve_keboola/main.py --flow-url "<url>"` parses `<PID>`/`<FID>`, resolves the per-project token by **verifying `.env` tokens against Keboola** (`/v2/storage/tokens/verify` → `owner.id` must equal `<PID>`; `owner.name` is the authoritative project name — so the token, the project id, and the project **name** all come from Keboola, no id→name hand-mapping), fetches the flow's orchestrator/flow config, and reads `name` → **`CURRENT_FLOW`**. It prints `Project '<name>' (id <PID>) …` and `Flow '<CURRENT_FLOW>' …` — read those two lines for the branch/folder values. (Keboola is the single source of truth; the manifest mis-attributed which flow owns which transformation and is retired — see [[manifest-stale-verify-live-keboola]].)

```bash
# URL → project + flow, live (also downloads the SQL + writes the task inventory — Step 2)
python3 retrieve_keboola/main.py --flow-url "https://connection.keboola.example/admin/projects/<PID>/flows/<FID>"
#   Project '30 Project C' (id <PID>) via KEBOOLA_TOKEN_30_PROJECT_C …   → project + <project_slug>
#   Flow 'Flow C' (id <FID>, keboola.orchestrator) — 17 task(s)            → CURRENT_FLOW
```

Map the parsed values to the inputs below: **`task:` → `PRODUCTIVE_TASK`** (the Productive.io task number — operator-supplied, used verbatim as the `#<task>` branch prefix and in the commit/MR title), **`flow:` → `CURRENT_FLOW`** (URL-resolved live per above, or taken verbatim in Form B; the branch/folder source) and **the Keboola project** (URL-resolved live from the token's `owner.name`, or the `project:` value in Form B — selects the `KEBOOLA_TOKEN_<PROJECT>` and the `<project_slug>`, both folder and `source()` slug). The project also **disambiguates** when the same flow name appears under more than one project — a URL is inherently unambiguous, which is why it's preferred. In Form B, pass `--flow-name "<flow>" --project "<project>"` — the downloader lists that project's flows live and resolves the id (errors if the name isn't exactly one flow). (Phrasing varies — `name of the project:`, missing comma, a bare URL with no `flow:` label, etc. — parse leniently.) **If `task:` is missing** (updated 2026-06-26), don't just stop — **auto-resolve it**: search Productive.io for an existing task whose title contains the flow name (one match → use its `task_number`; no match → create the task via [[productive-task-creator]]; multiple → ask). See the `PRODUCTIVE_TASK` input below for the exact API. It's needed at the **start** to create the branch (Step 1).

- **Flow identity — from LIVE Keboola, not a manifest (the manifest CSV is retired — [[manifest-stale-verify-live-keboola]]).** The operator gives a flow URL (Form A) or `project:`+`flow:` (Form B); the downloader (Step 2) resolves the project/token/flow-name/task-list live and writes `input/<flow>/_flow_tasks.json` — the authoritative per-flow inventory (each task's component kind: transformation-sql / transformation-python / extractor / writer, `enabled`, and output table ids). That JSON is the source of truth for "what's in the flow" (replacing the old manifest slice) — the pre-flight gate + conversion both read it.
- `CURRENT_FLOW` — the flow's live Keboola `name` (from the flow config, e.g. `Flow C`), as printed by the downloader.
- `PRODUCTIVE_TASK` — the Productive.io task number for this flow (e.g. `<task>`). Used verbatim as the `#<task>` branch prefix; **required early** (it's built into the branch name and the pod scratch dir name — the git branch is created in Step 1). **Resolve it like this (added 2026-06-26, per the lead):** if the operator supplied it, use it. If not, **search Productive.io first** for an existing task whose title contains the flow name, then decide:
  - Query the migration project (`$PRODUCTIVE_PROJECT_ID`) via the productive-task-creator API (`GET https://api.productive.io/api/v2/tasks?filter[project_id]=${PRODUCTIVE_PROJECT_ID}&filter[query]=<distinctive part of flow name>`, headers `X-Auth-Token` from the skill's `secret.env` + `X-Organization-Id: ${PRODUCTIVE_ORG_ID}`). Both come from the repo-root `.env-skill`. Titles follow `Week {N} - {project} - {flow}`.
  - **Exactly one match** → use it; the branch prefix is its **`task_number`** attribute (e.g. `<task>`), NOT the 8-digit API `id`. (Fetch via `GET /tasks/<id>` → `attributes.task_number`.)
  - **No match** → **create** the task via the [[productive-task-creator]] skill (`create_task.py`, assignee `$PRODUCTIVE_ASSIGNEE_ID`), then read back its `task_number`.
  - **Multiple ambiguous matches** → STOP and ask the operator which task #.
- `.env` at project root — `KEBOOLA_REGION` + one `KEBOOLA_TOKEN_<PROJECT>` per project. Never committed.
- `.env-skill` at project root — `KEBOOLA_POD`/`KEBOOLA_POD_NAMESPACE` (Steps 2b–5c below) and the
  `PRODUCTIVE_*` coordinates used here. Copy `.env-skill.example` if it's missing. Never committed.

Everything else (project, tenant host, config IDs, task list, output tables) is derived **live from Keboola** by the downloader. The operator does not supply IDs.

## Outputs the skill produces

- `input/<flow>/<transformation>/<code>.{sql,py}` — raw downloaded code per transformation (the "OLD" side; `.py` for Python transforms), plus `input/<flow>/_flow_tasks.json` — the live task inventory (kind / enabled / output tables per task)
- `models/sources.yml` — **one central, per-project** source list; this flow's external tables are **merged in** (never overwritten/deleted). Accumulates across all flows.
- `models/<project_slug>/<flow_dir>/<transformation_dir>/<output_table>.sql` — one converted model per Keboola output table, nested in the **project/flow/transformation** layout (see "Folder layout & naming" below)
- `models/<project_slug>/<flow_dir>/<transformation_dir>/<output_table>.yml` — schema, `quote: true` on every column, **plus reconciliation tests** wired against the legacy table (Step 5b)
- `dbt_project.yml` — this flow's `project → flow → transformation` nesting **merged into the `models:` block** (under the `keboola_migration` project key) with `+tags: ['<project_slug>']` at the transformation level (Step 5c). Accumulating, like `sources.yml`.
- The flow's **branch** `#<PRODUCTIVE_TASK>_Week_<week>_<project_slug>_<flow_dir>` (e.g. `#<task>_Week_1_20_Project_B_Flow_B`), **created off a fresh `qa` at Step 1** and left checked out for the downstream skills. No local commit here — the pull-back + commit + push + MR are [[keboola-pushing-skill]]'s (the old Step 6).
- A breadcrumb row in `migration_log.csv`

> The model `.sql`/`.yml` and the `sources.yml`/`dbt_project.yml` merges are **authored locally on the flow's branch** (Steps 3–5c), uncommitted — [[keboola-validation-skill]] uploads the branch to the pod scratch and validates there (syncing any pod-side fixes back), then [[keboola-pushing-skill]] commits and pushes.

One-time project scaffold (already in the repo — you don't recreate it per flow; [[keboola-validation-skill]] uploads it to the pod with the branch): `tests/generic/{missing_rows_enhanced,same_values_enhanced,not_all_null_values}.sql` (the reconciliation **generic test definitions** — they live in `tests/generic/`, **never** in flat `tests/` or `macros/`; dbt only discovers generic tests under a `generic/` subfolder of a test path, so a flat `tests/*.sql` definition fails `dbt parse` with `dbt1501 — macro test_<name> is unknown`), `packages.yml` (elementary 0.24.0 + its dbt_utils dep), and the Elementary `flags`/`vars`/`+schema` in `dbt_project.yml` + the `elementary` profile in `profiles.yml`. `dbt_packages/` is git-ignored, but Fusion's `dbt parse` auto-installs the declared packages on a fresh checkout (confirmed locally — move `dbt_packages/` aside and `dbt parse` reinstalls it), so the pushing skill's `dbt parse` gate still works without a manual `dbt deps`. Full Elementary runbook: `RECONCILIATION_AND_ELEMENTARY_HANDOFF.md`.

---

## Step 1 — Resolve inputs & create the branch (off a FRESH `origin/qa`, at the start)

> **Create the local branch now, at the start** (per the lead, 2026-07-06). **Always start from a FRESH pull of `origin/qa`** — fetch the latest `qa`, then create the per-flow branch from it (never branch off a stale local `qa`, which silently regresses the accumulating files — see [[stale-branch-silently-regresses-qa]]). Branching off `qa` (root-level layout) makes the eventual MR a clean same-history diff of just this flow — no `--orphan` full-tree diff (see [[dbt-project-root-level-structure]]). Authoring then happens **locally on this branch** (Steps 3–5c), left **uncommitted** — **migration creates the branch and the files; the commit + push + MR are [[keboola-pushing-skill]]'s.** The `<flow_dir>` is also reused later by validation for its pod scratch dir `/app/kbc/<flow_dir>_val`.

Each flow gets its own **standalone branch** (manager's rule: *separate branch per individual flow*), named after the **Productive task**:

```
#<PRODUCTIVE_TASK>_Week_<WEEK>_<project_slug>_<flow_dir>
# e.g.  #<task>_Week_1_20_Project_B_Flow_B
```

- `<PRODUCTIVE_TASK>` — the operator-supplied task number (the leading `#` is **literal**).
- `<WEEK>` — the `Week N` from the **Productive task title** (`Week {N} - {project} - {flow}`, e.g. task "Week 2 - 30 Project C - Flow C" → `2`). (The manifest used to supply this; it's retired.)
- `<project_slug>` — the project slug, same sanitization as the `source()` slug / folder name (e.g. `20 Project B` → `20_Project_B`).
- `<flow_dir>` — the flow name, same `<flow_dir>` sanitization as the folder layout (runs of non-alphanumeric → single `_`, trim ends; e.g. `Flow B` → `Flow_B`).

> **Quote the `#`.** git allows `#` in a branch name, but in zsh/bash `#` starts a comment, so the name MUST be single-quoted everywhere it appears (`git switch -c '#<task>_…'`, every refspec). Build it into a shell var once and always reference it quoted.

Build the name + slugs and **create the branch off a fresh `origin/qa`** now (you also need `<flow_dir>` for the folder layout):

```bash
# Construct per the template above; ALWAYS single-quoted (# is a shell comment):
BRANCH='#<task>_Week_1_20_Project_B_Flow_B'
FLOW_DIR='Flow_B'                                 # models/<project_slug>/${FLOW_DIR}/…; validation later uses /app/kbc/${FLOW_DIR}_val

git fetch origin qa                               # ALWAYS start from the FRESHEST qa (never a stale local qa)
git switch -c "$BRANCH" origin/qa                 # new per-flow branch based on fresh qa
```

**Then move the Productive task to Work in progress (`DEC-085`)** — the branch is what makes the flow
in progress:

```bash
python3 .claude/skills/productive-task-creator/set_status.py --task <PRODUCTIVE_TASK> --status wip
```

It moves only a task that is in Backlog / To Do / Pending (already WIP → no-op), reads the status back,
and prints one line — quote that line in the phase report. Exit `2` means the guard refused: the task is in
To Review / Done / another state, left where it is. Say so in the report and carry on authoring. A failed
call (exit `1`, auth, network) is reported once, not retried in a loop, and does not block authoring either.

> **Why off a fresh `origin/qa` and not `--orphan`.** The old flow made an `--orphan` snapshot and cleaned the tree — that produces a full-tree MR diff with no shared history. Branching off a **freshly-fetched** `origin/qa` (root-level layout) instead gives a same-history diff of just this flow's new model files + the accumulating `sources.yml`/`dbt_project.yml` once [[keboola-pushing-skill]] commits them onto it. Fetching fresh each time also avoids inheriting a stale `qa` that silently regresses the accumulating files ([[stale-branch-silently-regresses-qa]]). See [[dbt-project-root-level-structure]], [[per-flow-branch-only-this-flow]], and [[keboola-pushing-skill]] for the commit/push/MR mechanics.

## Step 2 — Download the raw SQL (LIVE from Keboola — no manifest)

Run the downloader with the **flow URL** (Form A) or `--flow-name`+`--project` (Form B). It reads the LIVE flow — resolves the token by verifying `.env` against Keboola, fetches the orchestrator/flow task list, and downloads each **transformation** task's code into `input/<flow>/<transformation>/<code>.{sql,py}`, plus the inventory `input/<flow>/_flow_tasks.json`.

```bash
python3 retrieve_keboola/main.py --flow-url "https://connection.keboola.example/admin/projects/<PID>/flows/<FID>"
# Form B (name within a project):
#   python3 retrieve_keboola/main.py --flow-name "Flow C" --project "30 Project C"
```

What it handles for you (no manual work):
- **Token, project id, project NAME — live** via `/v2/storage/tokens/verify` (matches the flow's `<PID>`; `owner.name` is authoritative). No id→name hand-mapping, no `.env`-slug guessing.
- **Discovery is the LIVE task list**, not a CSV — so it downloads *exactly* what the flow really runs (this is what fixed an earlier flow where the manifest hid 12 real transformations behind a lone event-trigger — [[manifest-stale-verify-live-keboola]]).
- **Classifies each task**: `transformation-sql` (→ dbt model) and `transformation-python` (→ **dbt can't do it**; downloaded as `.py`, flag for separate handling) are downloaded; `extractor`/`writer` (`keboola.ex-*`/`keboola.wr-*`) are ingestion (the data owner's layer) and are recorded but **not** downloaded.
- **Legacy** (`keboola.legacy-transformation`): `configuration.parameters.transformations[].parameters.queries`. **Newer** (`keboola.snowflake-transformation`): `…blocks[].codes[].script`. **Row-based**: `rows[]`. All covered by `extract_sql`.
- Prints, and records in `_flow_tasks.json`, each transformation's **output table ids** + `enabled` — the join key for the pre-flight gate's data-owner-sheet lookups.

To inspect raw config JSON instead of extracting: add `--inspect` (dumps `input/<flow>/_config_<id>.json` per transformation).

Breadcrumb: `echo "<flow_id>,,${CURRENT_FLOW},sql_downloaded,$(date -Iseconds),downloaded N file(s)" >> migration_log.csv`

> The downloaded SQL + the Storage-API column/PK fetch (§4h) are your **reference** for authoring; the model files are written **into the local repo on the flow's branch** (Steps 3–5c). *(The 2026-07-02 pod-first "Step 2b — set up the pod scratch" is REVERTED (2026-07-13, per the lead): migration does NOT create a pod scratch or write files to the pod — [[keboola-validation-skill]] owns the pod upload as its Step 0. If you need a data peek while authoring (a column's null-rate, a type, a dup check), a read-only `kubectl exec … duckdb` query against the attached S3 DBs is fine — that's a lookup, not authoring.)*

## Step 3 — Merge dependencies into the central sources.yml (before converting)

Do this **before** the SQL rewrite so the conversion already knows every `source()` vs `ref()`. The **live flow inventory** (`_flow_tasks.json` — each transformation's `input_tables` / `output_tables` from the Keboola storage mapping) is the authoritative lineage — do not parse SQL to discover sources.

There is **one central, accumulating** `models/sources.yml` for the whole migration — **not** one per flow. Each flow **merges** its external tables into it and never rewrites or deletes the rest. It grows to thousands of entries over the migration; treat it as append-only.

Sources are grouped **by Keboola project**. The source `name` is the project slug — the **same sanitization as the `.env` token** (Step 2): each non-alphanumeric → one `_`, no collapsing, original case preserved.
- `30 Project H` → `30_Project_H` · `00 Project G` → `00_Project_G` · `15 Project E & F` → `15_Project_E___F`

**Classify each input table** (`OUTPUTS_IN_FLOW = { tid for task in _flow_tasks['tasks'] for tid in task['output_tables'] }`; the input tables to classify are each transformation's `input_tables`):
- `Table ID` ∈ `OUTPUTS_IN_FLOW` → produced by a sibling → `{{ ref('<sibling output table, lowercased>') }}` (not a source)
- else → external → `{{ source('<project_slug>', '<Table Name>') }}`, where `<project_slug>` comes from **that row's `Project`** column.

> **A cross-flow producer's model IS a valid `ref()` target — but ONLY when that producer is in migration scope.** (Updated 2026-07-28, merging the lead's step-3 input classification. This **supersedes** the old *"`ref()` is intra-flow only, a cross-flow input stays a `source()` until the deferred cross-flow-stitching phase (Open Q8)"* rule, which the repo has already outgrown — `qa` carries ~48 cross-directory `ref()` pairs, including cross-project ones: `15_Project_E___F/Model_A` → `00_Project_I/MODEL_B`, `10_Project_D/Flow_G/prod_model_c` → `00_Project_J/…/PROD_MODEL_D`, `12_Project_K/…/PROD_MODEL_E` → `00_Project_L/Flow_H/Prod_MODEL_F`.) Classify every `out.c-…` input — the prefix alone is never the answer:
> - **Sibling in THIS flow** (`∈ OUTPUTS_IN_FLOW`) → `ref()`; ordinary intra-flow chain. Includes a code that reads *and* writes the same `out.c-*` (self-reference) — internal, but flag it as an incremental / `{{ this }}` wrinkle.
> - **Produced by ANOTHER IN-SCOPE flow** → **pretransformation** → `ref()` to the producer's model, and the **producer's MR merges FIRST** ([[cross-flow-ref-validation-and-merge-order]]). Producer not migrated yet → the verdict carries the ordering line *"merges after `<producer>`"* (create its Productive task if none exists); authoring and Gate 1 validation do not wait for it (`DEC-082`). ⚠ Producer identity is resolved by [[keboola-scope-skill]] (P1) and arrives with its type-of-source list — an `in.c-*` can be a **linked bucket** hiding a cross-flow transformation output (the `ZCUST_M02` ⇐ Flow I trap); the Storage API `bucket.sourceBucket.project` + `KBC.createdBy.component.id` is what settles it, not the prefix.
> - **Produced by a flow that is NOT in scope** → **stays a `source()`** on the pod domain DB, permanently. Two verified cases: a **'00' source-layer flow** the data owner owns and stages (project name starts with `00 ` — see the 1.PRE precedence rule; an earlier `10 (triggered by 00) …` flow was skipped and its consumer kept `source('in_src_a',…)`), and an **obsolete/frozen producer** (all codes disabled / `lastImportDate` frozen — seen on an earlier flow; the table is a frozen published copy). Do **not** rewire these to `ref()`, do **not** build passthrough models.
> - **Shared / Data-Catalog alias tables** (e.g. `SHARED_TABLE_A` aliased from `00 Project M` into `20 Project N`) are physically owned by the other project — even the source `<project_slug>` is the owner's, not this flow's. They follow the in-scope/out-of-scope verdict above.

> **A model's INPUT `source()` must NEVER point at the STG (`kbc_stg` / `stg_*`) layer — that layer is validation-only.** The `kbc_stg` domain (source names `stg_*`, `database: kbc_stg`) holds the **legacy Keboola outputs** (`out.*`) — precisely what the migration *replaces*. It exists on the pod **solely** as the reconciliation **reference** (proving new == old). So whatever a model reads in its `FROM`/`JOIN` must reflect the **production lineage**, never that scaffold:
> - **Raw / ingested input** → `source('in_*', …)` on the **IN** layer (`database: kbc_in`, or a domain DB like `ora`), NOT the `stg_*` twin.
> - **Produced by another transformation** → `ref()` (intra-flow sibling, or an in-scope cross-flow producer — `DEC-006`, `DEC-082`; an out-of-scope producer stays a `source()` on its **production** layer) — **never** its `stg_*` recon view.
> - **The ONLY allowed `stg_*` usage** is the reconciliation `reference: source('stg_*', …)` in a test (Step 5b) — never in a model's `SELECT`/`FROM`.
> Why it matters: sourcing a model from `kbc_stg` makes the new model **depend on the legacy pipeline still running** (migration replaces nothing) and produces a **false-green recon** — the model is compared against the very `stg` table it reads from (often circular → trivial PASS). In production those `stg_*` S3 snapshots aren't maintained → stale/absent data. (Do **not** confuse with the '00' source-layer case: the data owner's '00'-staged tables that downstream flows read via `source()` live in their own **IN/domain** layer, e.g. `source('in_src_a', …)`, **not** `kbc_stg`.) See [[stg-layer-is-validation-only-never-a-model-source]].
> ⚠ **MANDATORY GATE — this has already been silently violated 3 times (on three earlier flows, one of them on
> VBAK — see `HELP/FIXES.md`) by an agent ASSUMING "no durable copy exists" without checking.**
> Before writing a `stg_*` source block for ANY table, you MUST first run this catalog search against
> **every relevant attached input DB** (`sap`, `ora`, `kbc_in` — not just the one you expect) on the pod:
> ```sql
> SELECT database,schema,name FROM (SHOW ALL TABLES) WHERE upper(name) LIKE '%<TABLE_NAME_FRAGMENT>%'
> ```
> then confirm the candidate table actually has the columns the model needs (`DESCRIBE`) and a sane join
> key (`count(*)` vs `count(distinct <key>)`). **Only if this search comes up genuinely empty** may you
> proceed — and even then the answer is NOT "wire it to `stg_*` and document it as a deviation"; it's
> **escalate to the data owner to load it, and flag/block the model** until it lands (cross-flow-stitching-style
> note). A "known, documented deviation" comment in `sources.yml` is not a substitute for running this
> query — every prior deviation was also "documented" and still wrong.
> Models **already merged into `qa`** that read `kbc_stg` are tracked debt (`DEC-007`), not a precedent —
> they are cleared in batch by [[keboola-stgtablechange-skill]], never copied by a new flow.

**Only declare tables the converted SQL actually references.** Keboola input mappings are often broader than usage — an `input_tables` entry whose table never appears in any of the flow's SQL is **not** added (e.g. Flow J declares `ZCUST_T04` + `ZCUST_T05` but neither SQL reads them). Declaring unreferenced sources creates dead config that `dbt compile` flags.

**Source-name collision (one Table Name, two buckets).** dbt source tables are keyed `(project_slug, Table Name)`. If a project feeds two *physically different* tables that share a name from different buckets — verified on `TABLE_X`, which arrives as both `in.c-src_a.TABLE_X` and `in.c-src_b.TABLE_X` in the same project — they collide under one source block. Disambiguate by **bucket-suffixing** all but the canonical one: declare `TABLE_X` (src_b) **and** `TABLE_X_src_a`, and the model reading the src_a table uses `source('<slug>','TABLE_X_src_a')`. Pick which is "canonical" by whichever is more common across the flow; the suffix is the bucket's distinguishing token. (Ties into the eventual pod `database:`/`schema:` mapping — Open Q7.)

**Merge procedure** (Claude edits the YAML directly — no full rewrite):
1. Read the existing `models/sources.yml` (if absent, start with `version: 2` + empty `sources:`).
2. Find the `- name: <project_slug>` block; if the project isn't there yet, append a new block.
3. Add each referenced table as `- name: <Table Name>` **only if not already listed** (dedup — sibling flows in the same project share tables).
4. Leave every other project and table untouched. No `description`s.

```yaml
version: 2

sources:
  - name: 00_Project_G         # added by an earlier flow — leave intact
    tables:
      - name: src_table_b
  - name: 30_Project_H         # this flow merges its tables under here
    tables:
      - name: ZCUST_T03
```

**Worked example — `Flow F`** (project `10 Project D` → slug `10_Project_D`):

| Transformation | Direction | Table ID | Classification |
|---|---|---|---|
| Z_TRANS_A | input | `in.c-…-sheets-….SRC-SHEET-A` | `source('10_Project_D','SRC-SHEET-A')` |
| Z_TRANS_A | output | `out.c-bucket_a.ZCUST_T01` | produced here |
| ZCUST_M01 Metrics A/B | input | `in.c-…-s3-….ZSRC_T02` | `source('10_Project_D','ZSRC_T02')` |
| ZCUST_M01 Metrics A/B | input | `out.c-bucket_a.ZCUST_T01` | **intra-flow** → `ref('zcust_t01')` |
| ZCUST_M01 Metrics A/B | output | `out.c-bucket_a.ZCUST_M01` | terminal output |

→ merge `SRC-SHEET-A` + `ZSRC_T02` under `10_Project_D`; `zcust_m01` uses `ref('zcust_t01')`.

> **Branch-model note (local authoring, 2026-07-13):** you merge this into the **local** `models/sources.yml` on the flow's branch (created off a fresh `origin/qa` at Step 1, so it already holds the accumulated copy). [[keboola-pushing-skill]] later commits it alongside the flow's model dir with a **targeted `git add`** (not `-A`) — the central `sources.yml` keeps accumulating and the MR diff stays scoped to this flow. See [[per-flow-branch-only-this-flow]].

## Step 4 — Convert each SQL to dbt+DuckDB

Apply in order: structural rewrites, then dialect rewrites, then pick a materialization, then sanity-check against the worked examples.

### 4a. Structural rewrites (dbt-mandated)

| Pattern in Keboola SQL | Replace with | Why |
|---|---|---|
| `CREATE [OR REPLACE] TABLE X AS SELECT …` | drop the `CREATE … AS`; add `{{ config(materialized=…) }}` at top; filename = the **storage output table name from the live output mapping**, lowercased, **placed at `models/<project_slug>/<flow_dir>/<transformation_dir>/`** (derive the three dirs from live Keboola per "Folder layout & naming") | dbt owns table creation; filename = model = table; the path mirrors Keboola |
| `CREATE TABLE "OUT.<alias>" AS …` (legacy output-mapping alias) | same as above — resolve the alias to its storage name via the config's **live output mapping** (`_flow_tasks.json` `output_tables` / `configuration.storage.output.tables`). E.g. `OUT.Z_TRANS_A` → output `ZCUST_T01` → file `zcust_t01.sql` | Keboola maps the in-SQL alias to a *different* storage table; the live output mapping is the rosetta stone |
| `FROM "IN.<alias>"` (legacy input-mapping alias) | resolve via CSV input row → `{{ source('<project_slug>','<Table Name>') }}` or `{{ ref('<sibling>') }}` per Step 3. E.g. `IN.Sheet_A_Input` → `source('10_Project_D','SRC-SHEET-A')` | Same alias-resolution; never keep the `IN.` literal |
| Multiple `CREATE … TABLE` (or multiple legacy transformations) | one `.sql` file **per storage-output table** (from the live output mapping) — not per CREATE | one file = one model. (main.py already splits legacy multi-transformation configs into separate input files) |
| `CREATE … TABLE X` where `X` is **not** a storage output (an in-SQL temp / staging table) | fold into a **CTE** inside the model that consumes it; references to `X` downstream → the CTE name. **Exception — a large/complex flow** (many temps, deep chains, a temp reused by several models) may keep each temp as its own **intermediate model** rather than one unwieldy CTE stack — those are **build-only, no tests** (Step 5 🔴 rule). E.g. one large flow keeps ~60 intermediate models feeding the 2 output models. | only the models in the live output mapping get **tests**; every other DAG node is an intermediate step — CTE it when small, keep it as an untested model when the flow is too big for that. E.g. Flow D: `v3_C1`/`v3_C2`/`v3_tmp` aren't in the output mapping → three CTEs feeding the one output model `fact_orders_x` |
| `FROM <output>_INPUT` (self-reference for incremental) | `FROM {{ this }}` inside `{% if is_incremental() %} … {% endif %}` | dbt incremental pattern; `{{ this }}` = existing table |
| `// dead code` | delete | clean up on migration |
| `-- live comment` | keep | useful context |

> **In-SQL table name ≠ storage output name — for *newer* transformations too.** The `OUT.<alias>` row above is the legacy form, but `keboola.snowflake-transformation`s do the same with arbitrary names: the terminal `CREATE TABLE <name>` is whatever the author typed, and the output **mapping** routes it to the real storage table. Always resolve the filename from the live output mapping (`_flow_tasks.json` `output_tables` / the config's `storage.output.tables`), never the in-SQL name. Verified: `out_RESULT` → storage `METRICS_TABLE_A` (file `metrics_table_a.sql`); `SHARED_TABLE_A_C3_INCREMENT` → storage `SHARED_TABLE_A`. A single transformation can also write **several** outputs (e.g. `TABLE_B` → `TABLE_B` + `TABLE_B_PRIVATE`; `EVENT_LOG_A` → `EVENT_LOG_A` + `…_HISTORY` from one `SELECT`) → one model file per CSV output table.

> **Every model `.sql` opens with a `keboola-source:` link — exact marker, no exceptions (`DEC-068`).** First line after the `{{ config(...) }}` call, above the existing `-- Migrated from Keboola transformation "…"` header:
>
> ```sql
> -- keboola-source: https://<host>/admin/projects/<project_id>/components/<component_id>/<config_id>
> ```
>
> The four parts are exactly what `parse_bucket_url()` in `retrieve_keboola/main.py` already returns for the transformation's Bucket URL (`host`, `project_id`, `component_id`, `config_id`); for a row-based config append `/rows/<row_id>`. **One link per model — the transformation that produces THIS model's output table, not the upstream chain** (the data owner, 2026-09-03: *"Only the last one — the one that creates the table — is enough."*). It goes in the **`.sql`**, never only in the `.yml`, because dbt writes the compiled SQL of every node into `logs/dbt.log` at debug level on every run — that is how the link reaches the data owner (`grep "keboola-source" logs/dbt.log`) with no logging config at all. A `.yml` header never reaches the log. **Forward-only** — the ~45 flows migrated before 2026-09-03 are not backfilled (the data owner's own call).

### 4b. Snowflake → DuckDB dialect cheat sheet

Prefer the DuckDB-native form; never leave a Snowflake-only function in the output.

| Snowflake | DuckDB | Note |
|---|---|---|
| `TO_TIMESTAMP(str_col)` | `TRY_CAST(str_col AS TIMESTAMP)` | **Trap:** DuckDB's `TO_TIMESTAMP` parses Unix epoch numbers, not strings |
| `TO_TIMESTAMP(str_col, 'fmt')` | `strptime(str_col, '%…')` | when an explicit format is passed |
| `TO_DATE(str_col)` | `TRY_CAST(str_col AS DATE)` | same trap |
| `DATE(ts)` / `ts::DATE` where `ts` is a stored timestamp | `TRY_CAST({{ convert_to_local_time('"TS"') }} AS DATE)` — for a column that is ALREADY `TIMESTAMPTZ`, `TRY_CAST(timezone('Europe/Prague', ts) AS DATE)` | ⚠ pod views normalize timestamps to UTC but legacy Snowflake computed dates on LOCAL wall-clock text → rows at UTC hour 22/23 land one day early (verified on an earlier flow, 2026-07-08; see `HELP/FIXES.md`). Also makes a `view` model session-tz-independent. Signature when missed: recon diffs of exactly +1 day at UTC hours 22/23. **Check the column type first** — the macro is for a NAIVE column holding UTC and is actively wrong for one already `TIMESTAMPTZ` or already local (`tmp_model_x`, an earlier flow). `DEC-058`, `docs/TIMEZONES.md`. |
| `CURRENT_DATE` / `CURRENT_TIMESTAMP` / `$NOWINTIMESTAMP` (reading "now") | `cast({{ current_local_time() }} as date)`, or `{{ current_local_time() }}` for the instant | ⚠ **never a bare `current_date`** — the pod session is `Etc/UTC` while the business day is local time (CET/CEST), so it is a day behind between 00:00 and 01:59 local time. A daytime test cannot see it and recon cannot either (frozen `stg_*`). `CONVERT_TIMEZONE('PST8PDT','CET', CURRENT_TIMESTAMP)` is a Snowflake session artefact meaning "today's local date" — drop the conversion, do NOT transcribe it. Cost of getting this wrong: `now_ts_model_x` (an earlier flow, MR !<mr>). `DEC-058`, `docs/TIMEZONES.md`. |
| `LISTAGG(col, ', ') WITHIN GROUP (ORDER BY x)` | `STRING_AGG(col, ', ' ORDER BY x)` | ordering folds into STRING_AGG |
| `ARRAY_TO_STRING(ARRAY_AGG(DISTINCT col), '; ')` | `STRING_AGG(DISTINCT col, '; ')` | collapses the two-step pattern |
| `IFF(cond, a, b)` | `CASE WHEN cond THEN a ELSE b END` | CASE is safest cross-version |
| `DATEADD(DAY, -1, CURRENT_DATE())` | `CURRENT_DATE - INTERVAL 1 DAY` | unit inside INTERVAL |
| `DATEDIFF(DAY, a, b)` | `DATE_DIFF('day', a, b)` | unit becomes a quoted string |
| `CURRENT_DATE()` | `CURRENT_DATE` | no parens |
| `CURRENT_TIMESTAMP()` | `now()` (or `current_timestamp`, no parens) | **Trap (verified):** the parens form `current_timestamp()` errors in DuckDB — *"Scalar Function with name current_timestamp does not exist"*. Use `now()`. |
| `CONVERT_TIMEZONE('tz', ts)` (2-arg) | `timezone('tz', ts)` | ICU; returns wall-clock timestamp in `tz`. Verified |
| `DATEADD('day', -1, ts)` (3-arg, **string** unit) | `ts - INTERVAL 1 DAY` | DuckDB has no 3-arg string-unit `dateadd`; use INTERVAL math (covers any unit) |
| `OBJECT_AGG(k, v)::string` | `json_group_object(k, v)::VARCHAR` (⚠ key ORDER) | drop `::variant` casts; serializes as a JSON string. **⚠ Snowflake `object_agg` sorts keys ALPHABETICALLY; DuckDB `json_group_object` uses INSERTION order → the JSON string differs and recon on that column fails (verified on an earlier flow, 2026-06-28).** When the keys are a FIXED set, build the JSON as an **alphabetically-ordered struct → `to_json`** instead: `to_json({'application':a,'component':c,'country':co,…})::varchar` (declare fields A–Z) — byte-matches `object_agg`. See [[snowflake-objectagg-key-order]]. |
| `<tbl> UNPIVOT(val FOR name IN (cols))` | `<tbl> UNPIVOT (val FOR name IN (cols))` | DuckDB supports the SQL-standard form; same column order. Verified |
| `SHA1(x)` / `SHA2(x, 256)` | `sha1(x)` / `sha256(x)` | both built into DuckDB. Verified |
| `CONCAT(...)`, `UPPER`, `LOWER`, `TRIM`, `REPLACE` | identical | no change |
| alias reuse in same `SELECT` (a select-item references an earlier alias) | identical | DuckDB supports lateral alias references; keep as-is. Verified |
| `OBJECT_CONSTRUCT('a', x)` | `{'a': x}` | struct literal |
| `PARSE_JSON(str)` | `str::JSON` | native JSON cast |
| `LEFT` / `RIGHT` / `SUBSTR` / `NULLIF` / `COALESCE` / `\|\|` | identical | no change |
| `REGEXP_LIKE(s, p)` | `regexp_full_match(s, p)` | ⚠ Snowflake regex is **FULL-STRING anchored** — use `regexp_full_match`, NOT `regexp_matches` (partial). See ⚠ below. |
| `s REGEXP p` / `s RLIKE p` (infix) | `regexp_full_match(s, p)` | DuckDB has no infix `REGEXP`; rewrite to the function. **`regexp_full_match`**, not `regexp_matches`. |
| `s NOT REGEXP p` (infix) | `NOT regexp_full_match(s, p)` | wrap in `NOT`. |
| `::` cast, `"Quoted Idents"`, `WITH RECURSIVE` | identical | DuckDB supports all |

> **⚠ REGEX ANCHORING (validated on pod 2026-06-26, Flow D).** Snowflake `REGEXP`/`RLIKE`/`REGEXP_LIKE` match the
> **ENTIRE string** (implicitly anchored `^…$`). DuckDB's `regexp_matches(s,p)` is **partial** (matches a substring) —
> semantically different. Always map Snowflake regex to **`regexp_full_match(s,p)`**. Using `regexp_matches`
> silently mis-classifies: on Flow D's `COL_CHANNEL` CASE it inflated one channel bucket and emptied another.
> For "contains" semantics wrap the pattern in `.*….*`. See [[snowflake-regexp-is-anchored]].
| `SAFE_CAST(…)` | `TRY_CAST(…)` | name change |
| `TO_NUMBER(str)` / `TO_NUMERIC(str)` | `TRY_CAST(str AS DECIMAL(18,4))` | string→numeric; use `TRY_CAST` so bad values null out instead of erroring. Often wrapped in an empty-string guard — `IFF(TRIM(x)='', 0, TO_NUMBER(x))` → `CASE WHEN TRIM(x)='' THEN 0 ELSE TRY_CAST(x AS DECIMAL(18,4)) END` |
| `TO_NUMBER(str, p, s)` | `TRY_CAST(str AS DECIMAL(p,s))` | carry the precision/scale through |
| `SNOWFLAKE.CORTEX.*`, `HAVERSINE`, `VECTOR_COSINE_SIMILARITY` | ❌ no direct equivalent | flag for manual review; don't guess |

**Unrecognized-function rule:** for a Snowflake function not in this table, never guess silently. Two acceptable paths:
1. **Verify-then-apply** — derive a candidate DuckDB mapping and **prove it in the `duckdb` CLI against a synthetic fixture**. If it runs and is correct, apply it and add the row here so the next flow inherits it. This is how `timezone`/`json_group_object`/`unpivot`/3-arg-`dateadd` above were added.
2. **Flag** — if no mapping can be established/verified (e.g. `SNOWFLAKE.CORTEX.*`, `HAVERSINE`), append a `fail` row to `migration_log.csv` (`details="Unsupported function: <name>"`) and leave the flow for manual review.

Pick (1) only when you can actually verify; otherwise (2). Confirm with the operator on anything with subtle semantics (timezones, JSON shape).

### 4c. Materialization decision tree

```
Self-reference to <output>_INPUT in WHERE?
  ├─ YES → materialized='incremental'  (+ unique_key if a PK is known)
  │        wrap the self-reference comparison in {% if is_incremental() %} … {% endif %}
  └─ NO  → default 'view'
           → 'table' / 'incremental' ONLY with a concrete reason (see the reviewer note below):
             a _HISTORY / incremental output mapping, a genuinely large or expensive transform
             whose consumers need it persisted (an OUTPUT another model ref()s — §4i),
             or explicit senior direction
```
Default when unsure: **`view`** — NOT `table`. Never default to `incremental` (a misconfigured incremental silently drops rows).

> **Reviewer convention — materialize as `view`, not `table` (the senior reviewer, recurring).** The senior reviewer has repeatedly flagged `{{ config(materialized='table') }}` with just "view" across MRs — on Flow B (resolved by switching to `view`) and on a history-tracking flow (`model_desc_x`). **Default every model to `view`.** Reach for `table`/`incremental` only when there's a real reason (an incremental/`_HISTORY` output mapping per the note below, a large/expensive transform — e.g. the 12-way UNION in §4e — an OUTPUT another model `ref()`s, which §4i publishes to S3 (`DEC-084`), or explicit senior direction), and **state that reason in the MR reply**. A plain cleaning / passthrough / transform SELECT → `view`.

> **Incremental *output mappings* are invisible in the SQL.** A model can show a plain `SELECT` yet Keboola loads its output **incrementally** (append/history) via the output-mapping config, not the query — symptoms: a `…_HISTORY` output, or a daily-increment table feeding an accumulating store (verified: `EVENT_LOG_A_HISTORY`; `SHARED_TABLE_A` is a 270M-row accumulating table fed by a daily-increment SELECT). The SQL alone can't reproduce this. Model it as `table` for now and **leave an in-file `-- NOTE (pod review):`** flagging the incremental/history semantics + a candidate `unique_key`; convert to `incremental` at pod validation. The append/incremental flag lives in the flow's output mapping (`incremental: true`), confirm via `--inspect` when a `_HISTORY`/increment name shows up.

> **`unique_key` columns MUST be non-nullable.** dbt's incremental merge matches on `dest.col = src.col`, and
> `NULL = NULL` is never true — so any **nullable column in `unique_key`** makes NULL-key rows never match their
> existing row → they are **RE-INSERTED every run and accumulate as duplicate PKs** (2→4→8…), and it's **invisible
> on the full-refresh path** (only the `is_incremental()` MERGE hits it). Verified on a history-tracking flow
> (`model_desc_x_history` had nullable `CURRENCY` in the key, 2026-07-01). Build a key of non-nullable columns:
> drop a redundant nullable col if the rest are still unique **in the legacy table** (check it), or use a NULL-safe
> surrogate (`dbt_utils.generate_surrogate_key`). Always exercise the incremental path (build twice) — see
> [[keboola-validation-skill]] and [[incremental-unique-key-null-safety]].

> **The `unique_combination_of_columns` TEST must assert the SAME grain as the real PK / incremental `unique_key` —
> never a nullable superset.** Corollary to the rule above, and a mistake made on a history-tracking flow (caught 2026-07-01):
> once you drop a nullable column (e.g. `CURRENCY`) from `unique_key`, you MUST also drop it from the model-level
> `combination_of_columns`. A **superset** grain (key columns **plus** a nullable extra) is strictly **weaker** than
> the key: adding a column can only split groups, so two rows sharing the true key but differing on the extra
> (`EUR` vs `NULL`) read as distinct → the test **PASSES while the incremental PK duplicates** — i.e. it fails to
> catch the exact bug the NULL-safe key was built to prevent. So: `combination_of_columns` == the `unique_key`
> column list, verbatim. And put **`not_null` on EVERY key column** (all of `KEY_A, KEY_B, COUNTRY, VALID_FROM`
> — not just `KEY_A`+`VALID_FROM`): each `unique_key` member must be non-null, and the `not_null` test is the
> early-warning that guards the invariant. `CURRENCY` stays untested (nullable by design). See
> [[uniqueness-test-grain-matches-key]].

### 4d. Worked example — incremental self-reference (TABLE_A_90_DAYS)

Before → after (the canonical incremental pattern):

```sql
-- before
CREATE OR REPLACE TABLE PROD_TABLE_A_L90D_CSVBODY AS
SELECT DISTINCT … FROM PROD_TABLE_A
WHERE TO_TIMESTAMP(NULLIF(CREATED_AT,'')) >
      (SELECT MAX(TO_TIMESTAMP(NULLIF(CREATED_AT,''))) FROM PROD_TABLE_A_L90D_CSVBODY_INPUT)
  AND LEFT(METADATA,6) <> '{"new"';
```
```sql
-- after  (file models/00_Project_A/Scheduled_TABLE_A_90_DAYS/TABLE_A_90_DAYS/prod_table_a_l90d_csvbody.sql)
{{ config(materialized='incremental') }}
SELECT DISTINCT … FROM {{ source('00_Project_A', 'PROD_TABLE_A') }}
WHERE LEFT(METADATA, 6) <> '{"new"'
{% if is_incremental() %}
  AND TRY_CAST(NULLIF(CREATED_AT, '') AS TIMESTAMP) >
      (SELECT MAX(TRY_CAST(NULLIF(CREATED_AT, '') AS TIMESTAMP)) FROM {{ this }})
{% endif %}
```
Drop the CREATE; `_INPUT` → `{{ this }}`; `TO_TIMESTAMP` → `TRY_CAST`; the always-true filter stays outside the incremental block; everything else preserved.

### 4e. Worked example — legacy alias + multi-output (Flow F)

`Z_TRANS_A.sql` (legacy, one `CREATE TABLE "OUT.Z_TRANS_A"`, reads `"IN.Sheet_A_Input"`):

```sql
-- after  (file models/10_Project_D/Flow_F/Z_TRANS_A/zcust_t01.sql — basename from CSV output table ZCUST_T01, not the OUT. alias; nested project/flow/transformation per "Folder layout & naming")
{{ config(materialized='table') }}
SELECT 'BGT' AS SOURCE, COL_A, …, CASE … END AS COL_B
FROM {{ source('10_Project_D', 'SRC-SHEET-A') }}
```

`ZCUST_M01_METRICS.sql` is 12 `UNION ALL` blocks; the first 11 read `"IN.ZSRC_T02"` → `{{ source('10_Project_D','ZSRC_T02') }}`, the last reads `"IN.ZCUST_T01"` → `{{ ref('zcust_t01') }}` (intra-flow). All `SUBSTR`/`LEFT`/`||`/`CASE` carry over unchanged; UNION ALLs preserved verbatim (don't refactor into macros). `table` materialization (no incremental pattern).

### 4f. Mutation transformations (`ALTER` / `UPDATE` / `DELETE` / `MERGE`)

A transformation may not `CREATE` a table at all — it **mutates** one that already exists. dbt has no place for in-place mutation: a model is a `SELECT`. Resolve by the mutation's target:

| Mutation | If the target table is **produced in this flow** | If the target is **external** (not produced here) |
|---|---|---|
| `ALTER TABLE t ADD COLUMN c …` + `UPDATE t SET c = <expr>` | **fold into the producing model**: append `<expr> AS "c"` (an `UPDATE … SET c = CASE…` becomes `CASE… END AS "c"`) as the last column of `t`'s `SELECT`. No separate model. | flag for manual review — the source belongs to another flow; log a `fail` row |
| `UPDATE t SET col = <expr> WHERE p` | fold into the producing model as `CASE WHEN p THEN <expr> ELSE col END AS col` | flag for manual review |
| `DELETE FROM t WHERE p` | fold into the producing model as a `WHERE NOT (p)` filter | flag for manual review |
| `MERGE INTO t …` | this is an upsert → the model is `incremental` with `unique_key`; rebuild the merge logic as the incremental `SELECT` | flag for manual review |
| `ALTER TABLE t DROP COLUMN c` | omit `c` from `t`'s `SELECT` (just don't select it) | `t` is a **source** read via `*` → rewrite `t.*` as `t.* EXCLUDE ("c")` in the consuming model. A real translation, **not** a manual-review flag. |

Resolve "produced in this flow" via the live output mapping exactly like Step 3 (the target's storage table appears as some transformation's output in `_flow_tasks.json`). The mutation file itself never becomes its own model — it always folds into the model that builds its target.

**Worked example — `Add_channel_Flow_D`:** `ALTER TABLE "fact_orders_x" ADD COLUMN "COL_CHANNEL"` + `UPDATE "fact_orders_x" SET "COL_CHANNEL" = CASE…`. `fact_orders_x` is this flow's output, so the big `CASE… END AS "COL_CHANNEL"` becomes the final column of the `fact_orders_x` model. The mutation file produces **no** model of its own.

**Worked example — `Flow K` (DROP COLUMN on sources):** `ALTER TABLE "src_cost_a" DROP COLUMN "_timestamp"` + same on `"src_cost_a-daily"`, then `select a.* … from "src_cost_a-daily" a …`. Both targets are *sources*. Only `src_cost_a-daily` is read via `a.*`, so → `a.* EXCLUDE ("_timestamp")`; `src_cost_a` (b) is read by explicit columns only, so its drop is a no-op. (Caveat: `* EXCLUDE` errors if the column is absent — `_timestamp` is a Keboola system column present at load but hidden from the Storage API column list; confirm at pod-validation.)

### 4g. Disabled transformations

A transformation can be **disabled** in Keboola — it lives in the config but does not run. Migrate it, but mark it as inert so it neither builds nor masquerades as a live table:

- **Filename: `<output_table>_disabled.sql`** — the normal lowercased storage-output name with a `_disabled` suffix (e.g. disabled `TABLE_M` → `table_m_disabled.sql`, its YAML `table_m_disabled.yml`). The suffix keeps it out of the live model namespace, so no sibling `ref()`/`source()` accidentally resolves to a transformation that Keboola wasn't actually running.
- **Add `{{ config(enabled=false) }}`** at the top (in addition to the materialization) so `dbt parse`/`compile`/`build` skip it. Convert the SQL body normally anyway (full structural + dialect rewrite) so the model is correct the day it's re-enabled — flip the name back and drop `enabled=false`.
- Still emit the `.yml` (same `_disabled` basename); tests on a disabled model don't run.

**Detecting disabled — live.** Two levels: the **task** is disabled in the flow (`enabled: false` in `_flow_tasks.json`) → the flow doesn't run it at all; or a **code/row** inside an enabled transformation is disabled (legacy → `parameters.transformations[].disabled`; row-based/newer → `rows[].isDisabled`). Confirm via `--inspect` when unsure; never infer "disabled" from an empty/sample-only SQL body (that's a passthrough, not a disabled transformation).

### 4h. Passthrough / copy transformations (empty, sample-only, or `queries=0`)

Many transformations do **no real work** — they copy an input table to an output through Keboola's input/output **mapping**, with no meaningful SQL. Three shapes, all the same thing:
- the downloaded `.sql` is just the placeholder sample comment (`-- This is a sample query…`),
- it's empty,
- or **no `.sql` file was written at all** because the legacy config entry has `queries: 0` (the downloader only writes non-empty code) — confirm via `--inspect`.

These are **not** disabled (§4g) and **not** skipped — downstream flows read their output tables, so dropping them breaks the DAG. Migrate each as an **explicit-column copy**. Do **not** write `SELECT *` (Step 5 forbids it, and output mappings frequently select a column *subset* — verified: `TABLE_X`→11 cols and `TABLE_X_EXT`→25 cols both copy from the same input). Instead fetch the output table's real schema and list its columns:

```bash
# columns + primaryKey for a Keboola table (same per-project token as the downloader)
curl -s -H "X-StorageApi-Token: $TOKEN" \
  "https://connection.keboola.example/v2/storage/tables/<output Table ID>" \
  | python3 -c "import sys,json;d=json.load(sys.stdin);print(d['columns']);print(d['primaryKey'])"
```

```sql
-- <output_table>.sql
{{ config(materialized='table') }}
select
    "COL1", "COL2", ...        -- the fetched output columns, quoted to preserve case
from {{ source('<project_slug>', '<input Table Name>') }}
```

One template, three jobs at once:
- **sample-only / empty / `queries=0`** → straight copy of the fetched columns.
- **`_timestamp`-drop** (`ALTER … DROP COLUMN "_timestamp"`, §4f) → the fetched output schema *already* excludes `_timestamp`, so the explicit list **is** the drop. Prefer this over `* EXCLUDE` when you have the schema — no missing-column caveat.
- gives the per-column YAML for free (Step 5).

Gotchas (all verified):
- **404 on the output table** (not materialized yet) → fetch the **input** table's columns instead; for a passthrough, output cols = input cols.
- **Schema drift — trust the fetched schema ONLY for passthroughs.** For a real transform (§4a/4e), the stored output table can carry *more* columns than the current SQL emits (e.g. `TABLE_B`: 59 stored vs 36 in the SQL). There, the model's columns come from the **SQL's `SELECT`**, not the fetched schema.
- **Bulk flows** (dozens of passthroughs — one bulk flow had 89): fetch all output schemas once into a JSON, generate the regular models with a **throwaway** script, and hand-write only the bespoke transforms. Don't commit the generator — only `main.py` is sanctioned Python.
- Quote identifiers in **UPPERCASE** to match Keboola's column case and the `quote: true` YAML; unquoted identifiers fold to lowercase in DuckDB and won't match.

### 4i. Wire the S3 publish hook on every OUTPUT model — `copy_relation_to_s3()` (`DEC-084`)

Every **output** model (same classification as the 🔴 rule in Step 5: a table in the flow's LIVE Storage
output mapping, intermediate-datamart buckets included) carries the publish post-hook, except a filtered
variant (below). Intermediates never do. The hook is the channel Gate 2 publishes the chain through
([[keboola-chain-validation-skill]], `DEC-082` / `DEC-083`); nothing goes to `dwh-out` before that. Leave it out,
and the output cannot reach `dwh-out` when its chain passes.

```sql
{{ config(
    materialized='table',
    post_hook="{{ copy_relation_to_s3() }}",
) }}
-- Flow OUTPUT model → also copied to S3 as Parquet by the copy_relation_to_s3 post-hook
-- (<one line: why table / incremental / view — the materialization reason below>)
```

- **No path argument.** The macro derives `s3://dwh-out/<project>/<flow>/<relation>.parquet` from the
  folder layout (`docs/S3_EXPORT.md` §1), and an `alias` replaces `<relation>`.
- **Materialization (`docs/S3_EXPORT.md` §2).** `table` (or the `incremental` §4c already gave it)
  when the output is heavy or another model `ref()`s it, in this flow or another. A `view` output
  re-runs its whole query at COPY time and again for every consumer. `view` stays right for a light,
  terminal output. That is the concrete reason §4c's `view` default asks for, so put it in the header line.
  **Never `ephemeral`:** the hook on an ephemeral model is a silent no-op.
- **Not on a filtered / windowed variant** (a `*_filtered` version, a 3-month slice). It aliases to the
  production name, so it would publish the slice as full history, and the row-count verify cannot tell
  (the `copy_relation_to_s3.sql` header explains why). Its production twin carries the hook. The check
  shows a hook-less filtered variant ✅ and one with a hook ⚠. The 8 versioned models of one source project on
  `qa` carry it, so every build of their filtered version must pass `publish_to_s3: false`.
- **Nothing publishes before Gate 2** (`DEC-083`). `publish_to_s3` becomes false by default (macro change in
  the client repo, reviewed by the senior reviewer). Until that merges, every build — validation, proof, a scratch run, a
  pod-built upstream — passes `--vars '{publish_to_s3: false}'`, and only Gate 2 passes `true`. A local
  `dbt parse` or `dbt ls` writes nothing.
- **Check it** once Step 5's yml files exist (run from the repo root), passing the live output models:
  `python3 .claude/skills/keboola-migration-skill/check_s3_publish.py models/<project_slug>/<flow_dir> --outputs <model>,<model>`.
  No row may be ⛔. `--outputs` is the authority: without it the check falls back to *publish hook ⇔
  data tests*, which misreads an output with no ID/PK (`DEC-009` asks no test of it, so it has none —
  first hit on an earlier flow's `coef_table_x`). With it, a listed output without tests is ⚠ (needs the
  no-PK NOTE), and an unlisted model with tests is ⛔. So a ⛔ means the hook or the tests are wrong. Fix whichever is wrong;
  never mute the check. A ⚠ row (a helper with no yml, a filtered variant) is reported, not failed. On
  `qa` 106 of 115 flows pass today. The 9 that fail predate the outputs-only test rule (tests on
  intermediates, or one bulk pipeline with no yml). The check is for the flow you are
  migrating, not an audit of `qa`.

## Step 5 — Generate the model YAML(s)

One `.yml` beside each `.sql`, same basename. Rules:
- `version: 2`; one model entry; **every column `quote: true`**; **no `description`**.
- **No top-level `tags:` property under the model** — Fusion rejects it (`Property tags is not allowed`). Project/model tags are set in `dbt_project.yml` (Step 5c). The per-**test** `config: tags:` inside `data_tests` (Step 5b) is a different thing and stays valid.
- Columns come from the converted model's `SELECT` list. If the model is a passthrough `SELECT *`, **fetch the output schema (§4h)** to enumerate the columns — don't ship `SELECT *` and don't stop to ask. Only stop for the operator if the schema can't be fetched (404 on both output and input).

### 🔴 Tests go on OUTPUT models only — intermediate models carry NO tests (the senior reviewer, 2026-08-27)

Classify each model by **its position in the flow's DAG**, not by its filename:

- **Output model** — a model whose target is a table in the flow's **live Keboola Storage output
  mapping** (`out.c-<bucket>.<TABLE>`, resolved through the output-mapping rosetta-stone in the Step 4
  conversion table — "In-SQL table name ≠ storage output name"). These carry the **full** test surface:
  the Step 5 best-practice layer **and** the Step 5b reconciliation layer. (An output model may still be
  read by another model in the flow — being consumed downstream does not stop it being an output.)
- **⚠ Self-relay exception (`DEC-059`, 2026-10-02):** a table in the output mapping that **only this same
  flow reads back** is Keboola plumbing — the only way one legacy transformation hands data to the next — and
  counts as **intermediate**. Check per table, now at P3, all three: (1) `analyses/live/Weeks-ALL.csv` has no
  `Direction=input` row for it in any OTHER flow; (2) no writer/app component reads it (live configs);
  (3) DWH-KBC does not publish it as `INOUT=OUT`. If all hold → no tests; its values are still reconciled
  through the flow's real outputs, which carry them on the same key. On an earlier flow, 13 `out.c-bucket_m.OUT_*`
  were read only by the flow's own merge → intermediate; only `OUTPUT_A` / `OUTPUT_B` are tested.
  (Treating them as outputs had cost 13 extra references and a night-window refresh request to the data owner.)
- **Intermediate model** — any model that is **not** in the output mapping: an internal node of the DAG
  that exists only to build the output model(s) downstream of it. Decided by **DAG position, not the
  name** — `out_model_x1` is intermediate because nothing in the mapping points at it; a
  plainly-named model is an output when the mapping does. Intermediate models get **NO `data_tests` at
  all** — no reconciliation, no `same_values_enhanced`, and **no `unique` / `not_null`, not even on an
  `ID` / PK column**. The `.yml` is just `version: 2` + the model entry + the column list with
  `quote: true` (no `description`, no `data_tests:` key).

> **No tests does NOT mean no `.yml`.** Every model you create gets one, intermediate or output. One MR
> (2026-09-24) reached review with 41 intermediate models and no `.yml` at all, and the senior reviewer caught it.
> The client-repo pre-commit hook (`hooks/keboola-pre-commit`, guard 4) now blocks a commit that ADDS a
> `models/**/*.sql` without a `.yml` in the index. Do not `--no-verify` past it; write the yml. Take the
> column list from the model's final SELECT (for `select *` / `x.*`, follow the CTE / `ref()` it reads).
> Before handing off to validation, run
> `for f in $(git ls-files 'models/<flow dir>/*.sql'); do [ -f "${f%.sql}.yml" ] || echo "$f"; done`
> — it must print nothing.

Worked example — `.../10_Flow_L/`: `fact_service_x` and
`fact_service_x_ext` are the two tables in the Storage output mapping → full tests. Every
other model in the folder is a DAG node feeding those two and is not itself in the mapping →
intermediate → bare column-list `.yml`, zero tests. (`out_model_x1` included — the `out_`
prefix is not what makes a model an output.)

**Why:** the reconciliation that matters is new-output == legacy-output; an intermediate node has no
legacy Storage counterpart to reconcile against, and per-model `unique`/`not_null` across dozens of
internal models just slows every `dbt build` in the validation loop for no production signal — this is
the "make flow validation faster" change. It **narrows the test surface** of the "ID/IDs
`unique`+`not_null` on every model" mandate (the senior reviewer, 2026-06-29) to **output models only** — this is
**strictly about which models carry `data_tests`**; it changes nothing else in that rule.

### Best-practice data tests (in addition to reconciliation) — OUTPUT MODELS ONLY

> **🔴 TWO TEST LAYERS WITH DIFFERENT LIFETIMES — do not conflate them.** (the architect, 2026-08-03.)
> - **Reconciliation tests** (Step 5b: `no_missing_rows_enhanced` / `no_additional_rows_enhanced` /
>   `same_values_enhanced`) are **TEMPORARY migration scaffolding — REMOVED before production.** Their only
>   job is proving new == old while this migration runs. A permanent recon WARN is therefore **never** a
>   production concern, and a vacuous recon test costs validation confidence, not production correctness.
> - **Best-practice data tests** (this section: `unique` / `not_null` / `unique_combination_of_columns`) are
>   the **PERMANENT** layer. These are what actually guard the model in production — so when weighing
>   "is this model safe to ship", weigh these.
>
> ⚠ Do **not** infer recon-test lifetime from the plumbing: the shipped `profiles.yml` attaches `kbc_stg` in
> both `dev` and `prod` targets and `sources.yml` maps `stg_*` → `kbc_stg`, which makes recon tests *look*
> permanent. The plumbing outlives the tests. Same note, with the consequences spelled out, in
> [[keboola-validation-skill]].

These are the standard dbt best-practice tests, written into **each output model's** `.yml` (never an intermediate model's — see the 🔴 rule above) — a *separate, permanent* data-quality layer alongside the (temporary, migration-only) reconciliation tests of Step 5b. Get the PK from the fetched `primaryKey` (§4h). Apply **mechanically** — this is a breadth-first ~45-project migration and a senior validates each flow, so generate what's safe and leave the judgement calls flagged:

| Test | Where | Apply when |
|---|---|---|
| `not_null` | column | on **every** primary-key column (single **and** composite) |
| `unique` | column | PK is a **single column** |
| `dbt_utils.unique_combination_of_columns` | model level | PK is **composite** — list **exactly** the key columns (this is the uniqueness contract a composite key needs; plain `unique` can't express it). **`combination_of_columns` must equal the incremental `unique_key` verbatim — never a nullable superset** (a superset grain PASSES while the PK dups; a history-tracking flow, 2026-07-01). See [[uniqueness-test-grain-matches-key]]. |
| `not_null` | column | on **EVERY** primary-key / `unique_key` column — all parts of a composite key, not just some (missed `KEY_B`/`COUNTRY` on a history-tracking flow). Each key member must be non-null; this test guards that. |
| `not_null` | column | on **foreign-key columns** — any `*_id`/`*_ID` column that names another entity (`promo_id`, `party_id`, …). The senior reviewer infers "FK → not-null test" from the name and asks for it (recurring: a history-tracking flow). Skip **only** if the column is genuinely optional/nullable-by-design → verify on the pod (a history-tracking flow's `promo_id` = 99.96% NULL) then leave `# NOTE (senior review): <col> nullable by design`. |
| `accepted_values` | column | **only** where the valid domain is genuinely known (small enum/flag you can see). Never guess — if unknown, **skip** and leave `# NOTE (senior review): candidate accepted_values` |
| `relationships` | column | **only** where the parent is present in the project (an intra-flow `ref()` sibling or a declared `source()`). With one-flow-per-branch the parent is usually absent → **skip** + `# NOTE (senior review): candidate relationships` |

- **`severity: warn`** on all of them (the project has no global `tests:` default, so set it explicitly on each — same as reconciliation).
- **Fusion arg nesting** (same rule as Step 5b): a test that takes parameters nests them under `arguments:`, with `config:` as a sibling. Arg-less tests (`not_null`, `unique`) take just `config:`.
- `unit tests` and `snapshot/regression tests` are a **future tier** — not generated in this round.

> **ID / IDs column rule — senior-mandated (the senior reviewer, 2026-06-29).** One narrowing since (the senior reviewer, 2026-08-27):
> the **`unique` + `not_null` TEST requirement below applies to OUTPUT models only** — intermediate models
> carry no `data_tests` at all (🔴 rule above), so the tests are simply not written on them. Everything
> else in this rule is unchanged.
> On an **output** model the identifier tests are non-negotiable. The model's **identifier column(s)** — any column named `ID`/`IDs` (case-insensitive), and equally a row-identity column such as a `UUID` **even when the Storage-API `primaryKey` doesn't name it** — **MUST always carry both `unique` and `not_null`** in the `.yml`, in **every output model** that has one. This is the default on every output model, not only where a PK is declared (it generalises the table above: don't wait for `primaryKey` to flag the ID). A single identifier → column-level `unique` + `not_null`; a multi-column identifier → `dbt_utils.unique_combination_of_columns` at model level **plus** `not_null` on each part. Don't duplicate when the ID is already the PK handled above. The **only** way to omit these on a given output model is if they actually surface a WARN on the real pod run (validation, [[keboola-validation-skill]]): then drop the offending test **on that one model**, leaving an inline `# <test> removed — <documented justification>` comment. No silent omission — absent a justified removal, an output model's ID/IDs columns have `unique` + `not_null`. **If a model has NO identifier at all** (Storage `primaryKey` empty *and* no `ID`/`IDs`/`UUID`/`*_id` column to serve as one), do **not** ship it silently — the senior reviewer will comment *"ID missing, please explain"* (recurring: a history-tracking flow). Leave an inline `# NOTE (senior review): no primary key on <table> — <why it has none / candidate natural key>` in the `.yml` and call it out in the MR reply.

```yaml
version: 2
models:
  - name: <model_name>
    data_tests:
      # composite PK only — omit when the PK is a single column
      - dbt_utils.unique_combination_of_columns:
          arguments:
            combination_of_columns: ['<KEY1>', '<KEY2>']
          config:
            severity: warn
      # NOTE (senior review): candidate relationships — parent not present in this flow
    columns:
      - name: <KEY_COL>
        quote: true
        data_tests:
          - not_null:
              config:
                severity: warn
          # - unique:            # add this instead of unique_combination when PK is single-column
          #     config: { severity: warn }
      - name: <ENUM_COL>
        quote: true
        data_tests:
          # NOTE (senior review): candidate accepted_values — fill in the valid domain if known
      - name: <COL>
        quote: true
      # …
```

## Step 5b — Wire reconciliation tests onto the OUTPUT model YAML(s)

Reconciliation is the **migration-validation** layer — *temporary*, proves new == old, runs on the pod via Elementary (distinct from the *permanent* best-practice data tests in Step 5). Reconciliation = proving the **new dbt model** reproduces the **legacy Keboola output** 1:1. Add these custom tests (defined in `tests/generic/`, shipped with every branch) to **each output model's** `.yml` — **never an intermediate model's** (🔴 rule in Step 5: an internal DAG node has no legacy Storage table to point `reference` at) — with `reference` pointing at the **legacy/old version of that same table** (the source of truth):

| Test | Level | Warns when |
|---|---|---|
| `no_missing_rows_enhanced`    | row    | a row is in the reference (old) but **missing** from the model (new) |
| `no_additional_rows_enhanced` | row    | a row is in the model (new) but **not** in the reference (old) |
| `same_values_enhanced`        | column | a column **value differs** between model and reference for the same key |
| `not_all_null_values` (bonus) | column | a column is **entirely null** |

**The reference is a `source()` to the legacy output table.** Declare that legacy Keboola output table in the central `sources.yml` under its project slug (same Step 3 sanitization), then `reference: source('<slug>', '<legacy Table Name>')`. Because the legacy data lives on the pod (S3 domain views), these tests are **authored here (locally) but RUN on the pod by [[keboola-validation-skill]]** against the real legacy `source()`. (The full behaviour — each test catching its missing/extra/changed row and Elementary rendering the differing rows — runs via the pod's dbt-core 1.11; the pod is dbt-core, not Fusion, so `edr` + the reconciliation macros run directly.)

> ⚠ **MANDATORY GATE — verify the recon reference's PROVENANCE before wiring it, not just that a
> plausibly-named pod view exists (Flow X `zcust_c01` vs Flow Y `ZCUST_C01` — see `HELP/FIXES.md`).** A common/
> generic business-object name (a SAP transaction code, a warehouse/stock-order key, …) can be produced by
> **two unrelated flows**, staged by the data owner under similarly-spelled filenames but potentially **different
> `kbc_stg` schemas** (Flow X's real `ZCUST_C01` reference lives in `stg_src_c.zcust_c01_c`, NOT the
> domain-obvious `stg_src_d` — a plain `zcust_c01` view sitting in `stg_src_d` was Flow Y's, a
> different flow entirely). Wiring `reference: source('stg_*', 'X')` against whichever pod view merely has
> a matching/plausible `name:` in the schema you happened to check — instead of the one that's actually
> YOUR flow's staged file — produces a **plausible-looking, non-obviously-wrong recon**: if the two flows'
> tables share real business keys (e.g. one is downstream of the other via `ref()`/a linked bucket), the
> WARN counts still resemble a normal "frozen-snapshot recency" gap (large `no_additional`, `no_missing`
> near-zero, `same_values` near-clean) — nothing about the shape of the WARNs signals "wrong table." It
> shipped, merged, and passed review this way on Flow X before the mismatch was caught independently while
> migrating Flow Y.
> **Fix — before wiring ANY new `reference:` to a `stg_*` table, cross-check its row count against
> DWH-KBC, not just its existence, and search WIDE for candidates:**
> 1. Look up the flow's OWN output row in `analyses/live/DWH-KBC.csv` (keyed on `BUCKET_TABLE` = the live
>    Table ID for the SPECIFIC bucket you're migrating, e.g. `out.c-<your-bucket>.<TABLE>`) — note its
>    `OUTPUT_FILE_NAME` and `KBC_ROWS`.
> 2. Run `SELECT database,schema,name FROM (SHOW ALL TABLES) WHERE upper(name) LIKE '%<fragment>%'`
>    against `kbc_stg` — **across every schema, not just the one whose name matches your project/domain**
>    (a table can land in an unrelated-looking schema — `stg_src_c` held another domain's flow's reference).
>    A first pass scoped to one schema found nothing and wrongly concluded the table was "never loaded";
>    it was one schema over.
> 3. For each candidate, `SELECT count(*)` and compare against `KBC_ROWS` (within recency drift — not off
>    by 10x+, and never matching a DIFFERENT bucket's row count instead). If counts disagree but a
>    candidate's **column names match your model's own naming** (not a sibling flow's renamed variant),
>    don't discard it on the count mismatch alone — confirm with a join-proof (next step) before
>    concluding it's the wrong table OR that nothing is available.
> 4. **Prove it, don't just glance at the count:** join the candidate against your (already-built) model
>    on the natural/business key and confirm ~100% of the candidate's rows are found with matching values
>    on a value column you know should agree. A same-named-but-wrong view can still have a plausible row
>    count; a real join-proof is what actually confirms provenance.
> 3. If a same-named table exists in more than one flow (verified by diffing the two flows' legacy SQL —
>    same pattern as the shared-config-duplicity check), **disambiguate both the `sources.yml` table name
>    AND the dbt model name** for the non-canonical one (suffix convention: match the data owner's own file-prefix,
>    e.g. `_SRCB`/`_srcb`) — never let an un-suffixed, "canonical-looking" pod view name win by default.
> Skipping this is exactly how Flow X's `zcust_c01` ended up silently reconciling against Flow Y's data instead
> of its own for a full validation-and-review cycle.

### The pattern

Row tests go at **model level**; value tests go **per column**. `source_id_columns` = the **model's** key(s); `reference_id_columns` = the **reference's** key(s) — list them even when identical, and give different names when the model renamed a key (e.g. model `Primary` ↔ legacy `ID`).

```yaml
version: 2
models:
  - name: <model_name>                              # the NEW dbt model under test
    data_tests:
      - no_missing_rows_enhanced:
          arguments:
            reference: source('<slug>', '<legacy Table Name>')
            source_id_columns: ['<MODEL_PK>']        # model side key(s)
            reference_id_columns: ['<LEGACY_PK>']    # reference side key(s)
          config:
            severity: warn
      - no_additional_rows_enhanced:
          arguments:
            reference: source('<slug>', '<legacy Table Name>')
            source_id_columns: ['<MODEL_PK>']
            reference_id_columns: ['<LEGACY_PK>']
          config:
            severity: warn
    columns:
      - name: <COL>
        quote: true
        data_tests:
          - same_values_enhanced:                    # one per value column you want checked
              arguments:
                reference: source('<slug>', '<legacy Table Name>')
                model_id_columns: ['<MODEL_PK>']
                reference_id_columns: ['<LEGACY_PK>']
                column_name: '<COL>'
                reference_column_name: '<COL>'
              config:
                severity: warn
```

### Rules

- **`severity: warn` on every reconciliation test** — you want to SEE all diffs in the report, not halt the build on the first difference.
- **Fusion strictness (verified — these are why the macros/YAML look the way they do):**
  - Test args MUST nest under an `arguments:` key, with `config:` as a **sibling** of `arguments:` — args at the test's top level → `dbt1159`.
  - The macro's `config(description=...)` must be a **plain string**, not a list → a list trips `dbt1501`. The shipped macros already comply (`no_*_rows_enhanced` use a string; `same_values_enhanced` sets none).
- **Keys (a JOIN anchor here, not a uniqueness assertion):** take the key from the fetched `primaryKey` (§4h). Unlike Step 5's `unique`/`not_null` rule — which skips composite keys because they're not a clean uniqueness contract — a **composite key is fine here**: the macros LEFT JOIN on the COALESCEd key columns, so list all of them in both `*_id_columns`; a single-column PK lists one. No usable key → the row tests can't anchor; skip them, keep `same_values_enhanced` only where a key exists, or flag for pod review. (When keys match on both sides, list them identically — the "enhanced" arg names are always safe.)
- **`same_values_enhanced` is one test per value column.** Don't blanket every column — pick the meaningful value columns; skip the key columns (the row tests already cover those).
- **No `description`s** anywhere (Step 5 convention).
- The `source()` resolves to the real legacy view only on the pod — [[keboola-validation-skill]] runs the row-by-row comparison there and loops until 0 unexplained WARNs; locally you only verify the wiring parses (`dbt parse`).

## Step 5c — Register the flow's folders in dbt_project.yml

Tags are applied through `dbt_project.yml`, not the model YAML. **Merge** this flow's `project → flow → transformation` nesting into the `models:` block — append-only, exactly like the Step 3 `sources.yml` merge: leave every other flow's block and the `elementary` / `flags` / `vars` / `tests` config untouched.

Template + concrete worked example (`Scheduled TABLE_A_90_DAYS` in `00 Project A`):

```yaml
models:
  # post-hooks:                              # placeholder — project/flow post-hooks land here later
  keboola_migration:                         # ← project NAME; the hierarchy MUST nest under it
    <project_slug>:                          # = folder name = source() slug, e.g. 00_Project_A
      <flow_dir>:                            # e.g. Scheduled_TABLE_A_90_DAYS
        <transformation_dir>:                # e.g. TABLE_A_90_DAYS
          +tags: ['<project_slug>']          # tag = the project slug, at the transformation level

  # ── e.g. the TABLE_A flow resolves to: ──
  # keboola_migration:
  #   00_Project_A:
  #     Scheduled_TABLE_A_90_DAYS:
  #       TABLE_A_90_DAYS:
  #         +tags: ['00_Project_A']

  elementary:
    +schema: elementary
```

**Rules / traps (verified):**
- The **`keboola_migration` project-name key is mandatory**. Drop it and dbt treats the whole block as an unused config path (`dbt1097`) — the tags silently never bind. ⚠️ The manager's notes show the block *without* this wrapper (`models:` → `00_Project_A:` directly) and with a `00_Project__A` folder vs `00_Project_A` key; that exact form does **not** bind tags. Both are corrected here — keep the wrapper and one consistent spelling.
- The three keys must **match the on-disk folder names character-for-character** (same sanitization as the layout rules). A drift = silent no-op.
- `+tags` goes at the **transformation level** (mirrors the reference). It cascades to every model in that dir.
- **Verify it actually bound**, not just that parse succeeds: `dbt ls -s tag:<project_slug> --resource-type model` (locally — Fusion auto-installs the packages) must list this flow's models. An empty list = the keys don't match the folders.

## Step 5d — Re-run P2 over the model's ACTUAL inputs, then STOP

Migration's **last step** is to hand the model back to [[keboola-readiness-skill]] in
**post-migration mode** (`HELP/CHAIN.md`). This is not the same check P2 already did: it ran on the
*declared* inputs, and you now have the *actual* ones — every `source()` and `ref()` call in what you
just authored. Rows flip between the two lists, in both directions, because the sheet over- and
under-declares. Feed P2 the real list and let it own the verdicts; the checks below are the part of the
old gate that is specific to handing off, and they stay here.

Migration's **last step**. The model + tests now live on the local branch (Steps 3–5c), `dbt parse` is clean and the tag binds. Before handing off, confirm validation *can* actually run — the pod is reachable and the flow's real source/legacy data is loaded on S3. This is a **lightweight gate, NOT the validation itself** (the branch upload, `dbt build`/`dbt test` loop, WARN triage, and fixes are owned by [[keboola-validation-skill]]).

1. **Pod + VPN reachable:** `kubectl exec "$KEBOOLA_POD" -n "$KEBOOLA_POD_NAMESPACE" -- whoami` (pod config from the repo-root `.env-skill`). If it fails with `dial tcp: lookup apiserver.… no such host`, the VPN **VPN is disconnected** — STOP and ask the operator to reconnect, then retry. An `Unauthorized` error → re-login. Both in [[k8s-prd-auth-fix]].
2. **Data present on S3:** confirm the flow's inputs + legacy output tables exist in the attached S3 DBs (`kbc_in` / `kbc_stg` / `ora`). **Cross-reference `HELP/DATA_ACCESS.md` FIRST** — if the flow (or its domain schemas) is already in the per-flow map there, a quick re-confirm is enough; otherwise attach the S3 DBs and check the tables are present (the attach preamble + domain-view naming live in `HELP/DATA_ACCESS.md`).
2b. **Consolidate into a per-output-table table — don't let a per-model gap stay silent (verified missing on Flow Y `table_c03_srcb`, 2026-07-28).** Step 5b already discovered, one model at a time, whether each output's legacy recon reference exists on the pod (that's what "no legacy reference on pod (404) — best-practice tests only" means when you hit it while wiring a test). Before deciding, pull those per-model findings together into one explicit list — every output table this flow migrates, ✅ has a recon reference / ❌ doesn't — so a partial gap is a visible decision point, not something quietly absorbed into one model's YAML while the rest of the flow moves on unremarked:
    ```
    table_c01_srcb  ✅ srcb_table_c01
    table_c02_srcb  ✅ srcb_table_c02
    table_c03_srcb  ❌ no table_c03 / srcb_table_c03 view on the pod
    table_c04_srcb  ✅ srcb_table_c04
    table_c05_srcb  ✅ srcb_table_c05
    zcust_c01_srcb  ✅ zcust_c01
    ```
3. **Decide:**
   - **All outputs present → STOP and recommend [[keboola-validation-skill]]** — tell the operator **"ready for validation"**. The operator invokes the validation skill next (validation → when clean → pushing), or, when [[keboola-orchest-skill]] is driving, this line is its GO (`DEC-086`). **Mark it migrated:** update `MIGRATION_STATUS.md` (repo root — gitignored, local-only) — **upsert by flow name** (`## <flow name>` block; create from its TEMPLATE if absent) and set **`Migrated: ✅`** (leave `Validated`/`Pushed`/`MR` for the downstream skills). Breadcrumb: `echo "<flow_id>,,${CURRENT_FLOW},ready_for_validation,$(date -Iseconds),data on pod — recommend validation" >> migration_log.csv`.
   - **Some outputs present, some missing (partial)** → this is a decision, not a default: **tell the operator explicitly** which outputs lack a reference and ask whether to (a) proceed to validation for the covered outputs now, shipping the uncovered ones on best-practice tests only with an in-file note + a flagged data-owner ask, or (b) hold the whole flow until the data owner stages the rest. Don't silently pick (a) — record whichever the operator chooses in `MIGRATION_STATUS.md`, and only then hand off.
   - **All outputs missing / mistyped** (an IN domain not loaded; date-as-text→NULL) → **do NOT hand off to validation.** Tell the operator and **draft the data-owner message** ([[in-typing-fix-process]]; the message style + template live in [[keboola-validation-skill]]). Resume once the data owner confirms the load.

> This gate does **not** run `dbt build`, classify WARNs, or fix models — that's the validation skill's loop. It only answers "is the data there so validation can start?" then recommends the next skill.

---

## The rest of the chain — validation & pushing (separate skills, triggered next)

Migration ends at the Step 5d readiness gate. Validation and pushing are their own skills, run next. Each ends by recommending the next, and the operator invokes it, unless [[keboola-orchest-skill]] is driving (`DEC-086`):

- **[[keboola-validation-skill]]** — **uploads the branch to the pod scratch** (its Step 0), runs the real `dbt build`/`dbt test` against live pod data (the pod is dbt-core `1.11.x`, not Fusion — reconciliation tests + Elementary run directly), loops to **0 unexplained WARNs** (fix migration bugs / justify-drop invalid tests / accept+document expected diffs), **always consulting `HELP/FIXES.md`** on any error or WARN. Any pod-side fix gets **synced back to the local branch** (validation's final step). If issues remain it **asks the operator**; when clean it **recommends [[keboola-pushing-skill]]**. Mechanics: [[keboola-validation-skill]] + its `VALIDATION.md`, `HELP/DATA_ACCESS.md`, `HELP/FIXES.md`.
- **[[keboola-pushing-skill]]** — **commits the validated files already on the branch** this skill created at Step 1 (targeted `git add`, secret-guard, `dbt parse` structure gate), then handles the **push + MR into `qa`** + the Productive completion comment. (This is the old Step 6 + push, now consolidated there.)
- **Elementary report** (for the reviewer): build elementary models FIRST, `edr` in a venv, pull the self-contained HTML local and `open` it (the `http.server` port isn't reachable from the laptop when started via `kubectl exec`) — steps in `HELP/HOW_TO_VALIDATE.md` (Elementary section), [[elementary-pod-runbook]].

## Where this phase sits

**P3 of the chain — see `HELP/CHAIN.md`.**

| | |
|---|---|
| **Entry** | P2 PASS *for migration* — [[keboola-readiness-skill]] has emitted its table and no row blocks migrating. An unmerged cross-flow producer does **not** block this phase — nor P4; it gates only MR order (`DEC-052`). A producer nobody has migrated does not block either since `DEC-082` (2026-10-06): P3 wires `ref()` to the producer's model name (agree the name with the producer's task) and keeps a **local, uncommitted** stub of that model so `dbt parse` passes; P4 validates on the producer's same-run staged copy; the MR merges only after the producer (`DEC-006`). No P2 result → go run it first. |
| **PASS** | branch off fresh `qa` exists; every in-scope output has `.sql` + `.yml`, **with the recon layer on every output except the three cases `HELP/CHAIN.md` P3 enumerates** — (a) a pure projection whose source output already carries it (`DEC-066`), (b) an output whose reference the data owner has PARKED (`DEC-025`), the ship/no-ship call being the operator's, (c) an output whose reference is staged nowhere and undeclared (`DEC-073`; `DEC-050(b)` still forbids fetching or building it ourselves — STOP and draft the ask) — recon layer DEFERRED, the flow ships authored-but-parked and the row blocks P4 only (an earlier flow's `CATALOGUE_TABLE_X` as of 2026-08-20; staged 2026-08-31 and its recon suite restored — the layer is owed, not waived). The permanent layer (`DEC-009`) stays mandatory in all three; no fourth case (`DEC-051` + `DEC-073`). ⚠ Dropping an INDIVIDUAL unscopeable population test is a different axis and needs no exception. `check_s3_publish.py` shows no ⛔ row: every output carries the publish hook except a filtered variant, and no intermediate does (§4i, `DEC-084`) — the hook publishes nothing before Gate 2 (`DEC-083`). The task is at Work in progress, or the report says why the guard left it (Step 1, `DEC-085`). Then: `dbt parse` clean; tag binds; **and P2 re-run in post-migration mode over the model's actual `source()` / `ref()` calls** (Step 5d) |
| **Stop** | conversion blocked · parse errors · the P2 re-run turns up a row that blocks validation, which is reported, not worked around |

**The migrate/skip gate is NOT here.** It used to be duplicated in this file, which meant two copies of
one rule that could drift apart — the exact failure `HELP/DECISIONS.md` exists to prevent. It is
[[keboola-scope-skill]] (P1), it runs before this phase, and its verdict plus its type-of-source list are
this skill's input. Do not re-derive either: if you do not have them, the phase has not been entered
properly.

Priority — *which* flow — is [[keboola-flowpick-skill]], and it runs before P0.

## Open questions

1. **Repo push target** — migration creates the branch (Step 1, off a fresh `qa`) but **never commits or pushes**: it authors locally (uncommitted) and stops at the Step 5d readiness gate. **All git after the branch** (commit, push, `glab`-free MR into `qa` via push options, HTTPS PAT auth, clean same-history diff) lives in [[keboola-pushing-skill]]. **Layout RESOLVED 2026-06-30:** the project is root-level, matching `qa` (no more nested-vs-root diff — see [[dbt-project-root-level-structure]]).
2. **dbt target** — DuckDB (our prototype) vs Snowflake (manager's reference). Affects only the eventual pod validation.
3. ~~**PK identification for YAML tests**~~ — RESOLVED 2026-05-27, extended 2026-06-16: pull `primaryKey` from the Storage-API table fetch (§4h). Single-column PK → `unique`+`not_null`; **composite PK → `dbt_utils.unique_combination_of_columns`** (no longer "no test" — `dbt_utils` is now declared in `packages.yml`). `not_null` on every key column either way. Full best-practice test rules in Step 5.
4. ~~**CSV coverage**~~ — RESOLVED 2026-07-13: the weeks-1–2 manifest is **retired** (it was stale/mis-attributing). The downloader + pre-flight gate now read the flow's contents **live from Keboola** (any flow/week, no export needed). Flow priority still comes from the analyzer web tool / the operator. See [[manifest-stale-verify-live-keboola]].
5. **migration_log.csv** — stays local for now; full BigQuery state logging is parked with validation.
6. ~~**Central sources.yml vs orphan branches**~~ — RESOLVED 2026-05-27; pod-first detour 2026-07-02 → **REVERTED 2026-07-13 (local authoring)**: authoring is local on the branch created **off a fresh `origin/qa`** at Step 1, and [[keboola-pushing-skill]] commits with a **targeted `git add`** (this flow's model dir + the accumulating `sources.yml`/`dbt_project.yml`) — **not** `git add -A`, **not** an orphan snapshot. Clean same-history diff of just this flow.
7. **Per-project source physical mapping** — the slug (`30_Project_H`) is the dbt source `name` only. On the pod each project is a distinct warehouse database/schema, so each source block will eventually need `database:`/`schema:`. Parked with pod validation; needs the real DB/schema names per project.
8. ~~**Cross-flow `source()` → `ref()` stitching**~~ — RESOLVED, superseded by `DEC-006` (2026-07-22) and `DEC-082` (2026-10-06): an in-scope cross-flow producer is wired `ref()` in the committed model, a not-yet-migrated one on a local uncommitted stub. The history below is kept for the type-contract gotcha only. ~~Today every cross-flow input is a `source()` (see Step 3): the per-flow CSV slice has no cross-project lineage to resolve the producer model name, and stitching across the whole DAG is deferred (so a cross-flow input stays a `source()` even though the producer may already be present in the qa baseline). Once all flows live in one integrated project (the accumulating-`main` topology from Q6), inputs whose `Table ID` is another flow's output should be rewritten `source(...)` → `ref('<producer model>')` so dbt builds one DAG across the whole migration. Needs: (a) a global `Table ID → producing model` map built by walking **live Keboola** flows/transformation output mappings (the manifest that once carried this is retired), and (b) resolution of shared/Data-Catalog alias ownership (a shared table's producer lives in the owner project, e.g. `SHARED_TABLE_A` is owned by `00 Project M`, not the `20 Project N` flow that reads it). Until then, `source()` is correct and intentional.~~
   - **Type-contract gotcha (verified on the `metrics_table_a`←`shared_table_a` stitch, 2026-05-27):** a Keboola Storage table read as a `source()` exposes **all columns as text/VARCHAR**, and consumers rely on that (e.g. `metrics_table_a` does `TS != ''` and `TS::date`). When you replace that `source()` with a `ref()` to a dbt model, the producer model must **preserve the source's text contract** — emit the same columns as strings, not native types. Here the producer computed `TS` as a `TIMESTAMP`; the consumer's `TS != ''` then threw `invalid timestamp field format`. Fix: cast in the producer (`(strptime(...) + interval 1 day)::varchar as "TS"`). General rule: when stitching, match the producer's output column **types** to what the storage table held, or the data-level chain breaks even though `dbt compile` passes. Only an end-to-end run (e.g. the duckdb chain test) catches this — `compile` won't.

## Ending the reply (`DEC-056`)

**Every run ends by naming the next step.** Here that is: [[keboola-validation-skill]] (P4) once Step 5d re-ran P2 clean. On a blocked conversion: what is blocked and what the operator has to decide.

Never end on the findings alone — the operator should not have to work out what to run. This holds on a
halt, a SKIP and a parked flow too.

**Compound first (`DEC-022`).** Before that closing line — always, success or stop — write anything this
phase learned into `HELP/FIXES.md` (a new breakage + its fix, e.g. a dialect trap) and
`HELP/DATA_ACCESS.md` (a data-location fact), then name the entries added in the reply. Full rule:
`HELP/CHAIN.md`.
