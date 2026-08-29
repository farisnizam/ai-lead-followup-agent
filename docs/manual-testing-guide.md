# Manual Testing Guide — All Agent Scenarios

A step-by-step walkthrough of every distinct decision path the agent/guardrail system can take.
15 scenarios in 5 categories. See [README.md](../README.md) for base setup — this assumes the
server is already running at `http://localhost:8001` with a working `ANTHROPIC_API_KEY` in `.env`.

**Cost note:** categories A, D, and E cost nothing (no LLM call involved). Categories B and C
need real API calls — a full pass through both is roughly 9–12 calls, well under a cent each (see
the cost breakdown discussed earlier — $5 covers hundreds of these). Category C uses a DB-seeding
shortcut to avoid burning calls just to reach a hard-to-reach state.

Run the Python snippets from the project root with the venv active:
```bash
source .venv/bin/activate
python -c "<snippet>"
```

---

## A. Pre-LLM deterministic bypass (4 scenarios)

These never call Claude — the guardrail matches before the agent is invoked. Free, instant,
100% repeatable. Submit each via the landing page (`/`) or:
```bash
curl -s -X POST localhost:8001/leads -H "Content-Type: application/json" \
  -d '{"name":"Test","email":"unique-email-here@example.com","message":"<message below>"}'
```

| # | Message to submit | Expect |
|---|---|---|
| A1 | "Please unsubscribe me from this list." | `status: unsubscribed`, decision log shows `update_lead_status`, `model_used: null` |
| A2 | "Cancel my account, I want to speak to a human." | `status: escalated`, decision log shows `escalate_to_human`, `model_used: null` |
| A3 | "This is a damn mess and I'm furious." | Same as A2 — profanity triggers the same bypass (uses the `better-profanity` package) |
| A4 | Any message, on a lead that already has 6+ decisions (see snippet below) | Forces `escalate_to_human` regardless of content |

**A4 setup** — seed 6 prior decisions on a lead, then submit a reply:
```python
from app.db import SessionLocal
from app.models import Lead, AgentDecision
db = SessionLocal()
lead = Lead(name="Budget Test", email="budget-test@example.com", status="new")
db.add(lead); db.commit(); db.refresh(lead)
for _ in range(6):
    db.add(AgentDecision(lead_id=lead.id, trigger_event="followup_due",
        input_snapshot={}, rationale_summary="seed", decision="log_note"))
db.commit()
print(lead.id)
```
Then `POST /leads/{that id}/messages` with any message body — check the decision log for
`"Per-lead decision budget (6) reached"`.

For A1–A3, check on the lead's detail page (`/dashboard/{id}`): decision `rationale` will say
"Keyword match: ..." and `model_used` will show as `—` (never called Claude).

---

## B. Real agent tool choices (5 scenarios, needs your API key)

Claude decides based on content — these prompts *nudge* toward each tool but aren't guaranteed
(that's the point: it's real judgment, not keyword matching). Submit via `/` or `POST /leads`.
Use a fresh email each time.

| # | Tool | Suggested message |
|---|---|---|
| B1 | `send_followup_email` | "Hi, I'm very interested — can you send me pricing for a team of 8?" |
| B2 | `schedule_followup` | "Sounds interesting, but I'm swamped this week. Check back with me in about a week?" |
| B3 | `update_lead_status` | "We've decided to go with a different vendor, but thanks for reaching out." |
| B4 | `escalate_to_human` | "Before I commit, I need someone to confirm you're SOC 2 compliant and can meet our legal review requirements." |
| B5 | `log_note` | "just browsing, not ready to talk yet" |

Check the lead detail page after each: decision log shows the tool chosen + a real rationale,
`model_used: claude-sonnet-5`, and the **Actions** table shows `status: executed` with the
real effect (B1 → new message in the thread and in `/outbox`; B2 → "next follow-up" badge
appears; B3 → status badge changes; B4 → escalation banner appears; B5 → no visible side effect,
just the decision log entry).

---

## C. Execution-time guardrails on sends (3 scenarios)

Only `send_followup_email` has these. All three block the *execution*, not the decision — the
agent can still choose to send, the guardrail stops it from actually happening.

**C1 — escalation/unsubscribe lock.** Escalate a lead first (curl or the UI's Escalate button),
then send a reply worded to elicit a send (e.g. B1's message). Check the Actions table: the
`send_followup_email` action shows `status: failed`, payload includes
`"blocked_reason": "escalation_or_unsubscribe_lock"`, and no new message appears in the thread.

**C2 — 24h cooldown.** Seed a fake recent send, then try to elicit another one:
```python
from app.db import SessionLocal
from app.models import Lead, Message, MessageDirection
db = SessionLocal()
lead = Lead(name="Cooldown Test", email="cooldown-test@example.com", status="contacted")
db.add(lead); db.commit(); db.refresh(lead)
db.add(Message(lead_id=lead.id, direction=MessageDirection.OUT, subject="s", body="prior send"))
db.commit()
print(lead.id)
```
Then `POST /leads/{that id}/messages` with B1's message. Expect `blocked_reason: "cooldown_24h"`.

**C3 — hard cap (3 sends) forces escalation.** Seed 3 already-executed sends, then trigger a 4th:
```python
from app.db import SessionLocal
from app.models import Lead, Action, ActionStatus
db = SessionLocal()
lead = Lead(name="Hard Cap Test", email="hardcap-test@example.com", status="contacted")
db.add(lead); db.commit(); db.refresh(lead)
for _ in range(3):
    db.add(Action(lead_id=lead.id, type="send_followup_email", payload={}, status=ActionStatus.EXECUTED))
db.commit()
print(lead.id)
```
`POST /leads/{that id}/messages` with B1's message (one real API call). Expect: the send is
blocked, **and** a new decision appears with `trigger_event: guardrail_hard_cap`,
`decision: escalate_to_human`, `model_used: null` — and the escalation banner appears. This is
the one case where a blocked action automatically produces a *second*, forced decision.

---

## D. Human-initiated actions (2 scenarios, free)

**D1 — Escalate.** On any non-escalated lead's detail page, use the "Escalate to a human" form.
Expect: status → `escalated`, an entry appears under Escalation history with your reason and no
`resolved_at`.

**D2 — Resolve.** On an escalated lead, use the "Resolve escalation" form (name + optional
notes). Expect: status → `contacted`, the escalation history entry now shows `resolved_at`,
`resolved_by`, and your notes, and the Escalate form reappears (no longer locked).

---

## E. Trigger types / resilience (2 scenarios)

**E1 — Scheduler.** After B2 (or any `schedule_followup` decision) gives a lead a pending
follow-up, run `python -m scripts.run_scheduler` in a second terminal and wait for the poll
interval (30s default). Expect: a new decision appears with `trigger_event: followup_due`, and
the follow-up badge disappears from the lead detail page (fired).

**E2 — Graceful degradation.** Temporarily blank `ANTHROPIC_API_KEY` in `.env`, restart uvicorn,
submit a lead. Expect: still `201`, lead still created, decision log shows `invalid_output` with
an auth-error rationale. Restore the key and restart again afterward.

---

## Cleanup

Test leads accumulate in the dev DB. Reset to the 5 sample leads at any point:
```bash
python -m scripts.seed
```
