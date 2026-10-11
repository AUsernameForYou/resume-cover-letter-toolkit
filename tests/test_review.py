import contextlib
import copy
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
import career
import documents
import review
import toolkit


class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "private"
        self.initial = toolkit.init(self.root, True)
        self.config = self.root / "state/review-preference.json"

    def tearDown(self):
        self.temp.cleanup()

    def invoke(self, *args):
        out, error = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(error):
            code = toolkit.main(["--workspace", str(self.root), *map(str, args)])
        return code, json.loads(out.getvalue() or error.getvalue())

    def draft(self):
        return documents.initial_draft(self.root, "example-job", ["fact_education"])

    def write(self, path, value):
        path.write_text(json.dumps(value), encoding="utf-8")

    def completed(self, path, formats=("html",)):
        report = documents.self_review_checklist(self.root, path, formats)
        for claim in report["claims"]:
            claim.update(passed=True, notes="Compared fictional claim " + claim["id"]
                         + " with its listed fact and source references; retained the source scope.")
        notes = {
            "source_fidelity": "Compared all fictional claims, dates and credentials with their original evidence.",
            "scope_and_qualifiers": "Retained the shared contribution, approximate amount and completed-work qualifiers.",
            "pair_consistency": "Checked the fictional resume and letter against the same selected facts and profile.",
            "writing_quality": "Read both fictional documents for clear prose, grammar and employer relevance.",
            "rendered_documents": "Inspected both fictional previews for readable text, layout and safe contact links.",
        }
        for key, item in report["checks"].items():
            item.update(passed=True, notes=notes[key])
        return report

    def save_report(self, value):
        path = self.root / "applications/review-report.json"
        self.write(path, value)
        return path

    def reviewed(self):
        review.preference(self.root, "ai-self-review")
        path = self.draft()
        report = self.completed(path)
        receipt = documents.self_review(self.root, path, self.save_report(report))
        return path, report, receipt

    def test_missing_choice_asks_first_question_and_preserves_manual_legacy_review(self):
        code, status = self.invoke("review-mode")
        self.assertEqual(code, 0)
        self.assertEqual(status, self.initial["review_preference"])
        self.assertEqual(status["mode"], "manual")
        self.assertFalse(status["choice_recorded"])
        self.assertTrue(status["onboarding_required"])
        self.assertEqual(status["question"], review.QUESTION)
        self.assertIn("never authorization", status["scope"])
        self.assertFalse(self.config.exists())
        path = self.draft()
        with self.assertRaisesRegex(career.ValidationError, "approve"):
            documents.render(self.root, path, final=True)
        documents.approve(self.root, path)
        final = documents.render(self.root, path, final=True)
        self.assertEqual(final["review_kind"], "manual")
        self.assertEqual(final["status"], "ready")
        self.assertTrue(review.status(self.root)["onboarding_required"])
        self.assertFalse(self.config.exists())

    def test_both_explicit_choices_persist_across_processes_and_rebuilds(self):
        for mode in ("manual", "ai-self-review"):
            with self.subTest(mode=mode):
                code, chosen = self.invoke("review-mode", mode)
                self.assertEqual(code, 0)
                self.assertEqual(chosen["mode"], mode)
                self.assertTrue(chosen["choice_recorded"])
                self.assertFalse(chosen["onboarding_required"])
                self.assertIsNone(chosen["question"])
                self.assertIn("review-mode", chosen["change"])
                before = self.config.read_bytes()
                process = subprocess.run([sys.executable, str(PROJECT / "toolkit.py"), "--workspace",
                                          str(self.root), "review-mode"], capture_output=True, text=True)
                self.assertEqual(process.returncode, 0, process.stderr)
                self.assertEqual(json.loads(process.stdout), chosen)
                career.build(self.root)
                self.assertEqual(self.config.read_bytes(), before)

    def test_repeating_choice_keeps_identity_and_changing_choice_invalidates_it(self):
        first = review.preference(self.root, "manual")
        before = self.config.read_bytes()
        self.assertEqual(review.preference(self.root, "manual"), first)
        self.assertEqual(self.config.read_bytes(), before)
        second = review.preference(self.root, "ai-self-review")
        third = review.preference(self.root, "manual")
        self.assertEqual(len({first["choice_id"], second["choice_id"], third["choice_id"]}), 3)
        self.assertEqual(third["mode"], "manual")

    def test_invalid_preferences_fail_closed_and_preserve_original_bytes(self):
        valid = review.preference(self.root, "manual")
        invalid = [[], None, {}, dict(valid, mode="auto"), dict(valid, mode=[]),
                   dict(valid, format_version=True), dict(valid, format_version=2),
                   dict(valid, choice_id="f" * 31), dict(valid, choice_id="g" * 32),
                   dict(valid, unexpected=True)]
        for value in invalid:
            with self.subTest(config=value):
                self.write(self.config, value)
                original = self.config.read_bytes()
                for requested in (None, "ai-self-review"):
                    with self.subTest(requested=requested):
                        with self.assertRaises(career.ValidationError):
                            review.preference(self.root, requested)
                        self.assertEqual(self.config.read_bytes(), original)
        self.config.write_text("{broken", encoding="utf-8")
        with self.assertRaises(career.ValidationError):
            review.preference(self.root, "manual")
        self.assertEqual(self.config.read_text(), "{broken")

    def test_preference_symlinks_cannot_read_or_overwrite_other_storage(self):
        outside = Path(self.temp.name) / "other-state"
        outside.mkdir()
        target = outside / "review-preference.json"
        target.write_text("private target retained", encoding="utf-8")
        self.config.symlink_to(target)
        for mode in (None, "manual"):
            with self.subTest(symlink="file", mode=mode):
                with self.assertRaises(career.ValidationError):
                    review.preference(self.root, mode)
        self.config.unlink()
        (self.root / "state").rmdir()
        (self.root / "state").symlink_to(outside, target_is_directory=True)
        for mode in (None, "ai-self-review"):
            with self.subTest(symlink="directory", mode=mode):
                with self.assertRaises(career.ValidationError):
                    review.preference(self.root, mode)
        self.assertEqual(target.read_text(), "private target retained")

    def test_preference_requires_initialized_private_workspace_and_valid_mode(self):
        for mode in ("auto", True, []):
            with self.subTest(mode=mode):
                with self.assertRaises(career.ValidationError):
                    review.preference(self.root, mode)
        empty = Path(self.temp.name) / "uninitialized"
        with self.assertRaisesRegex(career.ValidationError, "initialized private"):
            review.preference(empty, "manual")
        self.assertFalse(empty.exists())
        with mock.patch.object(review, "__file__", str(self.root.parent / "review.py")):
            with self.assertRaisesRegex(career.ValidationError, "outside the checkout"):
                review.preference(self.root, "manual")
        (self.root / ".git").mkdir()
        with self.assertRaisesRegex(career.ValidationError, "initialized private"):
            review.preference(self.root, "manual")
        self.assertFalse(self.config.exists())

    def test_manual_choice_requires_approval_and_rejects_ai_attestation(self):
        review.preference(self.root, "manual")
        path = self.draft()
        with self.assertRaisesRegex(career.ValidationError, "explicitly"):
            documents.self_review_checklist(self.root, path)
        with self.assertRaisesRegex(career.ValidationError, "approve"):
            documents.render(self.root, path, final=True)
        documents.approve(self.root, path)
        result = documents.render(self.root, path, final=True)
        self.assertEqual(result["review_mode"], "manual")
        self.assertEqual(result["review_kind"], "manual")

    def test_ai_cli_checklist_creates_previews_and_finalizes_without_manual_approval(self):
        self.assertEqual(self.invoke("review-mode", "ai-self-review")[0], 0)
        path = self.draft()
        code, template = self.invoke("review-checklist", path)
        self.assertEqual(code, 0)
        self.assertEqual(template["formats"], ["html"])
        self.assertTrue(all(item["passed"] is False for item in template["claims"]))
        preview = documents.render(self.root, path)
        for name in ("resume.html", "cover-letter.html"):
            self.assertTrue((Path(preview["directory"]) / name).is_file())
        code, result = self.invoke("self-review", path, "--report", self.save_report(self.completed(path)))
        self.assertEqual(code, 0)
        self.assertEqual(result["review_kind"], "ai-self-review")
        self.assertIs(result["external_submission_authorized"], False)
        self.assertTrue(Path(result["self_review"]).is_file())
        self.assertFalse(path.with_suffix(".approval.json").exists())
        with self.assertRaisesRegex(career.ValidationError, "AI self-review is selected"):
            documents.approve(self.root, path)
        code, final = self.invoke("render", path, "--final")
        self.assertEqual(code, 0)
        self.assertEqual(final["version"], preview["version"])
        self.assertEqual(final["review_kind"], "ai-self-review")
        self.assertEqual(final["status"], "ready")

    def test_checklist_binds_every_claim_evidence_reference_and_preview_file(self):
        review.preference(self.root, "ai-self-review")
        path = self.draft()
        draft, _, data = documents.check_draft(self.root, path)
        report = documents.self_review_checklist(self.root, path)
        expected = [("summary", draft["selected_fact_ids"])] if draft["summary"].strip() else []
        expected += [("resume_bullets." + str(i), [row["fact_id"]])
                     for i, row in enumerate(draft["resume_bullets"])]
        expected += [("cover_letter." + str(i), row["fact_ids"])
                     for i, row in enumerate(draft["cover_letter"])]
        self.assertEqual([(row["id"], row["fact_ids"]) for row in report["claims"]], expected)
        for claim in report["claims"]:
            self.assertEqual(claim["source_ids"], sorted({ref["source_id"] for key in claim["fact_ids"]
                                                       for ref in data["facts"][key]["evidence"]}))
            self.assertIs(claim["passed"], False)
            self.assertEqual(claim["notes"], "")
        self.assertEqual(set(report["checks"]), documents.REVIEW_CHECKS)
        self.assertEqual(set(report["files"]), {"resume.html", "cover-letter.html", "evidence.json"})
        preview = documents.render(self.root, path)
        self.assertEqual(report["preview_version"], preview["version"])
        self.assertEqual(report["draft_sha256"], hashlib.sha256(path.read_bytes()).hexdigest())
        self.assertEqual(report["review_preference_sha256"], documents.digest(review.preference(self.root)))
        for name, digest in report["files"].items():
            self.assertEqual(digest, hashlib.sha256((Path(preview["directory"]) / name).read_bytes()).hexdigest())

    def test_incomplete_reports_cannot_create_review_receipts(self):
        review.preference(self.root, "ai-self-review")
        path = self.draft()
        good = self.completed(path)
        with self.assertRaises(career.ValidationError):
            documents.self_review(self.root, path, self.root / "applications/missing-report.json")
        self.assertFalse(path.with_suffix(".self-review.json").exists())
        cases = {
            "template": lambda r: r["claims"][0].update(passed=False),
            "truthy integer": lambda r: r["claims"][0].update(passed=1),
            "claim without notes": lambda r: r["claims"][0].update(notes=" "),
            "quality failure": lambda r: r["checks"]["writing_quality"].update(passed=False),
            "quality without notes": lambda r: r["checks"]["rendered_documents"].update(notes=""),
            "missing claim": lambda r: r["claims"].pop(),
            "extra claim": lambda r: r["claims"].append(copy.deepcopy(r["claims"][0])),
            "invalid claims type": lambda r: r.update(claims={}),
            "changed claim identity": lambda r: r["claims"][0].update(id="other"),
            "missing fact coverage": lambda r: r["claims"][0].update(fact_ids=[]),
            "missing source coverage": lambda r: r["claims"][0].update(source_ids=[]),
            "missing check": lambda r: r["checks"].pop("source_fidelity"),
            "invalid checks type": lambda r: r.update(checks=[]),
            "extra check": lambda r: r["checks"].update(extra={"passed": True, "notes": "Checked."}),
            "changed check schema": lambda r: r["checks"]["source_fidelity"].update(extra=True),
            "unresolved finding": lambda r: r.update(unresolved_findings=["Clarify fictional scope."]),
            "extra report field": lambda r: r.update(extra=True),
        }
        for label, change in cases.items():
            with self.subTest(report=label):
                report = copy.deepcopy(good)
                change(report)
                with self.assertRaises(career.ValidationError):
                    documents.self_review(self.root, path, self.save_report(report))
                self.assertFalse(path.with_suffix(".self-review.json").exists())
        for value in ([], None):
            with self.subTest(report=value):
                with self.assertRaises(career.ValidationError):
                    documents.self_review(self.root, path, self.save_report(value))
        for formats in (None, "html", [True], ["invalid"]):
            with self.subTest(formats=formats):
                report = dict(good, formats=formats)
                with self.assertRaises(career.ValidationError):
                    documents.self_review(self.root, path, self.save_report(report))
                self.assertFalse(path.with_suffix(".self-review.json").exists())

    def test_report_identity_fields_cannot_be_changed_or_dropped(self):
        review.preference(self.root, "ai-self-review")
        path = self.draft()
        good = self.completed(path)
        changed = {"format_version": True, "draft_sha256": "a" * 64,
                   "review_preference_sha256": "b" * 64, "preview_version": "c" * 64,
                   "files": {}, "formats": []}
        for field, value in changed.items():
            for action in ("changed", "dropped"):
                with self.subTest(field=field, action=action):
                    report = copy.deepcopy(good)
                    if action == "changed":
                        report[field] = value
                    else:
                        report.pop(field)
                    with self.assertRaises(career.ValidationError):
                        documents.self_review(self.root, path, self.save_report(report))
                    self.assertFalse(path.with_suffix(".self-review.json").exists())

    def test_ai_mode_rejects_missing_or_manual_only_receipt(self):
        path = self.draft()
        documents.approve(self.root, path)
        review.preference(self.root, "ai-self-review")
        documents.self_review_checklist(self.root, path)
        with self.assertRaisesRegex(career.ValidationError, "self-review"):
            documents.render(self.root, path, final=True)
        path.with_suffix(".approval.json").unlink()
        with self.assertRaisesRegex(career.ValidationError, "self-review"):
            documents.render(self.root, path, final=True)

    def test_malformed_ai_receipts_cannot_finalize(self):
        path, _, receipt = self.reviewed()
        valid = json.loads(receipt.read_text())
        for value in ([], dict(valid, review_kind="manual"), dict(valid, reviewed_at="invalid"),
                      dict(valid, report=None), dict(valid, unexpected=True)):
            with self.subTest(receipt=value):
                self.write(receipt, value)
                with self.assertRaises(career.ValidationError):
                    documents.render(self.root, path, final=True)
                self.assertEqual(documents.render(self.root, path)["status"], "draft")

    def test_review_paths_cannot_escape_applications_through_symlinks(self):
        review.preference(self.root, "ai-self-review")
        path = self.draft()
        good = self.completed(path)
        outside = Path(self.temp.name) / "outside-report.json"
        self.write(outside, good)
        original = outside.read_bytes()
        link = self.root / "applications/report-link.json"
        link.symlink_to(outside)
        for report_path in (outside, link):
            with self.subTest(path=report_path.name):
                with self.assertRaisesRegex(career.ValidationError, "inside the private workspace applications"):
                    documents.self_review(self.root, path, report_path)
        receipt = path.with_suffix(".self-review.json")
        receipt.symlink_to(outside)
        with self.assertRaises(career.ValidationError):
            documents.self_review(self.root, path, self.save_report(good))
        with self.assertRaises(career.ValidationError):
            documents.render(self.root, path, final=True)
        self.assertEqual(outside.read_bytes(), original)

    def test_editing_draft_after_ai_review_requires_new_report(self):
        path, _, _ = self.reviewed()
        draft = json.loads(path.read_text())
        draft["summary"] = "Practical engineering and delivery experience."
        self.write(path, draft)
        with self.assertRaises(career.ValidationError):
            documents.render(self.root, path, final=True)
        documents.self_review(self.root, path, self.save_report(self.completed(path)))
        self.assertEqual(documents.render(self.root, path, final=True)["status"], "ready")

    def test_changed_choice_does_not_reuse_ai_report_when_switching_back(self):
        path, report, receipt = self.reviewed()
        original = receipt.read_bytes()
        preview = documents.render(self.root, path)
        review.preference(self.root, "ai-self-review")
        self.assertEqual(documents.render(self.root, path, final=True)["version"], preview["version"])
        review.preference(self.root, "manual")
        with self.assertRaisesRegex(career.ValidationError, "approve"):
            documents.render(self.root, path, final=True)
        review.preference(self.root, "ai-self-review")
        with self.assertRaises(career.ValidationError):
            documents.render(self.root, path, final=True)
        with self.assertRaisesRegex(career.ValidationError, "stale or changed"):
            documents.self_review(self.root, path, self.save_report(report))
        self.assertEqual(receipt.read_bytes(), original)
        documents.self_review(self.root, path, self.save_report(self.completed(path)))
        self.assertNotEqual(documents.render(self.root, path, final=True)["version"], preview["version"])

    def test_final_formats_must_match_all_reviewed_previews(self):
        path, _, _ = self.reviewed()
        with self.assertRaises(career.ValidationError):
            documents.render(self.root, path, ("html", "docx"), final=True)
        def fictional_docx(person, blocks, destination):
            destination.write_text("Fictional document conversion fixture.", encoding="utf-8")
        with mock.patch.object(documents, "render_docx", side_effect=fictional_docx):
            report = self.completed(path, ("html", "docx"))
            self.assertEqual(set(report["files"]), {"resume.html", "cover-letter.html", "resume.docx",
                                                   "cover-letter.docx", "evidence.json"})
            documents.self_review(self.root, path, self.save_report(report))
            with self.assertRaisesRegex(career.ValidationError, "stale or changed"):
                documents.render(self.root, path, ("html",), final=True)
            result = documents.render(self.root, path, ("html", "docx"), final=True)
            self.assertEqual(result["status"], "ready")

    def test_ai_mode_preserves_numeric_eligibility_and_stale_source_checks(self):
        review.preference(self.root, "ai-self-review")
        path = self.draft()
        draft = json.loads(path.read_text())
        bad = copy.deepcopy(draft)
        bad["resume_bullets"][0]["text"] = "Led 999 coordinators."
        self.write(path, bad)
        with self.assertRaisesRegex(career.ValidationError, "numeric"):
            documents.self_review_checklist(self.root, path)
        self.write(path, draft)
        bad = copy.deepcopy(draft)
        bad["resume_bullets"][0]["fact_id"] = "fact_future"
        self.write(path, bad)
        with self.assertRaises(career.ValidationError):
            documents.self_review_checklist(self.root, path)
        self.write(path, draft)
        source = self.root / "data/base.json"
        pack = json.loads(source.read_text())
        pack["sources"][0]["notes"] = "Updated fictional source note."
        self.write(source, pack)
        with self.assertRaisesRegex(career.ValidationError, "stale"):
            documents.self_review_checklist(self.root, path)
        career.build(self.root)
        with self.assertRaisesRegex(career.ValidationError, "stale"):
            documents.self_review_checklist(self.root, path)

    def test_profile_and_document_tampering_invalidate_ai_finalization(self):
        path, _, _ = self.reviewed()
        preview = documents.render(self.root, path)
        out = Path(preview["directory"])
        for name in ("resume.html", "evidence.json"):
            with self.subTest(file=name):
                target = out / name
                original = target.read_bytes()
                target.write_text("Changed fictional preview.", encoding="utf-8")
                with self.assertRaisesRegex(career.ValidationError, "changed or incomplete"):
                    documents.render(self.root, path, final=True)
                target.write_bytes(original)
        person = json.loads((self.root / "profile.json").read_text())
        person["name"] = "Another Fictional Candidate"
        self.write(self.root / "profile.json", person)
        with self.assertRaisesRegex(career.ValidationError, "Profile changed"):
            documents.render(self.root, path, final=True)

    def test_manifest_cannot_claim_another_current_review_mode(self):
        path, _, _ = self.reviewed()
        preview = documents.render(self.root, path)
        target = Path(preview["directory"]) / "manifest.json"
        manifest = json.loads(target.read_text())
        for field, value in (("review_mode", "manual"), ("review_preference_sha256", "a" * 64),
                             ("review_kind", "manual")):
            with self.subTest(field=field):
                changed = dict(manifest, **{field: value})
                self.write(target, changed)
                with self.assertRaisesRegex(career.ValidationError, "changed or incomplete"):
                    documents.render(self.root, path, final=True)
                self.write(target, manifest)

    def test_refresh_preserves_original_ai_receipt_but_never_transfers_review(self):
        path, _, receipt = self.reviewed()
        before = receipt.read_bytes()
        person = json.loads((self.root / "profile.json").read_text())
        person["motivation"] = "Interested in useful fictional improvements."
        self.write(self.root / "profile.json", person)
        result = documents.refresh_draft(self.root, path)
        new = Path(result["path"])
        self.assertTrue(result["review_required"])
        self.assertNotEqual(new, path)
        self.assertEqual(receipt.read_bytes(), before)
        self.assertFalse(new.with_suffix(".self-review.json").exists())
        self.assertFalse(new.with_suffix(".approval.json").exists())
        with self.assertRaisesRegex(career.ValidationError, "self-review"):
            documents.render(self.root, new, final=True)
        documents.self_review(self.root, new, self.save_report(self.completed(new)))
        self.assertEqual(documents.render(self.root, new, final=True)["status"], "ready")

    def test_new_packages_report_current_mode_after_choice_changes(self):
        path = self.draft()
        documents.approve(self.root, path)
        manual = documents.render(self.root, path, final=True)
        review.preference(self.root, "ai-self-review")
        ai_preview = documents.render(self.root, path)
        self.assertNotEqual(manual["version"], ai_preview["version"])
        self.assertEqual(ai_preview["review_mode"], "ai-self-review")
        self.assertIsNone(ai_preview["review_kind"])
        documents.self_review(self.root, path, self.save_report(self.completed(path)))
        ai_final = documents.render(self.root, path, final=True)
        self.assertEqual(ai_final["review_kind"], "ai-self-review")
        review.preference(self.root, "manual")
        manual_again = documents.render(self.root, path, final=True)
        self.assertEqual(manual_again["review_mode"], "manual")
        self.assertEqual(manual_again["review_kind"], "manual")
        self.assertNotEqual(manual_again["version"], ai_final["version"])


if __name__ == "__main__":
    unittest.main()
