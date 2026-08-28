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

## Milestone 2 — agent core

**Stack/design decisions**
- One `client.messages.create(...)` call per trigger event, not a multi-turn tool loop: all 5
  DESIGN.md §7 tools are defined as `strict: true` Anthropic tools with
  `tool_choice: {"type": "any"}` (must call exactly one, no free-text reply). Each tool's input
  schema shares a common `intent` (the existing `LeadIntent` enum) + `rationale` base, so
  classification, decision, and rationale all come out of a single call.
- Tool input schemas are Pydantic models (`app/agent/schemas.py`), not hand-written JSON —
  they're the single source of truth for both the Anthropic `input_schema` (generated via
  `model_json_schema()`) and the defensive re-validation of whatever the model returns
  (`app/agent/core.py`). This is what turns DESIGN.md §8's "tool-call schema validation before
  execution" into actual code, and it's independent of Anthropic's own `strict` enforcement — our
  validation still runs even if a client (real or, in tests, fake) hands back something the
  Anthropic API itself would never have produced.
- Pydantic's `model_json_schema()` emits enum fields as a `$ref` into `$defs`; Anthropic's strict
  tool schemas expect a flat object, so `app/agent/tools.py` inlines those refs before building
  the tool definition. Verified empirically by printing the generated schemas — flat as expected,
  no leftover `$ref`/`$defs`.
- Chain-of-thought is never requested or stored: no `thinking` block is asked for, and the only
  reasoning captured is the model's own `rationale` field (instructed to be 1–3 sentences), which
  is what's stored in `AgentDecision.rationale_summary`.
- Stub-only execution is uniform across all 5 tools this milestone: every decision writes an
  `AgentDecision` + one `Action` row (`status=pending`) and nothing else — no `Message`,
  `FollowupSchedule`, or `EscalationEvent` rows, no `Lead.status` change, regardless of which
  tool was chosen. The one field updated directly is `Lead.current_intent`, since classification
  isn't one of the 5 tools — it's the agent's classification output, already modeled as plain
  `Lead` state in DESIGN.md.
- `decide_next_action` is wired into `POST /leads` only (`trigger_event="lead_created"`),
  matching DESIGN.md §2's core loop ("a lead is submitted → the agent reads context and decides
  an action"). No reply endpoint or scheduler trigger yet — those are later milestones.
- Resilience: `decide_next_action` never raises. Client/validation failures are caught internally
  and persisted as an `AgentDecision` with `decision="invalid_output"`; the router also wraps the
  call in a broad `try/except` as a second line of defense. Verified this contract holds all the
  way through the live endpoint, not just in the unit function.
- Automated tests never hit the real Anthropic API: the `client` test fixture defaults the agent
  client override to one that fails immediately and offline
  (`tests/fakes.py::always_fails`), so all 9 Milestone 1 tests keep passing unmodified. Tests
  specific to agent behavior reconfigure a mutable holder fixture per test.

**Issues hit and fixed during implementation**
- **Uncaught `TypeError` from missing credentials**: caught by the manual smoke test, not by the
  automated suite. When no Anthropic credentials resolve at all (no `ANTHROPIC_API_KEY`, no `ant`
  profile), the SDK raises a plain `TypeError` from header validation *before* attempting any
  request — not an `anthropic.APIError` subclass. `AnthropicAgentClient.decide` only caught
  `anthropic.APIError`, so this specific failure mode propagated past `decide_next_action`'s own
  exception handling entirely; only the router's second-line `try/except` caught it, and no
  `AgentDecision` row got written — the audit trail silently lost that failure. Fixed by also
  catching `TypeError` in the client and normalizing it to `AgentDecisionError` like every other
  failure mode. Added a regression test using the real `AnthropicAgentClient` (safe/offline,
  since this specific error fires before any network call) so this doesn't require a live smoke
  test to catch again.
- **`scripts/seed.py`'s cleanup broke once leads had child rows beyond `messages`**: the reset
  step used `db.query(Model).delete()` (a bulk SQL `DELETE`), which does not go through the ORM
  identity map — so `Lead`'s `cascade="all, delete-orphan"` relationships (covering
  `agent_decisions`, `actions`, etc.) never fired. It happened to work in Milestone 1 because no
  lead had rows in any FK-dependent table besides `messages` (deleted first, manually). Once
  Milestone 2 started writing `AgentDecision`/`Action` rows, `db.query(Lead).delete()` started
  failing with a `ForeignKeyViolation`. Fixed by loading and `db.delete()`-ing each `Lead`
  instance instead, which does honor the ORM cascade — and stays correct automatically as more
  child tables get populated in later milestones, instead of needing the delete order maintained
  by hand.

**Verification**
- `pytest`: 20/20 passing (9 from Milestone 1, unmodified, + 11 new: classification, 5x valid
  action selection, 3x malformed output, agent-failure resilience through the live endpoint, and
  a regression test for the missing-credentials bug above) — all against real Postgres, no
  network calls.
- Manual smoke test: ran `uvicorn` against the dev database with no `ANTHROPIC_API_KEY`
  configured, `POST /leads` via `curl` — confirmed the lead is still created (201) and, after the
  fix above, that the failure is correctly recorded as an `AgentDecision` row (verified by
  querying the dev DB directly). This is what surfaced both issues above; neither was caught by
  the fake-client test suite alone.

## Milestone 3 — real tool execution, scheduler, guardrails

**Stack/design decisions**
- Guardrails split into two layers, matching DESIGN.md §8's own split between "never depend on
  the model" and rate/cap/lock enforcement:
  - **Pre-LLM overrides** (`app/agent/guardrails.py::check_pre_llm_override`), run at the top of
    `decide_next_action` before any API call: keyword-matched unsubscribe/escalation phrases
    (plus profanity, via the `better-profanity` package rather than a hand-maintained word list —
    avoids embedding a slur list in a public portfolio repo) force the corresponding tool call
    directly; a per-lead decision-count budget (≥6) also forces escalation regardless of message
    content, as a runaway-loop safety net that only gets real teeth this milestone now that the
    scheduler makes repeat triggers per lead possible.
  - **Execution-time guardrails** (`check_execution_guardrail`), run in `execute_action`: only
    `send_followup_email` has any, per DESIGN.md §7's table — escalation/unsubscribe lock, 24h
    cooldown, and a hard cap of 3 automated sends. A blocked action is marked
    `status=failed` with the reason in its payload, not silently dropped.
- Forced escalations (both the pre-LLM bypass and the hard-cap case) are persisted as full
  `AgentDecision`+`Action` pairs (`model_used=None`), not bare side effects — reuses the same
  `_persist_decision` helper as a normal model-produced decision, so DESIGN.md's "full audit
  trail of agent decisions" holds for guardrail-forced actions too.
- `execute_action` (`app/agent/execution.py`) applies the real per-tool effect now that
  Milestone 2's stub boundary is lifted: outbound `Message` for sends, `FollowupSchedule` rows,
  actual `Lead.status` writes, `EscalationEvent` rows. It's idempotent by construction — a no-op
  if the `Action` isn't `pending` — which is what DESIGN.md §8 means by "dedupe by decision_id".
- `app/agent/core.py` gained `handle_trigger` (decide + execute, unified error handling) so the
  two trigger sources (the lead-creation endpoint and the new scheduler) share one code path
  instead of duplicating the wiring; `app/routers/leads.py` now calls it instead of
  `decide_next_action` directly.
- The scheduler (`app/agent/followups.py::process_due_followups` + `scripts/run_scheduler.py`) is
  a separate process, deliberately **not** wired into FastAPI's lifespan — `tests/conftest.py`'s
  `client` fixture already runs `TestClient(app)` (which triggers app lifespan) on every one of
  ~30 tests; a background poller hooked into that lifespan would start a real polling thread on
  every test run. A plain `while True: process(); sleep(interval)` loop was used instead of
  APScheduler — DESIGN.md §3 names both as equally acceptable, and a single periodic function
  doesn't need a scheduling library.
- `FollowupSchedule.status` is flipped to `fired` *before* processing (not after), so a crash
  mid-batch can't cause the same followup to be reprocessed (and re-trigger the agent) on the
  next poll.
- Two Milestone 2 tests explicitly encoded the "stub-only" invariant Milestone 2 deliberately
  imposed (`no tool produces a real side effect`) — updating them to reflect Milestone 3's actual
  behavior is expected test evolution, not a regression: `test_valid_action_selection...` was
  renamed and its assertions changed from `Action.status == pending` / "no side-effect rows" to
  `Action.status == executed` (the real per-tool effect coverage now lives in the new
  `tests/test_execution.py`, so this test stays scoped to decision persistence).

**Verification**
- `pytest`: 44/44 passing (33 carried over + 11 new across `test_guardrails.py`,
  `test_execution.py`, `test_followups.py`), all against real Postgres, no network calls.
- Manual smoke test: `POST /leads` with an unsubscribe-phrase message against a live server with
  no `ANTHROPIC_API_KEY` configured — confirmed `lead.status` flipped to `unsubscribed` and the
  decision was recorded with `model_used=None`, proving the LLM was never called for this case.
  Also manually inserted a `FollowupSchedule` due in the near past and ran
  `scripts/run_scheduler.py` — confirmed it picked the followup up on its first poll, marked it
  `fired`, and produced an `AgentDecision` (which itself hit the already-known/expected
  missing-credentials failure path from Milestone 2, handled gracefully as designed).
