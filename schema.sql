-- Career Vault schema v1. Canonical input is data/*.json; this database is derived.
PRAGMA foreign_keys = ON;
PRAGMA user_version = 1;
PRAGMA application_id = 1129726294;

CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE sources (
    id TEXT PRIMARY KEY, title TEXT NOT NULL,
    kind TEXT NOT NULL CHECK(kind IN ('resume','email','company_website','job_posting','user_update','repository')),
    source_date TEXT, retrieved_at TEXT NOT NULL, uri TEXT, local_path TEXT,
    sha256 TEXT, notes TEXT NOT NULL DEFAULT ''
);
CREATE TABLE organizations (
    id TEXT PRIMARY KEY, name TEXT NOT NULL,
    kind TEXT NOT NULL CHECK(kind IN ('employer','client','university','military','target_employer')),
    description TEXT NOT NULL DEFAULT '', notes TEXT NOT NULL DEFAULT ''
);
CREATE TABLE organization_sources (
    organization_id TEXT NOT NULL REFERENCES organizations(id),
    source_id TEXT NOT NULL REFERENCES sources(id),
    PRIMARY KEY (organization_id, source_id)
);
CREATE TABLE roles (
    id TEXT PRIMARY KEY, organization_id TEXT NOT NULL REFERENCES organizations(id),
    title TEXT NOT NULL, start_date TEXT, end_date TEXT, as_of TEXT NOT NULL, notes TEXT NOT NULL DEFAULT ''
);
CREATE TABLE role_sources (
    role_id TEXT NOT NULL REFERENCES roles(id), source_id TEXT NOT NULL REFERENCES sources(id),
    PRIMARY KEY (role_id, source_id)
);
CREATE TABLE projects (
    id TEXT PRIMARY KEY, organization_id TEXT NOT NULL REFERENCES organizations(id),
    name TEXT NOT NULL, start_date TEXT, end_date TEXT, as_of TEXT NOT NULL, notes TEXT NOT NULL DEFAULT ''
);
CREATE TABLE project_sources (
    project_id TEXT NOT NULL REFERENCES projects(id), source_id TEXT NOT NULL REFERENCES sources(id),
    PRIMARY KEY (project_id, source_id)
);
CREATE TABLE facts (
    id TEXT PRIMARY KEY, organization_id TEXT NOT NULL REFERENCES organizations(id),
    role_id TEXT REFERENCES roles(id), project_id TEXT REFERENCES projects(id),
    kind TEXT NOT NULL CHECK(kind IN ('achievement','responsibility','project_context','company_context','education','credential','publication')),
    claim TEXT NOT NULL, start_date TEXT, end_date TEXT, as_of TEXT NOT NULL,
    scope TEXT NOT NULL CHECK(scope IN ('personal','team','project','organization')),
    completion_status TEXT NOT NULL CHECK(completion_status IN ('completed','ongoing_as_of_source','planned','unclear')),
    verification_status TEXT NOT NULL CHECK(verification_status IN ('documented','user_confirmed','needs_confirmation','conflicted')),
    application_eligible INTEGER NOT NULL CHECK(application_eligible IN (0,1)),
    usage_notes TEXT NOT NULL DEFAULT '',
    CHECK(kind != 'company_context' OR (scope = 'organization' AND application_eligible = 0)),
    CHECK(application_eligible = 0 OR (completion_status NOT IN ('planned','unclear')
        AND verification_status NOT IN ('needs_confirmation','conflicted')))
);
CREATE TABLE fact_tags (
    fact_id TEXT NOT NULL REFERENCES facts(id), tag TEXT NOT NULL,
    PRIMARY KEY (fact_id, tag)
);
CREATE TABLE fact_metrics (
    fact_id TEXT NOT NULL REFERENCES facts(id), ordinal INTEGER NOT NULL,
    label TEXT NOT NULL, value NUMERIC, unit TEXT, currency TEXT,
    scope TEXT NOT NULL CHECK(scope IN ('personal','team','project','organization')),
    qualifier TEXT NOT NULL DEFAULT '', PRIMARY KEY (fact_id, ordinal)
);
CREATE TABLE fact_evidence (
    fact_id TEXT NOT NULL REFERENCES facts(id), ordinal INTEGER NOT NULL,
    source_id TEXT NOT NULL REFERENCES sources(id), locator TEXT NOT NULL, excerpt TEXT,
    PRIMARY KEY (fact_id, ordinal)
);
CREATE TABLE questions (
    id TEXT PRIMARY KEY, priority TEXT NOT NULL CHECK(priority IN ('high','medium','low')),
    question TEXT NOT NULL, reason TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('open','resolved')), answer TEXT
);
CREATE TABLE question_facts (
    question_id TEXT NOT NULL REFERENCES questions(id), fact_id TEXT NOT NULL REFERENCES facts(id),
    PRIMARY KEY (question_id, fact_id)
);
CREATE TABLE jobs (
    id TEXT PRIMARY KEY, organization_id TEXT NOT NULL REFERENCES organizations(id),
    title TEXT NOT NULL, url TEXT NOT NULL, captured_at TEXT NOT NULL,
    source_id TEXT NOT NULL REFERENCES sources(id),
    status TEXT NOT NULL CHECK(status IN ('captured','closed','unknown')), notes TEXT NOT NULL DEFAULT ''
);
CREATE TABLE requirements (
    id TEXT PRIMARY KEY, job_id TEXT NOT NULL REFERENCES jobs(id),
    category TEXT NOT NULL CHECK(category IN ('responsibility','required','preferred')),
    text TEXT NOT NULL, source_locator TEXT NOT NULL
);
CREATE TABLE requirement_tags (
    requirement_id TEXT NOT NULL REFERENCES requirements(id), tag TEXT NOT NULL,
    PRIMARY KEY (requirement_id, tag)
);
CREATE TABLE matches (
    id TEXT PRIMARY KEY, requirement_id TEXT NOT NULL REFERENCES requirements(id),
    fact_id TEXT REFERENCES facts(id), assessment TEXT NOT NULL CHECK(assessment IN ('direct','adjacent','gap')),
    rationale TEXT NOT NULL, review_status TEXT NOT NULL CHECK(review_status IN ('curated','needs_review')),
    CHECK((assessment = 'gap' AND fact_id IS NULL) OR (assessment != 'gap' AND fact_id IS NOT NULL))
);
-- Retain canonical records to support lossless readable/JSON exports and pack provenance.
CREATE TABLE record_payloads (
    entity_type TEXT NOT NULL, record_id TEXT NOT NULL, pack_name TEXT NOT NULL,
    payload_json TEXT NOT NULL, PRIMARY KEY (entity_type, record_id)
);
CREATE INDEX facts_organization ON facts(organization_id);
CREATE INDEX facts_eligibility ON facts(application_eligible, kind);
CREATE INDEX evidence_source ON fact_evidence(source_id);
CREATE INDEX requirements_job ON requirements(job_id);
CREATE INDEX matches_requirement ON matches(requirement_id);
CREATE VIRTUAL TABLE fact_search USING fts5(
    fact_id UNINDEXED, claim, tags, organization, role, project, usage_notes,
    tokenize = 'unicode61'
);
