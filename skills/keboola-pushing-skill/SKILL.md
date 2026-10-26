---
name: keboola-pushing-skill
description: >-
  **P5 of the migration chain (HELP/CHAIN.md), the last phase.** Entry is P4 PASS: keboola-validation-skill reported the flow clean (0 unexplained WARNs, each remaining one justified with pod evidence) and synced the validated files back onto the local branch. Never push a flow whose validation did not pass or did not run. Final skill in the chain: commit a VALIDATED Keboola→dbt flow (whose files keboola-validation-skill already pulled back from the pod scratch onto the local branch — the pod→local sync is validation's final step since 2026-07-08, NOT this skill's), then push it to GitLab + open the MR into qa + post the completion comment on the Productive task — all directly (osxkeychain has a cached PAT, so GIT_TERMINAL_PROMPT=0 git push works non-interactively; hand off to the operator only if the push errors). The per-flow branch #<task>_Week_<week>_<project_slug>_<flow_dir> exists from migration Step 1; this skill stages with a TARGETED git add (only this flow's files — never git add -A, never drops other merged flows, since the branch is based on qa), secret-guards, commits, pushes + creates the MR into qa, comments on Productive in the SETTLED bullet format (Step 3: `<li><b>Label</b> | ✅ YES | evidence</li>` rows mirroring the validation STATE + What-VALIDATED-covers tables — never a table, never `<pre>`, ≲3k chars; the lead signed this off 2026-07-27, do not redesign), and moves the task to To Review (<TO_REVIEW_STATUS_ID>) via set_status.py — NOT Done (Done is the post-merge state, DEC-085). Before the push it stops on any ⛔ row of check_s3_publish.py: an output without the S3 publish hook (filtered variants excepted) or an intermediate with one (DEC-084). No dbt parse / re-validation — the flow is already clean from keboola-validation-skill. Run after keboola-validation-skill reports the flow clean. Triggers on "push this flow", "push to gitlab", "commit and give me the push command".
---

# keboola-pushing-skill

Final skill in the migration chain. **Commits the validated flow** on the branch
[[keboola-migration-skill]] created (off a fresh `qa`) — the flow's files are **already on the local branch**:
the pod→local sync is [[keboola-validation-skill]]'s final step (moved there 2026-07-08, per the lead), so this
skill does NOT pull anything off the pod — then **pushes it to GitLab + opens the MR
into `qa`**, **posts the completion comment on the Productive task**, and **moves the task to To Review**
(`<TO_REVIEW_STATUS_ID>`, senior review — not Done). Claude pushes directly — the
osxkeychain has a cached PAT, so `GIT_TERMINAL_PROMPT=0 git push` works non-interactively; hand off to the
operator only if the push errors (stale PAT). Run this **after [[keboola-validation-skill]] reports the flow
clean** ("ready for pushing") — the flow is already validated, so **this skill does NOT run `dbt parse` or
re-validate anything**; it just ships. See [[gitlab-https-push-auth-pat]].

## Inputs (operator supplies)
- **`task:`** — Productive.io number → the `#<task>` branch prefix + commit/MR title. **Required; if
  missing, STOP and ask** (not derivable).
- **`project:`** + **`flow:`** — identify the flow: its pod scratch (`/app/kbc/<flow_dir>_val`), the model
  dir to pull, and the `#<task>_…` branch name migration created.
- **Pod target** — repo URL + **MR base branch**. Known: **`bi/keboola`** is where these per-flow branches
  live (`#<task>_…`, one per flow), and the **MR target/base branch is `qa`** — merge each flow branch into
  **`qa`** (the QA branch), NEVER `main`/`master`. Confirm repo + base for any project you're unsure about.
- **The branch already exists** (migration Step 1, off a fresh `qa`) and is checked out. If you're running
  standalone and it's absent, create it off a **fresh** `origin/qa` (`git fetch origin qa && git switch -c
  "$BRANCH" origin/qa`). Because the branch is based on `qa`, other already-merged flows are the baseline —
  **do NOT drop them**; a **targeted `git add`** keeps the commit scoped to this flow.
- **Per-user/per-pod config** — the pod target, commit identity, and Productive.io coordinates below come
  from the repo-root `.env-skill` (`KEBOOLA_POD`, `KEBOOLA_POD_NAMESPACE`, `GIT_USER_NAME`, `GIT_USER_EMAIL`,
  `PRODUCTIVE_PROJECT_ID`, `PRODUCTIVE_ORG_ID`; copy `.env-skill.example` if it's missing). `source .env-skill`
  (or `set -a && source .env-skill && set +a`) before running the commands below.

## What the pushed branch must look like — ROOT-LEVEL, based on `qa`, scoped by a targeted add

**The branch is based on a fresh `qa` and the project lives at the REPO ROOT** — no `dbt_project/` wrapper
(manager directive, 2026-06-30; [[dbt-project-root-level-structure]]). Since `qa` is already root-level,
there's normally nothing to flatten. The commit **adds only this flow** on top of the `qa` baseline:
- **This flow's files are already local** — `models/<project_slug>/<flow_dir>` + the accumulating
  `models/sources.yml` and `dbt_project.yml`, pulled back from the pod scratch by
  [[keboola-validation-skill]]'s final step (2026-07-08 — the pull mechanics live THERE now; this skill
  does not touch the pod). The rest of the tree is the `qa` baseline and stays as-is.
  **Never drop other flows' model dirs** (they're merged in `qa`) — scoping is done by the **targeted
  `git add`**, NOT by `git rm`. See [[per-flow-branch-only-this-flow]].
- **`sources.yml` + `dbt_project.yml` stay ACCUMULATING** (all projects' blocks; `dbt1097` warns OK).
- **Consolidation branch** (several flows in one MR) → `git add` exactly each flow's dir. Ask
  if scope is ambiguous.
- **Never staged** (prototype/local-only): `.claude/`, `retrieve_keboola/`, `migration_log.csv`, `input/`,
  `HELP/`, any `*_TEST/`. Use **targeted `git add <files>`, never `git add -A`**. See
  [[migration-commit-excludes-prototype-files]].
- **Any `.md` that DOES ship goes in `docs/`, never the repo root** (operator rule, 2026-08-07). A
  standalone document that belongs in the client repo — a convention writeup, a cross-cutting design
  note like `docs/TIMEZONES.md` — is committed as `docs/<NAME>.md`. Three exceptions, all pre-existing
  and staying put: root `README.md`, root `HOW_TO_BUILD.md`, and the per-folder `_README.md` files that
  document the models sitting beside them. This is about the CLIENT repo only — `HELP/` and the skills
  are symlinks into the local `keboola` workspace and never reach GitLab at all. Watch the timing: docs
  usually get written mid-task, long before this skill loads, so the placement decision happens when the
  file is CREATED, not here. See [[keboola-shipped-md-goes-in-docs]].
- **A thin input is not a reason to hold the MR (`DEC-047`)** — it blocks the production cutover only.
  Push and open the MR as normal, and put the disclosure in the MR body: the measured impact (`DEC-044`),
  the disclosed window, and the sentence *the backfill must land before this table replaces the legacy one
  for any consumer*. Confirm the item is logged in the operator's channel (`DEC-046`) before you push —
  an unlogged gap is the one that surfaces at cutover with nobody expecting it.
- **Pod-validation-only edits must not be in the commit** — a disclosed 3-month `CREATED` filter
  ([[client-accepts-3-month-validation]]), a temporary source repoint, or a pod-only date anchor never
  ships; the validation skill's pull-back already excludes them (and never brings the pod `profiles.yml`) —
  here it's a final eyeball on `git diff --cached`, not a re-pull.
- **`profiles.yml` NEVER enters git — no exception, no phase (`DEC-060`).** It is pod-local scratch
  config: the `dev` target gets re-tuned to whatever pod you are on ([[keboola-validation-skill]]
  Step 0b) and that edit is re-applied after every pod restart. So a modified `profiles.yml` in
  `git status` is the **expected steady state**, not something to tidy up by committing. The targeted
  `git add` below already excludes it — the failure mode is a well-meaning `git add -A` or a "let me
  just clean the working tree" reflex. If `git diff --cached` shows `profiles.yml`, unstage it.

## Procedure
1. **Pre-push context check** — confirm `task:`, `project:`/`flow:`, and pod target are known. Missing
   `task:`/target → STOP and ask. This runs **after [[keboola-validation-skill]] reported the flow clean**;
   if it isn't validated yet, stop and validate first (only push with an "MR → qa, validation in progress"
   comment if the operator explicitly asks).
2. **Be on the flow branch** (the validated files are already on it — [[keboola-validation-skill]]'s
   final step pulled them back; this skill does NOT touch the pod):
   ```bash
   BRANCH='#<task>_Week_<week>_<project_slug>_<flow_dir>'   # ALWAYS single-quote the # (zsh comment char)
   # Migration created the branch off a fresh qa; switch to it. If absent (standalone run), create off a FRESH qa:
   git rev-parse --verify "$BRANCH" >/dev/null 2>&1 && git switch "$BRANCH" \
     || { git fetch origin qa && git switch -c "$BRANCH" origin/qa; }
   # Gate: the flow's files must already be present (model dir + updated sources.yml/dbt_project.yml).
   # Missing, or in doubt they match the pod-validated state? STOP → re-run the validation skill's
   # "Final step when clean" pull-back — do NOT re-pull from here.
   git status -s; ls models/<project_slug>/<flow_dir>
   ```
   **Restructuring an already-pushed branch** (e.g. flattening an old nested layout): don't re-create —
   check it out, `git merge origin/qa`, make the changes, commit on top so the MR shows just that diff.
3. **Stage (targeted) + secret-guard + commit** — only this flow's files; NEVER `git add -A`, NEVER `git rm`
   other flows (they're the `qa` baseline). The tz guard fires from `.git/hooks/pre-commit` on the staged
   `.sql`; a **BLOCK** finding is a hard stop — fix it, never `--no-verify` past it (`DEC-058`):
   ```bash
   git config user.email "${GIT_USER_EMAIL}"; git config user.name "${GIT_USER_NAME}"
   git add models/<project_slug>/<flow_dir> models/sources.yml dbt_project.yml
   git diff --cached --name-only | grep -E '\.env$|\.duckdb|/target/|\.user\.yml|^logs/|credential|\.claude/' \
     && { echo 'ABORT: sensitive file staged'; exit 1; } || true
   git commit -m "feat: migrate <flow> to dbt (Productive #<task>)"
   git show --stat HEAD; git log --oneline -1
   ```
4. **Verify the tree** before pushing: `git diff --stat origin/qa...HEAD` shows **only this flow's**
   new model files + the two accumulating files; `git status -s` shows helper dirs (`input/`, `HELP/`,
   `.claude/`, …) still untracked; no `dbt_project/` wrapper.
   **S3 publish gate (`DEC-084`):** run
   `python3 .claude/skills/keboola-migration-skill/check_s3_publish.py models/<project_slug>/<flow_dir> --outputs <the output models P3 listed>`. Every
   output except a filtered variant must carry `copy_relation_to_s3()`, and no intermediate may. **Any ⛔ row → STOP before the push.**
   The fix is a P3 change (migration §4i). If the hook was added or moved, re-run validation's pull-back check
   so the pushed files still match what validated. Put the table's output rows (model → S3 path) in the MR
   body. That is where the reviewer sees what Gate 2 will publish for this flow — the merge itself publishes
   nothing (`DEC-083`).
5. **Push + auto-create the MR into `qa`** — Claude runs this directly (cached PAT; no `!`, no hand-off):
   ```bash
   GIT_TERMINAL_PROMPT=0 git push -u origin '#<task>_Week_<week>_<project_slug>_<flow_dir>' \
       -o merge_request.create \
       -o merge_request.target=qa \
       -o merge_request.title="Migrate <flow> to dbt (Productive #<task>)"
   ```
   `GIT_TERMINAL_PROMPT=0` makes a stale PAT fail fast (`Access denied`) instead of hanging — **only if it
   errors, hand the operator the same command with a leading `!`** so the credential prompt reaches their
   terminal (they may need to re-cache a fresh PAT). The MR must merge into **`qa`**, never main/master;
   the GitLab user is the operator's own (`GIT_USER_NAME` / the cached PAT, `DEC-011`). Grab the MR URL
   from the push output (`remote: … merge_requests/<n>`) for the comment.
   See [[gitlab-pod-dbt-repo]], [[gitlab-https-push-auth-pat]].

## Verify it landed
`git ls-remote --heads origin '#<task>_…'`, or check the GitLab branches page. The branch is **root-level**
(`analyses/ macros/ models/ tests/` + the dbt ymls at the root — no `dbt_project/` wrapper) and the MR diff
is scoped to this flow.

## Post the completion comment + move the task to To Review (push → MR → comment → review, all here)

After the push creates the MR, post a **completion comment** to the flow's Productive task — the task disclaimer
requires the **MR link** in a comment + a **justification for any data discrepancy**, after which it goes to senior
review. This is the pushing skill's job (the comment needs the MR link from the push). The comment is authored by
whichever operator's token is configured (`PRODUCTIVE_API_TOKEN`) — Productive has no separate "post as" field,
the token owner is the comment author.

1. **Find the task** the same way the migration skill resolves `task:` — search Productive for a task whose title
   contains the flow name: `GET https://api.productive.io/api/v2/tasks?filter[project_id]=${PRODUCTIVE_PROJECT_ID}&filter[query]=<distinctive part of flow>`,
   headers `X-Auth-Token` (from `productive-task-creator/secret.env`) + `X-Organization-Id: ${PRODUCTIVE_ORG_ID}`. Use the single
   match; the comment needs the **8-digit task `id`** (not `task_number`). See [[productive-task-creator]].
2. **Post the comment** — `POST /api/v2/comments`, body HTML, `relationships.task.data = {type:tasks, id:<task id>}`;
   verify author via `GET /comments/<id>?include=creator` (should match `PRODUCTIVE_ASSIGNEE_ID`'s account). *(The operator may instead ask for
   the text to paste manually — then just write it out; don't post via API.)*
3. **Style — CONCISE, and the two surfaces get DIFFERENT formats** (operator ask, 2026-07-27). Long narrative
   retros are OUT — the lead rejected exactly that on an earlier flow. But the fix is not "tables everywhere": **Productive
   cannot render tables**, so each surface gets the shape that actually reads there.

   **⛔ GitLab MR description → the two box-drawn tables.** Carry the **same STATE table and
   "What VALIDATED covers" table the validation ended with** ([[validation-ends-with-state-table]]), each wrapped
   in a ``` fence so markdown keeps it monospaced. ✅/→/− render fine here. Copy them from the validation output —
   never re-derive the numbers. ≲7k chars.

   **⛔ Productive comment → the SAME ROWS as bullets, NO tables, NO `<pre>`, NO code block.** Productive's
   `<pre>` does **not** hold monospace width — a box-drawn table wraps mid-row into unreadable mush, and it also
   renders inside an ugly grey code box (verified twice on an earlier flow; the lead rejected both). Keep the table's *content*
   but express each row as a list item in this exact shape:

   ```
   <p><b>State</b></p><ul>
   <li><b>Migrated</b> | ✅ YES | 1 model <code>MODEL_A</code> replaces 6 partitions + merge</li>
   <li><b>dbt parse</b> | ✅ CLEAN | 0 errors (was 8 on plain qa &mdash; repaired in <sha>)</li>
   <li><b>VALIDATED</b> | ✅ YES * | * C1/C2 scratch slice &mdash; see caveat</li>
   </ul>
   <p><b>What VALIDATED covers</b></p><ul>
   <li><b>no_missing_rows</b> | WARN 820 | 0.025% of 3,280,000 ref rows &rarr; 99.975% found</li>
   <li><b>normalized 52-col parity</b> | ✅ 98.55/98.92% | raw was 0% &mdash; typed-source formatting only</li>
   </ul>
   ```

   So: **`<b>Label</b> | <state> | <evidence>`** per `<li>` — the same three columns, just flowed instead of
   boxed. Keep the real ✅ emoji (it renders fine in rich text; it only breaks inside `<pre>`). Bold section
   labels (`State`, `What VALIDATED covers`, `Caveat`), `<code>` for identifiers, and HTML entities
   (`&mdash;` `&rarr;` `&minus;` `&hellip;` `&ndash;` `&harr;` `&times;`).
   Collapse repeat-cause rows into one bullet (the 6 `same_values` counts on one line) to stay short.
   **≲3k chars** — the reference comment landed at 2,827 with 18 bullets and 12 ✅.

   ✅ **SETTLED — the lead signed this ROW SHAPE off (2026-07-27) after seeing it rendered in Productive.**
   It is the required shape for EVERY post-push Productive comment; do not redesign it, do not "improve" it
   back into a table, and do not drop the ✅ glyphs. (The **section order** on top of this shape is
   `DEC-049` below — an extension, not a reversal: the rows still look exactly like this.) Three earlier attempts were rejected and each failure
   mode is already ruled out: a prose wall (too long), a `<pre>` box table (wraps + grey box), and plain
   bullets with no state column (no ✅ YES to scan). If a future flow's evidence doesn't fit a row, add a
   bullet — don't change the format.

   ⛔ **NO review questions in the Productive comment (the lead, 2026-08-12).** The "questions for review" /
   "open questions" list belongs in the **GitLab MR description ONLY** — that is where the reviewer is
   actually working, and where a question can be answered in a thread and resolved. Productive is the
   status surface: it says what the flow became and what the evidence is, and it ends at the MR link +
   `Validated.` Do not restate the questions there, do not add an `<ol>`, and do not soften them into a
   "notes" bullet — leave them out entirely. Raised on an earlier flow, where the comment carried a
   `Three questions for review` block that should only have been on its MR.

   ### Section ORDER is fixed — reviewer-facing first (`DEC-049`, the architect 2026-08-20)

   `DEC-010` settled the *shape* of a row; it never fixed the *order of the sections*, and that is what
   actually decides whether the comment is readable. Order them by **what the reviewer needs to decide**,
   not by the order the work happened in:

   1. **Verdict + scope** — one bold sentence: what the flow became, the MR link, the counts. Plus a ⚠ note
      if the branch was force-pushed/reworked ("review this version, not the original").
   2. **`⚠ Needs your eyes — N things`** — **MANDATORY when there is anything at all.** 2–5 bullets naming
      exactly what the reviewer must look at: legacy defects preserved verbatim, dialect traps that would
      have shipped wrong data, deliberate deviations, a narrowed recon window. Give the **count** in the
      heading so they can size the job before reading. ⚠ These are **findings stated as facts**, never
      questions — `DEC-036` still holds, and this section is the `Notes for review` the skill already
      sanctions, promoted to a fixed position. If a bullet ends in a question mark, it is in the wrong
      place: move it to the GitLab MR description.
   3. **Validation** — `Label | state | evidence` rows: the run result, the key-exact proof with both
      counts, and the window it holds over.
   4. **The WARNs — grouped by CAUSE, with a count per group** (`3 x rounding`, `2 x non-unique`,
      `6 x source churn`), never one bullet per failing test. A reviewer needs the number of *kinds* of
      problem, not the number of test rows. Close with `0 unexplained`.
   5. **Deliberate deviations from legacy** — each with its reason, if any are not already covered in (2).
   6. **`Waiting on others — not a blocker`** — so they do not chase it or ask. Say plainly whether it
      blocks, and what changes when it lands.
   7. **`Validated.`** as the final line — or, when validation read any staged upstream (`DEC-082` Gate 1),
      **`Validated on staged upstream: <tables> — gate 2 pending.`**

   **Staged-upstream disclosure (`DEC-082`, mandatory when the STATE table's `Upstream` row is `✅ STAGED`).**
   Both surfaces carry it — in the MR as a short block right under the STATE table, in Productive as a
   `<p><b>Staged upstream (gate 1)</b></p><ul>` list placed in section 3 (Validation):
   - one line per staged table: `<model>` ← `kbc_stg.<schema>.<TABLE>`, Keboola run `<date time>`, same run
     as the references or *one run newer* (say which), and WHY it was staged (not migrated / unbuildable /
     history only in legacy / sliced on S3 — with the measured rows);
   - for a producer that is not merged yet: *MR waits for #<producer> / !<producer MR>* — the flow merges
     only after its producer (`DEC-006`, no exception);
   - one closing line: *Gate 2 (chain validation before cutover) is pending.*

   **Tag EVERY pushed flow `gate2-pending`** — staged upstream or not (`DEC-082`/`DEC-083`: Gate 2 finds its
   flows by this tag, and only Gate 2 publishes our models to `dwh-out`, so an untagged flow would never be published).
   `DEC-023` as amended authorizes it. PATCH the task's `tag_list`, keeping any tags already there:
   ```bash
   curl -s -X PATCH -H "X-Auth-Token: $PRODUCTIVE_API_TOKEN" -H "X-Organization-Id: $PRODUCTIVE_ORG_ID" \
     -H "Content-Type: application/vnd.api+json" "https://api.productive.io/api/v2/tasks/<task id>" \
     -d '{"data":{"type":"tasks","id":"<task id>","attributes":{"tag_list":[<existing tags>,"gate2-pending"]}}}'
   ```
   **Read it back:** the PATCH response is the task itself. Quote its `tag_list` in the reply. It must hold
   `gate2-pending` **and** every tag the task had before (the list replaces, it does not append). Anything
   else is a failed step, not a pass ([[keboola-orchest-skill]] stops on it).

   ⚠ **Why this is an IMPROVEMENT, not a bug fix — be honest about it.** One earlier comment (2026-08-18)
   rendered as a continuous block: no verdict up front, the counts buried mid-sentence
   (`412,560 = 412,560 keys`), and the one line that called the reviewer to action ("five legacy defects …
   flagged in-file for the senior reviewer") near the end. But the row shape, the no-tables rule and the ≲3k budget were
   **all already in this file on that date** (verified against the repo at that commit) — so the prose wall
   was **non-compliance, not a missing rule**, and simply following the pre-existing spec would have avoided
   it. `DEC-049` adds four things the old spec genuinely lacked (the counted `Needs your eyes` block, WARN
   grouping by cause, the fixed order, the `Waiting on others` section) — it does not explain that comment.
   ⛔ **Do not read this as "the gap caused the wall".** And note the limit of the remedy: if the cause was a
   run skipping a prescribed section, adding another prescribed section is a weak defence against the same
   run skipping that one too. The stronger defences are a worked example for a COMPLEX flow (the one below
   is a single-model flow, which is where this broke) and eyeballing the rendered comment before moving on.
   Re-shaped to the order above, that comment's content came to **1,996 chars** — inside the budget, nothing removed.
   ⚠ The original body is **not measurable any more**: the comment was later edited in place, so any word
   count taken now describes the fix, not the original. Do not quote one.

   ⚠ **Two measurement traps, both hit while diagnosing this (2026-08-20).** (1) Productive's editor stores
   **`<strong>`, not `<b>`** — emitting `<b>` is fine, it normalizes, but counting `<b>` to check whether a
   comment is structured returns 0 on a perfectly structured comment. Count `<strong>`. (2) A comment edited
   in the Productive UI is replaced **in place**: `GET /comments` returns only the current body, with a fresh
   `updated_at` and the original `created_at`. The pre-edit text is **not recoverable via the API**, so
   compare `updated_at` against `created_at` before claiming to have measured "the original" — otherwise you
   measure the fix and conclude the opposite of the truth.

   Jargon stays. Column and table identifiers (`LOAD_TS`, `VBAP_ABGRU`), the test names, the
   counts and the MR link are what the reviewer greps for — a plain-language rewrite was tried on
   2026-08-20 and rejected as *less* useful to them. Write for the senior reviewer, not for a general audience.

   **GitLab MR description keeps its own shape** — the two fenced box-drawn tables, plus the
   questions/notes section that `DEC-036` keeps out of Productive.

   ### ⛔ Never manufacture a question (the lead, 2026-08-12)

   The questions section is **conditional, not a slot to fill**. A question earns its place only if the
   reviewer's answer would **change what gets committed** and you genuinely cannot settle it yourself from
   the code, the data, or an existing convention. If you have none — which is the common outcome on a clean
   flow — **write no questions section at all.** A short, confident MR with zero questions is the good
   result, not an incomplete one.

   Three shapes that are NOT questions, all of them written on one earlier flow and all wrong:

   - **A decision you already made and justified.** "`materialized='table'` instead of `view` — switch if
     you prefer?" You weighed it, you had a reason, it is in the file header. State the deviation as a fact
     so it does not read as an oversight; do not re-open it. If the reviewer disagrees they will comment —
     that is what review is for.
   - **Information phrased with a question mark.** "The staged reference types MATERIAL as BIGINT — same
     issue as #<task>?" Nothing is being asked. It is context; put it in the findings.
   - **A finding you already know the action for.** "The legacy has no PK — raise it with the data owner?" The
     convention already says to raise a missing PK ([[no-pk-in-legacy-tell-data-owner]]). Asking permission to
     follow a convention is noise; report the measurement and say you are raising it.

   Real measured findings still belong in the MR — as **findings**, stated as facts, not as questions.
   Prefer a short `**Notes for review**` paragraph or bullet list over an interrogative list.

   Reuse the ledger already recorded in `MIGRATION_STATUS.md` — do not recompute numbers here, and never quote a
   figure the validation run didn't produce. **After posting to Productive, ask the operator to eyeball it** —
   its renderer is the one that keeps surprising us.
4. **Move the task to "To Review"** (operator's convention since 2026-07-09). On push the flow goes to senior
   review (the senior reviewer), so set the Productive task to **To Review `<TO_REVIEW_STATUS_ID>`** — **NOT Done** (`DEC-085`):
   ```bash
   python3 .claude/skills/productive-task-creator/set_status.py --task <task#> --status review
   ```
   The script resolves the task number, refuses to touch a Done task, sends the PATCH, and reads the status
   back from the list endpoint. Quote its one output line in the reply. **Migration board workflow_status IDs**
   (project `${PRODUCTIVE_PROJECT_ID}`, board-specific, listed in the script; `--statuses` re-derives them
   live): Backlog `<BACKLOG_STATUS_ID>` · To Do `<TODO_STATUS_ID>` · **To Review `<TO_REVIEW_STATUS_ID>`** · Done `<DONE_STATUS_ID>` · Work in progress `<WIP_STATUS_ID>` ·
   Permanent/Ongoing `<ONGOING_STATUS_ID>` · Pending `<PENDING_STATUS_ID>`.
   This matches the task disclaimer ("move the task to senior engineer review"). **Done `<DONE_STATUS_ID>` is NOT set by this
   skill** — it's the post-merge state (set after the senior reviewer approves + merges), so leave it for the post-merge flip.

### Re-push after addressing the senior reviewer's GitLab review — the "fixed" case
When the senior reviewer has reviewed the MR on GitLab and you've **fixed** their comments and re-pushed the branch (the MR updates
automatically — the code changes are committed via Steps 2–5 above; for restructuring an already-pushed branch see
Step 2's note):
- **Set the task back to To Review `<TO_REVIEW_STATUS_ID>`** (same `set_status.py --status review`) so it re-enters the senior reviewer's review queue.
- **Post a short Productive comment: `Fixed per review — ready to merge. MR → qa: <link>`** (via `POST /comments`
  as in the Steps 1–3 above). Keep it to one line — the per-thread technical replies live on the GitLab MR itself
  (reply + resolve there, see [[gitlab-mr-review-reply]]); this Productive comment is just the "ready" signal.

> If the flow isn't validated yet, push + MR + an "MR → qa, validation in progress" comment is fine; add the final
> `Validated.` comment once validation is done. The task still goes to **To Review `<TO_REVIEW_STATUS_ID>`** on push either way
> (never Done from here). (Order varies — sometimes push precedes validation, sometimes follows.)

## Update the status tracker (MIGRATION_STATUS.md)
After handing off the push, update **`MIGRATION_STATUS.md`** (repo root — gitignored, local-only) for this
flow: **upsert by flow name** (`## <flow name>` block; create from its TEMPLATE if absent) and set
**`Pushed: ✅`** and **`MR → qa: ✅`** (drop the MR link / branch into **Notes** if useful). Leave
`Validated`/`Merged` for the validation skill and the post-merge manual flip. Local-only — never affects the push.

## Ending the reply (`DEC-056`)

**Every run ends by naming the next step.** Here that is: nothing of ours — the MR is open and the next move is the reviewer's. Say what the operator is waiting for (the senior reviewer's review, then the merge), and that the task sits at To Review.

Never end on the findings alone — the operator should not have to work out what to run. This holds on a
halt, a SKIP and a parked flow too.

**Compound first (`DEC-022`).** Before that closing line — always, success or stop — write anything this
phase learned into `HELP/FIXES.md` (a new breakage + its fix, e.g. a push/MR failure mode) and
`HELP/DATA_ACCESS.md`, then name the entries added in the reply. Full rule: `HELP/CHAIN.md`.
