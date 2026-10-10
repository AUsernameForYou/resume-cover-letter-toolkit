#!/usr/bin/env python3
"""Local, evidence-backed career inventory. Python standard library only."""
from __future__ import annotations

import argparse
import calendar
import contextlib
import datetime as dt
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import sys
import tempfile
from urllib.parse import urlsplit, quote

SCHEMA_VERSION = 1
ENGINE_FILE = Path(__file__).resolve()
ROOT = Path(__file__).resolve().parent
ENTITIES = ("sources", "organizations", "roles", "projects", "facts", "questions", "jobs", "requirements", "matches")
SCOPES = {"personal", "team", "project", "organization"}
ENUMS = {
    ("sources", "kind"): {"resume", "email", "company_website", "job_posting", "user_update", "repository"},
    ("organizations", "kind"): {"employer", "client", "university", "military", "target_employer"},
    ("facts", "kind"): {"achievement", "responsibility", "project_context", "company_context", "education", "credential", "publication"},
    ("facts", "scope"): SCOPES,
    ("facts", "completion_status"): {"completed", "ongoing_as_of_source", "planned", "unclear"},
    ("facts", "verification_status"): {"documented", "user_confirmed", "needs_confirmation", "conflicted"},
    ("questions", "priority"): {"high", "medium", "low"},
    ("questions", "status"): {"open", "resolved"},
    ("jobs", "status"): {"captured", "closed", "unknown"},
    ("requirements", "category"): {"responsibility", "required", "preferred"},
    ("matches", "assessment"): {"direct", "adjacent", "gap"},
    ("matches", "review_status"): {"curated", "needs_review"},
}
FIELDS = {
    "sources": "id title kind source_date retrieved_at uri local_path sha256 notes",
    "organizations": "id name kind description source_ids notes",
    "roles": "id organization_id title start_date end_date as_of source_ids notes",
    "projects": "id organization_id name start_date end_date as_of source_ids notes",
    "facts": "id organization_id role_id project_id kind claim start_date end_date as_of scope completion_status verification_status application_eligible tags metrics evidence usage_notes",
    "questions": "id priority question reason related_fact_ids status answer",
    "jobs": "id organization_id title url captured_at source_id status notes",
    "requirements": "id job_id category text tags source_locator",
    "matches": "id requirement_id fact_id assessment rationale review_status",
}
REQUIRED = {
    "sources": "id title kind retrieved_at",
    "organizations": "id name kind",
    "roles": "id organization_id title as_of",
    "projects": "id organization_id name as_of",
    "facts": "id organization_id kind claim as_of scope completion_status verification_status application_eligible evidence",
    "questions": "id priority question reason status",
    "jobs": "id organization_id title url captured_at source_id status",
    "requirements": "id job_id category text source_locator",
    "matches": "id requirement_id assessment rationale review_status",
}
LIST_FIELDS = {"source_ids", "related_fact_ids", "tags", "metrics", "evidence"}
NULL_FIELDS = {"source_date", "uri", "local_path", "sha256", "start_date", "end_date", "role_id", "project_id", "answer", "fact_id"}
TABLE_COLUMNS = {
    entity: [x for x in fields.split() if x not in LIST_FIELDS]
    for entity, fields in FIELDS.items()
}


class ValidationError(Exception):
    """Input is invalid and no derived database should be replaced."""


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def pretty(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n"


def reject_duplicates(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValidationError(f"Duplicate JSON key: {key!r}")
        result[key] = value
    return result


def parse_pack(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=reject_duplicates,
                          parse_constant=lambda value: (_ for _ in ()).throw(ValidationError(f"Non-finite JSON number: {value}")))
    except (OSError, UnicodeError, ValueError, RecursionError, ValidationError) as exc:
        raise ValidationError(f"{path.name}: {exc}") from exc


def date_bounds(value, field, *, nullable=True, exact=False):
    if value is None and nullable:
        return None
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{4}(?:-[0-9]{2}(?:-[0-9]{2})?)?", value):
        raise ValidationError(f"{field}: expected a valid YYYY, YYYY-MM, or YYYY-MM-DD date")
    if exact and len(value) != 10:
        raise ValidationError(f"{field}: expected YYYY-MM-DD")
    parts = [int(x) for x in value.split("-")]
    try:
        year = parts[0]
        month = parts[1] if len(parts) > 1 else 1
        day = parts[2] if len(parts) > 2 else 1
        earliest = dt.date(year, month, day)
        last_month = month if len(parts) > 1 else 12
        last_day = day if len(parts) > 2 else calendar.monthrange(year, last_month)[1]
        latest = dt.date(year, last_month, last_day)
        return earliest, latest
    except (ValueError, OverflowError) as exc:
        raise ValidationError(f"{field}: invalid calendar date {value!r}") from exc


def ensure_string(value, where, *, nullable=False, empty=False):
    if value is None and nullable:
        return
    if not isinstance(value, str) or (not empty and not value.strip()) or "\x00" in value:
        raise ValidationError(f"{where}: expected {'a string' if empty else 'a nonempty string'}")
    try:
        value.encode("utf-8")
    except UnicodeError as exc:
        raise ValidationError(f"{where}: string is not valid UTF-8") from exc


def list_of_strings(value, where):
    if not isinstance(value, list):
        raise ValidationError(f"{where}: expected a list")
    for index, item in enumerate(value):
        ensure_string(item, f"{where}[{index}]")
    if len(set(value)) != len(value):
        raise ValidationError(f"{where}: duplicate list values")


def normalize_record(entity, raw, where):
    if not isinstance(raw, dict):
        raise ValidationError(f"{where}: expected an object")
    fields = FIELDS[entity].split()
    unexpected = set(raw) - set(fields)
    if unexpected:
        raise ValidationError(f"{where}: unknown fields: {', '.join(sorted(unexpected))}")
    for field in REQUIRED[entity].split():
        if field not in raw or raw[field] is None:
            raise ValidationError(f"{where}.{field}: required")
    record = dict(raw)
    for field in fields:
        if field not in record or record[field] is None:
            if field in LIST_FIELDS and field not in REQUIRED[entity].split():
                record[field] = []
            elif field not in NULL_FIELDS and field not in REQUIRED[entity].split():
                record[field] = ""
            elif field not in record:
                record[field] = None
    for field, value in record.items():
        label = f"{where}.{field}"
        if field in LIST_FIELDS:
            if field not in {"metrics", "evidence"}:
                list_of_strings(value, label)
            elif not isinstance(value, list):
                raise ValidationError(f"{label}: expected a list")
        elif field == "application_eligible":
            if type(value) is not bool:
                raise ValidationError(f"{label}: expected true or false, not an integer/string")
        elif (entity, field) in ENUMS:
            if not isinstance(value, str) or value not in ENUMS[entity, field]:
                raise ValidationError(f"{label}: expected one of {', '.join(sorted(ENUMS[entity, field]))}")
        else:
            ensure_string(value, label, nullable=field in NULL_FIELDS,
                          empty=field not in REQUIRED[entity].split())
        if field in {"source_date", "start_date", "end_date", "as_of", "retrieved_at", "captured_at"}:
            date_bounds(value, label, nullable=field in NULL_FIELDS, exact=field in {"retrieved_at", "captured_at"})
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]*", record["id"]):
        raise ValidationError(f"{where}.id: use letters, digits, underscores, dots, colons or hyphens")
    if "start_date" in record and record["start_date"] and record["end_date"]:
        start = date_bounds(record["start_date"], where + ".start_date")
        end = date_bounds(record["end_date"], where + ".end_date")
        if end[1] < start[0]:
            raise ValidationError(f"{where}: end_date precedes start_date")
    if entity == "sources":
        if not record["uri"] and record["kind"] != "user_update":
            raise ValidationError(f"{where}.uri: required unless kind is user_update")
        if record["sha256"] and not re.fullmatch(r"[0-9a-fA-F]{64}", record["sha256"]):
            raise ValidationError(f"{where}.sha256: expected 64 hexadecimal characters")
        if record["local_path"]:
            path = record["local_path"].replace("\\", "/")
            if path.startswith("/") or ".." in path.split("/") or re.match(r"^[A-Za-z]:", path):
                raise ValidationError(f"{where}.local_path: must be relative, without parent traversal")
    if entity == "facts":
        validate_fact(record, where)
    return record


def validate_fact(record, where):
    if not record["evidence"]:
        raise ValidationError(f"{where}.evidence: at least one source and locator is required")
    for index, evidence in enumerate(record["evidence"]):
        label = f"{where}.evidence[{index}]"
        if not isinstance(evidence, dict) or set(evidence) - {"source_id", "locator", "excerpt"}:
            raise ValidationError(f"{label}: expected source_id, locator and optional excerpt")
        for field in ("source_id", "locator"):
            ensure_string(evidence.get(field), label + "." + field)
        ensure_string(evidence.get("excerpt"), label + ".excerpt", nullable=True, empty=True)
    for index, metric in enumerate(record["metrics"]):
        label = f"{where}.metrics[{index}]"
        if not isinstance(metric, dict) or set(metric) - {"label", "value", "unit", "currency", "scope", "qualifier"}:
            raise ValidationError(f"{label}: invalid metric fields")
        ensure_string(metric.get("label"), label + ".label")
        if not isinstance(metric.get("scope"), str) or metric["scope"] not in SCOPES:
            raise ValidationError(f"{label}.scope: every metric needs its own personal/team/project/organization scope")
        value = metric.get("value")
        if value is not None and (type(value) not in (int, float)
                                  or (type(value) is float and not math.isfinite(value))):
            raise ValidationError(f"{label}.value: expected a finite number or null")
        if type(value) is int and not -(2 ** 63) <= value < 2 ** 63:
            raise ValidationError(f"{label}.value: integer exceeds SQLite's signed 64-bit range")
        for field in ("unit", "currency", "qualifier"):
            ensure_string(metric.get(field), label + "." + field, nullable=True, empty=True)
    if record["kind"] == "company_context" and (record["scope"] != "organization" or record["application_eligible"]):
        raise ValidationError(f"{where}: company_context requires organization scope and application_eligible=false")
    if record["application_eligible"] and (
        record["completion_status"] in {"planned", "unclear"}
        or record["verification_status"] in {"needs_confirmation", "conflicted"}
    ):
        raise ValidationError(f"{where}: planned, unclear, unconfirmed or conflicted facts cannot be application eligible")


def load_data(root, extra=None):
    paths = sorted((p for p in (root / "data").glob("*.json") if not p.name.startswith(".")), key=lambda p: p.name)
    packs = [(p.name, parse_pack(p)) for p in paths]
    if extra is not None:
        packs.append(extra)
    if not packs:
        raise ValidationError(f"No data/*.json packs found under {root}")
    records = {entity: {} for entity in ENTITIES}
    origins = {}
    for name, pack in packs:
        if not isinstance(pack, dict) or set(pack) - set(ENTITIES):
            raise ValidationError(f"{name}: expected an object containing only entity arrays: {', '.join(ENTITIES)}")
        for entity in ENTITIES:
            rows = pack.get(entity, [])
            if not isinstance(rows, list):
                raise ValidationError(f"{name}.{entity}: expected a list")
            for index, raw in enumerate(rows):
                where = f"{name}.{entity}[{index}]"
                row = normalize_record(entity, raw, where)
                key = row["id"]
                if key in records[entity]:
                    raise ValidationError(f"{where}: duplicate {entity} ID {key!r}; already in {origins[entity, key]}")
                records[entity][key] = row
                origins[entity, key] = name

    def reference(entity, key, location, nullable=False):
        if nullable and key is None:
            return
        if key not in records[entity]:
            raise ValidationError(f"{location}: unknown {entity} ID {key!r}")

    for entity in ENTITIES:
        for key, row in records[entity].items():
            where = f"{origins[entity, key]}:{entity}/{key}"
            for field, target in (("organization_id", "organizations"), ("role_id", "roles"),
                                  ("project_id", "projects"), ("source_id", "sources"),
                                  ("job_id", "jobs"), ("requirement_id", "requirements"), ("fact_id", "facts")):
                if field in row:
                    reference(target, row[field], where + "." + field, nullable=field in {"role_id", "project_id", "fact_id"})
            for field, target in (("source_ids", "sources"), ("related_fact_ids", "facts")):
                for item in row.get(field, []):
                    reference(target, item, where + "." + field)
            if entity == "facts":
                for evidence in row["evidence"]:
                    reference("sources", evidence["source_id"], where + ".evidence")
                for field, target in (("role_id", "roles"), ("project_id", "projects")):
                    if row[field] and records[target][row[field]]["organization_id"] != row["organization_id"]:
                        raise ValidationError(f"{where}.{field}: organization differs from fact organization")
    return records, origins, [name for name, _ in packs]


def data_counts(data):
    counts = {entity: len(data[entity]) for entity in ENTITIES}
    counts["application_eligible_facts"] = sum(f["application_eligible"] for f in data["facts"].values())
    counts["open_questions"] = sum(q["status"] == "open" for q in data["questions"].values())
    return counts


def data_digest(data):
    ordered = {entity: [data[entity][key] for key in sorted(data[entity])] for entity in ENTITIES}
    return hashlib.sha256(canonical(ordered).encode("utf-8")).hexdigest()


def provenance_digest(origins):
    return hashlib.sha256(canonical(sorted((entity, key, pack) for (entity, key), pack in origins.items())).encode("utf-8")).hexdigest()


def engine_digest():
    return hashlib.sha256(ENGINE_FILE.read_bytes()).hexdigest()


def populate(connection, data, origins, packs, schema):
    connection.executescript(schema)
    connection.execute("BEGIN IMMEDIATE")
    metadata = {"schema_version": str(SCHEMA_VERSION), "data_sha256": data_digest(data),
                "schema_sha256": hashlib.sha256(schema.encode("utf-8")).hexdigest(),
                "packs": canonical(sorted(packs)), "provenance_sha256": provenance_digest(origins), "engine_sha256": engine_digest()}
    connection.executemany("INSERT INTO metadata(key,value) VALUES(?,?)", sorted(metadata.items()))
    for entity in ENTITIES:
        columns = TABLE_COLUMNS[entity]
        sql = f"INSERT INTO {entity} ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})"
        for key in sorted(data[entity]):
            row = data[entity][key]
            connection.execute(sql, [row[c] for c in columns])
            connection.execute("INSERT INTO record_payloads VALUES(?,?,?,?)",
                               (entity, key, origins[entity, key], canonical(row)))
    for entity, join, parent in (("organizations", "organization_sources", "organization_id"),
                                  ("roles", "role_sources", "role_id"), ("projects", "project_sources", "project_id")):
        for row in sorted(data[entity].values(), key=lambda r: r["id"]):
            connection.executemany(f"INSERT INTO {join}({parent},source_id) VALUES(?,?)",
                                   [(row["id"], source) for source in sorted(row["source_ids"])])
    for fact in sorted(data["facts"].values(), key=lambda r: r["id"]):
        key = fact["id"]
        connection.executemany("INSERT INTO fact_tags VALUES(?,?)", [(key, tag) for tag in sorted(fact["tags"])])
        for i, metric in enumerate(fact["metrics"]):
            connection.execute("INSERT INTO fact_metrics VALUES(?,?,?,?,?,?,?,?)",
                               (key, i, metric["label"], metric.get("value"), metric.get("unit"), metric.get("currency"),
                                metric["scope"], metric.get("qualifier") or ""))
        for i, evidence in enumerate(fact["evidence"]):
            connection.execute("INSERT INTO fact_evidence VALUES(?,?,?,?,?)",
                               (key, i, evidence["source_id"], evidence["locator"], evidence.get("excerpt")))
        role = data["roles"].get(fact["role_id"], {})
        project = data["projects"].get(fact["project_id"], {})
        connection.execute("INSERT INTO fact_search VALUES(?,?,?,?,?,?,?)",
                           (key, fact["claim"], " ".join(sorted(fact["tags"])),
                            data["organizations"][fact["organization_id"]]["name"], role.get("title", ""),
                            project.get("name", ""), fact["usage_notes"]))
    for row in sorted(data["questions"].values(), key=lambda r: r["id"]):
        connection.executemany("INSERT INTO question_facts VALUES(?,?)",
                               [(row["id"], fact) for fact in sorted(row["related_fact_ids"])])
    for row in sorted(data["requirements"].values(), key=lambda r: r["id"]):
        connection.executemany("INSERT INTO requirement_tags VALUES(?,?)",
                               [(row["id"], tag) for tag in sorted(row["tags"])])
    if connection.execute("PRAGMA foreign_key_check").fetchall():
        raise ValidationError("Database foreign-key validation failed")
    if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
        raise ValidationError("Database integrity validation failed")
    connection.commit()


def build(root):
    data, origins, packs = load_data(root)
    schema = (ROOT / "schema.sql").read_text(encoding="utf-8")
    destination = root / "build" / "career.sqlite"
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=".career-", suffix=".sqlite", dir=destination.parent)
    os.close(fd)
    temporary = Path(temporary_name)
    try:
        with contextlib.closing(sqlite3.connect(temporary)) as connection:
            connection.execute("PRAGMA foreign_keys=ON")
            populate(connection, data, origins, packs, schema)
        with temporary.open("rb") as handle:
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
        Path(str(temporary) + "-journal").unlink(missing_ok=True)
    return {"database": str(destination), "schema_version": SCHEMA_VERSION,
            "data_sha256": data_digest(data), "counts": data_counts(data)}


@contextlib.contextmanager
def open_database(root):
    path = root / "build" / "career.sqlite"
    if not path.is_file():
        raise ValidationError(f"Database not found: {path}. Run: python career.py build")
    try:
        current_data, current_origins, current_packs = load_data(root)
    except ValidationError as exc:
        raise ValidationError(f"Canonical data is invalid: {exc}. Fix the source packs and run build; the previous database is unchanged.") from exc
    current_data_hash = data_digest(current_data)
    current_schema_hash = hashlib.sha256((ROOT / "schema.sql").read_text(encoding="utf-8").encode("utf-8")).hexdigest()
    connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA query_only=ON")
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        if version != SCHEMA_VERSION:
            raise ValidationError(f"Database schema {version} is unsupported; run build with this version of career.py")
        metadata = dict(connection.execute("SELECT key,value FROM metadata"))
        changed = []
        if metadata.get("data_sha256") != current_data_hash:
            changed.append("canonical data")
        if metadata.get("schema_sha256") != current_schema_hash:
            changed.append("schema")
        if metadata.get("packs") != canonical(sorted(current_packs)):
            changed.append("source pack manifest")
        if metadata.get("provenance_sha256") != provenance_digest(current_origins):
            changed.append("record source provenance")
        if metadata.get("engine_sha256") != engine_digest():
            changed.append("engine")
        if changed:
            raise ValidationError(f"Database is stale: {', '.join(changed)} changed; run build: python career.py build. The previous database is unchanged.")
        stored_data, stored_origins = database_data(connection)
        if stored_data != current_data or stored_origins != current_origins:
            raise ValidationError("Derived database payloads differ from source records; run build")
        for entity in ENTITIES:
            columns = TABLE_COLUMNS[entity]
            actual = {row["id"]: dict(row) for row in connection.execute(f"SELECT {','.join(columns)} FROM {entity}")}
            expected = {key: {c: row[c] for c in columns} for key, row in current_data[entity].items()}
            if actual != expected:
                raise ValidationError(f"Derived database {entity} rows differ from source records; run build")
        expected_search = []
        for fact in current_data["facts"].values():
            role = current_data["roles"].get(fact["role_id"], {})
            project = current_data["projects"].get(fact["project_id"], {})
            expected_search.append((fact["id"], fact["claim"], " ".join(sorted(fact["tags"])), current_data["organizations"][fact["organization_id"]]["name"], role.get("title", ""), project.get("name", ""), fact["usage_notes"]))
        actual_search = [tuple(row) for row in connection.execute("SELECT fact_id,claim,tags,organization,role,project,usage_notes FROM fact_search")]
        if sorted(actual_search) != sorted(expected_search):
            raise ValidationError("Derived search index differs from source records; run build")
        if connection.execute("PRAGMA foreign_key_check").fetchall() or connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValidationError("Derived database integrity check failed; run build")
        yield connection
    finally:
        connection.close()


def database_data(connection):
    data = {entity: {} for entity in ENTITIES}
    origins = {}
    for row in connection.execute("SELECT * FROM record_payloads ORDER BY entity_type, record_id"):
        data[row["entity_type"]][row["record_id"]] = json.loads(row["payload_json"])
        origins[row["entity_type"], row["record_id"]] = row["pack_name"]
    return data, origins


def literal_fts_query(query):
    """Interpret words and double-quoted phrases literally, never as FTS operators."""
    terms = []
    for match in re.finditer(r'"([^"\n]*)"|([^\s"]+)', query):
        phrase, bare = match.groups()
        words = re.findall(r"[^\W_]+", phrase if phrase is not None else bare, flags=re.UNICODE)
        if phrase is not None and words:
            terms.append('"' + " ".join(words) + '"')
        else:
            terms.extend('"' + word + '"' for word in words)
    return " AND ".join(terms)


def search(connection, query, include_context=False, include_unconfirmed=False, limit=20):
    fts = literal_fts_query(query)
    if not fts:
        return []
    predicates = ["f.application_eligible=1"]
    if include_context:
        predicates.append("(f.kind IN ('company_context','project_context') AND f.completion_status NOT IN ('planned','unclear') AND f.verification_status NOT IN ('needs_confirmation','conflicted'))")
    if include_unconfirmed:
        predicates.append("f.kind NOT IN ('company_context','project_context')")
    if include_context and include_unconfirmed:
        predicates = ["1=1"]
    sql = """SELECT f.*, o.name AS organization, p.name AS project, r.title AS role
        FROM fact_search JOIN facts f ON f.id=fact_search.fact_id
        JOIN organizations o ON o.id=f.organization_id
        LEFT JOIN projects p ON p.id=f.project_id LEFT JOIN roles r ON r.id=f.role_id
        WHERE fact_search MATCH ? AND (""" + " OR ".join(predicates) + ") ORDER BY bm25(fact_search), f.id LIMIT ?"
    results = []
    for row in connection.execute(sql, (fts, limit)):
        result = dict(row)
        result["application_eligible"] = bool(result["application_eligible"])
        result["evidence"] = [dict(e) for e in connection.execute(
            "SELECT e.source_id, e.locator, s.title, s.uri FROM fact_evidence e JOIN sources s ON s.id=e.source_id WHERE e.fact_id=? ORDER BY e.ordinal", (result["id"],))]
        results.append(result)
    return results


def fact_details(data, origins, key):
    if key not in data["facts"]:
        raise ValidationError(f"Unknown fact ID: {key}")
    fact = dict(data["facts"][key])
    fact["organization_name"] = data["organizations"][fact["organization_id"]]["name"]
    fact["source_pack"] = origins["facts", key]
    fact["sources"] = [data["sources"][source] for source in sorted({e["source_id"] for e in fact["evidence"]})]
    return fact


def sorted_questions(data, include_resolved=False):
    priority = {"high": 0, "medium": 1, "low": 2}
    return sorted((q for q in data["questions"].values() if include_resolved or q["status"] == "open"),
                  key=lambda q: (priority[q["priority"]], q["id"]))


def match_job(data, job_id):
    if job_id not in data["jobs"]:
        raise ValidationError(f"Unknown job ID: {job_id}")
    result = {"job": data["jobs"][job_id], "method": "Explicit curated matches only; no fit score or automatic qualification inference.", "requirements": []}
    for requirement in sorted(data["requirements"].values(), key=lambda r: r["id"]):
        if requirement["job_id"] != job_id:
            continue
        entry = {"requirement": requirement, "coverage": "gap", "usable_matches": [], "review_or_context_only": [], "gap_notes": []}
        for match in sorted(data["matches"].values(), key=lambda m: m["id"]):
            if match["requirement_id"] != requirement["id"]:
                continue
            if match["assessment"] == "gap":
                entry["gap_notes"].append(match)
                continue
            fact = data["facts"][match["fact_id"]]
            item = {"match": match, "fact": fact}
            if match["review_status"] == "curated" and fact["application_eligible"]:
                entry["usable_matches"].append(item)
            else:
                item["excluded_reasons"] = []
                if match["review_status"] != "curated":
                    item["excluded_reasons"].append("Match requires review")
                if not fact["application_eligible"]:
                    item["excluded_reasons"].append("Fact is not application eligible; retain only as context or a clarification lead")
                entry["review_or_context_only"].append(item)
        if any(m["match"]["assessment"] == "direct" for m in entry["usable_matches"]):
            entry["coverage"] = "direct evidence"
        elif entry["usable_matches"]:
            entry["coverage"] = "adjacent evidence"
        result["requirements"].append(entry)
    return result


def period(record):
    start = record.get("start_date") or "start not recorded"
    end = record.get("end_date") or "end not recorded"
    return f"{start} to {end}; as of {record['as_of']}"


def metric_text(metric):
    value = metric.get("value")
    if type(value) is float and value.is_integer():
        value = int(value)
    rendered = "not quantified" if value is None else format(value, ",")
    units = " ".join(str(metric[key]) for key in ("currency", "unit") if metric.get(key))
    qualifier = f"; {metric['qualifier']}" if metric.get("qualifier") else ""
    return f"{metric['label']}: {rendered}{' ' + units if units else ''} (metric scope: {metric['scope']}{qualifier})"


def markdown(value):
    text = str(value).replace("\r", " ").replace("\n", " ")
    return re.sub(r"([\\`*_{}\[\]()<>#!|])", r"\\\1", text)


def literal(value):
    text = str(value).replace("\r", " ").replace("\n", " ")
    runs = re.findall(r"`+", text)
    fence = "`" * (max((len(x) for x in runs), default=0) + 1)
    return fence + " " + text + " " + fence


def source_reference(source):
    title = markdown(source["title"])
    uri = source.get("uri")
    if not uri:
        return title
    parsed = urlsplit(uri)
    if parsed.scheme.lower() in {"http", "https", "mailto"} and (parsed.netloc or parsed.scheme.lower() == "mailto"):
        return f"[{title}]({quote(uri, safe=':/?&=#@+%.-_~')})"
    return title + " (" + literal(uri) + ")"


def render_fact(fact, data, heading="####"):
    m = markdown
    lines = [f"{heading} {m(fact['id'])}", "", m(fact["claim"]), "",
             f"- Kind: {fact['kind']}; scope: {fact['scope']}",
             f"- Dates: {m(period(fact))}",
             f"- Status: {fact['completion_status']}; verification: {fact['verification_status']}",
             f"- Application eligible: {'yes' if fact['application_eligible'] else 'no'}"]
    if fact["role_id"]:
        lines.append(f"- Role: {m(data['roles'][fact['role_id']]['title'])} ({m(fact['role_id'])})")
    if fact["project_id"]:
        lines.append(f"- Project: {m(data['projects'][fact['project_id']]['name'])} ({m(fact['project_id'])})")
    if fact["tags"]:
        lines.append("- Tags: " + m(", ".join(sorted(fact["tags"]))))
    for metric in fact["metrics"]:
        lines.append("- " + m(metric_text(metric)))
    if fact["usage_notes"]:
        lines.append("- Usage notes: " + m(fact["usage_notes"]))
    for evidence in fact["evidence"]:
        source = data["sources"][evidence["source_id"]]
        lines.append(f"- Evidence: {source_reference(source)}; {m(evidence['locator'])} ({m(evidence['source_id'])})")
        if evidence.get("excerpt"):
            lines.append("- Source excerpt or supplied paraphrase: " + m(evidence["excerpt"]))
    return "\n".join(lines) + "\n"


def render_inventory(data):
    lines = ["# Career evidence inventory", "", "Only application-eligible facts are supported application evidence. Context, plans and unresolved claims remain separate. Source documentation is not independent verification. Dates and metric scope are preserved.", ""]
    for org in sorted(data["organizations"].values(), key=lambda o: (o["name"].casefold(), o["id"])):
        lines += ["## " + markdown(org["name"]), "", markdown(org["description"]), markdown(org["notes"]), ""]
        for role in sorted((r for r in data["roles"].values() if r["organization_id"] == org["id"]), key=lambda r:r["id"]):
            lines.append("- Role: " + markdown(role["title"]) + "; " + markdown(period(role)))
        lines.append("")
        for fact in sorted((f for f in data["facts"].values() if f["organization_id"] == org["id"]),key=lambda f:f["id"]):
            lines.extend([render_fact(fact,data).rstrip(), ""])
    return "\n".join(lines).rstrip() + "\n"


def render_sources(data, origins):
    lines = ["# Source index", "", "Source dates and retrieval dates are distinct. Local locators are descriptive and are not executed.", ""]
    for source in sorted(data["sources"].values(), key=lambda s:s["id"]):
        lines += ["## " + markdown(source["id"]) + ": " + markdown(source["title"]), "",
                  "- Kind: " + source["kind"], "- Source date: " + str(source["source_date"] or "not recorded"),
                  "- Retrieved: " + source["retrieved_at"], "- Source: " + source_reference(source),
                  "- Canonical pack: " + markdown(origins['sources',source['id']])]
        for field in ["local_path","sha256","notes"]:
            if source.get(field):lines.append("- " + field + ": " + markdown(source[field]))
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def render_questions(data, include_resolved=False):
    lines = ["# Clarification list", "", "Resolving a question does not automatically promote a fact.", ""]
    for row in sorted_questions(data, include_resolved):
        lines += ["## " + row["priority"].upper() + ": " + markdown(row["question"]), "",
                  "ID: " + markdown(row["id"]) + "; status: " + row["status"], "", markdown(row["reason"]), ""]
        if row["answer"]:lines.extend(["Recorded answer: " + markdown(row["answer"]), ""])
    return "\n".join(lines).rstrip() + "\n"


def render_matches(report):
    job = report["job"]
    lines = ["# Evidence match: " + markdown(job["title"]), "", literal(job["url"]), "", markdown(report["method"]), "", "Evidence coverage is not an ATS score or hiring prediction.", ""]
    for entry in report["requirements"]:
        req = entry["requirement"]
        lines += ["## " + markdown(req["id"]) + ": " + markdown(req["text"]), "", "Coverage: " + entry["coverage"], ""]
        for item in entry["usable_matches"]:
            lines += ["- " + item["match"]["assessment"] + ": " + markdown(item["fact"]["claim"]), "  Evidence ID: " + markdown(item["fact"]["id"]), "  Rationale: " + markdown(item["match"]["rationale"])]
        for note in entry["gap_notes"]:lines.append("- Gap note: " + markdown(note["rationale"]))
        for item in entry["review_or_context_only"]:lines.append("- Context/review only: " + markdown(item["fact"]["id"]))
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def atomic_text(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix="." + path.name + "-", dir=path.parent)
    temporary = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


EXPORT_FILES = {"career_inventory.md", "source_index.md", "clarification_list.md", "career_data.json"}


def safe_output(root, output):
    output = Path(output).resolve()
    if not output.is_relative_to(root.resolve()):
        raise ValidationError("Export destination must stay inside your private workspace")
    for name in ["data", "build", "state", "inputs"]:
        if output.is_relative_to((root / name).resolve()):
            raise ValidationError("Export destination is inside protected workspace storage")
    return output


def export_data(root, connection, output_dir=None):
    data, origins = database_data(connection)
    output = safe_output(root, output_dir or root / "exports")
    metadata = dict(connection.execute("SELECT key,value FROM metadata"))
    ordered = {entity: [data[entity][key] for key in sorted(data[entity])] for entity in ENTITIES}
    stamp = "<!-- Generated by resume-cover-letter-toolkit; data " + metadata["data_sha256"] + "; provenance " + metadata["provenance_sha256"] + " -->\n\n"
    files = {"career_inventory.md": stamp + render_inventory(data), "source_index.md": stamp + render_sources(data, origins), "clarification_list.md": stamp + render_questions(data), "career_data.json": pretty(ordered)}
    manifest_path = output / "export_manifest.json"
    if manifest_path.exists() or any((output / name).exists() for name in EXPORT_FILES):
        try:
            previous = parse_pack(manifest_path)
        except ValidationError as exc:
            raise ValidationError("Refusing to overwrite files without a toolkit export manifest") from exc
        if not isinstance(previous,dict) or previous.get("generator") != "resume-cover-letter-toolkit":
            raise ValidationError("Refusing to overwrite files owned by another generator")
    manifest = {"generator": "resume-cover-letter-toolkit", "metadata": metadata, "files": {name: hashlib.sha256(text.encode("utf-8")).hexdigest() for name,text in files.items()}, "record_origins": [{"entity":e,"id":key,"pack":pack} for (e,key),pack in sorted(origins.items())]}
    # The manifest is the commit marker. A partial write is detectable and never reports success.
    for name,text in sorted(files.items()):
        atomic_text(output / name,text)
    atomic_text(manifest_path,pretty(manifest))
    return {"exports": [str(output / name) for name in sorted(files)], "manifest": str(manifest_path), "counts": data_counts(data)}


def validate_exports(root, connection, output_dir=None):
    output = safe_output(root, output_dir or root / "exports")
    manifest = parse_pack(output / "export_manifest.json")
    if (not isinstance(manifest,dict) or manifest.get("generator") != "resume-cover-letter-toolkit"
            or not isinstance(manifest.get("files"),dict) or set(manifest["files"]) != EXPORT_FILES):
        raise ValidationError("Export manifest is invalid")
    metadata = dict(connection.execute("SELECT key,value FROM metadata"))
    if manifest.get("metadata") != metadata:
        raise ValidationError("Exports are stale; run export")
    for name,wanted in manifest["files"].items():
        path = output / name
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=wanted:
            raise ValidationError("Export generation is incomplete or changed; run export")
    return {"valid":True,"data_sha256":metadata["data_sha256"],"files":len(EXPORT_FILES)}


def add_pack(root, path, name=None):
    stem = name or path.stem
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", stem):
        raise ValidationError("Intake name must contain only letters, digits, underscores and hyphens")
    filename = "intake_" + stem + ".json"
    destination = root / "data" / filename
    if destination.exists():
        raise ValidationError(f"Refusing to replace existing pack: {destination}")
    pack = parse_pack(path)
    data, _, _ = load_data(root, extra=(filename, pack))
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".intake-", dir=destination.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(pretty(pack))
            handle.flush()
            os.fsync(handle.fileno())
        # Hard-link creates the destination exclusively; an existing file is never overwritten.
        os.link(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    return {"added": str(destination), "counts": data_counts(data), "next_step": "Run build and export to refresh derived files."}


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--root", type=Path, default=ROOT, help="Career data root; default is the folder containing career.py")
    subs = result.add_subparsers(dest="command", required=True)
    for name in ("build", "validate", "stats", "search", "show", "questions", "export", "validate-exports", "match", "add"):
        sub = subs.add_parser(name)
        sub.add_argument("--json", action="store_true", help="Machine-readable output")
        if name == "search":
            sub.add_argument("query", nargs="+", help='Literal keywords or double-quoted phrases; no FTS operators')
            sub.add_argument("--include-context", action="store_true")
            sub.add_argument("--include-unconfirmed", action="store_true")
            sub.add_argument("--limit", type=int, default=20)
        elif name == "show":
            sub.add_argument("fact_id")
        elif name == "questions":
            sub.add_argument("--all", action="store_true", help="Include resolved questions")
        elif name in {"export", "validate-exports"}:
            sub.add_argument("--output-dir", type=Path)
        elif name == "match":
            sub.add_argument("job_id")
        elif name == "add":
            sub.add_argument("pack", type=Path)
            sub.add_argument("--name", help="Name for data/intake_NAME.json; defaults to the input filename stem")
    return result


def main(argv=None):
    args = parser().parse_args(argv)
    root = args.root.resolve()
    try:
        if args.command == "build":
            result = build(root)
        elif args.command == "validate":
            data, _, packs = load_data(root)
            result = {"valid": True, "schema_version": SCHEMA_VERSION, "packs": sorted(packs), "counts": data_counts(data), "data_sha256": data_digest(data)}
        elif args.command == "add":
            result = add_pack(root, args.pack.resolve(), args.name)
        else:
            with open_database(root) as connection:
                if args.command == "search":
                    if not 1 <= args.limit <= 1000:
                        raise ValidationError("Search limit must be between 1 and 1000")
                    result = search(connection, " ".join(args.query), args.include_context, args.include_unconfirmed, args.limit)
                elif args.command == "export":
                    result = export_data(root, connection, args.output_dir.resolve() if args.output_dir else None)
                elif args.command == "validate-exports":
                    result = validate_exports(root, connection, args.output_dir.resolve() if args.output_dir else None)
                else:
                    data, origins = database_data(connection)
                    if args.command == "stats":
                        result = {"metadata": dict(connection.execute("SELECT key,value FROM metadata ORDER BY key")), "counts": data_counts(data),
                                  "facts_by_verification": {status: sum(f["verification_status"] == status for f in data["facts"].values()) for status in sorted(ENUMS["facts", "verification_status"])}}
                    elif args.command == "show":
                        result = fact_details(data, origins, args.fact_id)
                    elif args.command == "questions":
                        result = sorted_questions(data, args.all)
                    elif args.command == "match":
                        result = match_job(data, args.job_id)
        if args.json or args.command in {"build", "validate", "stats", "export", "add"}:
            print(pretty(result), end="")
        elif args.command == "search":
            if not result:
                print("No matching facts in the selected evidence scope.")
            for fact in result:
                print(f"{fact['id']} | {fact['organization']} | eligible: {'yes' if fact['application_eligible'] else 'no'}")
                print(f"  {fact['claim']}")
                print(f"  {fact['verification_status']}; {fact['completion_status']}; scope: {fact['scope']}; as of {fact['as_of']}")
                for evidence in fact["evidence"]:
                    print(f"  Source: {evidence['source_id']}; {evidence['locator']}")
                print()
        elif args.command == "show":
            print(render_fact(result, data, "##"), end="")
        elif args.command == "questions":
            print(render_questions(data, args.all), end="")
        elif args.command == "match":
            print(render_matches(result), end="")
        return 0
    except (ValidationError, OSError, sqlite3.Error, ValueError, RecursionError, UnicodeError) as exc:
        if getattr(args, "json", False):
            print(pretty({"error": str(exc)}), file=sys.stderr, end="")
        else:
            print(f"Error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
