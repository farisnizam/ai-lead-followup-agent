# AI Lead Follow-up Agent — Design

## 1. Problem Statement

Sales teams lose leads not because leads are uninterested, but because follow-up is slow,
inconsistent, or forgotten. A rep has to read every inbound message, judge intent, decide what
to do next, and remember to circle back — work that is repetitive, time-sensitive, and easy to
drop at volume.

This project builds a small, production-minded system that automates that loop: it ingests
leads, reads their messages, classifies intent, decides the next best action, executes or
schedules that action, and hands off to a human when the situation calls for judgment the agent
shouldn't have. The goal is not "a chatbot that emails people" — it's a demonstration of how to
put an LLM inside a system with real boundaries: persistent state, a constrained action space,
deterministic guardrails around a non-deterministic component, and full auditability.

Built as a portfolio project for an Applied AI Engineer application, scoped to finish in a few
days and run entirely from a browser demo — no terminal commands required to exercise the full
workflow.

## 2. V1 Scope

**Core loop:** a lead is submitted → the agent reads context and decides an action → the action
is executed through a bounded tool → state and audit log are updated → later events (a reply, a
scheduled follow-up firing, a human takeover) re-trigger the loop.

**In scope:**
- Single channel: email (real SMS/voice adds compliance surface with no added signal for a demo)
- Lead intake via a landing-page form (backed by the API)
- Inbound replies via a "simulate reply" UI control (no real inbox integration needed to prove
  the concept)
- Agent classification + next-action decision from a fixed, small action set
- Time-based follow-up scheduling (e.g., no reply in 48h → nudge)
- Full audit trail of agent decisions and actions, viewable in the UI
- Human escalation: flag, queue, and takeover that pauses the agent
- A minimal browser UI so the entire workflow — submit lead, agent responds, reply as the lead,
  watch the agent re-decide, escalate, view outbox — is demoable without curl

**Explicitly a demo, not a SaaS**: single deployment, no multi-tenant auth, one "org," one demo
inbox.

## 3. Architecture

```
Browser (demo UI)
   │  landing page (lead form) · dashboard · lead detail · simulate-reply · mock outbox
   ▼
Backend API (FastAPI)
   │
   ├─▶ Postgres  (leads, messages, decisions, actions, followup schedule, escalations)
   │
   ├─▶ Agent Orchestrator (triggered per event: new lead / inbound reply / followup due)
   │        │
   │        ▼
   │   Claude API (tool use) — classify intent, decide action, draft message
   │        │
   │        ▼
   │   Bounded Tool Layer (plain Python functions)
   │   send_followup_email · schedule_followup · update_lead_status
   │   escalate_to_human · log_note
   │        │
   │        ▼
   │   Deterministic guardrails (keyword escalation, rate limits, unsubscribe,
   │   cooldowns) wrap every tool call before it executes
   │
   └─▶ Scheduler (in-process polling loop over the FollowupSchedule table) — fires due
        followups as events into the orchestrator
```

**Stack choice, and why:**
- **FastAPI + Postgres**, no Celery/Redis/Kafka — a single polling job (APScheduler or a simple
  loop) is sufficient at demo volume. The README should note the swap-in path to a real queue at
  scale rather than build it.
- **UI: server-rendered pages from the same FastAPI app** (Jinja2 templates, HTMX or small
  fetch-based JS for interactivity — e.g. "simulate reply," "resolve escalation") rather than a
  separate frontend app. One deployable, one process, no build pipeline to maintain — the right
  size for a few-day project. A separate SPA is a reasonable V2 direction, not needed here.
- **Model: Claude Sonnet 5** for the classify + decide step — it needs judgment, not just
  keyword matching. A cost cascade (e.g. Haiku 4.5 for easy cases) is a good "V2 idea" line in
  the README, not something to build now.
- **Mock outbox, not real delivery**: outbound email is written to the `Message` table
  (direction=out) and rendered in an "Outbox" UI view. No SMTP/SendGrid integration in V1 — it's
  one line to explain as the production swap-in, and it removes an entire category of
  deliverability/auth setup from the demo's critical path.

## 4. Data Model

- **Lead** — id, name, email, source, created_at, status
  (`new → contacted → engaged → qualified → escalated → closed_won/closed_lost → unsubscribed`),
  current_intent, last_contacted_at, next_followup_at, owner (`agent` / `human:{id}`),
  metadata (JSON: form fields, UTM, etc.)
- **Message** — id, lead_id, direction (`in`/`out`), body, subject, created_at, sent_by
  (`agent`/`human`), status (`queued`/`sent`/`failed`). Outbound messages are what the mock
  Outbox view lists; inbound messages are what the "simulate reply" control creates.
- **AgentDecision** (audit log) — id, lead_id, trigger_event, input_snapshot, **rationale
  summary** (2–4 sentences, not raw chain-of-thought), decision, model_used, created_at. This
  table is the core auditability feature — surfaced directly in the lead detail page.
- **Action** — id, lead_id, decision_id, type, payload, status (`pending`/`executed`/`failed`),
  executed_at
- **FollowupSchedule** — id, lead_id, scheduled_for, reason, status
  (`pending`/`cancelled`/`fired`)
- **EscalationEvent** — id, lead_id, reason, triggered_at, resolved_at, resolved_by,
  resolution_notes

No separate "outbox" table — the outbox is a filtered view (`direction=out`) over `Message`,
avoiding a redundant model for something that's really just a read filter.

## 5. Main UI / Pages

A small set of server-rendered pages, enough to exercise the whole loop from a browser:

1. **Landing page** — public-facing lead submission form (name, email, message/interest). Posts
   to the ingestion API and triggers the agent's first decision.
2. **Lead dashboard** — table of all leads: name, status, current intent, owner (agent/human),
   next follow-up time, last activity. Entry point into each lead's detail page.
3. **Lead detail page** — the main demo surface for one lead:
   - message thread (inbound + outbound, chronological)
   - current status / intent / owner
   - next scheduled follow-up (if any)
   - agent decision log (trigger → rationale summary → action taken)
   - action history
   - escalate / resolve-escalation controls for the human-in-the-loop story
4. **Simulate inbound reply** — a form (on the lead detail page) to post a reply "as the lead,"
   re-triggering the agent — this is what makes the agent's reactive behavior demoable without a
   terminal.
5. **Mock outbox** — a simple list of all outbound emails across leads (subject, recipient, body,
   sent_at), so generated messages can be inspected without real email delivery.

## 6. Agent Responsibilities

The agent **decides**, it never directly **acts** — every decision is executed through the
bounded tool layer (§7), never by the agent writing to state itself.

Responsibilities:
- Classify intent (`interested` / `question` / `objection` / `pricing` / `not-interested` /
  `unsubscribe` / `spam` / `unclear`)
- Draft outbound message content when the decision is to send
- Choose exactly one action from the fixed tool set per triggering event
- Produce a **concise rationale summary** (a few sentences: what it saw, why it chose this
  action) — this is what gets stored and shown, not a raw chain-of-thought dump. Keeps the audit
  log genuinely readable by a human reviewer and avoids storing/exposing raw model reasoning
  traces.

The agent never: writes to the database directly, selects its own tools, sees other leads' data,
or executes an action outside the tool layer's validation.

## 7. Tool / Action Boundaries

A small, closed toolset. Each tool is independently guardrailed — the agent choosing a tool is
not sufficient for it to run.

| Tool | Constraint |
|---|---|
| `send_followup_email(lead_id, subject, body)` | max 1 send / 24h / lead; blocked if lead is escalated or unsubscribed |
| `schedule_followup(lead_id, when, reason)` | window-bounded (1–14 days out) |
| `update_lead_status(lead_id, status)` | enum-constrained, no free text |
| `escalate_to_human(lead_id, reason)` | always allowed, never blocked by other guardrails |
| `log_note(lead_id, note)` | internal only, never sent to the lead |

Explicitly no tool for: deleting leads, SMS/voice, arbitrary code or SQL execution, or accessing
another lead's data.

## 8. Guardrails

- **Deterministic bypass of the LLM** for compliance-critical paths: keyword-triggered
  escalation ("cancel," "lawsuit," "speak to a human," profanity) and unsubscribe handling never
  depend on the model classifying correctly.
- **Rate limiting / cooldown** per lead to prevent send loops.
- **Hard cap on automated follow-ups** (e.g. 3) before mandatory escalation.
- **Escalation lock**: once escalated, `send_followup_email` is blocked for that lead until a
  human resolves the escalation.
- **Prompt-injection awareness**: inbound lead text is treated as untrusted data, never as
  instructions to the agent — worth calling out explicitly since leads fully control that text.
- **Tool-call schema validation** before execution; malformed calls are rejected and logged, not
  silently retried.
- **Idempotent action execution** (dedupe by decision_id) so retries/crashes can't double-send.
- **Per-lead LLM call budget** to cap runaway cost from any single lead's event volume.

## 9. Implementation Milestones

1. **Day 1** — data model, migrations, ingestion API, seed data, basic lead CRUD
2. **Day 2** — agent core: classification + tool-call decision loop, full decision/rationale
   logging (tool execution can be stubbed/logged-only at this point)
3. **Day 3** — real tool execution against the mock outbox, scheduler for time-based follow-ups,
   guardrails (rate limits, keyword escalation, unsubscribe, escalation lock)
4. **Day 4** — UI: landing page, dashboard, lead detail (messages/status/decisions/actions),
   simulate-reply control, mock outbox view, escalate/resolve controls
5. **Day 5 (optional buffer)** — polish, guardrail tests, deploy (Railway/Render/Fly.io), README
   + short write-up of the design decisions, demo GIF

## 10. V1 Non-Goals

- Multi-channel (SMS, WhatsApp, voice)
- Real CRM integrations (Salesforce/HubSpot sync)
- Multi-tenant / auth / teams
- Fine-tuning or custom models
- RAG over a knowledge base
- A/B testing of message copy
- Real email delivery / deliverability concerns (SPF/DKIM, bounce handling) — mock outbox only
- Queue infrastructure (Celery/Redis/Kafka)
- Unbounded multi-turn agent planning — one decision per triggering event, not an open-ended
  agent loop
- Storing or exposing raw model chain-of-thought — only concise rationale summaries persist

## 11. Scaling Considerations

Not built in V1, but the design should make these swaps straightforward later — noted here so
scope decisions are traceable to a "why not now" rather than an oversight:

- **Follow-up scheduling**: in-process polling loop → a real scheduler/queue (e.g. Celery beat,
  a managed cron, or a durable workflow engine) once volume or reliability requirements exceed a
  single-process poll.
- **Email delivery**: mock outbox → SendGrid/SES with real deliverability handling (SPF/DKIM,
  bounce/complaint webhooks feeding back into lead status).
- **Multi-channel**: the tool-layer boundary (§7) is designed so a new channel is a new tool
  (`send_sms`, etc.), not a rearchitecture — intent classification and decision logic stay
  channel-agnostic.
- **Throughput**: the agent orchestrator is currently invoked synchronously per event; at volume
  this becomes a queue-consumed worker so ingestion isn't blocked on LLM latency.
- **Multi-tenancy**: would require scoping every table by org/workspace and moving auth from
  "none" to real accounts — deferred because it adds no signal to the core agent-design story
  this project is meant to demonstrate.
- **Cost**: a cascade (cheap model for clear-cut classification, Sonnet-tier for ambiguous cases)
  is the first lever if per-lead LLM spend becomes a concern.
