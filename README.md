# AI Lead Follow-up Agent

An AI agent that reads inbound leads, classifies intent, decides the next action from a fixed
tool set, and executes it — with deterministic guardrails, a full audit trail, and a
human-in-the-loop escalation flow. Portfolio MVP; see [DESIGN.md](DESIGN.md) for the full design
(problem statement, architecture, data model, guardrails, milestones). Engineering decisions and
issues hit along the way are logged in [docs/dev-log.md](docs/dev-log.md); current build status
is in [docs/current-status.md](docs/current-status.md). To exercise every guardrail/decision path
by hand, see [docs/manual-testing-guide.md](docs/manual-testing-guide.md).

**Status:** V1 functionally complete (Milestones 1–4): data model, lead ingestion, agent core
(Claude tool-use), real tool execution, scheduler, guardrails, and a browser UI.

## Quickstart

Five steps to a running app. Run each block in order from the project root.

**1. Start Postgres** (needs Docker running)
```bash
docker compose up -d db
```

**2. Set up the Python environment** (first time only)
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
```
Already have a `.venv`? Just `source .venv/bin/activate`.

**3. Apply database migrations**
```bash
alembic upgrade head
```

**4. Load sample data** (optional, but recommended for a first look)
```bash
python -m scripts.seed
```

**5. Start the app**
```bash
uvicorn app.main:app --reload --port 8001
```
Open **http://localhost:8001/** in a browser.

## Using the app

| Page | What it's for |
|---|---|
| `/` | Landing page — submit a lead, same as a real form would. Redirects you to that lead's page. |
| `/dashboard` | Table of every lead: status, intent, owner, next follow-up. |
| `/dashboard/{id}` | One lead: message thread, agent decision log, action history, escalation history, a "simulate a reply" form, and escalate/resolve controls. |
| `/outbox` | Every email the agent has "sent" (mocked — no real delivery, see DESIGN.md §3). |

**Without an `ANTHROPIC_API_KEY`**, the agent's LLM calls fail gracefully (the lead/reply is
still recorded, the failure shows up as a logged decision) — this is by design, not a bug. The
**deterministic guardrails still work without a key**, since they intentionally bypass the LLM:
try submitting a message containing "unsubscribe" or "speak to a human" and watch it take effect
immediately.

**To see real agent behavior**, add a key to `.env`:
```
ANTHROPIC_API_KEY=sk-ant-...
```
then restart `uvicorn`.

### Optional: run the follow-up scheduler

In a second terminal, so scheduled follow-ups actually fire:
```bash
source .venv/bin/activate
python -m scripts.run_scheduler
```
Polls every 30s (configurable via `SCHEDULER_POLL_INTERVAL_SECONDS` in `.env`) for due follow-ups.

## Running tests

```bash
source .venv/bin/activate
pytest
```
Runs against a real Postgres database (`leadagent_test`, created automatically on the same
docker-compose instance, not SQLite — the schema uses Postgres-specific types). No network calls
and no API key needed: the agent's LLM client is replaced with a fake in every automated test.

## Project layout

```
app/
  agent/        agent core: classification, decisions, execution, guardrails, scheduler logic
  routers/      leads.py (JSON API), pages.py (server-rendered UI)
templates/      Jinja2 templates for the UI
static/         stylesheet
scripts/        seed.py (sample data), run_scheduler.py (follow-up polling loop)
migrations/     Alembic migrations
tests/          pytest suite (real Postgres, fake LLM client)
```

## Troubleshooting

- **Can't reach `localhost:8001`**: confirm `uvicorn` is actually running (check the terminal
  it's in, or `ps aux | grep uvicorn`). If it's running but still unreachable, and you're using a
  remote/devcontainer setup, the port may need forwarding to your local machine.
- **`pytest` or the app can't connect to Postgres**: `docker compose ps` — the `db` container
  doesn't survive a host/session restart, so you may need `docker compose up -d db` again.
