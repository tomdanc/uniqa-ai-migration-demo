# UNIQA — AI-driven data platform migration (demo)

Material for the UNIQA AI Round Table: how Revolt BI migrates a legacy Keboola platform to
dbt + DuckDB with a chain of Claude Code skills, gated at every step and reviewed by people.

Everything here comes from a real migration and is **anonymized**. Client name, people,
flow, project, bucket, table and column names are replaced with synthetic tokens.
Sizes, row counts, timestamps, test counts and outcomes are kept as they were.

## Contents

| Folder | What's inside |
|--------|---------------|
| `data/` | `dwh_extractor_config_sample.csv`: 100 rows of the extractor config sheet (the table-level map of what is loaded from Keboola to S3), stratified across IN / STG / OUT. |
| `skills/` | The four chain skills: `keboola-readiness-skill` → `keboola-migration-skill` → `keboola-validation-skill` → `keboola-pushing-skill`. |
| `artifact/` | `weekboard.html`: five weeks of migration, 5–8 flows per week, each flow's phase, size, tests and outcome. |
| `presentation/` | `uniqa-ai-migrace.html`: a 4-slide deck in Czech. Open it in a browser; use the arrow keys to move between slides and F for fullscreen. |

## Skill chain

| Phase | Skill | Passes when |
|-------|-------|-------------|
| P2 | readiness | every input exists on the pod, fresh and complete (or the flow is skipped at pre-flight) |
| P3 | migration | the flow is converted to dbt models with tests and `dbt parse` is clean |
| P4 | validation | models are built on real data and reconciled against the legacy output, with 0 unexplained WARNs |
| P5 | pushing | a targeted commit, an MR into `qa`, an evidence comment on the task, and the task moved to senior review |

Each phase ends, reports and waits. The next phase starts only after a PASS, and a person merges.

## Anonymization

- **Data:** a deterministic token map (`GRP_nn`, `TABLE_nnn`, `COL_nn`, `VAL_nn`, project IDs `10nn`).
  Free-text comments are redacted, and filter values other than dates are tokenized.
- **Skills:**
  - People are replaced by roles (the lead, the data owner, the senior reviewer, the architect).
  - Flows and projects become `Flow A…` and `Project A…`, and client tables become generic placeholders.
  - Ticket, MR and status IDs become placeholders, and hosts point to `*.example`.
- **Check:** every file was scanned against a denylist built from all real flow, project, bucket,
  table and column names in the source sheets. The token map and denylist are not in this repo.
