# Dev Log

## Milestone 1 — project scaffolding, data model, lead ingestion/CRUD

**Stack decisions**
- FastAPI + SQLAlchemy 2.0 (sync, not async) + Alembic + Postgres 16 via `docker-compose.yml`.
  Sync was a deliberate simplification: the MVP has a handful of endpoints with no
  latency-sensitive concurrency requirement, so async session/engine plumbing wasn't worth the
  complexity yet.
- Dependency management via `pyproject.toml` + `pip install -e .[dev]`, not Poetry/uv — neither
  was present in the environment, and plain pip keeps setup to one command for anyone cloning
  the repo.
- UUID primary keys (Postgres `UUID`, generated client-side via `uuid4`) instead of serial
  integers, for the usual production reason (non-enumerable IDs) at negligible cost for this
  project's size.

**Design decisions worth flagging**
- `Lead.metadata` from DESIGN.md §4 collides with SQLAlchemy's reserved `Base.metadata`
  attribute on every declarative model. Renamed the column to `lead_metadata` in the ORM model
  (JSON contents/shape unchanged). Noting this because it's a naming deviation from the design
  doc's literal field list, not a scope change.
- Status/intent/direction fields use `SQLAlchemy Enum(..., native_enum=False)` — stored as
  `VARCHAR` + `CHECK` constraint rather than a native Postgres `ENUM` type. Native Postgres enums
  make adding/removing a value a schema-level `ALTER TYPE`, which is friction we don't want while
  the action/intent vocabulary is still likely to shift over the next few milestones (agent
  actions, escalation reasons). Validation still happens at the API boundary via Pydantic/Python
  enums either way.
- All 6 tables from DESIGN.md §4 (`leads`, `messages`, `agent_decisions`, `actions`,
  `followup_schedules`, `escalation_events`) were created now, in one migration, even though only
  `leads`/`messages` are used by an endpoint yet. Rationale: avoids repeated schema-churning
  migrations across Milestones 2-4 for a schema that was already fully specified in the design
  doc.
- No separate "outbox" table, per DESIGN.md §4 — outbound emails will just be `Message` rows with
  `direction=out`, filtered in the UI later.

**Issues hit and fixed during implementation**
- **Test isolation bug**: the first version of the `db_session` test fixture wrapped each test in
  a single `connection.begin()` transaction and rolled it back at teardown. That doesn't work
  once the code under test calls `session.commit()` (which the `leads` endpoints do normally) —
  the commit finalizes the outer transaction for real, so the teardown rollback becomes a no-op
  and test data leaks between tests. Fixed using SQLAlchemy's documented pattern: a SAVEPOINT
  (`connection.begin_nested()`) that's automatically restarted after every commit via an
  `after_transaction_end` event listener, so `session.commit()` only closes the SAVEPOINT while
  the real outer transaction stays open until the fixture rolls it back.
- **psycopg conninfo format**: the raw `psycopg.connect()` call used to create the
  `leadagent_test` database rejected the SQLAlchemy-style `postgresql+psycopg://` URL — libpq
  conninfo strings don't understand the `+psycopg` driver suffix. Fixed by stripping it before
  passing the URL to `psycopg.connect()` (only needed for that one admin connection; SQLAlchemy's
  own engine still uses the `+psycopg` URL as usual).

**Verification**
- `pytest`: 9/9 passing against a real Postgres test database (`leadagent_test`), covering lead
  creation (incl. initial inbound message), validation errors, list, get, 404s, and status
  update.
- Manual smoke test: ran `uvicorn` against the dev database and exercised `/health`, `POST
  /leads`, `GET /leads`, `GET /leads/{id}` (incl. a 404 case) with `curl` — confirmed the full
  docker-compose → Alembic → FastAPI path works end-to-end, not just through `TestClient`.
