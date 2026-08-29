"""Deterministic guardrails around the agent (DESIGN.md §8). Two layers:

- Pre-LLM overrides (`check_pre_llm_override`): bypass the model entirely for
  compliance-critical cases, so those cases never depend on the model
  classifying correctly.
- Execution-time checks (`check_execution_guardrail`): can block a tool the
  model already chose, right before it would take effect.
"""

from datetime import datetime, timedelta, timezone

from better_profanity import profanity
from sqlalchemy.orm import Session

from app.agent.schemas import EscalateToHumanInput, ToolInputBase, UpdateLeadStatusInput
from app.models import Action, ActionStatus, AgentDecision, Lead, LeadIntent, LeadStatus, Message, MessageDirection

UNSUBSCRIBE_PHRASES = ["unsubscribe", "stop emailing", "remove me", "opt out", "opt-out", "take me off"]
ESCALATION_PHRASES = ["cancel", "lawsuit", "legal action", "speak to a human", "talk to a person", "talk to someone"]

MAX_AUTOMATED_FOLLOWUPS = 3
SEND_COOLDOWN = timedelta(hours=24)
MAX_DECISIONS_PER_LEAD = 6

# Triggers that carry a fresh inbound message worth scanning for keywords.
# followup_due does not - it would just re-scan whatever message was already
# there the last time this lead was looked at.
MESSAGE_DRIVEN_TRIGGERS = {"lead_created", "reply_received"}


def _contains_any(text: str, phrases: list[str]) -> bool:
    lowered = text.lower()
    return any(phrase in lowered for phrase in phrases)


def check_pre_llm_override(
    db: Session, lead: Lead, trigger_event: str, snapshot: dict
) -> tuple[str, ToolInputBase] | None:
    """Returns (tool_name, validated_input) if a deterministic rule should
    decide this event instead of calling the model, else None."""

    # Per-lead LLM call budget: independent of message content, applies to
    # every trigger type - a runaway-loop safety net.
    decision_count = db.query(AgentDecision).filter_by(lead_id=lead.id).count()
    if decision_count >= MAX_DECISIONS_PER_LEAD:
        return "escalate_to_human", EscalateToHumanInput(
            intent=lead.current_intent or LeadIntent.UNCLEAR,
            rationale=f"Per-lead decision budget ({MAX_DECISIONS_PER_LEAD}) reached; escalating for human review.",
            reason="Automated decision budget exceeded.",
        )

    # Keyword bypass: only meaningful when this trigger carries a fresh
    # inbound message to scan (see MESSAGE_DRIVEN_TRIGGERS above).
    if trigger_event in MESSAGE_DRIVEN_TRIGGERS and snapshot["messages"]:
        latest = snapshot["messages"][-1]["body"]
        if _contains_any(latest, UNSUBSCRIBE_PHRASES):
            return "update_lead_status", UpdateLeadStatusInput(
                intent=LeadIntent.UNSUBSCRIBE,
                rationale="Keyword match: message requested to stop receiving emails.",
                status=LeadStatus.UNSUBSCRIBED,
            )
        if _contains_any(latest, ESCALATION_PHRASES) or profanity.contains_profanity(latest):
            return "escalate_to_human", EscalateToHumanInput(
                intent=LeadIntent.OBJECTION,
                rationale="Keyword match: message content requires human judgment (escalation phrase or profanity).",
                reason="Deterministic escalation trigger matched in message content.",
            )

    return None


def check_execution_guardrail(db: Session, lead: Lead, action: Action) -> str | None:
    """Returns a block reason if `action` must not be executed, else None.
    Only send_followup_email has execution-time constraints per DESIGN.md §7 -
    schedule/status/escalate/log were already fully validated in Milestone 2."""
    if action.type != "send_followup_email":
        return None

    if lead.status in (LeadStatus.ESCALATED, LeadStatus.UNSUBSCRIBED):
        return "escalation_or_unsubscribe_lock"

    last_sent = (
        db.query(Message)
        .filter_by(lead_id=lead.id, direction=MessageDirection.OUT)
        .order_by(Message.created_at.desc())
        .first()
    )
    if last_sent is not None and (datetime.now(timezone.utc) - last_sent.created_at) < SEND_COOLDOWN:
        return "cooldown_24h"

    sent_count = (
        db.query(Action)
        .filter_by(lead_id=lead.id, type="send_followup_email", status=ActionStatus.EXECUTED)
        .count()
    )
    if sent_count >= MAX_AUTOMATED_FOLLOWUPS:
        return "hard_cap_reached"

    return None
