# Current Status

_Last updated: 2026-08-28 — end of Milestone 3_

## Current Milestone

**Milestone 3 — real tool execution, scheduler, guardrails: complete.**
Next up: Milestone 4 — UI (landing page, dashboard, lead detail, simulate-reply, mock outbox
view, escalate/resolve controls).

## Completed Work

- Milestones 1–2: data model/migrations, lead ingestion/CRUD API, agent core (classification +
  bounded decision via structured Claude tool-use), seed data. (See prior entries for detail.)
- Tools now actually execute (`app/agent/execution.py::execute_action`), within V1's mock-outbox
  boundaries: `send_followup_email` writes an outbound `Message` and bumps `new`→`contacted`;
  `schedule_followup` writes a `FollowupSchedule`; `update_lead_status` writes `Lead.status`;
  `escalate_to_human` writes an `EscalationEvent` and sets `status=escalated`; `log_note` has no
  further effect. Idempotent by construction (no-op on a non-`pending` Action).
- Guardrails (`app/agent/guardrails.py`), matching DESIGN.md §8:
  - Pre-LLM: unsubscribe/escalation keyword phrases + profanity (`better-profanity`) bypass the
    model entirely; a per-lead decision-count budget (≥6) also forces escalation
  - Execution-time (only `send_followup_email` has any, per §7): escalation/unsubscribe lock,
    24h send cooldown, hard cap of 3 automated sends (which forces a real escalation, persisted
    as its own `AgentDecision`+`Action`, not a bare side effect)
- `app/agent/core.py::handle_trigger` unifies decide+execute for both trigger sources
- Scheduler: `app/agent/followups.py::process_due_followups` (testable core) +
  `scripts/run_scheduler.py` (thin polling-loop entrypoint, run as a separate process — see
  dev-log for why it's not in FastAPI's lifespan)
- Test suite: 44/44 passing (33 carried over + 11 new), real Postgres, no network calls
- Manual smoke tests (live server + live scheduler process) confirmed the unsubscribe bypass
  flips `lead.status` with zero LLM calls, and the scheduler picks up a due followup, marks it
  `fired`, and triggers the agent within one poll cycle

## Work In Progress

None — Milestone 3 closed out cleanly.

## Next Planned Steps (Milestone 4, per DESIGN.md §9)

- Server-rendered UI (FastAPI + Jinja2, per DESIGN.md §3): landing page (lead form), dashboard,
  lead detail (messages/status/decisions/actions), simulate-reply control, mock outbox view
  (filtered `Message` view, `direction=out`), escalate/resolve controls
- A reply-ingestion endpoint backing the simulate-reply control — note: the keyword-bypass check
  in `guardrails.py` is currently gated to `trigger_event == "lead_created"` specifically to
  avoid re-scanning old messages on every `followup_due` firing; adding a reply trigger needs its
  own equivalent gate (flagged in code comments)

## Open Issues

None blocking. Noted for awareness, not urgent:
- `starlette.testclient` emits a deprecation warning about `httpx` vs `httpx2`; tests pass, no
  action needed yet.
- No live Anthropic API call has been exercised in this environment (no `ANTHROPIC_API_KEY`
  configured) — real classification/decision and real guardrail fallthrough-to-LLM paths are
  implemented and covered by fake-client tests, but never observed against the real API. Worth a
  manual check once a key is available.
- The Postgres dev container (`docker compose`) does not persist across host restarts/sessions in
  this environment — needed a manual `docker compose up -d db` at the start of this milestone's
  work. Not a code issue, just an environment note for next time.

## Active Decisions / Constraints

- Sync FastAPI/SQLAlchemy, UUID primary keys, `VARCHAR`+`CHECK` enums, Claude Sonnet 5 — all
  unchanged from Milestones 1–2
- One Claude API call per trigger event, still no multi-turn agent loop (DESIGN.md §10)
- Scheduler runs as its own process (`scripts/run_scheduler.py`), not inside the API server
  process — a deliberate deviation from "in-process" in DESIGN.md §3's literal wording, kept for
  test-isolation reasons (see dev-log); the "no Celery/Redis, simple polling" intent is preserved
- Guardrail thresholds (3 sends, 24h cooldown, 6-decision budget) are plain module constants in
  `guardrails.py`, not runtime `Settings` — DESIGN.md gives them as fixed example numbers, not
  something meant to be reconfigured per deployment
- `Lead.metadata` implemented as `lead_metadata` in code — unchanged from Milestone 1
- Automated tests use a fake agent client exclusively; the real client is only exercised manually
- Scope discipline holds: no UI, no reply-ingestion endpoint, no real SMTP — see DESIGN.md §10
