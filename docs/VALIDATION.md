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
| Review preference and AI self-review | Manual default without a choice, explicit/persisted choices, mode changes, complete claim/check coverage, preference/draft/preview binding and refusal of incomplete or stale AI reports |
| Application history | Persistence across rebuilds and refusal to modify a foreign SQLite database |
| Repository privacy | Private workspace artifacts, credential patterns, non-example email and personal home paths, with findings that omit matched values |
| Optional Word output | Both documents preserve the fictional identity, evidence text, font and hyperlinks |

These checks validate behavior within the supported local workflow. They do not prove that a paraphrase is true, that a completed AI report reflects a real semantic review, that a résumé will pass every applicant tracking system, or that a repository contains no possible private information. The selected reviewer must check the claims; review files staged for publication yourself.

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

Before career intake, verify the agent's first onboarding question asks: **"Do you want to manually approve each document pair, or let your AI assistant self-review and finalize it?"** Exercise both choices with fictional workspaces:

1. Read `review-mode` without a saved choice and confirm `onboarding_required` is true and manual approval remains active. A preview must work, but final rendering must require manual approval. Verify a legacy workspace without a preference behaves the same way.
2. Explicitly save `review-mode manual`. After reviewing the pair, exercise `approve` and `render --final`. Read the preference again and rebuild; the choice must persist and onboarding must not repeat.
3. Save `review-mode ai-self-review`. Run `review-checklist DRAFT`, redirecting its JSON to a report inside `applications/`. Inspect the full private bundle, source evidence and both previews. Complete every generated claim and required check with true values and specific notes, resolve findings, then run `self-review DRAFT --report REPORT` and `render DRAFT --final` with the same formats. Confirm finalization works without `approve` and the receipt records AI self-review separately.
4. Confirm incomplete checks, missing claims or notes, unresolved findings, changed evidence references, changed drafts/preferences/previews and mismatched final formats prevent AI finalization. A deterministic check alone must not produce a completed review.
5. Repeat the current `review-mode` choice and confirm it retains the choice identifier. Change modes and confirm an earlier AI report is rejected, including after changing back. Complete a fresh review to finalize again.

For both workflows, check `history`, record a manual status, rebuild the evidence store and confirm history and the review preference remain. An assistant testing fictional approval behavior must not record real application prose as human-reviewed. Confirm that documentation and agent instructions distinguish local artifact finalization from external submission authorization and retain host-agent rules, legal assent, sensitive-data sharing confirmations and factual evidence requirements.

## Verification boundaries

The core has no backend or provider API, so authentication, deployment, model-call and automatic-submission tests do not apply. AI self-review is performed by the user's chosen assistant; accepting a completed report cannot prove its judgment or source truth. The optional document job checks Word structure; it does not install LibreOffice or claim PDF visual coverage. Source freshness and manifests detect stale or inconsistent artifacts, but a person with write access to every workspace file can alter the sources and receipts.
