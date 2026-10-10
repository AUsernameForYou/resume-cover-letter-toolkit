# Field reference

Save UTF-8 JSON packs in your private workspace's `data/` folder. A pack is an object with any of these arrays: `sources`, `organizations`, `roles`, `projects`, `facts`, `questions`, `jobs`, `requirements`, `matches`. Omitted arrays are empty. Keep at least one pack, even if it contains only empty arrays. Duplicate JSON keys, unknown fields and duplicate IDs within an entity are rejected, including duplicates across packs.

IDs start with a letter or digit; the remaining characters may also include `_`, `.`, `:`, or `-`. References use the linked record's ID. Strings must be valid UTF-8 and cannot contain document-incompatible control characters. Required strings are nonempty. Optional text defaults to an empty string, optional lists to `[]`, and nullable fields to `null` when omitted. Use JSON `true` and `false` for booleans.

Dates preserve what the source establishes. `source_date`, `start_date`, `end_date` and required `as_of` accept valid `YYYY`, `YYYY-MM`, or `YYYY-MM-DD` dates. `retrieved_at`, `captured_at` and a draft's `letter_date` require a complete calendar date, `YYYY-MM-DD`. An end date cannot precede the start date. A missing end date does not prove a role continues today.

## Sources

| Field | Required | Type and meaning |
| --- | --- | --- |
| id | Yes | Source ID |
| title | Yes | Short source title |
| kind | Yes | `resume`, `email`, `company_website`, `job_posting`, `user_update`, `repository` |
| source_date | No | Date or `null`; when the source was written |
| retrieved_at | Yes | Full date; when you obtained it |
| uri | Conditional | Source locator string or `null`; required for every kind except `user_update` |
| local_path | No | Relative path or `null`; no absolute path, drive prefix or `..` traversal |
| sha256 | No | 64 hexadecimal characters or `null`; optional source file digest |
| notes | No | Private source notes |

A URI is a locator, not a request to open a page. The toolkit does not fetch or independently verify sources. A `user_update` can record your own factual confirmation without a URL. A local file can use a locator such as `file:inputs/resume.pdf` and a relative `local_path`.

## Organizations

| Field | Required | Type and meaning |
| --- | --- | --- |
| id | Yes | Organization ID |
| name | Yes | Display name |
| kind | Yes | `employer`, `client`, `university`, `military`, `target_employer` |
| description | No | Context text |
| source_ids | No | List of source IDs |
| notes | No | Private notes |

## Roles

| Field | Required | Type and meaning |
| --- | --- | --- |
| id | Yes | Role ID |
| organization_id | Yes | Organization ID |
| title | Yes | Recorded role title |
| start_date | No | Date or `null` |
| end_date | No | Date or `null` |
| as_of | Yes | Date through which the source describes this role |
| source_ids | No | List of source IDs |
| notes | No | Private notes |

## Projects

| Field | Required | Type and meaning |
| --- | --- | --- |
| id | Yes | Project ID |
| organization_id | Yes | Organization ID |
| name | Yes | Recorded project name |
| start_date | No | Date or `null` |
| end_date | No | Date or `null` |
| as_of | Yes | Date through which the source describes this project |
| source_ids | No | List of source IDs |
| notes | No | Private notes |

## Facts

| Field | Required | Type and meaning |
| --- | --- | --- |
| id | Yes | Fact ID |
| organization_id | Yes | Organization ID; use the university for a degree |
| role_id | No | Role ID or `null` |
| project_id | No | Project ID or `null` |
| kind | Yes | `achievement`, `responsibility`, `project_context`, `company_context`, `education`, `credential`, `publication` |
| claim | Yes | The actual claim, preserving qualifiers and attribution |
| start_date | No | Date or `null` |
| end_date | No | Date or `null` |
| as_of | Yes | Date through which this claim is supported |
| scope | Yes | `personal`, `team`, `project`, `organization` |
| completion_status | Yes | `completed`, `ongoing_as_of_source`, `planned`, `unclear` |
| verification_status | Yes | `documented`, `user_confirmed`, `needs_confirmation`, `conflicted` |
| application_eligible | Yes | Boolean; whether it may be selected as application evidence |
| tags | No | List of nonempty labels |
| metrics | No | List of metric objects below |
| evidence | Yes | Nonempty list of evidence objects below |
| usage_notes | No | Private cautions or drafting guidance |

A linked role or project must belong to the same organization as the fact. All referenced records must exist, though they may be in another pack. `planned`, `unclear`, `needs_confirmation` or `conflicted` facts must have `application_eligible: false`. Record organization-wide background as `company_context`, with `scope: organization` and `application_eligible: false`. Employer results do not establish your personal contribution. Documentation shows that something was stated; it is not independent proof of the outcome.

### Evidence objects

Only these fields are accepted:

| Field | Required | Type and meaning |
| --- | --- | --- |
| source_id | Yes | Source ID |
| locator | Yes | Nonempty location within that source, such as a page, section or message date |
| excerpt | No | Text or `null`; optional private source excerpt |

### Metric objects

Only these fields are accepted:

| Field | Required | Type and meaning |
| --- | --- | --- |
| label | Yes | Nonempty metric label |
| value | No | Finite number or `null`; integer values must fit signed 64-bit SQLite storage |
| unit | No | Text or `null`, such as `dollars` or `days` |
| currency | No | Text or `null`, such as `USD` |
| scope | Yes | `personal`, `team`, `project`, `organization`; each metric has its own scope |
| qualifier | No | Text or `null`; preserve approximations and shared contribution |

The integer range is −9,223,372,036,854,775,808 through 9,223,372,036,854,775,807. Booleans, infinity and NaN are not metric values. A project budget is project scale; it does not become personal savings. Put important qualifiers in the claim as well as the metric so they remain visible in prose.

## Questions

| Field | Required | Type and meaning |
| --- | --- | --- |
| id | Yes | Question ID |
| priority | Yes | `high`, `medium`, `low` |
| question | Yes | Missing factual detail |
| reason | Yes | Why it needs clarification |
| related_fact_ids | No | List of fact IDs |
| status | Yes | `open`, `resolved` |
| answer | No | Text or `null` |

A resolved question does not automatically change or approve a fact. Update the fact separately after confirming the answer.

## Jobs

| Field | Required | Type and meaning |
| --- | --- | --- |
| id | Yes | Job ID |
| organization_id | Yes | Target organization ID |
| title | Yes | Job title |
| url | Yes | Nonempty posting locator; `capture-job` requires an HTTP/HTTPS URL |
| captured_at | Yes | Full date |
| source_id | Yes | Source ID for the posting |
| status | Yes | `captured`, `closed`, `unknown` |
| description | No | Posting text explicitly intended for drafting context |
| notes | No | Private job notes, excluded from assistant prompts |

`capture-job` reads a local text file and records its contents in `description`. It does not fetch `url`. For an older pack that stored the posting in `notes`, deliberately move only the public posting text into `description`; keep personal notes private. Rebuild afterward.

## Requirements

| Field | Required | Type and meaning |
| --- | --- | --- |
| id | Yes | Requirement ID |
| job_id | Yes | Job ID |
| category | Yes | `responsibility`, `required`, `preferred` |
| text | Yes | Requirement text |
| tags | No | List of labels |
| source_locator | Yes | Location in the posting |

## Matches

| Field | Required | Type and meaning |
| --- | --- | --- |
| id | Yes | Match ID |
| requirement_id | Yes | Requirement ID |
| fact_id | Conditional | Fact ID for `direct`/`adjacent`; `null` for `gap` |
| assessment | Yes | `direct`, `adjacent`, `gap` |
| rationale | Yes | Explanation of this mapping |
| review_status | Yes | `curated`, `needs_review` |

The gap/null rule is enforced. Only curated mappings to eligible facts supply usable matching evidence. You can also select eligible facts with `--fact` without creating a match. A gap describes missing documented evidence, not a person's inability. `questions`, `requirements` and `matches` are optional; a first draft can use an explicitly selected fact.

## Minimal valid fictional pack

After `init`, replace the empty `data/base.json` with this pack. It needs no project, role, job or match records yet:

```json
{
  "sources": [{
    "id": "src_confirmation",
    "title": "Fictional confirmation",
    "kind": "user_update",
    "retrieved_at": "2026-01-15"
  }],
  "organizations": [{
    "id": "org_example",
    "name": "Example Company",
    "kind": "employer"
  }],
  "facts": [{
    "id": "fact_inspection",
    "organization_id": "org_example",
    "kind": "achievement",
    "claim": "Created a repeatable inspection workflow.",
    "as_of": "2026-01",
    "scope": "personal",
    "completion_status": "completed",
    "verification_status": "user_confirmed",
    "application_eligible": true,
    "evidence": [{"source_id": "src_confirmation", "locator": "Confirmed example"}]
  }]
}
```

Replace the fictional claim with your own supported wording and update `profile.json`, then validate and build. This pack alone can be searched and exported; capture a job before preparing application documents.

## Private profile

`profile.json` accepts only these fields:

| Field | Required | Type and meaning |
| --- | --- | --- |
| name | Yes | Nonempty display name; replace the `Your Name` placeholder |
| email | No | Text; omitted/empty hides it |
| phone | No | Text; omitted/empty hides it |
| location | No | Text; omitted/empty hides it |
| links | No | Object with at most eight nonempty label-to-HTTP/HTTPS-URL pairs |
| font | No | `Georgia` (default), `Garamond`, `Times New Roman`, `Arial` |
| motivation | No | Personal motivation; included in assistant prompts |

Installed fonts affect Word/PDF appearance. Choosing a name does not install or license that font. Contact values are display text, not verified addresses.

## Editable paired draft

`draft` creates a format-version-2 JSON file inside the workspace's `applications/` directory. Its exact fields are:

| Field | Editing rule |
| --- | --- |
| format_version | Keep `2` |
| job_id | Keep the generated job ID |
| snapshot | Keep the generated evidence/database metadata object |
| profile_sha256 | Keep the generated profile digest |
| selected_fact_ids | Keep the generated list of 1–30 unique eligible fact IDs |
| letter_date | Full ISO date; you may change it before approval |
| summary | String, possibly empty; must be supported by selected facts |
| resume_bullets | Nonempty list of `{ "fact_id": "selected_id", "text": "Supported wording" }` |
| cover_letter | List of 1–8 paragraph objects described below |

Each cover-letter paragraph has exactly `kind`, `text`, and `fact_ids`. `kind` is `supported_claim`, `personal_statement`, or `future_plan`; `text` is nonempty; `fact_ids` is a list drawn from the selected IDs. A supported claim needs at least one fact ID. Personal statements and future plans may have no IDs. A future plan must describe a future approach, never an invented past outcome.

A chosen assistant returns only `{ "summary": "...", "resume_bullets": [...], "cover_letter": [...] }`. Paste these three values into the existing generated draft; do not replace the whole file or regenerate fixed metadata. There are no editable name, employer, role-title or chronology fields in the draft. Those come from the private source records. `refresh-draft` creates a new unapproved file when sources or software change; it does not authorize edits to old metadata.
