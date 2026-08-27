# Current Status

_Last updated: 2026-08-28 — end of Milestone 2_

## Current Milestone

**Milestone 2 — agent core: complete.**
Next up: Milestone 3 — real tool execution against the mock outbox, scheduler for time-based
follow-ups, guardrails (rate limits, keyword escalation, unsubscribe, escalation lock).

## Completed Work

- Milestone 1: project scaffolding, full 6-table schema/migrations, lead ingestion/CRUD API,
  seed data, initial test suite. (See prior entry below for detail.)
- Agent core (`app/agent/`): intent classification + one bounded next-action decision from the
  fixed 5-tool set (DESIGN.md §7), in a single structured Anthropic tool-use call
  (`tool_choice: {"type": "any"}`, `strict: true` schemas)
- Tool input schemas are Pydantic models (`app/agent/schemas.py`) — single source of truth for
  both the Anthropic `input_schema` and defensive re-validation of the model's response
- Every decision persists to `agent_decisions` with a concise `rationale_summary` (never raw
  chain-of-thought — no `thinking` block requested or stored)
- Tool execution is stubbed/logged-only this milestone: every decision writes one `Action` row
  (`status=pending`) and nothing else — no `Message`/`FollowupSchedule`/`EscalationEvent` rows,
  no `Lead.status` change, for any of the 5 tools. `Lead.current_intent` is updated directly
  (classification isn't tool-gated)
- `decide_next_action` wired into `POST /leads` (`trigger_event="lead_created"`) — the only
  trigger this milestone, per DESIGN.md §2's core loop
- Resilience: an agent failure (auth, network, malformed output) never blocks lead ingestion —
  verified through the live endpoint, not just the unit function
- Test suite: 20/20 passing (9 from Milestone 1 unmodified + 11 new), all against real Postgres,
  no network calls in the automated suite (fake agent client by default)
- Two real bugs found via manual smoke testing and fixed (see dev-log): a `TypeError` from
  missing credentials wasn't being normalized into the client's error type, so that failure mode
  skipped the audit trail; and `scripts/seed.py`'s cleanup broke once leads had child rows beyond
  `messages`, because bulk `Query.delete()` doesn't honor SQLAlchemy's ORM-level cascades

## Work In Progress

None — Milestone 2 closed out cleanly.

## Next Planned Steps (Milestone 3, per DESIGN.md §9)

- Turn `pending` Actions into real effects: `send_followup_email` writes an outbound `Message`,
  `schedule_followup` writes a `FollowupSchedule` row, `update_lead_status` actually updates
  `Lead.status`, `escalate_to_human` writes an `EscalationEvent`
- In-process scheduler polling `FollowupSchedule` for due follow-ups
- Guardrails: rate limiting/cooldown, hard cap on automated follow-ups, keyword-triggered
  deterministic escalation/unsubscribe (bypassing the LLM), escalation lock

## Open Issues

None blocking. Noted for awareness, not urgent:
- `starlette.testclient` emits a deprecation warning about `httpx` vs `httpx2`; tests pass, no
  action needed yet.
- No live Anthropic API call has been exercised in this environment (no `ANTHROPIC_API_KEY`
  configured) — the real `AnthropicAgentClient` code path is implemented and its failure mode is
  tested, but a successful real classification+decision hasn't been observed yet. Worth a manual
  check once a key is available.

## Active Decisions / Constraints

- Sync FastAPI/SQLAlchemy (not async); UUID primary keys throughout; enums stored as `VARCHAR` +
  `CHECK` (`native_enum=False`) — all from Milestone 1, unchanged
- Model: Claude Sonnet 5 (`claude-sonnet-5`), per DESIGN.md §3 — now actually wired in
  (`app/agent/client.py`), `output_config.effort="low"` (classification-type workload)
- One Claude API call per trigger event, not a multi-turn agent loop — matches DESIGN.md §10's
  "no unbounded multi-turn planning" non-goal
- Stub-only tool execution is deliberately uniform across all 5 tools in Milestone 2 — no
  exceptions for tools that would be "safe" to execute for real (e.g. `update_lead_status` is
  just a DB write); real execution is entirely Milestone 3's job
- Automated tests use a fake agent client exclusively (no cost, no network, deterministic);
  the real client is only exercised manually
- `Lead.metadata` (DESIGN.md) implemented as `lead_metadata` in code — unchanged from Milestone 1
- Scope discipline holds: no scheduler, real tool execution, guardrail enforcement, or UI built
  yet — see DESIGN.md §10 for the full V1 non-goals list
