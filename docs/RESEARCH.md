# Comparable projects and useful patterns

Reviewed primary project READMEs on October 10, 2026. This is an architectural comparison, not a functional audit of those projects. No third-party implementation code, templates or assets were copied.

| Project | Documented pattern worth learning from | Our implementation choice |
| --- | --- | --- |
| [DaveVoyles/resume-builder](https://github.com/DaveVoyles/resume-builder) | An evidence ledger, assistant-written drafts, deterministic CLI validation/rendering and a private job tracker. | Selected source IDs, a paired draft contract, exact review receipts and private version history. The toolkit also has a deterministic initial draft and does not require an assistant. |
| [Star-cloud626/resume-builder](https://github.com/Star-cloud626/resume-builder) | SQLite keeps fixed candidate history; a provider writes résumé, cover-letter and screening-answer prose. | Keep identity/roles/dates in the store and use one snapshot for both documents. No mandatory provider account. |
| [end1989/tailored](https://github.com/end1989/tailored) | A master profile and structural checks for generated employers, titles, dates, degrees and certifications. | Render fixed career fields directly from stored records; validate evidence references and source freshness. Structural checks do not imply perfect semantic truth. |
| [Amey-Thakur/RESUME-ENGINE](https://github.com/Amey-Thakur/RESUME-ENGINE) | Shared JSON drives a matching résumé and cover letter with searchable PDF output. | Share profile and typography, provide matched outputs, keep page length flexible and all personal artifacts local. |

The useful combination is a reusable evidence layer, small job-specific context, paired writing, reviewable versions and friendly exports. It is a feature-selection judgment, not a claim that this project outperforms them in conversion, hiring results or security.

Potential later additions: interview-preparation bundles, a reviewed screening-answer bank, JSON Resume interchange and a small local dashboard. They should reuse the evidence model and privacy boundaries. They are not implemented or promised by this release.
