# Current Status

_Last updated: 2026-08-28 — end of Milestone 1_

## Current Milestone

**Milestone 1 — project scaffolding, data model, lead ingestion/CRUD: complete.**
Next up: Milestone 2 — agent core (classification + tool-call decision loop, decision/rationale
logging; tool execution may stay stubbed/logged-only per DESIGN.md §9).

## Completed Work

- Project scaffolding: `pyproject.toml` (pip-installable, no Poetry/uv), git repo, Postgres 16 via
  `docker-compose.yml`, `.env.example`
- FastAPI app (`app/main.py`) with `/health`
- SQLAlchemy 2.0 (sync) models for all 6 DESIGN.md §4 entities: `Lead`, `Message`,
  `AgentDecision`, `Action`, `FollowupSchedule`, `EscalationEvent`
- Alembic wired up; single migration creates the full schema
- Lead ingestion/CRUD API: `POST /leads` (creates lead + initial inbound `Message`),
  `GET /leads`, `GET /leads/{id}`, `PATCH /leads/{id}` (status)
- `scripts/seed.py` — 5 sample leads at varied statuses/intents, re-runnable
- Test suite (`tests/`): 9 pytest cases against a real Postgres test database, covering
  create/list/get/update/validation/404
- Verified end-to-end: `pytest` (9/9 passing) and a manual smoke test against a live `uvicorn`
  process, not just `TestClient`
- `README.md` (setup/run instructions) and `docs/dev-log.md` (decisions and issues log)

## Work In Progress

None — Milestone 1 closed out cleanly; nothing left mid-flight.

## Next Planned Steps (Milestone 2, per DESIGN.md §9)

- Agent core: intent classification + tool-call decision loop against the Claude API
- Persist `AgentDecision` rows with concise rationale summaries (not raw chain-of-thought, per
  agreed design)
- Tool execution can remain stubbed/logged-only at this stage — real sending is Milestone 3

## Open Issues

None blocking. Noted for awareness, not urgent:
- `starlette.testclient` currently emits a deprecation warning about `httpx` vs `httpx2`; tests
  pass, no action needed yet.

## Active Decisions / Constraints

- Sync FastAPI/SQLAlchemy (not async) — deliberate simplicity for this MVP's scale
- UUID primary keys throughout
- Enums stored as `VARCHAR` + `CHECK` (`native_enum=False`), not native Postgres `ENUM` types —
  keeps the intent/action vocabulary easy to evolve across the remaining milestones
- `Lead.metadata` (DESIGN.md) implemented as `lead_metadata` in code — name collides with
  SQLAlchemy's reserved `Base.metadata`; contents/shape unchanged
- All 6 tables exist now even though only `leads`/`messages` are used by an endpoint yet, to
  avoid repeated schema-churning migrations later
- No separate outbox table — outbound email will be `Message` rows with `direction=out`,
  filtered in the UI (Milestone 4)
- Model choice for the agent: Claude Sonnet 5 (per DESIGN.md §3), not yet integrated
- Scope discipline holds: no agent, scheduler, email sending, or UI built yet — see DESIGN.md §10
  for the full V1 non-goals list
