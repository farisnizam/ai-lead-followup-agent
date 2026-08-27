# AI Lead Follow-up Agent

Portfolio MVP — see [DESIGN.md](DESIGN.md) for the full design (problem statement, scope,
architecture, data model, guardrails, milestones). Engineering decisions and issues encountered
during implementation are logged in [docs/dev-log.md](docs/dev-log.md).

**Status:** Milestone 1 complete (project scaffolding, data model, lead ingestion/CRUD). No
agent, scheduler, email sending, or UI yet.

## Setup

```bash
cp .env.example .env
docker compose up -d db

python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

alembic upgrade head
python -m scripts.seed   # optional sample data

uvicorn app.main:app --reload
```

API is then available at `http://localhost:8000` (`/health`, `/leads`).

## Tests

```bash
pytest
```

Tests run against a real Postgres database (`leadagent_test`, created automatically on the same
docker-compose instance), not SQLite — the schema uses Postgres-specific types (JSONB, UUID).
