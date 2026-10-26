---
name: keboola-validation-skill
description: >-
  **P4 of the migration chain (HELP/CHAIN.md).** Entry is P3 PASS plus keboola-readiness-skill (P2) re-run in post-migration mode over the model's ACTUAL source()/ref() calls, with no row blocking validation — an undeclared recon reference or no overlap window stop this phase. A cross-flow producer that is unmerged or not migrated does not: Gate 1 (DEC-082) validates only the flow's LOGIC, on the same-run staged copy of every producer that has not passed Gate 2, publishes nothing (DEC-083), and the MR merges after the producer (DEC-006). If that re-run has not happened, DO NOT START BUILDING — run it first. Validate a migrated Keboola→dbt flow against REAL pod data (reconcile new vs legacy + render the Elementary report). Runs on the pod where the source/legacy tables are domain views on S3, reached via the attached DuckDB DBs kbc_in / kbc_stg. Walks the operator through it ONE STEP AT A TIME: locate the data on S3, confirm the 3 tables + datatypes, repoint the model sources.yml to the real pod schemas, dbt deps → build → test (reconciliation, threads sized from nproc), then build Elementary models → dbt test (capture results) → edr report → serve the HTML. threads is sized from the pod's nproc and dropped to 1 only for a heavy build or a shared pod (DEC-008 as amended). LOOPS until 0 unexplained WARNs (fix migration bugs, drop invalid tests with pod-evidenced justification, accept+document expected diffs). Invoked after keboola-migration-skill authored the model LOCALLY on the flow branch (this skill's Step 0 upload puts that branch on the pod scratch — local authoring since 2026-07-13, pod-first reverted) or standalone to re-validate a pushed branch. On any error/WARN it consults HELP/FIXES.md first; when the loop is clean it PULLS THE VALIDATED FILES BACK onto the local branch (pod→local sync is validation's final step, 2026-07-08) and recommends keboola-pushing-skill (which only commits/pushes/MRs); if issues remain it asks the operator. EVERY run ENDS with TWO box-drawn tables: (1) the flow STATE table (Stage | State | Evidence — migrated / sources=production / built / recon / synced / committed / pushed / MR / merged; glyphs ✅ YES, ❌ NO, ⬜ NO, ⚠ STALE; every row carries evidence; a rule separates done from not-done; VALIDATED is marked `✅ YES *` with a caveat whenever scope was reduced), then (2) the per-WARN table (Test | Result-with-count | Verdict-with-denominator, plus ✅ positive-proof rows below a rule). Triggers on "validate this flow", "run the validation on the pod", "reconcile against the legacy table", "run elementary on this flow".
---

# keboola-validation-skill

Pod-side validation of a migrated flow. The migration itself is done by
[[keboola-migration-skill]]; this skill takes the migrated models, points them at the **real** pod
data, and proves new == old via the reconciliation tests + Elementary.

## Step 0 — ALWAYS start by reading `HELP/DATA_ACCESS.md` and `HELP/FIXES.md`

Before guessing schemas or touching the pod, read **both** files (repo root, local-only — never shipped
to pod branches). They are the accumulated memory of every prior validation run, and skipping them means
re-deriving from scratch what's already been solved:
- **`HELP/DATA_ACCESS.md`** — the authoritative, continually-updated map of **where every flow's data
  lives on the pod**: the 3 kinds of S3 DuckDB DB (`ora`/`kbc_in`/`kbc_stg`), the attach preamble, a
  **per-flow data map** (input + legacy-output table for each already-validated flow), and the repoint
  pattern. If the current flow is already in that map, Steps 1–2 of the runbook collapse to a quick
  re-confirm instead of a fresh guess-and-search.
- **`HELP/FIXES.md`** — the catalog of **previous migration/validation mistakes and their exact
  fixes** (the branch-integrity pre-merge gate, stale-accumulating-files regression, the senior reviewer's recurring
  review asks, the build-breaking `unique` landmine, etc). **Many WARNs and breakages repeat across
  flows** — check this file FIRST when something breaks or a WARN looks unfamiliar; matching a known
  pattern is faster than debugging fresh.

Keep both current as you go, and **write your findings back at the END of every run** — this is a mandatory
step of the skill, not something you do only when a mistake feels novel (see "After each validation —
compound your findings into FIXES.md" near the end). Add any newly-discovered data location to
`DATA_ACCESS.md`'s per-flow map, and append every genuinely new error + its exact fix to `FIXES.md` in its
existing structure (no duplicates) so the next validation solves the same problem in one step.

**Two entry modes (updated 2026-07-13 — LOCAL authoring; the 2026-07-02 pod-first mode is reverted).**
- **Mid-migration (the default):** [[keboola-migration-skill]] just **authored the model + tests LOCALLY on the flow branch** (created off a fresh `qa`; its Steps 3–5c) and stopped at its readiness gate. **Do the Step 0 upload** (the branch's tree → pod scratch `/app/kbc/<flow>_val`) and then run build+test. There's no MR yet → **skip the GitLab-review-state pull**. When the loop terminates clean, **pull the validated files back onto the local branch yourself** (the "Final step when clean" section below — pod→local sync is THIS skill's job, 2026-07-08; if every loop fix was made locally and re-uploaded, it collapses to a verify-diff), then **recommend [[keboola-pushing-skill]]** — it commits and pushes.
- **Standalone re-validation:** the flow is already pushed / has an MR / the pod was reset. Do the Step 0 upload **and** pull the MR review state first (below), so you validate the *reviewed* version.

**This is a LOOP, not a one-shot — iterate to 0 *unexplained* WARNs.** Run the real `dbt build`/`dbt test`, read EVERY WARN, classify it, act, and **re-run** until the terminal condition holds:
- **migration bug** (fixable model ≠ legacy — dialect, FLATTEN, key-order, cast) → fix the model on the pod scratch, re-run. **Whenever a real (shippable) model fix lands, post a SHORT Productive note on that flow's task** (`DEC-020`) — ≈5 words, e.g. *"Fixed ambiguous COL_A in model_x qualify → attr.COL_A"*. A **cross-flow producer** you had to fix gets the note on **its own** task, not the flow under validation. Mechanics: find task → `POST /comments` with the operator's token, as [[keboola-pushing-skill]] Step 3. Separate from the final completion comment. A **pod-only validation-scoping edit that does NOT ship** (a disclosed filter, a `table`-flip, a producer scoped to the recon set) needs no comment.
- **invalid test** (e.g. `unique`/`unique_combination` on a genuinely non-unique upstream column — pod-verify by counting in the source) → drop that one test with an inline `# <test> removed — <justification + count>` (the mandatory-ID escape hatch below), re-run.
- **expected diff** (data recency, incremental-superset, upstream-source nulls, typed-view formatting) → **accept + document** — do NOT suppress or weaken a real test to force a green count.

**Terminal = build clean OR every remaining WARN individually justified.** Prove 1:1 where you can (full-row symmetric `EXCEPT` = 0 both ways is the strongest proof for a small/keyless table). If blocked on missing/mistyped pod data (IN domain not loaded; date-as-text→NULL), **STOP and draft the data-owner message** (below) — never fake the terminal condition.

**Operating rule #0 — on ANY error or WARN, check `HELP/FIXES.md` FIRST, before debugging.** Most breakages
and WARNs repeat across flows and their exact fix is already catalogued there (the build-breaking `unique`
landmine, stale-accumulating-files regression, the senior reviewer's recurring review asks, dialect traps…). Match the known
pattern before diagnosing from first principles; if you hit a genuinely new class of mistake, **append it to
`FIXES.md`** in its existing structure so the next flow inherits the fix. This is non-negotiable — skipping it
means re-deriving solved problems (Step 0 above; also cross-referenced in the runbook).

**Operating rule #0b — TEST ONLY THE FLOW UNDER VALIDATION, NEVER ITS ALREADY-MIGRATED DEPENDENCIES**
(the architect, 2026-08-11). When a flow reads a producer that is **already migrated and merged into `qa`**, that
producer's models are **NOT TESTED** here — and, since `DEC-082`, not built either: they are local views
(rule #0d), built on the pod only when the operator chose that (rule #0d step 2.3). Its recon tests were run and signed off in its own
validation + MR review; re-running them proves nothing about this flow, costs a large share of the pod run,
and pollutes the WARN table with another flow's known/accepted diffs.
- **Upstream as local views, test only ours (`DEC-082`):** run **rule #0d** first, then
  `dbt build -s tag:<flow_slug> --vars '{upstream_from_s3: false, publish_to_s3: false}'`. Every upstream
  `ref()` resolves to a LOCAL view in the scratch `.db` — over its `dwh-out` parquet when the producer is
  `gate2-passed`, over its same-run staged copy otherwise — neither built nor tested. `upstream_from_s3:
  true` is NOT used in Gate 1: under it `macros/ref.sql` reads every `ON_S3` file directly, including the
  ones that have not passed Gate 2, and the staged views would be bypassed. The DAG/lineage is unchanged. **Never** `dbt build -s +tag:<flow_slug>` — the `+` prefix on a `build` drags
  in every upstream model's tests too.
- The rule is about **tests**, not data: an upstream is never a test target here, whatever stands in
  for it (rule #0d).
- Fallback (an old branch without `macros/ref.sql`), **only after the operator chose a pod build of the
  upstream** (rule #0d step 2.3): `dbt run -s +tag:<flow_slug> --vars '{publish_to_s3: false}'` then
  `dbt test -s tag:<flow_slug>`. Nothing is published (`DEC-083`). Say in the summary that you fell back.
- The WARN table and the state table therefore cover **this flow's models only**. If an upstream build
  surfaces something genuinely broken (not a WARN — a build failure or obviously wrong data), report it to
  the operator as a separate finding against that flow; do not silently absorb it into this validation.

**Operating rule #0d — GATE 1 UPSTREAM: validate the LOGIC only, on the upstream legacy actually read
(`DEC-082`, 2026-10-06; publishing `DEC-083`).** Gate 1 answers ONE question: *does our code, given the same
inputs, produce what legacy produced?* Upstream health, persistence and the chain are Gate 2's
([[keboola-chain-validation-skill]]). Here an upstream is only an input, chosen to be as close as possible
to what the legacy flow read, so no other flow's bug enters this flow's WARNs. **Nothing is published in
Gate 1** — every build here runs `publish_to_s3: false` (`DEC-083`). Commands in VALIDATION.md Step 1c.
1. **CHECK: show the table.** `dbt parse --profiles-dir .` then
   `python upstream_s3_check.py --flow <flow_slug>` (in this skill folder, copied to the scratch). It walks
   the flow's cross-flow `ref()` chain and prints **one box-drawn row per upstream model**: model,
   project/flow, which of our models needs it, status (`ON_S3` / `RUN+PUBLISH` / `LOCAL` / `CUSTOM_PATH`),
   S3 path, **rows** and **last modified**. **Show the operator this table every time.**
2. **CHOOSE each upstream, in this order:**
   1. **Our model from `dwh-out` — only if it has passed Gate 2**: the producer's Productive task carries the
      tag `gate2-passed` → a local view over its `dwh-out` parquet. `ON_S3` alone proves nothing (`DEC-083`;
      an earlier flow found slices and an empty table there).
   2. **Otherwise its STAGED legacy copy (`kbc_stg`) from the SAME legacy run as the recon references:**
      - read every staged table's and every reference's Keboola `lastImportDate` (Storage API); refresh
        the references AND the staged copies together in ONE GRP window after the flow's night run
        (`DEC-078`, `HELP/RECON_REFRESH.md` §2b — never a row whose `GRP` starts `INIT_SAP`); a copy one run
        newer, or from another run because of `INIT_SAP`, is allowed only when disclosed;
      - a split stage (IN/OUT, per country) is reassembled pod-only and its coverage of the keys the model
        actually reads is MEASURED before it is trusted (an earlier flow's `SRC_TABLE_A`: OUT alone covered 161k of
        1.94M keys, OUT ∪ IN all but 1,445 run-to-run movers);
      - wire it pod-only: `create view main.<model> as select * from kbc_stg.…` in the scratch `.db` (the
        `ref()` falls back to local), cast to the producer model's contract where types differ (FIXES
        T-AAAAB / CH). **For a producer nobody has migrated**, also drop a pod-only `models/<…>/<model>.sql`
        of that name into the scratch (`select * from kbc_stg.…`) so `ref()` parses and builds; never
        committed (the same uncommitted stub lets `dbt parse` pass locally).
   3. **No staged copy (no DWH-KBC row) → STOP and ask the operator**: a data-owner ask for the stage, or
      building the upstream ourselves on the pod (`publish_to_s3: false`). Never decide it yourself.
   Mark each row `S3 (gate2-passed)`, `STAGED (<table>, Keboola run <date time>)` or `BUILT ON POD` next to
   the check table.
3. **VALIDATE:** `dbt build -s tag:<flow_slug> --vars '{upstream_from_s3: false, publish_to_s3: false}'`.
   Every upstream resolves to its local view (`not found - using local` / no `ref(upstream_from_s3)` lines);
   an upstream that resolves anywhere else means a view is missing.
4. **DISCLOSE** in the WARN summary, the STATE table (`Upstream` row), and hand to the pushing skill for the
   MR, Productive and the `gate2-pending` tag. Status: *validated on staged upstream: <tables> — gate 2
   pending* (+ *— waiting for #<producer> merge* while the producer is unmerged; the MR merges only after
   it, `DEC-006`).

**Operating rule #1 — PROPERLY VALIDATE ON THE POD. NO SHORTCUTS.** A flow is "Validated" ONLY after a real
`dbt build` / `dbt test` runs against the live pod data and you have reported the **actual per-test PASS/WARN**.
**Never** substitute a hand-written DuckDB query / "logic spot-check" / idempotency argument for the real test
run and call it validated — a spot-check confirms the SQL executes, but only the real run surfaces the
`not_null` / `unique` / reconciliation WARNs (lesson from an earlier flow: a spot-check said "no warnings"; the real
`dbt build` surfaced 6 `not_null` WARNs = 10,033 source rows with null PK columns). If a specific test is
genuinely too heavy to run, drop it from the **test copy** and **say so explicitly** — do not silently skip it
and imply a clean pass. Build the model on real data, run the tests, read every WARN, explain each (upstream
source data vs migration bug — verify by counting in the source), and only then mark Validated.

**Operating rule #0c — ONLY OUTPUT MODELS CARRY TESTS; intermediate models are build-only (the senior reviewer, 2026-08-27).**
Classify each model by **DAG position, not name**: an **output model** is one whose target is in the flow's
live Keboola Storage output mapping (`out.c-<bucket>.<TABLE>`); an **intermediate model** is any other node
of the flow's DAG — it exists only to build the outputs downstream of it (a name like `out_*` or a plain
name says nothing; the mapping decides). **Exception — self-relay (`DEC-059`, 2026-10-02):** a mapped table that
ONLY this same flow reads back (no other flow's input in Weeks-ALL, no writer/app reads it, not `INOUT=OUT` in
DWH-KBC) is plumbing, i.e. **intermediate** — verify consumers before wiring or refreshing any reference for it
(an earlier flow: 13 `OUT_*` were tested as outputs until P4, which nearly cost a night-window refresh ask to the data owner).
Per [[keboola-migration-skill]] Step 5 (🔴 rule), **intermediate
models ship with NO `data_tests` at all** — no reconciliation, no `same_values_enhanced`, no
`unique`/`not_null`, not even on an ID column. So in the validation loop they are **materialized but never a
test target**, exactly like an already-merged upstream producer under rule #0b. The WARN table, the per-WARN
table and the STATE table cover **the output models only**. If an intermediate model's `.yml` still carries
tests (an older-style branch), that is a migration-skill miss — strip those tests as part of validation and
note it, don't chase the WARNs. This is the "make flow validation faster" change: recon + Elementary run
against the handful of outputs, not every internal node.

**ID / IDs `unique`+`not_null` is mandatory on OUTPUT models — only the pod run may justify dropping it
(the senior reviewer, 2026-06-29; scoped to output models 2026-08-27).** Every **output** model's identifier column(s) — a
column named `ID`/`IDs`, or a row-identity column like `UUID` — must ship with **both `unique` and
`not_null`** in the `.yml` ([[keboola-migration-skill]] Step 5). They stay on **every output** model by
default (intermediate models carry no tests — rule #0c). This validation run is the **only** place that may
remove one: if a real-pod `dbt build` surfaces a `unique`/`not_null` WARN on an ID column, **count it in the
source** to confirm it's genuine upstream data (not a migration bug), then drop **just that test on that one
model** with an inline `# <test> removed — <justification + count>` comment, and note it in the MR comment /
`MIGRATION_STATUS.md`. No silent removal, no removal without the pod evidence — absent a justified drop,
an output model's ID/IDs carry both tests.

**Operating rule #2 — you run the commands yourself, ONE STEP AT A TIME.** The operator has granted direct
pod access (see below), so **execute each step via `kubectl exec` and show the operator the output** —
don't hand commands over for copy-paste. Still proceed one logical step at a time: run a step, read the
result, then the next, so the operator can course-correct. Don't fire the whole sequence blind.

## Direct pod access (operator-granted — verified 2026-06-26)

You can run commands **directly on the pod** — no copy-paste handoff. This is what makes validation fast.
- **Pod:** `$KEBOOLA_POD`, namespace `$KEBOOLA_POD_NAMESPACE` — from the repo-root `.env-skill` (currently
  `pod-01` / `bi`; copy `.env-skill.example` if it's missing). Enabled by the allow rule
  `Bash(kubectl exec <pod> -n <namespace>:*)` in `.claude/settings.local.json` (operator added it via
  `/permissions` — update it too if you point this skill at a different pod). kubectl context is
  `$KEBOOLA_K8S_USER`; if exec fails with `Unauthorized`, re-login per [[k8s-prd-auth-fix]].
- **If exec fails with `dial tcp: lookup apiserver.k8s-prd.example.internal: no such host` (DNS NXDOMAIN)**,
  it's **NOT** a permissions/kubectl problem — the operator's **VPN is disconnected**. The
  apiserver is an internal corporate hostname that only resolves over the corp VPN; off-VPN, the local
  router DNS returns NXDOMAIN. **STOP and tell the operator to reconnect the VPN**, then
  re-test with `kubectl exec "$KEBOOLA_POD" -n "$KEBOOLA_POD_NAMESPACE" -- whoami`. (Their VS Code `vscode-tunnel` terminal still
  reaches the pod without VPN — it's a persistent tunnel, not kubectl — so until the VPN is back you can
  fall back to handing them commands to paste there.)
- **Exec pattern** (always append `2>&1` so the operator sees stderr too):
  - shell: `kubectl exec "$KEBOOLA_POD" -n "$KEBOOLA_POD_NAMESPACE" -- /bin/bash -c '<cmd>' 2>&1`
  - DuckDB: `kubectl exec "$KEBOOLA_POD" -n "$KEBOOLA_POD_NAMESPACE" -- duckdb -c "<sql>" 2>&1`
- **dbt project lives in `/app`**; the operator's DuckDB scratch dir is `/app/kbc`.
- **S3 attach works out of the box** — credentials are already configured on the pod, so the
  `ATTACH 's3://dwh-in/dwh-conf/keboola_in.db' AS kbc_in (READ_ONLY); ATTACH …keboola_stg.db AS kbc_stg …`
  preamble runs with no manual secret init. (Verified: `kbc_in` 15 schemas / 115 views, `kbc_stg`
  20 schemas / 158 views on 2026-06-26.)
- The pod is **shared** (`pod-02`, `pod-03`, Kestra pods in the same namespace) and **resets daily** —
  flag before running anything heavy, size `threads` from the measured `nproc` and drop it to `1` for a
  heavy build or a busy pod (`DEC-008` as amended 2026-09-12 — not an unconditional `1`; see
  [[pod-recon-run-notes]]), and rebuild Elementary models each day (see [[elementary-pod-runbook]]).

## Inputs (operator supplies on invocation)

Like the migration skill, the operator names the **project** and the **flow**, e.g.
`/keboola-validation-skill project: 00 Project A, flow: Flow A`.
- **`project:`** → the Keboola project → its slug and the likely pod **domain schema** to look in
  (`00 Project A` → `in_src_a` / `stg_src_a`; this is the Step 1 guess).
- **`flow:`** → the flow → its **migrated model set** (which models to build/test) and the **legacy
  output tables** to reconcile against.
- **No `task:` number** is needed — validation doesn't create a branch.

If `project:` or `flow:` is missing, **ask** before starting (you can't pick the schema/models without
them). Resolve them **live from Keboola** exactly as the migration skill does (flow URL, or the downloader's
`--flow-name`/`--project` — the manifest CSV is retired; see [[manifest-stale-verify-live-keboola]]).

## Before you validate — PULL THE BRANCH'S GITLAB REVIEW STATE FIRST (validate the *right* version)

**A flow under review is a moving target — never validate a stale version.** Before touching the pod, pull
**all current information about this flow's branch from GitLab**: whether an MR is open, the **senior
reviewer's review comments**, every unresolved review **thread**, and any
merge-request discussion. If the review asks for a change (materialization, a dropped/added test, a grain
fix, a rename…), **apply it — or confirm it's already applied in the copy you're about to build — BEFORE you
validate**, and validate that corrected version. **After any post-review code change, RE-VALIDATE from
scratch** — a prior clean run of the *old* code does not carry over (an earlier flow, 2026-07-01: the senior reviewer's review
drove a `unique_key`/test-grain fix → the flow had to be re-validated on the pod against the new tests, not
signed off on the earlier run).

- **Mechanics live elsewhere — this step just says "do it first."** Reading / replying to / resolving MR
  threads is owned by **[[keboola-pushing-skill]]** and detailed in memory [[gitlab-mr-review-reply]]:
  Claude's shell reaches `gitlab.example.com` directly, the API PAT lives in the file at `$GITLAB_TOKEN_FILE`
  (from the repo-root `.env-skill`, default `~/.client_tokens`) as `GITLAB_API_TOKEN`, and Claude can **read** threads itself (the operator runs push + MR create/merge).
  Use those to fetch the MR + its notes for this branch; see [[gitlab-pod-dbt-repo]] for the repo/MR setup.
- **What to reconcile:** the model files you validate on the pod must match the branch **after** the latest
  review-driven commits. If you find review-requested changes that aren't in the branch yet, flag them to the
  operator (or apply + commit per the migration/pushing skills) **before** running the pod build — don't
  validate code you already know is about to change.
- **Feed it back:** note any review-driven change (and its pod evidence) in the `MIGRATION_STATUS.md` summary
  and reply/resolve the corresponding MR thread once the pod run confirms it (e.g. a justified test drop).
- **No MR yet?** If the branch isn't pushed / has no MR, there's nothing to pull — proceed to validation; the
  review loop happens after the pushing skill opens the MR, and you re-validate then if the review asks for changes.

## Context the operator must know
- The pod holds only the dbt project — **all data is on S3**, exposed as **typed domain views** in the
  attached DuckDB DBs: per-domain input DBs like `ora` (`oracle.db`), `kbc_in` (other IN / raw), and
  `kbc_stg` (STG / where legacy `out.*` results land — **temporary scaffold**). Views are
  renamed **by domain** (lowercased), NOT by Keboola project. Full map → `HELP/DATA_ACCESS.md`.
- Column names/types differ from the raw Keboola Storage (e.g. a date may already be a real `TIMESTAMP`),
  so the model's `source()` mapping + some casts must be repointed/adjusted for the pod copy.
- Reconciliation tests are `severity: warn`; a `no_additional_rows` WARN on an **incremental** model is
  expected (a full-refresh is a superset of the legacy incremental accumulation) — not a failure.
- **TEST INCREMENTAL MODELS TWICE — full-refresh passing ≠ incremental passing.** A first `dbt build` on a fresh
  target runs the **full-refresh** path; only the **2nd** run exercises the `is_incremental()` MERGE. A model can be
  perfectly clean on full-refresh while the incremental merge silently **duplicates rows every run**. Verified on
  an earlier flow (2026-07-01): `fact_history_x` passed full-refresh, but its `unique_key` included the
  **nullable `currency`** — dbt merges on `col = col` and `NULL = NULL` is never true, so NULL-currency rows never
  matched and were re-inserted each run (**1391 dup PKs, accumulating 2→4→8…**). Legacy was unique, so it was a real
  migration bug. **Build the incremental model twice and re-check `unique`/`unique_combination` + row-count stability;**
  a nullable column in `unique_key` is the classic cause (fix: drop the redundant nullable col or use a NULL-safe
  surrogate). See [[incremental-unique-key-null-safety]].
- **REPORTING DISCIPLINE — never claim "validated / 0 warnings" until you've run the operator's EXACT command.**
  Report PASS/WARN only from the same run the operator will do: the **whole flow** (`dbt build --select tag:<slug>`,
  not piecemeal single-model builds) and, for incrementals, the **2nd (incremental) run** — not a first-run-only or
  separate-model build. Lesson from an earlier flow (2026-07-01): I built the two models separately as first-runs, saw
  all-PASS, and reported "0 warnings / validated"; the operator then ran the whole flow (which hit the incremental
  merge) and got **1 WARN**. That gap — clean piecemeal report vs the operator's real run — must not happen. Run their
  command yourself, twice for incrementals, BEFORE saying validated.
- **ALWAYS run the actual `dbt build`/`dbt test` and report the real PASS/WARN per test — do NOT substitute a
  raw-SQL "logic spot-check" and call it validated** (lesson from an earlier flow, 2026-06-26: a duckdb idempotency
  spot-check reported "no warnings"; the real `dbt build` surfaced **6 `not_null` WARNs** — 10,033 source rows
  with null PK columns). A spot-check can confirm the SQL runs, but only the real test run surfaces
  not_null/unique/recon warnings. If a test is genuinely too heavy to run (e.g. a 58M-row self-join), drop it
  from the **test copy** and say so — don't silently skip and imply everything passed.
- **RECON TESTS ARE TEMPORARY VALIDATION SCAFFOLDING — THEY ARE REMOVED BEFORE PRODUCTION. Never reason about
  them as production tests.** (the architect, 2026-08-03.) The three recon generics —
  `no_missing_rows_enhanced` / `no_additional_rows_enhanced` / `same_values_enhanced` — exist for exactly one
  purpose: proving new == old during this migration. They are stripped before the project goes to production
  ([[keboola-migration-skill]] Step 5's "best-practice data tests" section says the same in passing: the
  best-practice tests are the *permanent* layer, the recon tests are *migration-only*).
  **What follows from this — get these right, they are easy to invert:**
  - A permanent recon WARN (`no_missing_rows` = the whole un-backfilled legacy history, `no_additional_rows` =
    each run's own batch) is **not** a production concern and must never be reported as one. It's an artefact
    of comparing against a frozen legacy snapshot that will not exist in production.
  - The **permanent** test layer is the data-quality one: `unique` / `not_null` /
    `unique_combination_of_columns`. When you judge "will this model be safe in production", judge THOSE.
  - A **vacuous** recon test (one whose reference overlap is 0 rows — e.g. a build-time `now()` timestamp
    inside the recon key, Problem T-NN addendum) costs **validation confidence, not production correctness**.
    Say precisely that: "this proved less than the PASS suggests", not "production is at risk". Then supply
    the positive fidelity proof yourself (re-key the comparison off the timestamp and compare on the real
    business grain) — that is what the "positive proofs" section under the WARN table is for.
  - **Do NOT reason about recon-test lifetime from `profiles.yml` or `sources.yml`.** The shipped
    `profiles.yml` attaches `kbc_stg` in **both** `dev` and `prod` targets (a deliberate 2026-07-06 fix so the
    checked-in project could reach real data at all), and `sources.yml` maps `stg_*` → `database: kbc_stg`.
    From that plumbing it *looks* like recon tests are permanent production tests. **They are not** — the
    plumbing outlives the tests. Inferring lifetime from the attach list is exactly the wrong-turn this note
    exists to prevent.
- **STG (`kbc_stg` / `stg_*`) is a RECONCILIATION REFERENCE only — a model must NEVER read `FROM` it.** (The one
  validation-time use besides the reference is `DEC-082`'s staged upstream — a pod-only view standing in for a
  `ref()`, rule #0d step 2; the shipped SQL still never names `stg_*`.) When repointing
  `sources.yml` to the pod schemas, the `stg_*` (`database: kbc_stg`) views are the **legacy outputs** used *only* as the
  recon `reference:` (proving new == old). If a model's own `SELECT`/`FROM`/`JOIN` reads `source('stg_*', …)`, that is a
  **migration bug, not a repoint** — flag it, don't just make it run. The model's real input is an **IN** table
  (`source('in_*', …)`, `database: kbc_in`, or a domain DB like `ora`) or a `ref()` to an upstream model. Sourcing from
  `stg_*` yields a **false-green recon** (the model is compared against the same table it reads — often circular) and in
  production reads unmaintained scaffold data. **Do not silently repoint an input onto `stg_*` to make the build pass**;
  fix the source (or, if it's a genuine cross-flow input with no IN twin yet, note it for cross-flow stitching). See
  [[stg-layer-is-validation-only-never-a-model-source]].
  ⚠ **This has already happened 3 times (three earlier flows — a `VBAK` input, a `SRC_TABLE_B` input, a `SRC_TABLE_C` input — FIXES Problems
  MM/VV) by assuming "no durable copy exists" without checking.** If you spot a model reading `source('stg_*', …)`
  as an input during validation, before accepting any explanation for it, run
  `SELECT database,schema,name FROM (SHOW ALL TABLES) WHERE upper(name) LIKE '%<TABLE_NAME_FRAGMENT>%'`
  against `sap`/`ora`/`kbc_in` yourself — a comment claiming "no durable copy exists" is not evidence, it's
  a claim; verify it before letting the `stg_*` read ship.
- **The recon reference is a FROZEN SNAPSHOT — check its window before trusting a WARN, and refresh it if it's
  stale.** A `kbc_stg` / `s3://dwh-in/stg_xxx/` slice does NOT follow the live Keboola table; it is whatever was
  staged, whenever it was staged. So a huge `no_missing_rows` can mean *the reference is old*, not that the model
  is wrong — and when the staged window does not overlap the pod's **input** window at all, the recon is
  meaningless rather than failing. **Always compare both windows first** (`min`/`max` of the date column on the
  reference vs the input), then pick a validation window that is complete on BOTH sides and disclose it (same
  convention as the 3-month filter below). You do **not** need the data owner to refresh a stale reference — set
  `GRP = NEW_REFRESH` on the table's DWH-KBC row and run `worker_run_grp` on the pod. ⚠ It runs on **any**
  pod since 2026-08-31 (`DEC-062` — the `pod-01`-only restriction is retired), but
  `/app/dwh-tools/env.sh` must be sourced first, and `CUSTOM_FILTER` is a lower bound you should leave
  alone. If the loop iterates nothing, check that `/tmp/dwh_kbc.json` exists — a failed gsheet read looks
  like "no matching rows", not like an error. Full runbook + all 8 gotchas: **`HELP/RECON_REFRESH.md`** (proven on an earlier flow, 2026-07-29, where the staged
  slice ended 2026-06-25 while the usable input started 2026-07-22 → zero overlap).
- **A NARROWED WINDOW HAS ONE MECHANISM, WHATEVER THE REASON (`DEC-042`).** There are two reasons to
  narrow — (a) **volume**: the table is big enough that an unbounded build risks OOM or an unacceptable
  run, and (b) **a thin input**: the input simply does not have the history. They are NOT separate rules.
  Both obey the same three conditions below, and the reason changes only what we ask of the data owner:
  volume asks for nothing (the data exists in full, we just compare less of it), a thin input asks for a
  backfill. The one thing that differs is the consequence for the shipped model: under (a) the model is
  correct everywhere; under (b) **the model produces wrong values outside the window and every test stays
  green while it does**, because the window was chosen to be exactly where the input is complete.
  - **Whether you may proceed at all is decided by the OVERLAP GATE below** (`DEC-043`): is there a
    window where the input AND the reference are both complete? If yes,
    validate; if no, the flow is blocked. Never try to decide it by predicting whether the missing input
    changes the output — that needs a build (an earlier flow: the predicted mechanism was a branch with zero rows).
  - **For a thin input, the out-of-window impact MUST be measured and reported** (`DEC-044`, method
    under the overlap gate below). Not estimated: backfills are scheduled by the number we state.
- **LARGE TABLES / long-run risk — the window is P2's decision, and volume is one of its two triggers
  (`DEC-055`).** When a source/legacy table is big enough that an unbounded `dbt build` / reconciliation
  risks OOM or an unacceptable run on the shared pod (see the `threads=1` note above), that is **not a
  separate mechanism** from a coverage gap — it is the same narrowing, reached from the other side, and
  [[keboola-readiness-skill]] step 3 picks the window for both. Standard for a volume-driven window: the
  **last 3 months on the table's `CREATED`/date column**. Here you **apply and disclose** it: **(1)** the
  SAME window on the new model AND the legacy reference, so the recon stays apples-to-apples; **(2)**
  stated EXPLICITLY in the WARN summary + `MIGRATION_STATUS` ledger; **(3)** pod-validation-only — the
  filter **stays on the pod and MUST NOT be pulled back into the shipped model** (the pull-back rule
  below, [[client-accepts-3-month-validation]]). Do not invent a window here, and do not widen P2's.
  Prefer a bounded-but-real run over dropping the test; only drop one when even the filtered slice is too
  heavy (e.g. a 58M-row self-join), and then **say so explicitly**.
- **In-place mutation flows** (the CSV input `Table ID` == the output `Table ID`, e.g. a dashboard flow's
  `DASHBOARD_TABLE_A`) have a **CIRCULAR recon reference** — the legacy "reference" IS the table the model reads,
  so row reconciliation is meaningless (guaranteed-pass) and often huge. Validate them instead by: (1) the model
  **builds**, (2) **data-quality tests** (not_null / unique_combination) on real data, (3) the transform's
  **idempotency** (e.g. `left(x,400)` changes 0 rows because the data already satisfies it). Note nulls/dupes that
  are **upstream source data** (verify by counting them in the source) vs introduced by the migration.

## Before you build — P2 must have passed FOR VALIDATION

This phase does not re-derive readiness. [[keboola-readiness-skill]] owns every availability question —
the overlap gate (`DEC-043`, is there a window where the input and the legacy reference are both
complete), the impact measurement of a thin input (`DEC-044`), the recon reference being declared
(`DEC-050`), the producer states, the full-history record (`DEC-047`). Its table is this phase's entry
condition (`HELP/CHAIN.md`).

So before the runbook:

1. **Is there a P2 result, and was it run in post-migration mode** over this model's actual `source()`
   and `ref()` calls (migration Step 5d)? No → go run it; do not start building.
2. **Does any row block validation?** Read the *validation* column, not a merged verdict. A row that
   blocks only the production cutover (a full-history gap) does not stop this phase; an undeclared recon
   reference or no overlap window does. A producer that is unmerged or not migrated at all does **not** —
   validate on its same-run staged copy (rule #0d step 2) and report *validated on staged upstream — gate 2
   pending — waiting for #<producer> merge* (`DEC-082`; the MR merges after the producer, `DEC-006`). With no
   staged copy, rule #0d step 2.3 applies: stop and ask the operator.
3. **Is it stale?** Pod availability flips week to week. A P2 table measured more than a few days ago is
   re-run, not trusted.

If a row blocks validation, this phase **stops and reports** — it never widens a window, never fetches a
missing reference, and never validates against a copy it made itself (`DEC-050`). A staged upstream under
`DEC-082` is not "a copy it made itself": it is the data owner's declared stage, refreshed in the same window as the
reference; with no stage the operator decides (rule #0d step 2.3).

## The step-by-step runbook

Follow **`VALIDATION.md`** in this folder — it is the canonical, ordered list of steps (built up over
time). Execute it top-to-bottom, one step per turn, substituting the current flow's project schema,
table names, and model names for the running 00 Project A example. **Cross-reference `HELP/DATA_ACCESS.md`**
for the data locations — if the flow is already mapped there, Steps 1–2 collapse to a quick re-confirm.
**Cross-reference `HELP/FIXES.md`** the moment a WARN or error shows up — check for a matching known
pattern before diagnosing from first principles.

## The data owner is the LAST RESORT — iterate to exhaustion first (the lead, 2026-07-31/08-01)

**Do not surface "we need the data owner" while you still have moves left.** A null-rate, a row-count gap, a
missing-looking table, a huge WARN are **hypotheses, not verdicts**. Keep iterating silently; raise the data owner
only at the point you have genuinely STOPPED — that is the signal the lead acts on, so it must mean
"I am out of options", not "this looks bad".

**Cost of getting it wrong (an earlier flow, 2026-07-31 — the case this rule comes from):**
`sap.main.ZSERIAL_T01.CHANGED_AT` was NULL for 533,670,707 of 534,246,972 rows (year files 2019-2024
100% NULL). I declared the flow BLOCKED and drafted the message. It was **not** blocked: those NULLs are the
legacy's own `'0'` sentinel, which the transformation DELETEs in its first three statements. The verdict was
built on comparing **input** rows (222,399 filtered) with **output** rows (2,181,400 reference) — different
units, in a pipeline that legitimately multiplies rows (12 UNION branches + 3x LTAK + 3x MLGN fan-out).
One 30-second query settled it the right way. See FIXES Problem T-UU2.

**The ladder — climb ALL of it before drafting anything:**
1. **Coverage, not population.** Does the REFERENCE's key-set exist on the pod, over the SAME window?
   `select count(*) from ref_keys r where not exists (select 1 from pod_keys p where p.k = r.k)` — a
   count of **0** means nothing is missing no matter how alarming the null-rate looks. Run this FIRST for
   any "data looks missing" suspicion.
2. **Compare like with like.** Never weigh input rows against output rows, or a model row count against a
   reference row count, in a pipeline with UNION branches / fan-out joins. Compare distinct KEYS.
3. **Read the legacy SQL for a matching guard.** A `DELETE … WHERE col = '0'` / `WHERE col != ''` upstream
   usually explains exactly the nulls/blanks you are alarmed by — the legacy discarded them too.
4. **Hunt every alternate home** — `_HISTORY` sibling, renamed/suffixed variant (`_stg`, `_v2`, `0`-prefix,
   `_YYYY`), a second copy in `kbc_in`/`kbc_stg`, uncatalogued parquet via `glob`, or another column that
   reconstructs the value (check `DWH_TS` is a real event time, not a 1-distinct-value load stamp).

5. **Re-read the raw parquet directly**, not just the catalog view — and per year file, since one file can
   differ from the rest.
6. **Read the operator's vault** (`$BRAIN_DIR`, default `./brain` — `HELP/BRAIN.md`, `DEC-040`), if it
   exists. The question may already have been asked and answered months ago: `12_Chat/` is the data-owner
   thread by month, `30_Notes/` is one finding per note. A hit here is **evidence for the report, not a
   rule** — cite the note and its date; anything that would change how we migrate goes to the operator
   as a proposal, never straight into `DECISIONS.md`. No vault → skip this rung, it is never a blocker.
7. **Then, and only then**, draft the message — and still HOLD it for the lead to send.

Everything below applies once step 7 is genuinely reached.

---

## ⚠ FIRST — is it a "needs TODAY's data" gap? Then PROPOSE adapting the validation, don't park the flow on a data-owner ask

Run this check **before** drafting the data-owner message below. A large class of "we can't validate this"
is not a missing-data problem at all — it is the migrated logic needing **today's** data, on either
side of the comparison:

- **Input side.** The model's legacy SQL pins the current date (`CURRENT_DATE() - DATUM = 0`,
  `WHERE date = CURRENT_DATE`, `changed_since` windows). The data owner's `IN_PREP` dumps are written **just
  after midnight** (`~00:12` in the filenames), so the pod copy essentially *never* contains today →
  the model builds **0 rows**. Legacy is fine because it reads the live Keboola table.
- **Reference side.** The `stg_*` recon reference is a frozen snapshot (see
  [[keboola-recon-refresh-runbook]]) whose window does not overlap the pod input's window → nothing
  to compare, so every row reads as missing/extra.

> **🔴 Do NOT stretch this into "the input has no history".** The two shapes above are about the *edges*
> of an otherwise complete table — today's rows, or a non-overlapping snapshot window. An input that is
> only ever a **few days deep** (`count(distinct DWH_TS) = 1`, count orders of magnitude below the Keboola
> `rowsCount`) is a different thing: unfinished backfill, and per the data owner 2026-08-12 — *"The rule is that a view
> must point to the full history. If it doesn't, always let me know and I'll migrate it."* — it
> is **always** an ask the data owner wants raised, whether or not we can work around it. Report it first, adapt the
> validation second; adapting quietly and saying nothing is exactly what that rule forbids. Flowpick should
> have caught it (the data owner's backfill runs 3–4 h per table, so the ask belongs there) — if it reaches validation
> unreported, send it now and note the miss. Full rule + the FULL-vs-incremental test in
> `HELP/DATA_ACCESS.md`; an `IN_PREP/` target path alone proves nothing either way.

Neither is a correctness problem, so **do not stop and wait on the data owner**. Instead work out the
adaptation and **put it to the operator as a proposal**:

- refresh the recon reference **yourself** (`HELP/RECON_REFRESH.md`, `GRP=NEW_REFRESH` +
  `worker_run_grp` on whichever pod you are on — every pod has egress since 2026-08-31, `DEC-062`);
- **pin a fixed date** in place of `CURRENT_DATE` **for the pod test run only** (e.g. `2026-07-28`),
  and prove the model reproduces that day's reference rows exactly;
- scope the comparison to the days that are complete on **both** sides, and state that window as a
  disclosed scope reduction.

> **🔴 NEVER do this unilaterally — operator sign-off is mandatory.** The architect, 2026-07-30, verbatim (translated):
> *"I definitely don't want you changing test conditions on your own — they always need to be validated
> with the operator."* Pinning a date, narrowing a window, scoping to overlapping days, dropping a test —
> each is a **proposal**: state the evidence, state exactly how much coverage is lost, then wait.
> Present it; do not apply it and report afterwards.

Two hard boundaries:

1. **The committed model stays 1:1 with legacy.** The adaptation touches only how the test is run on
   the pod — never the model in the repo. (Same discipline as the `CUSTOM_FILTER`-is-only-a-staging-slice
   rule: document the diff, don't filter the model down to match.)
2. **"Blocks validation" ≠ "blocks production" — classify both.** If the pod copy will *never* hold
   today, the migrated model returns 0 rows on **every** production run too. The date-pin unblocks
   validation but not deployment, so that one still warrants a data-owner ask — framed as
   *production correctness*, not as a validation blocker, or they may reasonably deprioritise it.

Worked example — an earlier flow, `Flow B` / `Transformation B` (2026-07-30): SQL filters
`CURRENT_DATE() - DATUM = 0`; pod `LOG_TABLE_A` ended 29.7. 19:08 while the reference `rep_daily_x`
ended 24.6. — a gap on *both* sides at once. The first draft asked the data owner for `LOG_TABLE_A` history, which
was the wrong fix entirely: the output mapping is `incremental = True` and the SQL appends one day per
run, so those 142,079 rows are **1,035 days accumulated one at a time since 2022-11-29** — rebuilding
them from source would need the full 35-billion-row log. The right answer was refresh-the-reference
(ours) + a proposed fixed-date test run, and the data-owner ask shrank to "let the daily copy include the
current day". **Always check the output mapping's `incremental` flag and the SQL's own date filter
before concluding that history is missing.**

## When validation is blocked on missing pod data → draft a message to the data owner

If a required source isn't on the pod — an **IN domain not loaded** (no matching `in_*` view for the
flow's inputs) or a **wrongly-typed column** (date-as-text → NULL; see [[in-typing-fix-process]]) —
STOP validation and **draft a chat message to the data owner** for the operator to send (the data owner owns the IN/STG load).

**⚠ First, which side is missing — the INPUT or the RECON reference? The two are not interchangeable
(`DEC-050`).** Self-serving a small static table (download it on the pod, pin it under
`s3://dwh-in/_val_snapshots/`) is an **INPUT-only** move: an input is something the model reads, so a
correct copy of it makes the model compute correctly and the recon still judges the result independently.
A **recon reference is the judge itself.** Fetching it ourselves from Keboola and then validating against
it proves only that our copy matches our copy — the test passes vacuously and reports a clean flow.
So the test is **is the reference declared in the data owner's DWH-KBC sheet?**

- **Declared** — it has a DWH-KBC row — → whatever is wrong with the staged file (stale, frozen,
  missing, or the output of a different legacy run than the one our input snapshot feeds) it is **ours
  to refresh and never a data-owner ask** (`DEC-078`). Re-exporting the legacy's own output ourselves
  counts as a refresh when `worker_run_grp` is unreachable
  ([[keboola-recon-refresh-runbook]]). Mirror the data owner's `CUSTOM_FILTER` exactly and record both the snapshot
  and the reason in `DATA_ACCESS.md` — an earlier flow's `ref_catalogue_x` did precisely this (the data owner's file frozen at
  its 2026-06-21 import, the input reaching 2026-08-14).
- **Not declared anywhere, and not on the pod** → **STOP with the drafted ask.** Nobody has ever named
  that table a reference, so fetching it invents the judge. Say plainly that the flow is unvalidatable
  until it lands. This is what went wrong on 2026-08-20: missing in both places, pulled from Keboola into
  a temp S3 folder, flow reported validated.

**Style — match the operator's voice exactly (verified from real exchanges):**
- **Language is the operator's** (`DATA_OWNER_MESSAGE_LANG`, `DEC-030`) — each operator writes in their own
  configured language. Polite and conversational (the data owner replies in theirs). Short, no corporate stiffness.
- **Open with the `DEC-030` salutation, exactly `Good day, <data owner>`** (the architect, 2026-08-16) — never
  `Hi`/`Hey all`, never a bare name. Then `I ran into ... on flow <flow>, <schema.table>`; state the issue precisely
  (column/table, what's wrong, the impact e.g. "all 427 rows fall to NULL"); note **what's fine**
  ("The other columns are fine"); make the ask ("Could you …?"); close with `Thanks.` + status
  ("Otherwise it's migrated."). The data owner explicitly wants a **link to the table in Keboola** — always include it.

Content to cover: (1) flow + project; (2) exactly what's missing & where you looked (e.g. "there is no
`in_src_c` in `kbc_in`, so I can't get to `TABLE_X`/`TABLE_Y`"); (3) the **Keboola table link(s)**
(`…/projects/<id>/storage/<bucket>/table/<TABLE>`); (4) what IS already there ("the outputs are in `stg_src_b`");
(5) the ask ("load `in.c-src-c` into the IN layer"). Then pause until the data owner confirms, and resume from Step 1.

Reference example (a lookup table — wrong typing). The lead → the data owner. ⚠ Translated from the real 2026
exchange, whose opener predates `DEC-030` — copy the *structure*, not the salutation:
> *Good day, I ran into one small thing on flow Flow C, in_src_b.ref_table_x. You have the column
> COL_DATE_FROM typed as DATE, but the source sends it as text DD.MM.YYYY (01.04.2021),
> so it doesn't parse on load and all 427 rows fall to NULL. The other columns are fine, only
> this date. Could it be left as VARCHAR in the IN layer? I'll do the parsing in the model. Thanks. Otherwise
> it's migrated.*
The data owner → the lead: *Yes, that will definitely work … if you run into an odd date, just send me a link to the table in Keboola and I'll work it into the "in".*

## Update the status tracker (MIGRATION_STATUS.md)

When validation finishes, update **`MIGRATION_STATUS.md`** (repo root — gitignored, local-only) for this
flow: **upsert by flow name** (`## <flow name>` block; create from its TEMPLATE if absent) and set
**`Validated: ✅`** on a clean pass (note the result, e.g. "20/22 PASS, 2 expected superset warns"),
**`Validated: ✅ staged`** on a clean Gate-1 pass that read any staged upstream (`DEC-082` — list the staged
tables with their Keboola run times; the shared list of flows waiting for Gate 2 is the Productive tag
`gate2-pending`, which the pushing skill adds), or
**`Validated: ⚠️`** when blocked, with the blocker in **Notes** (e.g. missing IN domain + "data-owner msg sent").
Local-only — doesn't touch any branch.

## After each validation — compound your findings into `HELP/FIXES.md` (ALWAYS) — `DEC-022`

Every validation run ends with a write-back to `HELP/FIXES.md` — **always**, not only when something feels
novel (`DEC-022`, the chain-wide rule in `HELP/CHAIN.md`; this is its fullest instance because validation
learns the most). The loop above is only worth the tokens if the next flow inherits what this one learned.
Before you recommend pushing (or stop on a blocker):

1. **List what broke and what you changed** this run — every migration bug you fixed (dialect / typed-view
   guard / source wiring / materialization / key null-safety…), every test you dropped or added, every WARN you
   had to classify, and the exact fix or justification.
2. **Match each against `FIXES.md` — write only the genuinely new, never duplicate.** If a matching
   Problem/entry already exists, don't re-add it (at most append a one-line "also seen on <flow>" if it sharpens
   the pattern). If it's a new class of breakage or a reusable fix pattern, **append a new entry in the existing
   structure** — `## Problem <next letter> — <symptom> (case: <flow>)` with **Symptom / Why / Fix** — and add any
   recurring WARN to a WARN-taxonomy note.
3. **Write a fix recipe, not a diary** — a symptom you can grep for, the root cause, and the copy-pasteable fix,
   so the next validation resolves it in one step instead of re-deriving it from scratch.

Same discipline for `DATA_ACCESS.md` (per-flow data map). A validation is **not "done"** until `FIXES.md` /
`DATA_ACCESS.md` reflect what this run learned.

### Also record how long it took — `HELP/runtimes.csv` (added 2026-08-11)

dbt overwrites `target/run_results.json` on every invocation, so the measurement exists for about a minute and
then it is gone forever. Nothing else on the pod keeps it. Capture it **right after each of the two commands**
— a pod build of an upstream the operator chose (rule #0d step 2.3, `run`, only when one was needed) and the step-3
`dbt build -s tag:<flow> --vars '{upstream_from_s3: false, publish_to_s3: false}'` (`build`); on the rule #0b
fallback path (operator-chosen pod build), `dbt run -s +tag:<flow> --vars '{publish_to_s3: false}'` and
`dbt test -s tag:<flow>`. Keep them separate rows: the
upstream fill scales with the upstream chain, the flow build only with this flow's own models + recon volume:

```bash
# on the pod, immediately after the command finishes
python3 - "$FLOW_SLUG" run <<'PY'          # ... and again with `test` after dbt test
import json, sys
d = json.load(open("target/run_results.json"))
r = sorted(d["results"], key=lambda x: -x["execution_time"])
tot = sum(x["execution_time"] for x in r)
print(",".join([sys.argv[1], d["metadata"]["generated_at"][:10], sys.argv[2], str(len(r)),
                f"{tot:.1f}", f"{r[0]['execution_time']:.1f}" if r else "0",
                r[0]["unique_id"].split(".")[-1] if r else ""]))
PY
```

Append the two lines to `HELP/runtimes.csv` locally as part of the pod→local sync below — header
`flow_slug,date,phase,nodes,seconds,slowest_seconds,slowest_node,pod,memory_limit,outcome`. ⚠ The last
three were added 2026-08-12 (the file was still empty, so nothing depended on the old header): a duration
without the **pod** and the **`memory_limit`** it ran under is not comparable to any other row — the same
14-model build took 1056 s for one model on `pod-03` and 490 s on `pod-01`, and a *lower* limit can be the faster
one (FIXES T-EE addendum 4). `outcome` carries `OK` or the failure, so a partial run is still a datapoint. These rows are the only ground truth we
will ever have about pod runtimes: they are what lets [[keboola-weekboard]] show a real duration instead of a
guess, and they are the calibration for flows not yet migrated. Record them even when the run failed — a
row with the failure noted is still a volume datapoint, and a build that got slower over time is itself a
finding.

## Final step when clean — pull the validated files back onto the LOCAL branch (added 2026-07-08, per the lead)

**Validation owns the pod→local sync** (moved here from [[keboola-pushing-skill]]): once the loop is clean,
bring exactly what validated back from the pod scratch into the local working tree (the flow branch's checkout
or its git worktree), so the operator sees the validated state in VS Code and the pushing skill starts from an
already-synced tree. This closes the circle: author locally → upload → validate on pod (loop fixes may land
pod-side) → **sync back local** → push.

```bash
FLOW_DIR='<flow_dir>'                          # pod scratch = /app/kbc/${FLOW_DIR}_val
# run from the flow branch's checkout root (repo root or its worktree):
kubectl exec "$KEBOOLA_POD" -n "$KEBOOLA_POD_NAMESPACE" -- tar czf - -C /app/kbc/${FLOW_DIR}_val \
  models/<project_slug>/<flow_dir> models/sources.yml dbt_project.yml | tar xzf -
git status -s; git diff --stat                 # eyeball: ONLY this flow's files changed
```

- **Pull ONLY this flow's files** — the model dir + the accumulating `models/sources.yml` / `dbt_project.yml`.
  **Never** the pod `profiles.yml` (S3-attach, scratch-only) or the scratch `.db`/`target/`.
- **Do NOT bring back pod-validation-only edits** — a disclosed 3-month `CREATED` filter
  ([[client-accepts-3-month-validation]]), a temporary source repoint, or a pod-only date anchor stays on the
  pod; pull the **shipped** model.
- If you fixed models locally and re-uploaded each fix to the pod as you went (the usual local-authoring loop),
  this collapses to a **verify-diff** — still run it: the tar must produce **no unexpected change** (`git
  status`/`diff` confirm local == pod) before you recommend pushing.

## DURING a long validation — the PER-MODEL progress table, every 10 MINUTES (the lead, 2026-08-07/08)

**Cadence: every 10 minutes. Shape: one row per MODEL, ticked as it completes, with the % underneath.**
The lead asked for exactly this during an earlier heavy flow: they want to see *the models*, not a prose summary — a checklist
where the done ones are ticked, so one glance shows how far the build actually is.

```
P5 progress — <flow> (#<task>)

┌────┬──────────────────────────────────────┬────────┬───────────────────────────────────┐
│ #  │ Model                                │ State  │ Time / note                       │
├────┼──────────────────────────────────────┼────────┼───────────────────────────────────┤
│ 1  │ stg_orders_x                         │ ✅     │ 0.08s                             │
│ 2  │ int_customer_attr_x                  │ ⏳     │ 12m04s in (benchmark 47m05s)      │
│ 3  │ dim_division_x                       │ ⬜     │ —                                 │
│ …  │ …                                    │ …      │ …                                 │
│ 35 │ fact_shipments_x                     │ ⬜     │ FINAL 2/2                         │
└────┴──────────────────────────────────────┴────────┴───────────────────────────────────┘

PROGRESS: ~<n>%   ·  <b> of <N> models built  ·  <elapsed> elapsed  ·  ERROR=<e> SKIP=<s>
<one line: what is running now + its liveness proof>
```

Rules:
- **Every model gets a row, always** — including the ones not started. The point is the shape of the
  whole run, not just the current node. Group only if the list exceeds ~40 rows.
- **Glyphs:** `✅` done (with its real seconds) · `⏳` running (elapsed + benchmark) · `⬜` not started ·
  `⚠` overrun/risk · `❌` errored. Never a tick without its time.
- **The % goes UNDERNEATH the table**, on its own line, with the counts that justify it. It is
  **time-weighted, not row-weighted** — say so when the two diverge badly (a 47-min model and a 0.08s
  view are not both "1 of 35").
- **Recon tests are their own rows** once the build is done — the test suite gets a summary row per
  test family (`no_missing` / `no_additional` / `same_values` / data-quality), not one row per test.
  Only **output models** contribute tests (rule #0c); intermediate DAG nodes appear in the build rows
  but never in a test row.
- Keep the liveness proof (CPU ticks or spill delta) on the running line — that is what separates
  "working" from "hung". Never advance the % off numbers you could not re-read.

The FULL box-drawn phase table further below is still the right artifact at a **phase boundary**
(producers → flow models → recon suite), on an ERROR/BLOCKED, or at run end.

### The full P5 progress table (milestones, blockers, and on request)

P5 on a heavy flow runs for hours across pod restarts, OOMs and VPN drops. The two tables below are
**terminal** artifacts — they describe a finished run. While the run is still going the operator needs a
different thing: *where are we, and how much is left*. Emit **this** table at the milestones listed above,
and keep emitting it even when nothing changed — "no movement, still on model X, 41 min in" is itself the
answer to the question being asked.

```
P5 validation progress — <flow> (#<task>)

┌────┬────────────────────────────────────┬────────────┬──────────────────────────────────────────────────┐
│ #  │ P5 step                            │ State      │ Evidence                                         │
├────┼────────────────────────────────────┼────────────┼──────────────────────────────────────────────────┤
│ 1  │ Scratch on a healthy pod           │ ✅ DONE    │ which pod, cgroup size, exclusive or shared      │
│ 2  │ Branch uploaded                    │ ✅ DONE    │ sha, dbt deps, S3 attach verified                │
│ 3  │ Scope key-sets built               │ ✅ DONE    │ each key-set + its reduction factor              │
│ 4  │ Producers: cheap                   │ ✅ DONE    │ per-model seconds                                │
│ 5  │ Producer: <the expensive one>      │ ⏳ RUNNING │ elapsed / benchmark, anon GiB, spill GB          │
│ …  │ Producers: remaining <n>           │ ⬜ NOT YET │ name the ones with known risk                    │
│ …  │ <heaviest flow model>              │ ⚠  RISK    │ prior peak memory vs this pod's ceiling          │
│ …  │ The <n> flow models                │ ⬜ NOT YET │ —                                                │
│ …  │ Recon suite (<n> tests)            │ ⬜ NOT YET │ the test breakdown                               │
│ …  │ WARN triage to 0 unexplained       │ ⬜ NOT YET │ —                                                │
│ …  │ pod→local sync verify              │ ⬜ NOT YET │ —                                                │
├────┼────────────────────────────────────┼────────────┼──────────────────────────────────────────────────┤
│    │ P5 OVERALL                         │ ~<n>%      │ <n> of <n> steps; what the long pole is          │
└────┴────────────────────────────────────┴────────────┴──────────────────────────────────────────────────┘
```

Rules that keep it useful rather than decorative:
- **Same glyphs as the STATE table** — `✅ DONE` · `⏳ RUNNING` · `⬜ NOT YET` · `⚠ RISK` · `❌ BLOCKED` ·
  `⬜ REDO` (built once, lost to a pod restart — call that out, it is not progress).
- **Evidence on every row, numbers not adjectives.** "41 min in of a 55-min benchmark, 9.6 GB spill,
  anon 5.01/8.00" — not "still going".
- **The % is time-weighted, not step-weighted**, and say so. On an earlier heavy flow, 6 of 14 steps was ~35% by count but
  the remaining producers were hours — a count-based number would have implied it was nearly half done.
- **Never let a ⏳ row hide a stall.** Compare elapsed against the model's known benchmark and against
  pod-clock time (never your own wall clock); a flat dbt log is NOT evidence of a stall, and CPU ticks +
  growing spill are what prove liveness (FIXES T-TTT).
- **Carry the unknowns honestly.** Recon-suite duration and WARN triage are usually unmeasured — mark them
  as estimates, because triage is historically where flows spend days, not minutes.

---

## Terminal decision — recommend pushing (clean) or ask the operator (issues)

### FIRST, ALWAYS: the flow STATE table (operator ask, 2026-07-27)

**Every validation ends with a box-drawn state table** — the operator's at-a-glance "where is this flow?".
Emit it **before** the per-WARN table (state first, then the WARN detail behind it). Never replace it with
prose, and emit it even when the run is blocked or dirty — a blocked flow is exactly when the state matters.

```
┌────────────────────────────────┬────────────┬────────────────────────────────────────────────────────────┐
│ Stage                          │ State      │ Evidence                                                   │
├────────────────────────────────┼────────────┼────────────────────────────────────────────────────────────┤
│ Migrated                       │ ✅ YES     │ <n> model(s) <names>; what it replaces                     │
│ Sources = production           │ ✅ YES     │ <n>/<n> source() on <durable db>; stg_* block deleted      │
│ Upstream (DEC-082 Gate 1)      │ ✅ GATE2   │ all ref() gate2-passed on S3 — or ✅ STAGED: <tables>, run  │
│ No kbc_stg model inputs        │ ✅ YES     │ grep source('stg_ in model SQL = 0                         │
│ Rebased onto current qa        │ ✅ YES     │ qa <sha> IS ancestor; diff = <n> files, additions only     │
│ dbt parse                      │ ✅ CLEAN   │ 0 errors                                                   │
│ Built on pod                   │ ✅ YES     │ <duration>, <rows> rows, memory_limit <X>, threads=<n>     │
│ Recon tests run                │ ✅ YES     │ PASS=<p> WARN=<w> ERROR=<e>, all <w> justified             │
│ Data-quality/source guards     │ ✅ PASS    │ which tests, on what                                       │
│ Pod↔local sync verified        │ ✅ YES     │ <n>/<n> IDENTICAL; any pod-only edit named                 │
│ Committed locally              │ ✅ YES     │ head <sha> (<n> commits)                                   │
│ VALIDATED                      │ ✅ YES     │ add ` *` + a caveat line if scope was reduced; ✅ STAGED   │
│                                │            │ = on staged upstream, gate 2 pending (DEC-082)             │
├────────────────────────────────┼────────────┼────────────────────────────────────────────────────────────┤
│ <anything NOT done>            │ ❌ NO      │ why, in one clause                                         │
│ Pushed to origin               │ ⬜ NO      │ what origin currently holds                                │
│ MR → qa                        │ ⚠  STALE   │ MR !<n> state                                              │
│ Merged                         │ ⬜ NO      │ —                                                          │
│ Productive #<task>             │ 🔵 To Review│ when set; whether the comment reflects this run            │
└────────────────────────────────┴────────────┴────────────────────────────────────────────────────────────┘
```

Rules that keep it honest:
- **Glyphs are fixed:** `✅ YES`/`✅ CLEAN`/`✅ PASS` = done & evidenced · `❌ NO` = attempted or required but
  not achieved · `⬜ NO` = not attempted yet (normal at this stage) · `⚠ STALE` = exists but points at
  superseded code · `🔵 <status>` = external tracker state. `❌` and `⬜` mean different things — don't merge them.
- **A horizontal rule separates done from not-done.** Everything below it is what the operator still owes.
- **Every row carries EVIDENCE, never a bare tick** — a duration, a row count, a sha, a grep result, a
  PASS/WARN tally. A tick with no evidence is the thing this table exists to prevent.
- **`VALIDATED` is one row and it must not be inflated.** If the run reduced scope in any way — a pod-only
  prefilter, a dropped heavy test, a guarded window, one country instead of all — mark it `✅ YES *` and put
  the caveat immediately under the table saying what was and was NOT proven. Reducing recon scope to match a
  sliced reference costs zero coverage and is fine; **not proving the production-scale build is a `❌` row of
  its own**, never folded into the ✅.
  - **EXCEPTION — the huge-table 6-month window (the lead, 2026-07-31, on an earlier heavy flow).** When a table is
    **genuinely huge**, i.e. a full-scope recon would run **multiple hours**, validating roughly the
    **last 6 months** IS full validation: mark it a plain **`✅ YES`**, with **no `*` and no
    "production-scale build unproven" caveat row**. A 6-month slice of a big fact table already exercises
    every branch, join and type path; the remaining years buy wall-clock, not confidence.
    **The default is still NO filter — validate everything you can**; this is the escape hatch for the
    genuinely heavy cases only, never a routine shortcut. (an earlier flow's `fact_movements_x`: the unfiltered 2024+
    scope ran **3h41m on ONE model** with 34GB spill and still had not finished → filtered to
    `EVENT_DATE >= 2026-01-01`.) Prefer aligning the window to the recon reference's **own staged slice**,
    which makes the coverage cost literally zero — rows outside it are unreachable by every test anyway.
    ⚠ Check the reference window **per model** before filtering: that flow's sibling error-log ref spanned the
    FULL 2024-01→2026-06 range, so narrowing that one would have manufactured a false `no_missing`.
    Still **state plainly which window was validated** — disclosure yes, downgrade no. See
    [[six-month-window-counts-as-fully-validated]]; the filter stays pod-only
    ([[months-filter-model-map]]).
    - ⚠ **A SECOND reason to narrow a big table's window, and it is not wall-clock (`DEC-048`).** The data owner,
      standup 2026-08-13: for big tables validate **the current year** — older years *"probably don't
      make sense"*. **One business region (Region N) was disconnected around 2025-08**, so last year's legacy rows still carry that region's
      warehouses while the new DWH has none of them; a wider window manufactures a mismatch that is not a
      model bug. Practical effect: the 6-month escape hatch above and this rule point the same way, but
      this one applies **even when the recon would run fast** — so do not widen a big table's window back
      out past January just because there is time for it. State the window either way.
      ⚠ Scoped by the data owner to big tables; the reason is not size-dependent (a small table with Region N data has
      the same incomparable 2025) and that gap is deliberately **open** — do not close it on the data owner's behalf.
- Rows are a floor, not a ceiling: add flow-specific ones (2nd incremental run, Elementary report, precursor
  merged first, data-owner dependency outstanding). Drop rows that genuinely don't apply.
- Same ledger goes to `MIGRATION_STATUS.md` in prose — the table is the operator's view, that file is the record.

### THEN: the per-WARN table — "What VALIDATED covers"

**ALWAYS follow the state table with a box-drawn per-WARN table** (operator ask 2026-07-11, format fixed
2026-07-27): one row per WARN so the operator can scan every warning and its evidence in one place, then a
horizontal rule and the **positive proofs** that make those WARNs safe to accept.

```
┌──────────────────────────┬──────────────┬─────────────────────────────────────────────────────┐
│ Test                     │ Result       │ Verdict                                             │
├──────────────────────────┼──────────────┼─────────────────────────────────────────────────────┤
│ no_missing_rows          │ WARN     820 │ 0.025% of 3,304,309 ref rows → 99.975% found        │
│ no_additional_rows       │ WARN  51,276 │ 43,904 (85.6%) pure recency; residual 0.22%         │
│ same_values GR_QTY       │ WARN 370,505 │ composite-key cross-pairing, ~13% dup BOTH sides    │
│ same_values INVOICE_VAL  │ WARN 337,267 │ same artifact                                       │
├──────────────────────────┼──────────────┼─────────────────────────────────────────────────────┤
│ measure sums (6, dated)  │ ✅ −0.08…+0.50% │ positive fidelity proof                          │
│ normalized 52-col parity │ ✅ 98.55/98.92% │ raw was 0% — typed-source formatting only        │
└──────────────────────────┴──────────────┴─────────────────────────────────────────────────────┘
```

- **`Result` carries the number, not just the word** — `WARN 51,276`, never a bare `WARN`. The count is the
  thing the operator is judging.
- **`Verdict` is the justification in one clause, with its denominator.** `820` means nothing; `0.025% of
  3,304,309 → 99.975% found` is a verdict. Repeat-cause rows may say `same artifact` once the first row
  spelled it out — don't re-paste the same paragraph six times.
- **Below the rule go the POSITIVE proofs**, marked `✅`, not WARNs: aggregate measure sums, normalized
  full-row parity, symmetric EXCEPT, input-row parity. A WARN table with no positive proof section is an
  excuse list, not a validation — when a `same_values` count is a keying artifact you must show fidelity
  some other way ([[legacy-incremental-artifact-warn-family]], FIXES Problem **T-DD** — the lead's series; see the `T-series` banner in FIXES.md, the local `Problem DD` is a different problem).
- Where a raw metric is misleading, show **both** numbers and name the reason (`raw was 0% — typed-source
  formatting only`). Never quietly report only the flattering one.
- After the table: a **"noise to ignore"** line (harmless Elementary hook error, deprecation warnings) and any
  **dropped tests** + where their inline justification lives. Same spirit as
  [[operator-validation-warn-summary-format]]; `MIGRATION_STATUS.md` carries the same ledger in prose.

- **Whenever the window was narrowed, also disclose the UNTESTED BRANCHES (`DEC-045`).** A window that is
  narrow *and recent* leaves code paths never compared against legacy, because those situations do not
  occur in recent data — and a green recon says nothing about them. This is a **separate** disclosure from
  the input-completeness item: no backfill fixes it, only a wider window does. Find them by counting each
  output classification code inside vs outside the window on the REFERENCE:
  ```sql
  SELECT coalesce("<code_col>",'<NULL>') code,
         sum(CASE WHEN "<date>" >= <lo> AND "<date>" < <hi> THEN 1 ELSE 0 END) inside,
         sum(CASE WHEN "<date>" <  <lo> THEN 1 ELSE 0 END)                     before
  FROM <reference> GROUP BY 1 HAVING inside = 0;
  ```
  Put the list, with row counts, in the MR. On an earlier flow: `CODE_A` (316 rows) and
  `CODE_B` (36) never occur inside the window, so both branches shipped
  unverified. The same query also reveals genuinely **dead** branches (zero rows on both sides anywhere) —
  say which, so a reviewer does not read a missing comparison as a missing test.

**When the loop is clean** — 0 unexplained WARNs (build clean, or every remaining WARN individually justified) —
**pull the files back (section above), then recommend [[keboola-pushing-skill]]**: tell the operator
**"ready for pushing"**. The operator runs the pushing skill next (or [[keboola-orchest-skill]] takes this line as its GO, `DEC-086`),
which commits the already-synced branch, pushes, and opens the MR.

**When issues remain** — an unresolved WARN you can't classify, a suspected migration bug you couldn't fix, or a
block on missing/mistyped pod data — **STOP and ask the operator** (for the blocked-on-data-owner case, draft the
message above). Do **not** recommend pushing until it's resolved.

## Hand the validation result to the pushing skill (which posts the Productive comment)

Posting the completion comment to the Productive task lives in **[[keboola-pushing-skill]]** now (push → MR →
comment are one flow there, since the comment needs the MR link). This skill's job: run the real validation and
**record the result** in `MIGRATION_STATUS.md` as a **one/two-sentence justify-then-`Validated.`** summary
(`Validated on staged upstream: <tables> — gate 2 pending.` when rule #0d step 2 used a staged copy, `DEC-082`)
(why any diff is expected — incremental superset, data recency, upstream source nulls, typed-view formatting…).
The pushing skill reuses that summary verbatim in the comment. Don't post the comment from here.

## Gate 2 — chain validation, before production cutover (`DEC-082`)

Not this skill. Gate 1 (this skill, rule #0d) validates one flow's logic; Gate 2 validates the chain and is
the only place that publishes to `dwh-out` (`DEC-083`). Its procedure is owned by
[[keboola-chain-validation-skill]]; the flows waiting for it are the Productive tasks tagged `gate2-pending`.

## Ending the reply (`DEC-056`)

**Every run ends by naming the next step.** Here that is: [[keboola-pushing-skill]] (P5) when the loop is clean. On a remaining WARN: the question, not a recommendation to push.

Never end on the findings alone — the operator should not have to work out what to run. This holds on a
halt, a SKIP and a parked flow too.
