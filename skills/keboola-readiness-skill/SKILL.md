---
name: keboola-readiness-skill
description: >-
  P2 of the client's Keboola→dbt migration chain — AVAILABILITY: is everything this flow needs actually usable today, and if not, who unblocks it? One skill, one table, a verdict on EVERY row and never one merged answer. Step 0 of EVERY run re-downloads the data owner's DWH-extractor-config workbook LIVE (refresh-sheet.sh) — it is never inherited from P1, because he edits it several times a day and a one-day-old copy turns a queued GET_NOW row into a false "undeclared reference" (DEC-071). Checks, live and now: every model INPUT (durable production home — sap.main / ora / kbc_in / a merged ref() — versus the temporary kbc_stg scaffold versus missing entirely, verdicts ✅ production / ❌ STG / ⛔ MISSING); each input's COMPLETENESS (present ≠ usable — a single DWH_TS batch with a count far below Keboola is one daily batch, not history); every cross-flow PRODUCER's state (merged on qa / migrated but branch unmerged / not migrated at all — a producer migrated but unmerged blocks NEITHER — author against its branch, validate on its staged copy (DEC-082), gate only MR order, DEC-052; a producer nobody has migrated blocks neither either — P3 wires ref() and P4 validates on its same-run staged copy, DEC-082, while the MR waits for the producer; with no staged copy the operator decides between a data-owner ask and a pod build); the RECON REFERENCE, which is checked to EXIST and to be DECLARED in the data owner's DWH-KBC sheet (excluding a stg_* reference from the STG verdict never exempts it from being looked for — an undeclared reference means the flow cannot be validated, DEC-050); the OVERLAP GATE, i.e. whether any window exists where the input and the legacy reference are both complete, so validation is possible at all (DEC-043) with its current-year upper bound (DEC-048); and FULL HISTORY, which blocks nothing and is recorded for the production cutover (DEC-047). Every not-ready row is then LOGGED through the operator's channel from .env-skill (DATA_OWNER_ASK_CHANNEL, DEC-046) — a table logged nowhere is a table nobody is loading. Runs in three modes: pre-migration on the declared inputs, post-migration on the model's actual source()/ref() calls, and a lookup mode for planning order. It does NOT decide MIGRATE/SKIP or classify what an input IS (that is TYPE OF SOURCE, keboola-scope-skill, P1), does NOT create a branch, build, validate or push. Use when asked whether a flow can be migrated or validated, what is missing, or what to ask the data owner for. Triggers on "are the tables ready", "is X on the pod", "can we validate X", "what's missing for X", "source audit", "readiness for X", "is it ready", "what is missing", "what should I ask the data owner for", "is there a validation window".
---

# keboola-readiness-skill

**P2 of the chain — see `HELP/CHAIN.md` for the phase order.**

| | |
|---|---|
| **Entry** | P1 PASS — [[keboola-scope-skill]] has returned MIGRATE / MIGRATE-SUBSET **and** a type of source for every input. Without that classification this skill does not know where to look: a `ref()` target is checked in git, a `source()` target on the pod. No P1 result → go run it first. |
| **PASS** | the table below is emitted with **a verdict on every row**, and no row blocks the phase being entered. |
| **Stop** | any row that blocks the phase being entered, or any row you could not resolve. A row without a verdict is a stop, not a pass. |

## The rule that shapes everything here

**A verdict per row, per phase. Never one aggregate ✅/❌.**

The questions below do not block the same things, and merging them loses exactly the
distinction that matters. A thin input and an undeclared recon reference are different
problems, with different owners and different consequences, and one decision must not
clear both. This is not style — it is the defect that let a flow ship as validated on
2026-08-20 (`DEC-050`).

| Row asks | Blocks migration | Blocks validation | Blocks the production cutover |
|---|---|---|---|
| input has a durable production home | ⛔ if `⛔ MISSING` · ⚠ if `❌ STG` | ⛔ if missing | ⛔ if `❌ STG` |
| input is complete (not one daily batch) | no (`DEC-047`) | ⚠ narrow the window and disclose it | ⛔ |
| cross-flow producer state | no — `ref()` (a local uncommitted stub for parse when not migrated, `DEC-082`) | no — any producer without `gate2-passed` → same-run staged copy (`DEC-082`); ⛔ when no staged copy exists, until the operator decides (data-owner ask or pod build) | ⛔ until the chain passes Gate 2 (`DEC-082`) |
| recon reference exists **and is declared** | no | ⛔ if undeclared (`DEC-050`) | no |
| an overlap window exists | no | ⛔ if none (`DEC-043`) | no |
| full history | **no** | no | ⛔ — recorded, never blocking here (`DEC-047`) |

Read the row you need for the phase you are entering. A ⛔ in the *validation* column
does not stop P3 — it stops P4, and the report must say which.

## The three modes

| Mode | Input list | When |
|---|---|---|
| **pre-migration** | the *declared* inputs — the live flow's input mappings ∩ what the legacy SQL actually reads (grep it; the sheet both over- and under-declares, [[weeks-all-input-row-is-declaration-not-use]]) | P2, before P3 |
| **post-migration** | the *actual* inputs — every `source()` and `ref()` call in the authored model, one row per distinct call | at the end of P3, and it is P4's entry condition |
| **lookup** | one flow or one bare table list, availability only, no phase verdict | planning migration order, or a bare "is X on the pod?" |

The first two are not the same check twice — the second runs against a better list, and
a row can flip between them (`HELP/CHAIN.md`). Never collapse them.


## Step 0 — refresh the data owner's sheet LIVE (ALWAYS, before anything else) (`DEC-071`)

**Every run of this skill re-reads the workbook live. No exceptions, no inheritance from P1.**

```bash
.claude/skills/keboola-scope-skill/refresh-sheet.sh
```

One command, no tool call, ~10 s. It rewrites every tab into `analyses/live/<Tab>.csv` and stamps
`analyses/live/_fetched.json` with the workbook's `sheet_modified_time` + the fetch time. Full
rationale, the rclone setup and the Drive-connector fallback live in **`HELP/SCOPE_SHEET.md`** and in
[[keboola-scope-skill]] step 0 — this step is the same mechanism, deliberately run again.

**Why this is not a duplicate of P1's refresh.** P1 answers *is this flow in scope*; this phase answers
*is the reference declared*, and the two are read from the same sheet at different times. The data owner edits
that workbook several times a day: he flips a `teamRequest` from Weeks-ALL into a DWH-KBC row, he adds
a `GRP=GET_NOW` row, he fills a `CUSTOM_FILTER`. Each of those turns one of this skill's ⛔ rows into a
✅ or into a different ask. Inheriting P1's copy makes the report as old as P1 — and P1 may have run
yesterday, or last week on a parked flow.

**Measured, 2026-09-11.** P2 ran on P1's copy from the previous afternoon (`sheet_modified_time
2026-09-10T11:07`, 886 DWH-KBC rows). The live sheet that morning had **888** rows, and the two new ones
were exactly this flow's: `out.c-project_e.SRC_TABLE_A` with `GRP=GET_NOW` → `s3://dwh-in/stg_src_a`,
plus `teamRequest=<architect> W6` on both Weeks-ALL output rows. The report therefore said *"undeclared,
stop with a drafted ask"* about a table the data owner had already queued, and the drafted message asked him to
add a row that existed. The operator caught it, not the gate.

The refresh is **a row in the `What ran` table**, with the workbook's modified time and the row count,
so the reader can see how old the answer is:

| Step | Checked | Result |
|---|---|---|
| 0 | Data owner's sheet — downloaded live? | ✅ `sheet_modified_time 2026-09-11T12:11`, DWH-KBC **888** rows (yesterday 886 — this flow's `GET_NOW` row was added) |

⚠ **When a refreshed value contradicts something P1 or an earlier run of this skill stated, that
correction goes in the `⚠ Corrections to my previous estimate` section, at the top of the reply** — a
silently-corrected DWH-KBC row is exactly the failure this step exists to prevent.

⚠ **Both refresh paths failing is a PARK, never a fallback to the copy on disk.** Say the sheet is
unreachable, name what you could still verify live (pod, git, Keboola, Productive), and leave every
sheet-dependent row unanswered. Before concluding that, check how stale the local copy actually is:
`python3 .claude/skills/keboola-scope-skill/fetch_sheet.py --require-fresh 6` (exit 0 = fresh within 6 h,
1 = stale, 2 = no copy). A stale copy does not error — it answers with last week's scope.

## Step 1 — cross-flow producers: what state is each one in?

P1 already said *which* inputs are cross-flow producers and which producing flow owns each.
This step asks only whether that producer is usable, and the answer has three states — not two.

```bash
git branch -a | grep -iE '<producer flow slug>'      # local + origin per-flow branches
grep -niE '<producer flow name>' MIGRATION_STATUS.md  # Migrated/Pushed/Validated/Merged state
```

A teammate may have it on an unmerged branch not in the tracker ([[check-colleague-branch-before-migrating]]). Mark each producer ✅ already migrated (→ just `ref()` + merge-order) or ⬜ not yet (→ its Productive task exists or is created; until it lands the flow still wires `ref()`, parses on a local uncommitted stub and validates on the staged copy, `DEC-082`). Wiring + merge order: `ref()` the producer's model and the producer's MR merges FIRST — without exception, also when this flow was validated on the producer's staged copy (`DEC-006`; [[cross-flow-ref-validation-and-merge-order]]).

| Producer state | Migration | Validation | What the row says |
|---|---|---|---|
| **merged on `qa`** | ✅ | ✅ when it is `gate2-passed` (view over `dwh-out`) or has a staged copy (`DEC-082`); ⛔ otherwise, until the operator decides (data-owner ask or pod build) | `ref('<model>')`, nothing to order |
| **migrated, branch not merged** | ✅ — author against the producer's branch | ✅ — on the producer's **same-run staged copy** (`DEC-082`; its branch only for a pod build the operator chooses) | base this flow's branch on the producer's and order the MRs (`DEC-006`, producer merges first); report the flow as *validated on staged upstream — waiting for !<producer MR>, gate 2 pending*, never as merged-clean. Name the branch and its task |
| **not migrated at all** | ✅ — the model wires `ref()`; a local uncommitted stub of the producer model lets `dbt parse` pass (`DEC-082`) | ✅ — on the producer's **same-run staged copy** (`DEC-082` Gate 1); ⛔ with no staged copy until the operator decides: a data-owner ask, or a pod build | the MR merges only after the producer (`DEC-006`). Name the producer flow and its Productive task (create it if none exists); report the flow as *validated on staged upstream — waiting for #<producer> merge, gate 2 pending*. Never a SKIP |

**The middle row is the one people get wrong, and it blocks NEITHER phase** (`DEC-052`, amended
2026-09-03 and 2026-10-06). An unmerged producer stops neither authoring nor validating: authoring runs
against the producer's branch, validation on its staged copy (`DEC-082`). What is gated is **MR ORDER** —
the producer's MR merges first, so until it does the flow is reported as *validated on staged upstream —
waiting for !<producer MR>*, never as merged-clean. The earlier
wording ("validation waits for the merge") is void: four shipped flows disregarded it, the last one
built and tested on `ref('<producer_model>')` with the producer's MR still open.
One condition makes it safe: you author against the branch that is actually being merged (not a stale
local copy). Reporting the middle state as a hard stop parks a flow that could have been finished.

**The last row stopped both phases until 2026-10-06; `DEC-082` replaced that.** The producer's staged
legacy copy is exactly the table the legacy flow read, so validating on it proves our code cleanly, with
no producer bugs mixed in — on the condition that it comes from the SAME legacy run as the recon reference
(Step 2, question 3 applies to it too). Whether the migrated chain works is checked once per chain at
Gate 2, before cutover. The same staged copy is the Gate 1 input for EVERY producer that has not passed
Gate 2 (no `gate2-passed` tag), migrated or not — that choice is made at P4 (validation rule #0d step 2),
not here; this row only records whether a staged copy exists.

⚠ A teammate may hold the producer on a branch that is in neither the tracker nor your local
git ([[check-colleague-branch-before-migrating]]). Check `git branch -a` after a fresh fetch
**and** Productive, exactly as P0 does for this flow.


## Step 2 — the RECON REFERENCE: does it exist, and is it DECLARED?

This is its own row and it is the one most easily skipped, because a `stg_*` reference is
legitimately excluded from the STG verdict — and that exclusion has been misread as "no need
to look for it at all". It is not. **Excluding it from the verdict never exempts it from
being checked to exist** (`DEC-050`).

Three questions, in this order:

1. **Is it declared in the data owner's `DWH-KBC` sheet?** (`analyses/live/DWH-KBC.csv` — **refreshed by
   step 0 of THIS run**, never inherited from P1.) A row there means he stages it and it
   is a legitimate reference. ⚠ The absence of a row is the single most consequential negative
   this skill emits — it becomes a drafted ask and a parked flow — so it must never be read off
   a copy that is even one day old (`DEC-071`).
2. **Is the staged file current?** Compare its window against the input's.
3. **Is it the output of the RIGHT RUN?** For a flow whose input is a pinned prior-run
   snapshot (a cut cycle, a watermark-driven flow), **and for every staged upstream used under
   `DEC-082`** — the reference and the staged upstreams must come from the same legacy run (a copy one
   run newer passes only when disclosed as such). There
   *current* is not the test — see the third row below.

| Declared | On the pod | Verdict |
|---|---|---|
| yes | yes, current | ✅ — the reference is usable, **unless question 3 applies** |
| yes | yes, but frozen/stale | ⚠ — **refresh it** (`HELP/RECON_REFRESH.md`, `DEC-050`(a)). Re-exporting the legacy's own output ourselves counts as a refresh when `GRP=NEW_REFRESH` is unreachable: mirror his `CUSTOM_FILTER` exactly and record the snapshot + the reason in `HELP/DATA_ACCESS.md` (on an earlier flow, `dim_catalog_x` — his file frozen at its 2026-06-21 import while the input reached 2026-08-14) |
| yes | yes, current, but it is a **different legacy run's** output than the one our input snapshot feeds | ⚠ — **refresh it ourselves, timed** into the gap after that run and before the next. Current ≠ correct: on an earlier flow the staged files were dated 21. 9. 01:15 and carried the **20. 9.** run, while our state snapshot was the input of the **22. 9.** run. Applies only where the flow reads prior-run state; `HELP/RECON_REFRESH.md` §2 |
| yes | missing | ⛔ validation — **and it is OURS to fix, not a data-owner ask.** A DWH-KBC row *is* the authorization to refresh (`DEC-078`): set `GRP`, run `worker_run_grp` on the pod. Escalate only if the export itself fails |
| **no** | missing | ⛔ validation — **STOP with the drafted ask** (`DEC-050`(b)) |

⚠⚠ **Before drafting ANY message to the data owner about a reference, grep `analyses/live/DWH-KBC.csv`
for its `BUCKET_TABLE`.** A hit means there is nothing to ask — staged, stale, missing or from the
wrong run, a table with a row is ours to re-run on our own clock, and that includes rows whose
`GRP` reads `DONE` (`DEC-078`, data owner 2026-09-21). What still belongs to him is **acquiring a table
that has no row yet**. Measured cost of missing this on an earlier flow: a message asking him to re-stage 19
tables that all had rows, with a day of waiting planned around it.

⚠⚠ **Never self-serve an undeclared reference.** A missing INPUT may be downloaded and pinned
under `s3://dwh-in/_val_snapshots/` — the model reads an input, so a correct copy lets it
compute correctly and the recon still judges the result independently. The reference **is** the
judge: fetch it ourselves and the test compares our copy with our copy, passes vacuously, and
reports a clean flow. That is exactly what happened on 2026-08-20.


## Step 3 — the WINDOW: can this flow be validated at all, and on what slice? (`DEC-043`, `DEC-055`)

**Answer this before anything is built** — this step decides the validation window, and it is the only
place that decides it. There are **two triggers and one mechanism** (`DEC-055`):

| Trigger | Question it answers |
|---|---|
| **coverage** — an input or the reference does not reach back far enough | is there a window where both sides are complete? |
| **volume** — the table is big enough that an unbounded recon risks OOM or an unacceptable run | how far back can we afford to compare? (standard: last 3 months on the table's `CREATED`/date column) |

Whichever trigger fires, the resulting window carries the **same three conditions** — they are not two
different rules: **(1)** the SAME window on the model AND the legacy reference, so the recon stays
apples-to-apples; **(2)** stated explicitly in the WARN summary and the `MIGRATION_STATUS` ledger — a
validation scope, never a silent shortcut; **(3)** pod-validation-only, and it **must not** be pulled back
into the shipped model ([[client-accepts-3-month-validation]]). Both triggers can fire at once: take the
intersection, and say which one bound it.

[[keboola-validation-skill]] then **applies and discloses** the window this step chose — it does not pick
its own.

The coverage question is the one answerable with no build at all:

> Is there a window where the **INPUT** and the legacy **REFERENCE** are both complete, and is it big
> enough to be meaningful?

```sql
-- both sides, same date column, per month; find where they overlap AND both are complete
SELECT date_trunc('month', "<date_col>") m, count(*) FROM <input>     GROUP BY 1 ORDER BY 1;
SELECT date_trunc('month', "<date_col>") m, count(*) FROM <reference> GROUP BY 1 ORDER BY 1;
-- and the key-coverage of the thin input against the DRIVING table, per month
```

| Answer | Verdict | What happens |
|---|---|---|
| **yes** | ⚠ not production ready, **validation proceeds** | validate on that window, disclose it, then measure the out-of-window impact (`DEC-044`) and raise the owner ask (step 6). The flow goes to MR. |
| **no** | ⛔ **blocked** | no window exists where both sides are complete. Migrate without validation, park the recon, and say so — do not invent a window. |

**⚠ Before parking on a "no", ask WHY there is no overlap.** A **stale reference** is not a blocked flow:
refresh it first ([[keboola-recon-refresh-runbook]], `DEC-050`(a)) and re-run the query. Park only when
the reference is current and the refresh reproduces the same gap — i.e. the producer itself decayed.

**⚠ The window has an UPPER bound too, and it is not about wall-clock (`DEC-048`).** For a **big
table** the answer is **the current year** — the data owner, standup 2026-08-13: *"for the big ones really
validate this year, the old years probably don't make sense"*. The reason is the data: **region C2 was disconnected around 2025-08**,
so last year's legacy table still carries C2's locations and the new DWH has none of them. Widening
the window past January manufactures a mismatch that is not a model bug. His own wording of why is exactly
this gate's criterion — *"this year will be the only period that is complete on both sides"*. So when the
overlap query gives you more than the current year on a big table, **take the current year and say why**;
more is not safer here.
⚠ He scoped the instruction to big tables but the reason does not care about size — a small table carrying
C2 data has the same incomparable 2025. That gap is **open, not closed**: nobody asked him. Don't decide
it in a run; if it bites, raise it through the operator's channel (step 6).

**Which phase does a thin input actually block? (`DEC-047`)** Only the production cutover — not
validation, not push, not the MR, not the merge. Nothing consumes the migrated table until it replaces the
legacy one, so wrong values outside the window harm nothing before that. **The one condition: it is only
"not a blocker" while it is logged and reported** (step 6). An unlogged gap becomes a blocker nobody knows
about at cutover, which is worse than one that stopped work early. Say the dependency in the MR in this
form: *merge is fine, the backfill must land before this table replaces the legacy one for any consumer*.

⚠⚠ **"Not production ready" is NOT "cannot be validated"** (`DEC-043`). The first is an item for the data
owner and the flow ships; the second stops work. Confusing them costs a week of a stalled flow — it has
already happened (an earlier flow was written up as unvalidatable and was not). Before parking anything as blocked,
run the query above and prove no window exists.

**Do NOT try to classify by asking "does the missing input change the output?"** — that cannot be answered
without building and comparing. On an earlier flow the mechanism was predicted (`ZCUST_T01`) and the prediction was
wrong: that branch produces zero rows anywhere. The real impact appeared only after the build. Overlap is
measurable now; effect is not.

## Step 4 — measure the IMPACT of every thin input (`DEC-044`)

A gap reported without a number does not get scheduled. Estimate nothing; run these three, in order:

1. **Per-month divergence profile.** Gradual rise with age = ordinary churn. A flat rate that drops to ~0 in
   one month = a coverage cliff, i.e. the input is the cause. Worked example: flat 0.47–0.60 % for 13 months,
   **0.000 %** at 2026-03, and the partially-covered month between them (37.5 %) at a reduced 0.38 %.
2. **Split by COVERAGE, not by date.** `left join (select distinct <key> from <thin input>)` and compare
   the two buckets. This holds the date constant, so it is causation rather than correlation. Same example:
   **0.009 %** on covered rows vs **0.543 %** on uncovered — 62×.
3. **`group by ref_value, model_value order by count desc`.** Do this BEFORE naming a mechanism; it is
   what falsified the `ZCUST_T01` guess and named the real one (a specific code collapsing to a generic
   fallback).

For numeric columns quantify with `abs(a-b) > <epsilon>`, **never** `round(a,n) <> round(b,n)` — ties make
the count swing with the precision (same example: 150 at 6dp, 14,553 at 5dp, 78 by epsilon). Restrict to keys
unique on BOTH sides, or recon cross-pairing inflates it.

## Step 5 — the availability table (ALWAYS emit it — this is the last thing in the reply)

Every run of this skill **ends** with the source-audit table so the operator sees at a glance whether the
flow is ready to migrate. Never replace it with prose, never put it mid-reply, never summarise it away —
"can we migrate?" is answered by this table. Verdict column values are exactly `✅ production`,
`❌ STG`, or `⛔ MISSING`.

**It is drawn with markdown pipes, not box characters** (`DEC-069`, narrowing `DEC-034`): it carries a
Keboola URL per row, and a URL is neither clickable nor width-affordable inside a box table — seven columns
with a URL is ~250 characters of frame. Markdown also survives a paste into an MR or a Productive comment,
which is what `DEC-034` was protecting in the first place. A verdict table with **no** links still gets box
characters.

**And the table is SPLIT INTO BLOCKS by the phase each row holds up** — one block per phase, the phase as
the block heading, most-blocking first (`DEC-069`). The `Verdict` column answers *where does this table
live*; that is not the same question as *what does this stop*, and merging them is the defect the per-row
rule table at the top of this skill exists to prevent. Without the split the operator has to re-derive the
phase from the verdict, or go open the registry page — which is exactly what happened on an earlier flow
(2026-09-08), where the availability table showed 8 `❌ STG` rows and could not say that none of them
blocked anything we were about to do.

Block order is fixed, each block is its own `###` heading with the row count, and a block with no rows is
dropped (not printed empty):

1. `⛔ Blocks migration and validation` — reserved for the rows where there is **nothing to author and nothing
   to stand in for it**. A merely missing INPUT is NOT one of these (`DEC-065`), and since `DEC-082` neither is
   a producer nobody has migrated (`ref()` + staged copy; the MR waits for the producer)
2. `⛔ Blocks validation`
3. `⚠ Blocks production cutover`
4. `✅ Blocks nothing`

Every block repeats the SAME seven columns, so the whole thing reads as one table cut into pieces.
`Blocks nothing` is usually the biggest block and is never omitted — a verdict on every row is the rule, and
a dropped row reads as "not checked". Below the last block, one bold tally line:
*`38 rows · Blocks: migration 1 · validation 1 · production 13 · nothing 23.`*

### The seven columns

| Column | What goes in it |
|---|---|
| `Table` | the table as the flow sees it — the legacy alias / bare name. A transitive input keeps its provenance: `↳ transitive via ref('fact_orders_x')`. In variant A, the `source()`/`ref()` call prefixed by its line numbers (`42 · source('stg_src_a','src_table_b')`) |
| `Type` | `INPUT` · `REF` · `RECON`, the SAME three values [[keboola-missing-tables]] uses, so one table can be read against the other: **`INPUT`** = the model reads it and it must live in a durable DB (`sap` / `ora` / `kbc_in`) · **`REF`** = one of OUR models produces it, so it is wired as `ref()` · **`RECON`** = the legacy output the reconciliation compares against, belongs in `kbc_stg`. ⚠ One widening against that skill: it scopes `REF` to *a producer of the same week*, this one does not — a producer merged three weeks ago is still a `REF`, because the question here is the wiring, not the schedule. `INPUT` vs `REF` is decided by P1's type-of-source verdict, never re-derived here |
| `Keboola origin (URL)` | the **bare URL**, not a markdown link — the operator copies it. Always the ORIGIN, never the relay the flow reads: `https://connection.keboola.example/admin/projects/<PID>/storage/<bucket>/table/<TABLE>`. Chase `sourceTable` one hop past the `out.c-from_X_to_Y` relay — on an earlier flow all eight SAP inputs resolved from `out.c-from_00_project_a_to_10_project_b.*` to `out.c-project_a.*` in project `<PID>`. For a set of sibling tables read through one extractor, link the **bucket** instead and say `(4×)` in `Table` |
| `Project` | the owning project NAME, **without the id** (`00 Project C`, not `00 Project C (<PID>)`) — the id is already in the URL |
| `On the pod` | where it actually resolves today plus the numbers: `sap.main.A902` / `ref('x')` #<task> merged / `kbc_stg.…`, row count vs Keboola, and the window. This replaces the old `Durable home` **and** `Target` — the target DB is the prefix of the value, so a separate column duplicated it |
| `Verdict` | `✅ production` · `❌ STG` · `⛔ MISSING`, plus a `⚠` qualifier and the registry id (`❌ STG, T12`) |
| `Note` | **what somebody has to DO, and who** — see below. `—` when nobody has to do anything |

### The `Note` column

It exists so the operator never has to open the registry to find out who is on the hook. Three prefixes,
and nothing else goes in this column:

- `**Data owner:**` — the concrete ask, in his vocabulary: which `INOUT` value, which S3 prefix, which
  filter, and the row count. *"add a DWH-KBC row `INOUT=IN` → `in_src_b/`, full (25 000 rows)"*.
  A question rather than a load starts `**Data owner — question:**`, and one that must be answered before any
  load starts `**Data owner — question first, then load:**`.
- `**Our work:**` — ours, with what exactly (a missing model in another task, a repoint, a snapshot).
- `**Not a data-owner item**` — mandatory on a row whose `Verdict` looks like his problem but is not
  (an `❌ STG` whose durable replacement already exists, so it is a repoint). Without it that row reads as
  a pending ask forever.

A `✅` row may still carry a `⚠` note when something about it is worth knowing but blocks nothing — a
stale staged copy the model does not read, say. Everything else gets `—`, so the column stays scannable.

Assign the block mechanically from the per-row rule table — never by judgement:

| Verdict cell | Block |
|---|---|
| `✅ production` | `nothing` |
| `✅ production` + a `⚠` qualifier (frozen load, thin, incomplete) | `production` — validation is merely windowed (`DEC-047`) |
| `❌ STG` | `production` — the pin builds and validates fine ([[no-stg-inputs-in-models-rule]]) |
| `⛔ MISSING` input | `validation` — a missing input does not stop AUTHORING (P3 needs `dbt parse` and a tag bind, not data — `DEC-065`: *"P3 finishes, P4 waits"*); it stops the BUILD. A `_val_snapshots/` pin (`DEC-050`) removes it from this block entirely |
| producer merged, or migrated but branch unmerged | `nothing` when it is `gate2-passed`; `production` when it has only a staged copy — P4 validates on it, the cutover waits for the chain's Gate 2 (`DEC-082`); `validation` when it has neither, until the operator decides (data-owner ask or pod build). The unmerged one also blocks MR order (`DEC-052`) — say so in `Note` as *MR waits for !<producer MR>* |
| producer not migrated at all | `production` — P3 wires `ref()`, P4 validates on the same-run staged copy, the MR waits for the producer (`DEC-082`, `DEC-006`); `validation` when no staged copy exists, until the operator decides (data-owner ask or pod build) |

An **undeclared recon reference** is a normal row with `Type = RECON` — it used to be a sub-list, which was
pointless once `Type` carries the distinction. It is the most common `validation` blocker. The same Keboola
table can legitimately appear TWICE under different types: on an earlier flow `SRC_TABLE_C` was a `REF` (the
`ref()` target does not exist, because the producing flow never migrated that code) **and** a `RECON` (no reference was
staged for the model we were about to write) — two rows, two different actions, two different owners. That
is not a duplicate; do not collapse it.

**Recon references that are staged and current stay OUT of the table** — they are neither a blocker nor an
STG violation. Say how many in one line beneath it (*"32 staged recon references are not in the table"*).
A reference that BECAME staged during the work is the exception: keep it as a `✅` row so the delta is
visible, with the registry id in `Verdict` (`✅ staged 9. 9., T15 done`).

Pick the variant by whether a model already exists:

**A — flow already authored** (a `#<task>_Week_*` branch carries model SQL): audit **every** `source()` /
`ref()` in the model, one row per distinct call, line numbers collapsed into the `Table` cell
(`190, 291 · source(...)`). Open the reply with the one-line verdict (`No — it's authored, but 3 of its 9
source references still point at STG, not production`) then the blocks.

**B — not yet authored**: one row per **required input table** (from the live `_flow_tasks.json` input
mappings **∩ what the legacy SQL actually reads** — [[weeks-all-input-row-is-declaration-not-use]] both
ways: the sheet over-declares *and* under-declares, so grep the SQL). Same seven columns, same blocks.

The shape, in both variants:

```markdown
### ⛔ Blocks validation (1)

| Table | Type | Keboola origin (URL) | Project | On the pod | Verdict | Note |
|---|---|---|---|---|---|---|
| SRC_TABLE_C | REF | https://connection.keboola.example/admin/projects/<PID>/storage/out.c-bucket_c/table/SRC_TABLE_C | 00 Project C | model does not exist; inputs `*_part` 14 000 / 25 000 rows on the pod | ⛔ MISSING (our producer, T17) | **Our work:** add model `src_table_c` to #<task>. **Data owner:** automate the input load (`GRP=TODO_AUTOMATE`) — does not block. |

### ✅ Blocks nothing (2)

| Table | Type | Keboola origin (URL) | Project | On the pod | Verdict | Note |
|---|---|---|---|---|---|---|
| A902 | INPUT | https://connection.keboola.example/admin/projects/<PID>/storage/out.c-project_a/table/A902 | 00 Project A | `sap.main.A902` 560 000 000 rows (C1 495 M, C2 0), 4 batches | ✅ production (C1 slice) | — |
| ↳ transitive via `ref('fact_orders_x')` | INPUT | https://connection.keboola.example/admin/projects/<PID>/storage/out.c-bucket_d/table/src_table_d | 00 Project D | `kbc_stg.stg_src_d.src_table_d` 11 000 000 rows | ❌ STG (inherited from earlier flows, T09) | **Not a data-owner item** — a durable replacement is already on S3, so this is a repoint, not a load. |
```

⚠ A transitive row sits in the block of **its own** phase, not its parent's — on an earlier flow the parent
`FACT_ORDERS_X` was `✅ nothing` while its inherited `src_table_d` was `⚠ production`. The
`↳ transitive via ref('…')` label is what keeps the origin readable once they are in different blocks.

Rules that make the table trustworthy:

- **Check LIVE on the pod, never from a sheet or from memory.** A table's readiness flips week to week
  ([[sap-db-landings-2026-07-26]]); catalog presence alone is not readiness
  ([[sap-ready-on-s3-not-in-catalog]]). Row-count + window per table.
- **A `00 *`-project table absent from the pod is NOT `⛔ MISSING` until step 3b clears it.** The pod is the
  wrong place to look for a table our own repo already produces — a migrated producer's output lives in the
  dbt project, not in `sap`/`ora`/`kbc_in`, so the pod probe returns "nothing" for a table that is perfectly
  available. Run the step-3b qa grep on the **bare table name** first; a hit makes the row `✅ production`
  with `ref('<model>')` in its `On the pod` cell. Skipping this once turned `SRC_TABLE_E` into a `⛔` row and a
  data-owner ask for a table another flow had already migrated and merged.
- **`kbc_stg` as a model input is always `❌ STG`**, never "ready" — [[no-stg-inputs-in-models-rule]]. A
  `stg_*` in a recon test `reference:` is *correct* and does **not** belong in this table (say so in a
  one-liner beneath it instead).
- **⚠ Excluding the recon reference from the VERDICT is not the same as not checking it EXISTS.** The
  exclusion above says a `stg_*` reference is not a *STG violation*; it never says the table is exempt
  from being looked for. So probe it like any other: is it in the data owner's DWH-KBC sheet, and is it on the
  pod? Absent from **both** = **undeclared** — the flow cannot be validated, and it becomes a row with
  `Type = output` in the `⛔ Blocks validation` block whose `Note` carries the ask (step 6), exactly like
  a `⛔ MISSING` input. Declared but merely stale is a different
  thing and is not an ask: it gets refreshed (`DEC-050`). This is the hole that let a flow through on
  2026-08-20: the reference was in neither place, nothing gated on it, and validation ran against a
  copy pulled from Keboola instead. A recon reference that exists nowhere is a stop, not a footnote.
- **Distrust in-repo justifications for a STG pin.** Comments in `sources.yml` / the model explaining why
  something *had* to be STG go stale silently (one earlier flow carried three such claims, all false within a week) —
  re-verify each against the live pod and say plainly that the stated reason no longer holds.
- **Before calling a STG→production repoint safe, prove the durable home is a superset**: per-key coverage
  (`N/N found, 0 missing`) or per-month counts across the overlap window. A narrower durable home is the
  [[interim-stg-slice-narrower-than-legacy]] trap, not a repoint.
- **An increment-only input is `⛔ MISSING`, and its `Note` must name the ask.** Present-in-the-catalog is not
  ready: `count(distinct DWH_TS) = 1` with a count ≪ Keboola `rowsCount` and a few-days window is a single
  daily batch. Per the data owner's 2026-08-12 rule (step 3) this is unfinished backfill work he *wants* reported,
  so `Note` carries the ask — table name, pod count vs Keboola count, the window — not just the ⛔.
  Judge by that measurement, **not** by the view's target path: an `IN_PREP/` view over a FULL-exported
  table is complete and final (`SRC_TABLE_F`, 80M rows), so it is `✅ production` and generates no ask.
  Before drafting the ask, check whether a *different* durable table can serve: prefer the accumulated
  sibling if it carries every column the SQL reads (on one flow `ZDOC_FLOW_X` had no substitute — `sap.main.VBFA` is
  accumulated but lacks `BWART`, which the filter needs; on the same flow `ATTR_VIEW_X` did — `0ATTR_FULL_X`,
  86.5M vs the same-columned 755k view).
- **A "needs TODAY's data" gap is NOT `⛔ MISSING` and NOT a blocker** — it is a validation-scoping
  problem. Two shapes: the legacy SQL pins the current date (`CURRENT_DATE() - DATUM = 0`) while the data owner's
  `IN_PREP` dump is written just after midnight so the pod copy never holds today; or the frozen `stg_*`
  reference's window doesn't overlap the pod input's. Mark the row `✅ production` (the table IS there)
  and note the freshness/window gap beneath the table, with the fix being a **proposed** validation
  adaptation — refresh the reference ourselves ([[keboola-recon-refresh-runbook]]) plus a fixed-date test
  run, never applied without operator sign-off. Full rule in [[keboola-validation-skill]]. Before ever
  writing "history is missing", check the output mapping's `incremental` flag and the SQL's own date
  filter: an `incremental` output that appends one day per run has accumulated its history over years and
  can never be recomputed from a source window (`SRC_TABLE_G` — 1,035 days since 2022-11-29; the first
  draft wrongly asked the data owner for the full 35-billion-row `LOG_TABLE_H` log). Do still record it as a data-owner ask
  if the pod copy will never hold today — but as *production correctness*, not as a validation blocker.
- Under the table, add only what changes the decision: the repoint targets, join-type traps between the stg
  and durable typings, expected-WARN facts (history floor vs legacy start, [[validation-window-3-years]]),
  and scale/OOM risk. Then the verdict + next action.


### Full history — recorded, never blocking (`DEC-047`)

**⚠ An increment-only pod input is ALWAYS a data-owner ask, and it must be raised HERE — at P2.** The data owner, asked directly 2026-08-12 (full text + his backfill pipeline in `HELP/DATA_ACCESS.md`): *"The rule is that a view has to point at the full history. If it doesn't, always let me know and I will migrate it."* Full history is the **target state**, not a later phase — a thin slice is unfinished work he schedules **by our priorities**, so an unreported gap is one that never gets fixed. Two rules follow:
- **Report before you adapt.** Narrowing the validation to the available slice is a legitimate interim, but it is the *second* step. Silently scoping around the gap and saying nothing is the failure mode this rule exists to stop.
- **Raise it at P2, not at validation.** Backfilling one big table (split by year, each part re-typed, plus any dependency transformation he has to migrate himself) is **3–4 hours** of his work. The ask has to be in his queue while we are still authoring the model.
⚠ And do NOT read an `IN_PREP/` target path as a gap on its own: ~230 SAP tables live there legitimately, because a table SAP exports as **FULL** has its whole content in the daily file. Only an **incremental** export is short. Decide on the measurement (count vs Keboola `rowsCount`, `DWH_TS` batch count, date window), never on the path.

## Step 6 — log every not-ready table, via the OPERATOR'S channel (`DEC-046`)

**Every row that is not `✅` gets logged — a table logged nowhere is a table nobody is loading.**
This is the one write this skill performs. It covers more than the two audit glyphs: an `❌ STG` or
`⛔ MISSING` input, an undeclared or stale recon reference, a producer nobody has migrated, **and a
full-history gap** — which blocks nothing here but is scheduled from this registry or not at all
(`DEC-047`).

**The channel is read from `.env-skill` (`DATA_OWNER_ASK_CHANNEL`), never hardcoded** — the same pattern as
`DEC-030` for message language. Two values:

| `DATA_OWNER_ASK_CHANNEL` | Where the row goes | Who |
|---|---|---|
| `sheet` | one appended row per table in the batch Google Sheet | the lead |
| `vault` | the operator's registry page + a drafted message for them to send | the architect |

### `vault` — the registry page (the architect)

Append one row per table to the operator's registry page in `$BRAIN_DIR` —
**`01_Projects/Input and recon tables — status.md`, the ONE canonical page** (operator decision
2026-08-20, `DEC-053`). `01_Projects/Open items for the data owner.md` is archived: two pages for one purpose
meant an item could be written to either and read from neither. Then **draft the message** for the
operator to send — formal, `DEC-030` salutation, language from `DATA_OWNER_MESSAGE_LANG`. Do not send it.

**The page has two layers: a scannable table, and one detail section per table.** Keep them that way —
an earlier version put paragraph-length prose in the table cells and became unreadable.

**Table row**, columns in this order:

| Column | Content |
|---|---|
| `#` | a permanent `T<n>` id — assigned once at write time, **never renumbered**, not even when the item is resolved and moves to *Resolved*. Refer to items as `T3`, never by position. |
| `Logged` | date and time of the entry. **First column, and the table is sorted by it**, oldest first, so it reads as a log. |
| table | the pod-side name (`sap.main.ZCUST_T02`) |
| `INPUT` / `RECON` | always explicit, never inferred. An input that is incomplete makes the model compute wrongly; a recon reference that is missing only stops validation. |
| flows | `[[#<task-a>]]`, `[[#<task-b>]]` — one row per TABLE, so a table blocking three flows lists three flows here |
| **our copy** | link, text = `<project id> · <bucket>` |
| **most-upstream original** | link, same text form. Leave empty (`— *is the origin*`) when our table IS the origin. |
| `kind` | what kind of item this is, from the fixed vocabulary — `missing` · `stopped load` · `stale` · `incomplete` · `undeclared` · **`full history`** · `unmigrated producer`. One word, never a sentence. `full history` is the non-blocking kind: it waits for the production cutover, so it never holds a flow up but it does have to be here to ever get scheduled (`DEC-047`) |
| problem | **a link to the detail section**: `[[#T3 — SRC_X|detail ↓]]`. Nothing longer — the `kind` column already says what kind it is |
| state | `⬜ open` / `assigned <date>` / `done <date>`, plus a `⚠ re-measure` note when the measurement is more than a few days old |
| blocks | which phase this actually holds up — `validation` · `migration` · `production` · `nothing`. Straight from the per-row table at the top of this skill, so the registry never has to re-derive it |

**Detail section** per table, heading `## T<n> — <SHORT NAME>`. ⚠ The heading must be **plain text** —
no wikilinks, no backticks — or the `[[#...]]` anchor from the table does not resolve in Obsidian. Put
the longer identification (full name, INPUT/RECON, flows) on an italic line under the heading. Then, in
this order: **Problem** (two or three plain sentences saying what is actually wrong and why it matters —
never a bare category label, which explains nothing) · **Links** · **Measured** with its date ·
**Impact** (`DEC-044` — measured, never estimated) · **What we want** · **Status**.

All numbers live in the detail section, never in the table row.

⚠ **The original is what the data owner needs, not our copy.** We read a linked copy in an `in.c-from_*`
bucket; he needs the table that actually produces the data. Chase `sourceTable` in the Storage API and
**stop only when `sourceTable` disappears — NOT when the bucket stops being linked**: on an earlier flow the
`ZCUST_T03` origin sat in `out.c-from_00_project_a_to_10_project_b`, a bucket named like a relay,
and `out.c-project_a.ZCUST_T03` returned 404. Resolving one table costs two or three API calls and a
token for the upstream project.

The page is the operator's, in their vault, and **never enters the client repo** (`brain` is excluded from
git). It is the one exception to the vault being read-only context (`DEC-040`): this single named file is
written to, nothing else in the vault is.

## Ownership

| Not here | Owner |
|---|---|
| is the flow already migrated / pushed / merged | [[keboola-status-skill]] (P0) |
| MIGRATE / SKIP, and what each input IS (`ref()` vs `source()`) | [[keboola-scope-skill]] (P1) |
| branch, SQL conversion, model + test authoring | [[keboola-migration-skill]] (P3) |
| the build, the recon run, WARN triage | [[keboola-validation-skill]] (P4) |
| the same inventory across a RANGE of weeks | [[keboola-missing-tables]] — it calls this skill per flow rather than carrying its own copy of these checks |
| clearing `kbc_stg` debt on models **already merged into `qa`** (this skill's `❌ STG` verdict is for the flow being migrated now; the accumulated debt is a batch job) | [[keboola-stgtablechange-skill]] |

This skill decides nothing about scope and writes nothing to a branch. Its only write is
step 6.

## Output — the shape of the reply (`DEC-057`)

**Sections in this order. Evidence goes in a table CELL, never in a paragraph** — keep the count, the
date, the percentage; drop the sentence explaining why it matters. Drawing: the availability
table is **markdown pipes** because it carries URLs (`DEC-069`, narrowing `DEC-034`), and so is everything
below it.

### 1 — The verdict, as a heading

```
# ✅ PASS — nothing blocks migration or validation
**`15 Project F / Flow A`** · measured live on `pod-03`, 2026-08-21 ~08:45
```

`✅ PASS` · `⚠ PASS with a condition` · `⛔ BLOCKED` — and a PASS says **what it clears**, because this phase
gates two different things: `nothing blocks migration or validation` reads differently from
`migration yes, validation no`. Always name the pod and the measurement time: these numbers decay.

### 2 — `⚠ Corrections to my previous estimate` — when a measurement contradicts an earlier claim

**Mandatory whenever a number you or a prior phase stated turns out wrong, and it goes FIRST — above the
step table.** One bullet per correction: the corrected fact, the number, and *why the old one was wrong*.
Then a bullet for its consequence, if it changes what P3 must do.

A silently-corrected number is the worst failure this phase has: the next phase inherits the old one from
the conversation. Example that earned this section — `KBC_ROWS` in DWH-KBC is the **Keboola** row count,
not the parquet's, so a reference filter read as a no-op was actually removing 82 %.

### 3 — `What ran` — one row per step, and per question

| Step | Checked | Result |
|---|---|---|
| 0 | Data owner's sheet — downloaded live? | ✅ `sheet_modified_time 2026-08-21T06:12`, DWH-KBC 874 rows, unchanged since P1 |
| 1 | State of cross-flow producers | ✅ producer **Flow B** merged on `qa` → `ref()` works |
| 2 | Recon reference — declared? exists? | ✅ in DWH-KBC **and** on the pod, 4 400 000 rows |
| 3 | Validation window — is there an overlap? | ✅ `2014-03-31 → 2026-06-30`, neither the coverage nor the volume trigger |
| 3a | `DEC-048` cap | ➖ does not apply — the reference has not a single C2 row |
| 5 | Input availability | ✅ 4/4 `production` |
| — | Full history (production cutover) | ✅ nothing missing, no entry |
| 6 | Write to the vault registry | ➖ nothing added — nothing to log |

Glyphs: `✅` fine · `⚠` fine but qualified · `⛔` this is what blocks · `➖` did not apply · `❓` could not
answer. **A step that ran but did not apply still gets its row** — a missing row reads as "not checked",
and that is exactly how a recon reference nobody looked for slipped through on 2026-08-20.

⚠ **Where a row blocks something, the cell says WHICH phase** (`⛔ blocks validation, not migration`).
Never one merged verdict for the whole table — that is this skill's core rule, and the output must show
it. The vault write is a row too, including when nothing was written: `➖` plus why.

### 4 — The measurement tables — only the ones that carry a number

- **`Window — reference vs pod, by year`** whenever a window was decided: per-year counts on both sides
  plus a `Diff` column, so "nine years match to the row" is visible instead of asserted.
- **`Expected WARNs — quantified before the build`**: one row per recon test, its predicted WARN size, and
  the one-line reason. This is the highest-value thing this phase produces — P4 recognises those WARNs
  instead of investigating them, and a WARN that arrives at a size you did not predict is a real finding.
- A refresh decision, when the reference is stale: state it and why, in one sentence, with the runbook
  offered rather than run.

### 5 — `📌 For P3` — bullets, one line each

What P3 must not rediscover, each with its number: the recon key and whether it is unique **on both
sides** (name the duplicate count if not), joins that need a dedup and the precedent file+lines to copy,
type/dialect traps found in the real data, `sources.yml` entries to add, and stale in-repo comments the
measurement disproved. Mark with `⚠` anything that contradicts a note already in the repo.

### 6 — The availability table, LAST (`DEC-069`)

Markdown pipes, seven columns — `Table · Type · Keboola origin (URL) · Project · On the pod · Verdict ·
Note` — **split into blocks by the phase each row blocks**, headings and order per step 5, empty blocks
dropped, the same columns repeated in every block. Full column semantics, the `Note` prefixes and the
worked shape are in step 5; do not restate them here.

Then the bold tally line — *`38 rows · Blocks: migration 1 · validation 1 · production 13 · nothing 23.`* —
and, only if they apply, the one-liners: how many staged recon references were deliberately left out, and
the note that `Type` uses the same `INPUT`/`REF`/`RECON` vocabulary as [[keboola-missing-tables]].

Then the `DEC-056` closing line — the next phase and the branch name.


## Ending the reply (`DEC-056`)

**Every run ends by naming the next step.** Here that is: [[keboola-migration-skill]] (P3) after a pre-migration run, [[keboola-validation-skill]] (P4) after a post-migration one. On a blocking row: the drafted ask, its owner, and that the flow waits.

Never end on the findings alone — the operator should not have to work out what to run. This holds on a
halt, a SKIP and a parked flow too.

**Compound first (`DEC-022`).** Before that closing line — always, success or stop — write anything this
phase learned into `HELP/FIXES.md` (a new breakage + its fix) and `HELP/DATA_ACCESS.md` (a data-location
fact), then name the entries added in the reply. Full rule: `HELP/CHAIN.md`.
