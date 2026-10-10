# Getting started

Keep the code folder shareable and your career workspace private. The README's fictional demo is the quickest way to see the two documents before entering your information. Use `python3` below; on Windows substitute `py -3`, quote paths with spaces and run each command on one line in PowerShell.

## Build your evidence store

1. Run `python3 toolkit.py init ~/my-career` from the code folder. Choose a workspace outside the checkout.
2. Open the new workspace's `profile.json`. Replace the placeholder name and enter only the contact information you want on documents.
3. Put original résumés, notes or posting text in its `inputs/` folder. These are private reference material, not automatically parsed.
4. Open `data/base.json`. Start with the [minimal valid pack](SCHEMA.md#minimal-valid-fictional-pack), replace its fictional claim with your own supported work, and record where you confirmed it. The [field reference](SCHEMA.md) covers all fields, allowed values, dates and nested objects.
5. Validate and build:

```sh
python3 toolkit.py --workspace ~/my-career validate
python3 toolkit.py --workspace ~/my-career build
python3 toolkit.py --workspace ~/my-career search "inspection"
```

A source can be a résumé, email, user confirmation, repository or public page. Source text shows what was stated; it is not independent verification. Preserve dates, metric scope, approximate amounts and individual versus team contribution. Record missing details as questions. Keep plans and unresolved/conflicted claims ineligible. Organization-wide context belongs in `company_context`, with organization scope and eligibility false.

To import another JSON pack, use `python3 toolkit.py --workspace ~/my-career add /path/to/pack.json`. It validates the combined records and refuses duplicate IDs and overwrites. To revise a fact already present, edit its source pack deliberately. Run `validate` and `build` after any change. Export a readable inventory with `export`; `validate-exports` checks the generated set.

## If an assistant helps with intake

Give it this instruction with your chosen workspace path:

> Help me build a private career workspace with this toolkit. Read its README, contributor guidance and field reference. Ask for my existing résumé or notes, then collect one missing factual detail at a time. Preserve source dates and individual versus team scope. Use my own words as evidence, label unresolved claims and keep plans separate from delivered work. Do not invent facts, ask for passwords, send applications or approve your own draft. Store personal files outside the code checkout. After I select a job, prepare a résumé and cover letter using the same evidence and show both for review.

The toolkit has no built-in model connection. Giving an assistant your source documents is your own sharing decision; confirm what it can access.

## Capture a posting and choose evidence

Save the posting text in `inputs/job.txt`, then:

```sh
python3 toolkit.py --workspace ~/my-career capture-job inspection-role --company "Example Company" --title "Inspection Lead" --url "https://example.invalid/jobs/inspection" --description ~/my-career/inputs/job.txt
python3 toolkit.py --workspace ~/my-career build
python3 toolkit.py --workspace ~/my-career draft inspection-role --fact fact_inspection
```

Replace example names, URL and fact ID with your records. Posting text goes into `jobs.description`, which is drafting context. `jobs.notes` stays private. No URL is fetched. Requirements and matches are optional; add them only when you want explicit reviewed mappings. Education can explain capability without claiming past program ownership. Repeat `--fact` to select relevant breadth beyond the posting.

The generated résumé includes selected roles, newest first. Other roles remain in the evidence store but do not automatically appear in this application. With a missing end date, the rendered `Started YEAR` wording preserves source uncertainty rather than asserting present employment.

## Write and review the pair

The draft command prints the local draft path. Keep it inside the workspace's `applications/` directory. The initial text is a rough first pass to rewrite.

If you use an assistant, inspect the generated prompt file first. It excludes profile contacts, private notes, source URIs/paths/excerpts and pack names. Selected career claims, organizations, role titles, source titles, metric values/qualifiers, motivation and the job's `description` are still shared. Compare its response against the full private evidence bundle.

Ask for prose-only JSON containing `summary`, `resume_bullets` and `cover_letter`. Copy only those three values into the existing generated draft. Keep `format_version`, `job_id`, `snapshot`, `profile_sha256` and `selected_fact_ids` unchanged. Identity and fixed career fields are rendered from stored records. You can edit the ISO `letter_date` before approval; later rendering keeps that date.

The [draft field reference](SCHEMA.md#editable-paired-draft) defines bullet references and paragraph kinds. A `supported_claim` needs eligible fact IDs. A `personal_statement` records your motivation, and a `future_plan` must describe a future approach. Neither is permission to invent past credentials or outcomes.

```sh
python3 toolkit.py --workspace ~/my-career check-draft /path/to/draft.json
python3 toolkit.py --workspace ~/my-career render /path/to/draft.json
```

Review both previews for factual meaning, names, dates, spelling, spacing and links. Numeric checks are conservative: recorded numbers with ordinary sentence punctuation work, but equivalent reformulations such as a changed number format can still be rejected. Checks cannot establish semantic truth or detect every invented word-number, qualification or causal claim. Keep qualifiers in prose and do not broaden team/project outcomes into personal ownership.

Once you have reviewed both documents:

```sh
python3 toolkit.py --workspace ~/my-career approve /path/to/draft.json
python3 toolkit.py --workspace ~/my-career render /path/to/draft.json --final
```

The receipt is a hash-bound local attestation, not proof of the reviewer's identity. The person owns approval and sending. An assistant must not approve its own real application prose. Changes to the draft, date, profile or source snapshot require a new review.

## Preserve edited work after an update

A source change, another captured job or a toolkit update can make an older snapshot stale. Rebuild, then run:

```sh
python3 toolkit.py --workspace ~/my-career refresh-draft /path/to/old-draft.json
```

It carries your prose and selected IDs to a new unapproved draft using current evidence, and prints `path`, `changes`, `review_required` and `letter_date`. Old files remain. Legacy version-1 drafts gain the current format and an explicit date. If an older evidence bundle is unavailable, some change details are reported as `null`; inspect current sources yourself. Removed/ineligible evidence or prose failing current checks must be resolved deliberately. Approval never transfers.

After rendering, `history` shows document versions. `status VERSION_ID applied`, `interview`, `closed` or `declined` records an action taken elsewhere, even for a preview; it does not certify review. Only final rendering sets `ready`. Rebuilding `build/career.sqlite` preserves `state/application_history.sqlite`.
