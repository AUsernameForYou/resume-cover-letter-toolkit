# Resume and cover letter toolkit

A local evidence store for preparing a résumé and cover letter that agree. Record sourced career facts once, select relevant evidence for each job, and keep editable drafts and application history in a private workspace.

The core uses Python and SQLite. It makes no AI-provider calls and never submits applications. Edit drafts yourself or use a selected prompt with your preferred assistant. No API key is required.

## Try the fictional example

Install Python 3.10 or newer with SQLite FTS5. From the code folder, run:

```sh
python3 toolkit.py init ~/career-demo --example
python3 toolkit.py --workspace ~/career-demo draft example-job --fact fact_education
```

On Windows, use `py -3` in place of `python3`. Replace `~/career-demo` with a private path outside the checkout, such as `"C:\Career Demo"`. Put each command on one line in PowerShell; the backslash continuation used in some Unix examples is not PowerShell syntax. Quote paths containing spaces.

The draft command prints a `draft` path. Replace `/path/to/draft.json` below with it:

```sh
python3 toolkit.py --workspace ~/career-demo check-draft /path/to/draft.json
python3 toolkit.py --workspace ~/career-demo render /path/to/draft.json
```

The render command prints a `directory` and `letter_date`. Open that directory's `resume.html` and `cover-letter.html` locally. They share typography and can be printed to PDF in your browser. Jordan Example, the employers, the university and the posting are fictional.

The initial draft is a rough first pass built from source wording. Rewrite it before sending. Choose your evidence deliberately: the résumé includes selected roles, newest first, rather than every unselected job in your history. A role without a recorded end date says `Started YEAR`; the tool does not infer that an old source proves present employment.

## Add your information

```sh
python3 toolkit.py init ~/my-career
```

Edit `profile.json` and the empty `data/base.json` in that new workspace. [Getting started](docs/GETTING_STARTED.md) walks through the workflow; the [field reference](docs/SCHEMA.md) lists every accepted field and includes a minimal valid pack. Keep original résumés and notes in the workspace's `inputs/` folder, outside this repository.

After editing records:

```sh
python3 toolkit.py --workspace ~/my-career validate
python3 toolkit.py --workspace ~/my-career build
python3 toolkit.py --workspace ~/my-career search "project coordination"
python3 toolkit.py --workspace ~/my-career export
python3 toolkit.py --workspace ~/my-career validate-exports
```

Results are printed as JSON. `validate` checks source records and the profile; `build` recreates the searchable database. Edit the source JSON, then rebuild, rather than editing the derived SQLite database.

## Prepare both documents for a job

Save the posting as a local text file. `capture-job` reads that file; it does not fetch the URL:

```sh
python3 toolkit.py --workspace ~/my-career capture-job delivery-role --company "Example Company" --title "Delivery Lead" --url "https://example.invalid/job" --description ~/my-career/inputs/job.txt
python3 toolkit.py --workspace ~/my-career build
python3 toolkit.py --workspace ~/my-career draft delivery-role --fact your_fact_id
```

Replace `your_fact_id` with a fact in your workspace. Repeat `--fact` to add useful breadth. Curated requirement/match records can also select evidence. A `match` report shows documented coverage; it is not an ATS score or hiring prediction.

`draft` also prepares private evidence and separate résumé/cover-letter prompts. `bundle JOB_ID --fact FACT_ID` prepares those without making another starter draft. Review a prompt before sharing it. Prompts exclude profile contacts, source paths and URLs, private notes, excerpts and pack filenames; they still share selected claims, employer names, source titles, metrics, job-description text and your motivation. The full `bundle.json` stays private.

Your assistant should return only `summary`, `resume_bullets` and `cover_letter`. Copy those three values into your existing local draft. Keep generated metadata and selected IDs unchanged. Names, employers, role titles and dates come from stored records.

Run `check-draft`, render a preview and review both documents. References and numeric checks cannot prove a paraphrase is true. Check individual versus shared work, approximate amounts, qualifications and planned versus delivered results. Set `letter_date` to the date you intend to use before approval; it is a fixed ISO date in the draft and does not silently change when you render later.

```sh
python3 toolkit.py --workspace ~/my-career approve /path/to/reviewed-draft.json
python3 toolkit.py --workspace ~/my-career render /path/to/reviewed-draft.json --final
```

The approval receipt records an attestation tied to the exact file hash. It does not authenticate a human identity. A person owns the factual review and sending decision; an assistant must not approve its own real application prose. Editing the draft, date, profile or source snapshot requires new review.

## Recover an out-of-date draft

Source changes, capturing another job or updating the toolkit can invalidate an older snapshot. Rebuild the database first, then carry your edited prose into a new draft:

```sh
python3 toolkit.py --workspace ~/my-career build
python3 toolkit.py --workspace ~/my-career refresh-draft /path/to/old-draft.json
```

The result prints the new `path`, reported `changes`, `review_required` and `letter_date`. Old drafts and receipts are preserved. Review the new file against current evidence, preview it, then approve it again. Refresh also upgrades legacy version-1 drafts. It refuses unknown/ineligible references or prose that fails current checks; it does not silently repair claims or transfer approval.

## Track what you do elsewhere

```sh
python3 toolkit.py --workspace ~/my-career history
python3 toolkit.py --workspace ~/my-career status VERSION_ID interview
```

Use the version ID returned by rendering. `applied`, `interview`, `closed` and `declined` are manual records of external actions; they can be recorded for a preview and do not imply review. Only `render --final` records `ready`. The separate application-history database survives rebuilding the career evidence database. There is no submission function.

## Optional Word and PDF output

```sh
python3 -m pip install -r requirements-documents.txt
python3 toolkit.py --workspace ~/my-career render /path/to/draft.json --format html --format docx
```

For direct PDF conversion, install LibreOffice from its official distribution and add `--format pdf`; `--soffice /path/to/soffice` selects an executable. PDF also needs the Word dependency above. Otherwise print HTML locally or export from Word. Fonts must be available on your machine. Preview every page and check selectable text and links before using either document. Page length is flexible; no universal ATS compatibility is promised.

## Troubleshooting

- If the database is stale, run `python3 toolkit.py --workspace YOUR_WORKSPACE build`. The error supplies a command for the affected workspace.
- If a draft is stale after rebuilding, use `refresh-draft` as described above. Keep its metadata intact.
- If `init` reports missing FTS5, use a Python installation that includes SQLite FTS5. This check runs before workspace files are created.
- If the initial database build fails after source files were created, those files are preserved. Resolve the reported cause and run the supplied build command. Do not delete your sources or repeat `init` on that populated folder.

## Privacy and development

Keep workspaces outside the code checkout. Inputs, databases, contacts, drafts and outputs stay local unless you deliberately share them. Keep confidential material out of eligible application evidence. Export manifests detect changed, incomplete or stale file sets, and protected workspace storage cannot be used as an export destination.

```sh
python3 -m unittest discover -s tests -v
python3 scripts/check_privacy.py
```

See [Design](docs/DESIGN.md), [Comparable projects](docs/RESEARCH.md) and [Validation](docs/VALIDATION.md). Research uses documented patterns; no third-party implementation code or assets were copied. The privacy checker is a useful check, not a guarantee; review staged files and history before publication.

## License

MIT. Copyright © 2026 Artifex Innovations LLC.
