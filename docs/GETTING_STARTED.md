# Getting started

The code folder is shareable. Your career workspace is private. Create a workspace outside this repository before adding personal information.

## If an assistant is helping you

Give it this instruction, replacing the workspace path:

> Help me build a private career workspace with this toolkit. Read its README and contributor guidance. Ask for my existing résumé or notes, then collect one missing factual detail at a time. Preserve source dates and individual versus team scope. Use my own words as evidence, label unresolved claims and keep plans separate from delivered work. Do not invent facts, ask for passwords, send applications or approve your own draft. Store my personal files outside the code checkout. After I select a job, prepare a résumé and cover letter using the same evidence snapshot and show me both for review.

## What to record

`profile.json` holds your display name, location, contact details, links, font preference and optional motivation. It stays private.

`data/*.json` packs hold:

| Record | Purpose |
| --- | --- |
| sources | Where a fact came from, source date and retrieval date |
| organizations, roles, projects | Employer history and project setting |
| facts | Claims with status, scope, metrics and source references |
| questions | Missing details to resolve without pretending an answer |
| jobs, requirements, matches | Job descriptions and explicitly reviewed evidence mappings |

The fictional files in `examples/` show the schema. IDs link records. A source can be a résumé, email, user confirmation, project repository or public page. Documentation is evidence that something was stated; it is not independent verification.

A claim can be `documented` or `user_confirmed`; unresolved/conflicted and planned facts remain ineligible. Organization-wide results are context. Amounts retain their own scope and qualifiers.

Use `add` to validate a new pack and refuse duplicate IDs. To change an existing fact, edit its source pack deliberately. Then run `validate`, `build` and `export`; `validate-exports` checks the generated set.

## Selecting a job

`capture-job` saves text you supply; it does not fetch a URL. You can add explicitly curated requirement and match records later. Alternatively choose eligible facts with `--fact` to prepare a first bundle.

The bundle includes only relevant selected evidence. Education may explain capability. A future operating approach can appear as a `future_plan`; it must not become a claim of past delivered work.

## Reviewing the pair

The paired draft contains `resume_bullets` with a `fact_id`, and cover-letter paragraphs with a kind and `fact_ids`. Keep the snapshot fields unchanged. Contact and fixed career history are rendered from the source store, not supplied by generated prose.

The numeric guard is conservative: unsupported numeric expressions are rejected. Prefer recorded wording or add explicit evidence before using a changed numeric form. It cannot prove semantic equivalence or detect every invented word-number, credential or causal claim. Read the prose yourself.

Approve only after both documents are accurate and readable. Approval records the exact draft hash. Edited drafts, profiles and source snapshots require fresh review. Document versions and manual status live in `state/application_history.sqlite`; rebuilding `build/career.sqlite` preserves that ledger.
