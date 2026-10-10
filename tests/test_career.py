"""Risk-focused tests for source quality, safe retrieval, and rebuild safety."""
import copy
import contextlib
import errno
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

PROJECT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("career", PROJECT / "career.py")
career = importlib.util.module_from_spec(spec)
spec.loader.exec_module(career)


def fixture():
    facts = []
    base = {
        "id": "f_ready", "organization_id": "org", "role_id": "role", "project_id": "project",
        "kind": "responsibility", "claim": "Reviewed data center grid procurement and DuckDB/SQLite integration.",
        "start_date": "2024", "end_date": "2025-02", "as_of": "2025-03-01", "scope": "personal",
        "completion_status": "completed", "verification_status": "documented", "application_eligible": True,
        "tags": ["grid", "procurement"], "metrics": [],
        "evidence": [{"source_id": "source", "locator": "Page 2, project section"}], "usage_notes": "Self-authored résumé."
    }
    facts.append(base)
    for key, changes in (
        ("f_company", {"kind": "company_context", "scope": "organization", "application_eligible": False}),
        ("f_planned", {"completion_status": "planned", "application_eligible": False}),
        ("f_conflicted", {"verification_status": "conflicted", "application_eligible": False}),
        ("f_project_planned", {"kind": "project_context", "scope": "project", "completion_status": "planned", "application_eligible": False}),
        ("f_metric", {"kind": "achievement", "metrics": [{"label": "Project value", "value": 2000000000, "unit": "dollars", "currency": "USD", "scope": "project", "qualifier": "Project context; not a personally controlled budget"}]}),
    ):
        fact = copy.deepcopy(base)
        fact.update(changes)
        fact["id"] = key
        facts.append(fact)
    requirements = [{"id": key, "job_id": "job", "category": "required", "text": "Coordinate grid delivery", "tags": ["grid"], "source_locator": "Requirements"}
                    for key in ("req_ready", "req_planned", "req_review", "req_gap")]
    return {
        "sources": [{"id": "source", "title": "Example résumé", "kind": "resume", "source_date": "2025-03", "retrieved_at": "2026-10-09", "uri": "https://example.com/resume", "notes": "Self-report"}],
        "organizations": [{"id": "org", "name": "Example Works", "kind": "employer", "source_ids": ["source"]}],
        "roles": [{"id": "role", "organization_id": "org", "title": "Developer", "start_date": "2024", "end_date": None, "as_of": "2025-03-01", "source_ids": ["source"]}],
        "projects": [{"id": "project", "organization_id": "org", "name": "Grid test project", "start_date": "2024", "end_date": None, "as_of": "2025-03-01", "source_ids": ["source"]}],
        "facts": facts,
        "questions": [{"id": "q1", "priority": "high", "question": "Was the planned work completed?", "reason": "Old plan is not completed evidence.", "related_fact_ids": ["f_planned"], "status": "open"}],
        "jobs": [{"id": "job", "organization_id": "org", "title": "Infrastructure lead", "url": "https://example.com/job", "captured_at": "2026-10-09", "source_id": "source", "status": "captured"}],
        "requirements": requirements,
        "matches": [
            {"id": "m_ready", "requirement_id": "req_ready", "fact_id": "f_ready", "assessment": "direct", "rationale": "Documented work", "review_status": "curated"},
            {"id": "m_planned", "requirement_id": "req_planned", "fact_id": "f_project_planned", "assessment": "direct", "rationale": "Later outcome unknown", "review_status": "curated"},
            {"id": "m_company", "requirement_id": "req_planned", "fact_id": "f_company", "assessment": "adjacent", "rationale": "Company operates in this space", "review_status": "curated"},
            {"id": "m_review", "requirement_id": "req_review", "fact_id": "f_ready", "assessment": "direct", "rationale": "Proposed mapping", "review_status": "needs_review"},
            {"id": "m_gap", "requirement_id": "req_gap", "fact_id": None, "assessment": "gap", "rationale": "Missing lifecycle evidence", "review_status": "curated"},
        ]
    }


class CareerSafetyTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        (self.root / "data").mkdir()
        self.pack = fixture()
        self.write_pack()

    def tearDown(self):
        self.temporary.cleanup()

    def write_pack(self):
        (self.root / "data" / "seed.json").write_text(json.dumps(self.pack), encoding="utf-8")

    def fact(self, key="f_ready"):
        return next(f for f in self.pack["facts"] if f["id"] == key)

    def test_build_is_repeatable_and_preserves_scoped_metrics(self):
        first = career.build(self.root)
        path = Path(first["database"])
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        second = career.build(self.root)
        self.assertEqual(first, second)
        self.assertEqual(digest, hashlib.sha256(path.read_bytes()).hexdigest())
        with career.open_database(self.root) as db:
            self.assertEqual(db.execute("PRAGMA foreign_keys").fetchone()[0], 1)
            self.assertEqual(db.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            metric = db.execute("SELECT value,scope FROM fact_metrics WHERE fact_id='f_metric'").fetchone()
            self.assertEqual(tuple(metric), (2000000000, "project"))
            career.export_data(self.root, db)
        rendered = (self.root / "exports" / "career_inventory.md").read_text(encoding="utf-8")
        self.assertIn("metric scope: project", rendered)
        self.assertIn("2,000,000,000", rendered)
        self.assertIn("Example Works", rendered)
        self.assertIn("as of 2025-03-01", rendered)

    def test_build_sync_uses_writable_descriptor_without_weakening_durability(self):
        career.build(self.root)
        self.fact()["claim"] = "Released an updated sourced workflow."
        self.write_pack()
        original_open = Path.open
        original_fsync = career.os.fsync
        handles = {}
        synced = []
        def track_database_open(path, *args, **kwargs):
            handle = original_open(path, *args, **kwargs)
            if path.name.startswith(".career-") and path.suffix == ".sqlite":
                handles[handle.fileno()] = handle
            return handle
        def require_writable_sync(fd):
            handle = handles.get(fd)
            if handle is not None:
                if not handle.writable():
                    raise OSError(errno.EBADF, "Windows commit requires a writable descriptor")
                synced.append(fd)
            return original_fsync(fd)
        with mock.patch.object(Path, "open", track_database_open):
            with mock.patch.object(career.os, "fsync", side_effect=require_writable_sync):
                career.build(self.root)
        self.assertEqual(len(synced), 1)
        with career.open_database(self.root) as db:
            self.assertEqual(db.execute("SELECT claim FROM facts WHERE id='f_ready'").fetchone()[0], self.fact()["claim"])
        self.assertEqual(list((self.root / "build").glob(".career-*")), [])

    def test_invalid_input_cannot_replace_existing_database(self):
        career.build(self.root)
        database = self.root / "build" / "career.sqlite"
        before = database.read_bytes()
        self.fact()["evidence"] = []
        self.write_pack()
        with self.assertRaisesRegex(career.ValidationError, "at least one"):
            career.build(self.root)
        self.assertEqual(database.read_bytes(), before)
        self.assertEqual(list((self.root / "build").glob(".career-*")), [])

    def test_default_search_only_returns_eligible_evidence(self):
        career.build(self.root)
        with career.open_database(self.root) as db:
            ids = lambda **kw: {f["id"] for f in career.search(db, "grid", **kw)}
            self.assertEqual(ids(), {"f_ready", "f_metric"})
            self.assertEqual(ids(include_context=True), {"f_ready", "f_metric", "f_company"})
            self.assertEqual(ids(include_unconfirmed=True), {"f_ready", "f_metric", "f_planned", "f_conflicted"})
            self.assertEqual(len(ids(include_context=True, include_unconfirmed=True)), 6)

    def test_query_refuses_changed_canonical_data_until_rebuilt(self):
        career.build(self.root)
        database = self.root / "build" / "career.sqlite"
        before = database.read_bytes()
        self.fact()["claim"] = "Released the application after the prior source snapshot."
        self.write_pack()
        with self.assertRaisesRegex(career.ValidationError, "Database is stale.*canonical data.*run build"):
            with career.open_database(self.root):
                self.fail("Stale database must not be exposed to a query")
        self.assertEqual(database.read_bytes(), before)
        career.build(self.root)
        with career.open_database(self.root) as db:
            result = career.search(db, "Released application")
        self.assertEqual([fact["id"] for fact in result], ["f_ready"])

    def test_query_refuses_invalid_canonical_data_without_damaging_database(self):
        career.build(self.root)
        database = self.root / "build" / "career.sqlite"
        before = database.read_bytes()
        self.fact()["evidence"] = []
        self.write_pack()
        with self.assertRaisesRegex(career.ValidationError, "Canonical data is invalid.*at least one.*run build"):
            with career.open_database(self.root):
                self.fail("Invalid source data must block query access")
        self.assertEqual(database.read_bytes(), before)

    def test_query_refuses_changed_schema_without_damaging_database(self):
        career.build(self.root)
        database = self.root / "build" / "career.sqlite"
        before = database.read_bytes()
        (self.root / "schema.sql").write_text((PROJECT / "schema.sql").read_text(encoding="utf-8") + "\n-- schema revision\n", encoding="utf-8")
        with mock.patch.object(career, "ROOT", self.root):
            with self.assertRaisesRegex(career.ValidationError, "Database is stale.*schema.*run build"):
                with career.open_database(self.root):
                    self.fail("Changed schema must block query access")
        self.assertEqual(database.read_bytes(), before)

    def test_literal_search_accepts_punctuation_and_quoted_terms(self):
        career.build(self.root)
        with career.open_database(self.root) as db:
            self.assertEqual(len(career.search(db, '"data center"')), 2)
            self.assertEqual(len(career.search(db, "DuckDB/SQLite")), 2)
            for query in ("C++", "(grid):*", '"unclosed', '" OR 1=1; DROP TABLE facts; --', "---", '""'):
                career.search(db, query)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM facts").fetchone()[0], 6)
            self.assertEqual(career.literal_fts_query("OR NOT"), '"OR" AND "NOT"')

    def test_match_never_promotes_plans_company_context_or_pending_reviews(self):
        data, _, _ = career.load_data(self.root)
        report = career.match_job(data, "job")
        requirements = {row["requirement"]["id"]: row for row in report["requirements"]}
        self.assertEqual(requirements["req_ready"]["coverage"], "direct evidence")
        self.assertEqual(requirements["req_planned"]["coverage"], "gap")
        self.assertEqual(len(requirements["req_planned"]["review_or_context_only"]), 2)
        self.assertEqual(requirements["req_review"]["coverage"], "gap")
        self.assertEqual(requirements["req_gap"]["coverage"], "gap")
        self.assertNotIn("fit_score", report)

    def test_bad_references_and_cross_employer_role_are_rejected(self):
        self.fact()["evidence"][0]["source_id"] = "missing"
        self.write_pack()
        with self.assertRaisesRegex(career.ValidationError, "unknown sources"):
            career.load_data(self.root)
        self.pack = fixture()
        self.pack["organizations"].append({"id": "other", "name": "Other employer", "kind": "employer"})
        self.pack["roles"][0]["organization_id"] = "other"
        self.write_pack()
        with self.assertRaisesRegex(career.ValidationError, "organization differs"):
            career.load_data(self.root)

    def test_duplicate_ids_and_duplicate_json_keys_are_rejected(self):
        (self.root / "data" / "duplicate.json").write_text(json.dumps({"facts": [self.fact()]}), encoding="utf-8")
        with self.assertRaisesRegex(career.ValidationError, "duplicate facts ID"):
            career.load_data(self.root)
        (self.root / "data" / "duplicate.json").write_text('{"facts": [], "facts": []}', encoding="utf-8")
        with self.assertRaisesRegex(career.ValidationError, "Duplicate JSON key"):
            career.load_data(self.root)

    def test_source_scope_and_eligibility_invariants(self):
        cases = [
            ("f_ready", "application_eligible", 1, "true or false"),
            ("f_planned", "application_eligible", True, "cannot be application eligible"),
            ("f_conflicted", "application_eligible", True, "cannot be application eligible"),
            ("f_company", "scope", "personal", "company_context"),
            ("f_company", "application_eligible", True, "company_context"),
        ]
        for key, field, value, error in cases:
            with self.subTest(key=key, field=field):
                self.pack = fixture()
                self.fact(key)[field] = value
                self.write_pack()
                with self.assertRaisesRegex(career.ValidationError, error):
                    career.load_data(self.root)

    def test_calendar_dates_and_partial_precision(self):
        self.fact()["end_date"] = "2025-02-30"
        self.write_pack()
        with self.assertRaisesRegex(career.ValidationError, "invalid calendar date"):
            career.load_data(self.root)
        self.fact()["end_date"] = "2023"
        self.write_pack()
        with self.assertRaisesRegex(career.ValidationError, "precedes"):
            career.load_data(self.root)
        self.fact()["start_date"] = "2025-05"
        self.fact()["end_date"] = "2025"
        self.write_pack()
        career.load_data(self.root)  # Coarse end date overlaps start date; retain the uncertainty.

    def test_source_hash_paths_and_chat_uri(self):
        self.pack["sources"][0]["local_path"] = "../private.docx"
        self.write_pack()
        with self.assertRaisesRegex(career.ValidationError, "relative"):
            career.load_data(self.root)
        self.pack["sources"][0].pop("local_path")
        self.pack["sources"][0]["kind"] = "user_update"
        self.pack["sources"][0]["uri"] = None
        self.write_pack()
        career.load_data(self.root)
        self.pack["sources"][0]["kind"] = "resume"
        self.write_pack()
        with self.assertRaisesRegex(career.ValidationError, "uri: required"):
            career.load_data(self.root)

    def test_intake_is_validated_and_never_overwrites(self):
        incoming = self.root / "incoming.json"
        incoming.write_text(json.dumps({"facts": [self.fact()]}), encoding="utf-8")
        before = set((self.root / "data").iterdir())
        with self.assertRaisesRegex(career.ValidationError, "duplicate facts ID"):
            career.add_pack(self.root, incoming)
        self.assertEqual(before, set((self.root / "data").iterdir()))
        new_fact = copy.deepcopy(self.fact())
        new_fact["id"] = "f_incoming"
        incoming.write_text(json.dumps({"facts": [new_fact]}), encoding="utf-8")
        result = career.add_pack(self.root, incoming)
        saved = Path(result["added"])
        saved_bytes = saved.read_bytes()
        with self.assertRaisesRegex(career.ValidationError, "Refusing to replace"):
            career.add_pack(self.root, incoming)
        self.assertEqual(saved.read_bytes(), saved_bytes)
        self.assertEqual(career.build(self.root)["counts"]["facts"], 7)

    def test_cli_works_outside_project_directory(self):
        command = [sys.executable, str(PROJECT / "career.py"), "--root", str(self.root)]
        built = subprocess.run(command + ["build", "--json"], cwd=self.root, capture_output=True, text=True)
        self.assertEqual(built.returncode, 0, built.stderr)
        self.assertEqual(json.loads(built.stdout)["counts"]["facts"], 6)
        searched = subprocess.run(command + ["search", '"data center"', "--json"], cwd=self.root, capture_output=True, text=True)
        self.assertEqual(searched.returncode, 0, searched.stderr)
        self.assertEqual(len(json.loads(searched.stdout)), 2)
        shown = subprocess.run(command + ["show", "missing", "--json"], capture_output=True, text=True)
        self.assertEqual(shown.returncode, 2)
        self.assertIn("Unknown fact ID", json.loads(shown.stderr)["error"])

    def test_sql_constraints_reject_direct_eligibility_override(self):
        career.build(self.root)
        with contextlib.closing(sqlite3.connect(self.root / "build" / "career.sqlite")) as db:
            with db:
                with self.assertRaises(sqlite3.IntegrityError):
                    db.execute("UPDATE facts SET application_eligible=1 WHERE id='f_company'")

    def test_match_validation_and_build_agree_on_gap_fact_references(self):
        career.build(self.root)
        before = (self.root / "build/career.sqlite").read_bytes()
        for assessment, fact in [("direct", None), ("adjacent", None), ("gap", "f_ready")]:
            with self.subTest(assessment=assessment, valid=False):
                self.pack = fixture()
                self.pack["matches"][0].update(assessment=assessment, fact_id=fact)
                self.write_pack()
                for operation in [career.load_data, career.build]:
                    with self.assertRaisesRegex(career.ValidationError, "gap matches require null"):
                        operation(self.root)
                self.assertEqual(before, (self.root / "build/career.sqlite").read_bytes())
        for assessment, fact in [("direct", "f_ready"), ("adjacent", "f_ready"), ("gap", None)]:
            with self.subTest(assessment=assessment, valid=True):
                self.pack = fixture()
                self.pack["matches"][0].update(assessment=assessment, fact_id=fact)
                self.write_pack()
                career.load_data(self.root)
                career.build(self.root)
                with career.open_database(self.root) as db:
                    self.assertEqual(tuple(db.execute("SELECT assessment,fact_id FROM matches WHERE id='m_ready'").fetchone()), (assessment, fact))

    def test_core_cli_requires_workspace_and_recovery_hint_is_safe(self):
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as exc:
                career.parser().parse_args(["build"])
        self.assertEqual(exc.exception.code, 2)
        with self.assertRaisesRegex(career.ValidationError, "run build for your private workspace") as exc:
            with career.open_database(self.root):
                self.fail("missing database must fail")
        self.assertNotIn("python career.py build", str(exc.exception))
        self.assertFalse((self.root / "build").exists())

    def test_wrong_database_application_id_is_rejected_read_only(self):
        career.build(self.root)
        path = self.root / "build/career.sqlite"
        for application_id in [0, 12345]:
            with self.subTest(application_id=application_id):
                with contextlib.closing(sqlite3.connect(path)) as db:
                    with db:
                        db.execute(f"PRAGMA application_id={application_id}")
                before = path.read_bytes()
                with self.assertRaisesRegex(career.ValidationError, "belongs to another application"):
                    with career.open_database(self.root):
                        self.fail("foreign identity must not be exposed")
                self.assertEqual(before, path.read_bytes())
        career.build(self.root)
        with career.open_database(self.root) as db:
            self.assertEqual(db.execute("PRAGMA application_id").fetchone()[0], career.DATABASE_APPLICATION_ID)

    def incoming_pack(self):
        incoming = self.root / "incoming.json"
        new_fact = copy.deepcopy(self.fact())
        new_fact["id"] = "f_incoming"
        incoming.write_text(json.dumps({"facts": [new_fact]}), encoding="utf-8")
        return incoming

    def test_intake_supports_filesystems_without_hardlinks(self):
        incoming = self.incoming_pack()
        for code in sorted({errno.EPERM, errno.ENOSYS, errno.EOPNOTSUPP, errno.EXDEV}):
            with self.subTest(errno=code):
                with mock.patch.object(career.os, "link", side_effect=OSError(code, "hard links unsupported")):
                    result = career.add_pack(self.root, incoming, "without_links")
                saved = Path(result["added"])
                self.assertEqual(json.loads(saved.read_text(encoding="utf-8")), json.loads(incoming.read_text(encoding="utf-8")))
                data, _, _ = career.load_data(self.root)
                self.assertIn("f_incoming", data["facts"])
                self.assertEqual(list((self.root / "data").glob(".intake-*")), [])
                saved.unlink()

    def test_intake_fallback_preserves_concurrently_created_destination(self):
        incoming = self.incoming_pack()
        destination = self.root / "data/intake_incoming.json"
        def competing_file(*args):
            destination.write_bytes(b"another writer's file")
            raise OSError(errno.EOPNOTSUPP, "hard links unsupported")
        with mock.patch.object(career.os, "link", side_effect=competing_file):
            with self.assertRaises(FileExistsError):
                career.add_pack(self.root, incoming)
        self.assertEqual(destination.read_bytes(), b"another writer's file")
        self.assertEqual(list((self.root / "data").glob(".intake-*")), [])

    def test_intake_fallback_write_failure_removes_only_owned_partial_file(self):
        incoming = self.incoming_pack()
        source_before = (self.root / "data/seed.json").read_bytes()
        incoming_before = incoming.read_bytes()
        original_fsync = career.os.fsync
        calls = []
        def fail_destination_sync(fd):
            calls.append(fd)
            if len(calls) == 2:
                raise OSError(errno.ENOSPC, "disk full")
            return original_fsync(fd)
        with mock.patch.object(career.os, "link", side_effect=OSError(errno.EOPNOTSUPP, "hard links unsupported")):
            with mock.patch.object(career.os, "fsync", side_effect=fail_destination_sync):
                with self.assertRaisesRegex(OSError, "disk full"):
                    career.add_pack(self.root, incoming)
        self.assertEqual(len(calls), 2)
        self.assertFalse((self.root / "data/intake_incoming.json").exists())
        self.assertEqual((self.root / "data/seed.json").read_bytes(), source_before)
        self.assertEqual(incoming.read_bytes(), incoming_before)
        self.assertEqual(list((self.root / "data").glob(".intake-*")), [])

    def test_intake_does_not_mask_other_hardlink_errors(self):
        incoming = self.incoming_pack()
        for code in [errno.EACCES, errno.EIO]:
            with self.subTest(errno=code):
                with mock.patch.object(career.os, "link", side_effect=OSError(code, "original I/O failure")):
                    with self.assertRaises(OSError) as exc:
                        career.add_pack(self.root, incoming)
                self.assertEqual(exc.exception.errno, code)
                self.assertFalse((self.root / "data/intake_incoming.json").exists())
                self.assertEqual(list((self.root / "data").glob(".intake-*")), [])

    def test_exports_protect_application_packages_and_resolve_relative_workspace_paths(self):
        career.build(self.root)
        protected = self.root / "applications/key/documents/version"
        protected.mkdir(parents=True)
        sentinel = protected / "resume.html"
        sentinel.write_text("reviewed document", encoding="utf-8")
        with career.open_database(self.root) as db:
            for destination in [self.root / "applications", protected, Path("applications/key/documents/version")]:
                with self.subTest(destination=str(destination)):
                    with self.assertRaisesRegex(career.ValidationError, "protected workspace storage"):
                        career.export_data(self.root, db, destination)
                    self.assertEqual(sentinel.read_text(encoding="utf-8"), "reviewed document")
                    self.assertEqual(sorted(p.name for p in protected.iterdir()), ["resume.html"])
            result = career.export_data(self.root, db, Path("reports"))
            self.assertEqual(Path(result["manifest"]).parent, self.root.resolve() / "reports")
            self.assertTrue(career.validate_exports(self.root, db, Path("reports"))["valid"])
            with self.assertRaisesRegex(career.ValidationError, "must stay inside"):
                career.export_data(self.root, db, Path("../outside"))
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = career.main(["--root", str(self.root), "validate-exports", "--output-dir", "reports"])
        self.assertEqual(code, 0)
        self.assertTrue(json.loads(output.getvalue())["valid"])

    def test_markdown_neutralizes_leading_lists_and_rules(self):
        cases = {"- source prose": "\\- source prose", "+ source prose": "\\+ source prose", "1. source prose": "1\\. source prose", "  12. source prose": "  12\\. source prose", "1) source prose": "1\\) source prose", "---": "\\---", "  - - -": "  \\- - -", "ordinary prose": "ordinary prose", "cost - benefit": "cost - benefit", "-word": "-word"}
        for raw, escaped in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(career.markdown(raw), escaped)
        self.pack["organizations"][0]["description"] = "- fake export list"
        self.fact()["claim"] = "---"
        self.write_pack()
        data, _, _ = career.load_data(self.root)
        rendered = career.render_inventory(data)
        self.assertIn("\\- fake export list", rendered)
        self.assertIn("\\---", rendered)

    def test_source_strings_reject_xml_invalid_controls_and_keep_valid_whitespace(self):
        for character in ["\x00", "\x01", "\x0b", "\x0c", "\x1f", "\ufffe", "\uffff"]:
            with self.subTest(codepoint=ord(character)):
                self.pack = fixture()
                self.fact()["claim"] = "source" + character
                self.write_pack()
                with self.assertRaises(career.ValidationError):
                    career.load_data(self.root)
        self.pack = fixture()
        self.fact()["claim"] = "Résumé\twith\nvalid\rwhitespace and 😀"
        self.write_pack()
        data, _, _ = career.load_data(self.root)
        self.assertEqual(data["facts"]["f_ready"]["claim"], self.fact()["claim"])

    def test_job_description_roundtrips_separately_from_private_notes(self):
        for description in ["Public role details about grid delivery.", None]:
            with self.subTest(description=description):
                self.pack = fixture()
                self.pack["jobs"][0]["notes"] = "Private follow-up note for the example job."
                if description is not None:
                    self.pack["jobs"][0]["description"] = description
                self.write_pack()
                source_before = (self.root / "data/seed.json").read_bytes()
                data, _, _ = career.load_data(self.root)
                job = data["jobs"]["job"]
                self.assertEqual(job["description"], description or "")
                self.assertEqual(job["notes"], self.pack["jobs"][0]["notes"])
                built = career.build(self.root)
                self.assertEqual(built["schema_version"], 2)
                with career.open_database(self.root) as db:
                    self.assertEqual(tuple(db.execute("SELECT description,notes FROM jobs WHERE id='job'").fetchone()), (description or "", job["notes"]))
                    self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 2)
                    career.export_data(self.root, db)
                exported = json.loads((self.root / "exports/career_data.json").read_text(encoding="utf-8"))
                self.assertEqual(exported["jobs"][0], job)
                self.assertEqual((self.root / "data/seed.json").read_bytes(), source_before)
                with tempfile.TemporaryDirectory() as clean:
                    restored = Path(clean)
                    (restored / "data").mkdir()
                    (restored / "data/export.json").write_text(json.dumps(exported), encoding="utf-8")
                    roundtripped, _, _ = career.load_data(restored)
                    self.assertEqual(roundtripped["jobs"]["job"], job)


if __name__ == "__main__":
    unittest.main()
