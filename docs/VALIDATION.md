# Validation

Tests use fictional records and temporary private workspaces. No personal database, employer account or AI provider is needed.

## Run the checks

From the code folder (on Windows, substitute `py -3` for `python3`):

```sh
python3 -m unittest discover -s tests -v
python3 scripts/check_privacy.py
```

For optional Word output:

```sh
python3 -m pip install -r requirements-documents.txt
python3 -m unittest discover -s tests_documents -v
```

Before changing a test scope, inspect the discovered methods and subcases. A passing exit code with zero executed tests is a failure. Record the tested source revision, Python version, executed count and any failures or skips.

The CI configuration runs the core suite on Ubuntu with Python 3.10–3.13, plus macOS and Windows with Python 3.12, and Word checks on Ubuntu with Python 3.12. Each job prints discovery and execution counts, lists test results, and explicitly fails if no tests are discovered or every test is skipped. That configuration is a coverage plan; only completed runs establish a result on those versions. PDF conversion and visual inspection require a separate local check with LibreOffice.

## What the tests exercise

| Area | Checks |
| --- | --- |
| Evidence store | Repeatable builds, eligibility, scoped metrics, references, dates, duplicate records, invalid intake and protection of existing databases |
| Freshness and exports | Changed source/schema/pack ownership, normalized database edits, protected output locations, malformed JSON, escaped Markdown and incomplete or stale export manifests |
| Paired documents | Selected evidence, stale drafts/profiles, unsupported numbers, preserved prose during refresh, explicit letter dates, hash-bound review receipts, safe HTML, package hashes and selected fixed career fields |
| Application history | Persistence across rebuilds and refusal to modify a foreign SQLite database |
| Repository privacy | Private workspace artifacts, credential patterns, non-example email and personal home paths, with findings that omit matched values |
| Optional Word output | Both documents preserve the fictional identity, evidence text, font and hyperlinks |

These checks validate behavior within the supported local workflow. They do not prove that a paraphrase is true, that a résumé will pass every applicant tracking system, or that a repository contains no possible private information. Review claims and the files staged for publication yourself.

## Check the complete fictional workflow

Use a fresh workspace outside the checkout:

```sh
python3 toolkit.py init ~/career-validation --example
python3 toolkit.py --workspace ~/career-validation validate
python3 toolkit.py --workspace ~/career-validation export
python3 toolkit.py --workspace ~/career-validation validate-exports
python3 toolkit.py --workspace ~/career-validation draft example-job --fact fact_education
```

Use the draft path printed by the last command:

```sh
python3 toolkit.py --workspace ~/career-validation check-draft /path/to/draft.json
python3 toolkit.py --workspace ~/career-validation render /path/to/draft.json
```

Open both HTML files. Check names, links, dates, evidence wording and spacing. For Word/PDF output, render the same pair with `--format html --format docx --format pdf`, then inspect every PDF page and verify its text is selectable. Confirm that longer career histories paginate sensibly; a one-page fictional example does not establish every layout.

After reviewing the pair, exercise `approve` and `render --final`. Check `history`, record a manual status, rebuild the evidence store and confirm the history remains. An assistant testing fictional approval behavior must not record real application prose as human-reviewed.

## Verification boundaries

The core has no backend or provider API, so authentication, deployment, model-call and automatic-submission tests do not apply. The optional document job checks Word structure; it does not install LibreOffice or claim PDF visual coverage. Source freshness and manifests detect stale or inconsistent artifacts, but a person with write access to every workspace file can alter the sources and receipts.
