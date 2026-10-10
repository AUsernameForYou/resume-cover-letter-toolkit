# Resume and cover letter toolkit

A local evidence store and command-line workflow for making a résumé and cover letter that agree. Store sourced career facts once, select relevant evidence for a job, and prepare both documents from the same snapshot.

The core uses Python and SQLite. It makes no AI-provider calls and never submits applications. You can edit the drafts yourself or give a small evidence bundle to your preferred assistant. No API key is required by this program.

## Try it with fictional data

Python 3.10 or newer with SQLite FTS5 is required. From this code folder:

```sh
python toolkit.py init ~/career-demo --example
python toolkit.py --workspace ~/career-demo draft example-job --fact fact_education
```

The second command prints a `draft` file path. Replace `/path/to/draft.json` below with that path. Quote it if it contains spaces:

```sh
python toolkit.py --workspace ~/career-demo check-draft /path/to/draft.json
python toolkit.py --workspace ~/career-demo render /path/to/draft.json
```

The render command prints a `directory`. Open its `resume.html` and `cover-letter.html` locally. They use matching typography and selectable text and can be printed to PDF in your browser. Everything about Jordan Example, the employers and the job is fictional.

## Use your own information

Create a separate private workspace:

```sh
python toolkit.py init ~/my-career
```

Edit its `profile.json` and add career records to `data/`. Each claim needs a source, date, scope and status. Use [Getting started](docs/GETTING_STARTED.md) for the field guide and an assistant-ready intake prompt. Original résumés and notes belong in the workspace's private `inputs/` folder, never in this repository.

After editing records:

```sh
python toolkit.py --workspace ~/my-career validate
python toolkit.py --workspace ~/my-career build
python toolkit.py --workspace ~/my-career search "project coordination"
python toolkit.py --workspace ~/my-career export
python toolkit.py --workspace ~/my-career validate-exports
```

## Résumés and cover letters share one evidence bundle

Save a job description locally and capture it:

```sh
python toolkit.py --workspace ~/my-career capture-job delivery-role \
  --company "Example Company" --title "Delivery Lead" \
  --url "https://example.invalid/job" --description ~/my-career/inputs/job.txt
python toolkit.py --workspace ~/my-career build
python toolkit.py --workspace ~/my-career bundle delivery-role --fact your_fact_id
python toolkit.py --workspace ~/my-career draft delivery-role --fact your_fact_id
```

The bundle includes selected eligible facts, their sources and the job context. It writes separate résumé and cover-letter prompts with the same draft contract. It does not include unrelated or ineligible records. A `match` report uses your explicit curated mappings; it is evidence coverage, not an ATS score or hiring prediction.

The initial draft keeps source wording. Improve its prose yourself or with your chosen assistant. Identity, employers, titles and dates are rendered from the stored profile and role records. Extra breadth can be selected with repeated `--fact` arguments.

Run `check-draft`, preview the pair, and review the meaning yourself. References and numeric checks cannot prove that a paraphrase is true. Check shared contributions, approximate amounts, project versus personal scope, historical dates, credentials and planned versus delivered work.

```sh
python toolkit.py --workspace ~/my-career approve /path/to/reviewed-draft.json
python toolkit.py --workspace ~/my-career render /path/to/reviewed-draft.json --final
```

A changed draft, profile or source snapshot requires new review. The tool records private document versions and manual application status in a separate SQLite ledger, preserved when the career database is rebuilt:

```sh
python toolkit.py --workspace ~/my-career history
python toolkit.py --workspace ~/my-career status VERSION_ID interview
```

`applied` is a manual record of an action you took elsewhere. The toolkit has no submission function.

## Optional Word and PDF output

```sh
python -m pip install -r requirements-documents.txt
python toolkit.py --workspace ~/my-career render /path/to/draft.json --format html --format docx
```

For direct PDF conversion, install LibreOffice from its official distribution and add `--format pdf` to the render command; `--soffice /path/to/soffice` selects an explicit executable. PDF output also needs the Word dependency above. Otherwise print the HTML locally or export from Word. Résumé length is flexible; preview pagination before using either document.

## Privacy and safety

- Keep personal workspaces outside the code checkout. The public repository contains only code, documentation and fictional examples.
- Inputs, profile details, databases, prompts, drafts and outputs stay in your workspace. Nothing is automatically sent to a model, employer or hosting service.
- Review a selected prompt before pasting it into an assistant. Keep confidential or restricted material out of application-eligible facts.
- Do not edit the derived career SQLite file directly. Edit source records and rebuild. The reader checks source/provenance/engine freshness and normalized-record consistency.
- Exports cannot target protected storage or leave the private workspace. A manifest detects incomplete, changed or stale export generations. Existing unrelated files are preserved.
- Source text is escaped in readable exports; structured eligibility is never inferred from rendered headings.

## Development

```sh
python -m unittest discover -s tests -v
python scripts/check_privacy.py
```

See [Design](docs/DESIGN.md), [Comparable projects](docs/RESEARCH.md) and [Validation](docs/VALIDATION.md). Research uses other projects' documented patterns; no third-party implementation code or assets were copied.

## License

MIT. Copyright © 2026 Artifex Innovations LLC.
