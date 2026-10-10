# Design

The toolkit separates three responsibilities:

1. A canonical evidence store supplies validated facts, chronology, scope and provenance.
2. A person or their chosen assistant writes the tailored prose from a selected bundle.
3. Deterministic code validates references, pins career details, renders the pair and records private versions.

The standard-library CLI and HTML path need no provider account. Word output is optional. PDF conversion uses an explicitly selected or installed LibreOffice executable without shell interpolation.

The full evidence bundle stays private. Assistant prompts use an explicit field allowlist: selected claims, chronology, scopes, metric qualifiers, organizations, source titles, job-description text and motivation. Contact details, private notes, source locations/excerpts and pack names are omitted. A person still reviews what the selected text reveals before sharing it. The assistant returns only the three prose fields; fixed draft metadata stays in the local file.

## Storage boundaries

| Path in a private workspace | Owner and lifecycle |
| --- | --- |
| profile.json, data/ | Human-curated source of truth |
| inputs/ | Original personal material; not automatically exported |
| build/career.sqlite | Atomically rebuilt derived database |
| exports/ | Generated evidence exports with a commit manifest |
| applications/ | Selected bundles, editable drafts and versioned document pairs |
| state/application_history.sqlite | Mutable manual-status/version ledger preserved across rebuilds |

The reader compares semantic data, source-pack ownership, schema and engine digests, payloads, normalized entities and FTS rows. This protects against stale or inconsistent derived artifacts; it is not an authentication boundary against someone who owns and can rewrite all workspace files.

Readable source fields are escaped. Contact URLs use http/https; other source locators remain stored but render as literal text when their scheme is not a web/mail link. Export destinations cannot enter canonical/private state storage or leave the workspace.

An export manifest is written last and contains file hashes and source metadata. Partial writes return failure and are detectable with `validate-exports`. The implementation does not claim an atomic directory swap or publish generated personal documents.

Evidence bundles and document packages are staged before being moved into their versioned directories. Existing saved bundles/packages are checked before reuse. Draft paths must remain inside the workspace's `applications/` directory.

## Review and versioning

Draft format version 2 records an explicit ISO `letter_date`. The rendered date comes from that file, including when a preview is promoted later. Approval is an exact-file-hash attestation recorded by the local command, not human identity authentication or proof of semantic truth. The person remains responsible for review. An assistant must not attest that its own real application prose was human-reviewed.

The database checks conservative whole-store freshness, so an unrelated data change or engine update can invalidate an existing draft. `refresh-draft` preserves prose in a new unapproved file bound to current evidence, reports changes when earlier evidence is available, and retains older files. Removed/ineligible references or newly unsupported prose fail rather than being silently repaired. Legacy version-1 drafts are upgraded through this same path.

Only final rendering sets `ready`. Manual `applied`, `interview`, `closed` and `declined` states record external actions, including actions involving a preview; they do not imply review. Application status and artifact approval are separate facts.

## Limits

Fact references and numerical checks do not establish semantic truth. Human review remains necessary for paraphrases, qualifications and attribution. The toolkit does not score employability, guarantee ATS behavior, select people for jobs or submit applications.

One person per workspace is the simple privacy model. Use one writer at a time. There is no hosted account system, automatic scraping, external AI integration or credential manager.
