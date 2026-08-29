# Current Status

_Last updated: 2026-08-29 — post-Milestone-4 bugfix (live API key verification)_

## Current Milestone

**Milestone 4 — UI: complete. Post-milestone bugfix (Anthropic strict-schema rejection): complete.**
Next up: Milestone 5 (optional buffer, per DESIGN.md §9) — polish, deploy, README/write-up, demo
GIF. V1 scope is otherwise functionally complete.

## Completed Work

- Milestones 1–3: data model/migrations, lead ingestion/CRUD API, agent core, real tool
  execution, scheduler, guardrails. (See prior entries for detail.)
- Server-rendered UI (`app/routers/pages.py` + `templates/` + `static/style.css`), per DESIGN.md
  §5: landing page (`/`), dashboard (`/dashboard`), lead detail (`/dashboard/{id}` — messages,
  status/intent/owner, next follow-up, decision log, action history, escalation history),
  simulate-reply form, escalate/resolve controls, mock outbox (`/outbox`)
- Two new backend gaps closed: `POST /leads/{id}/messages` (reply-ingestion, backs simulate-reply,
  `trigger_event="reply_received"`) and `POST /leads/{id}/escalate` /
  `POST /leads/{id}/resolve` (human-initiated escalation/resolution — `EscalationEvent`'s
  `resolved_at`/`resolved_by`/`resolution_notes` fields are now actually used)
- `guardrails.py`'s keyword-bypass gate generalized from a single trigger-name check to
  `MESSAGE_DRIVEN_TRIGGERS = {"lead_created", "reply_received"}`
- Test suite: 60/60 passing (57 carried over + 3 new in `test_tools.py`), real Postgres, no
  network calls
- Verified the real HTTP/HTML flow via `curl` (submit → dashboard → detail → resolve → reply →
  outbox) against a live server — see dev-log for what was checked and the one caveat below
- **A real `ANTHROPIC_API_KEY` was configured for the first time and the live path was exercised
  end-to-end.** This immediately surfaced a real bug: Anthropic's `strict: true` tool schemas
  reject `minimum`/`maximum` on integer properties, which Pydantic's `Field(ge=1, le=14, ...)` on
  `ScheduleFollowupInput.days_from_now` was emitting — breaking every decision call, not just
  `schedule_followup` ones. Fixed in `app/agent/tools.py` (strip those keys before sending to
  Anthropic; the Pydantic model itself is untouched, so our own response validation still
  enforces the 1–14 window). Re-verified live: a real lead now gets real classification, a
  genuinely drafted follow-up email, and a real executed send. See dev-log for full detail.

## Work In Progress

None — Milestone 4 closed out cleanly.

## Next Planned Steps (Milestone 5 — optional buffer, per DESIGN.md §9)

- Polish pass, guardrail tests review, deploy (Railway/Render/Fly.io), README + short design
  write-up, demo GIF
- Nothing functionally required by DESIGN.md's V1 scope remains unbuilt after this milestone

## Open Issues

None blocking. Noted for awareness, not urgent:
- `claude-in-chrome` was not connected in this environment, so Milestone 4's UI was verified via
  direct `curl`/HTML-content checks against a live server, not an actual browser click-through.
  Worth a real browser pass (or the demo GIF capture itself will serve as one) before calling V1
  fully demo-verified.
- `starlette.testclient` emits a deprecation warning about `httpx` vs `httpx2`; tests pass, no
  action needed yet.
- The Postgres dev container does not persist across host restarts/sessions in this environment —
  needed a manual `docker compose up -d db` again this milestone.
- `claude-in-chrome` still isn't connected in this environment — the real-browser click-through
  noted as outstanding at the end of Milestone 4 is still outstanding.

## Active Decisions / Constraints

- Sync FastAPI/SQLAlchemy, UUID primary keys, `VARCHAR`+`CHECK` enums, Claude Sonnet 5, module-
  constant guardrail thresholds — all unchanged from Milestones 1–3
- UI is server-rendered Jinja2 + plain `fetch()`-based JS, no SPA framework, no HTMX — pages query
  the DB directly rather than through the JSON API's response schemas, which stay a separate,
  minimal contract used by curl/pytest
- Resolving an escalation does not reset the hard-cap send counter (deliberately conservative —
  see dev-log); post-resolve status is fixed at `contacted`, not restored from any prior state
  (no "previous status" tracking exists or is planned)
- `Lead.metadata` implemented as `lead_metadata` in code — unchanged from Milestone 1
- Automated tests use a fake agent client exclusively; the real client is only exercised manually
- Scope discipline holds: no real SMTP, no auth/multi-tenant, no CRM integrations — see
  DESIGN.md §10 for the full V1 non-goals list
