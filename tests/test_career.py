"""Risk-focused tests for source quality, safe retrieval, and rebuild safety."""
import copy
import hashlib
import importlib.util
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
        rendered = (self.root / "exports" / "career_inventory.md").read_text()
        self.assertIn("metric scope: project", rendered)
        self.assertIn("2,000,000,000", rendered)
        self.assertIn("Example Works", rendered)
        self.assertIn("as of 2025-03-01", rendered)

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
        (self.root / "schema.sql").write_text((PROJECT / "schema.sql").read_text() + "\n-- schema revision\n")
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
        (self.root / "data" / "duplicate.json").write_text(json.dumps({"facts": [self.fact()]}))
        with self.assertRaisesRegex(career.ValidationError, "duplicate facts ID"):
            career.load_data(self.root)
        (self.root / "data" / "duplicate.json").write_text('{"facts": [], "facts": []}')
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
        incoming.write_text(json.dumps({"facts": [self.fact()]}))
        before = set((self.root / "data").iterdir())
        with self.assertRaisesRegex(career.ValidationError, "duplicate facts ID"):
            career.add_pack(self.root, incoming)
        self.assertEqual(before, set((self.root / "data").iterdir()))
        new_fact = copy.deepcopy(self.fact())
        new_fact["id"] = "f_incoming"
        incoming.write_text(json.dumps({"facts": [new_fact]}))
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
        with sqlite3.connect(self.root / "build" / "career.sqlite") as db:
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute("UPDATE facts SET application_eligible=1 WHERE id='f_company'")


if __name__ == "__main__":
    unittest.main()
