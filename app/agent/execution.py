"""Turns a decided (but pending) Action into a real effect - within V1's
mock-outbox boundaries (DESIGN.md §3): no real SMTP, just the DB writes that
represent the effect. Subject to the execution-time guardrails in
guardrails.py. Idempotent by construction: re-running on an Action that
isn't `pending` is a no-op (DESIGN.md §8's "idempotent action execution...
dedupe by decision_id")."""

from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.agent.guardrails import check_execution_guardrail
from app.models import (
    Action,
    ActionStatus,
    AgentDecision,
    EscalationEvent,
    FollowupSchedule,
    FollowupStatus,
    Lead,
    LeadStatus,
    Message,
    MessageDirection,
    MessageSentBy,
    MessageStatus,
)


def _apply_effect(db: Session, lead: Lead, action: Action, now: datetime) -> None:
    payload = action.payload

    if action.type == "send_followup_email":
        db.add(
            Message(
                lead_id=lead.id,
                direction=MessageDirection.OUT,
                sent_by=MessageSentBy.AGENT,
                subject=payload["subject"],
                body=payload["body"],
                status=MessageStatus.SENT,
            )
        )
        lead.last_contacted_at = now
        if lead.status == LeadStatus.NEW:
            lead.status = LeadStatus.CONTACTED

    elif action.type == "schedule_followup":
        db.add(
            FollowupSchedule(
                lead_id=lead.id,
                scheduled_for=now + timedelta(days=payload["days_from_now"]),
                reason=payload["reason"],
                status=FollowupStatus.PENDING,
            )
        )

    elif action.type == "update_lead_status":
        lead.status = LeadStatus(payload["status"])

    elif action.type == "escalate_to_human":
        db.add(EscalationEvent(lead_id=lead.id, reason=payload["reason"]))
        lead.status = LeadStatus.ESCALATED

    elif action.type == "log_note":
        pass  # nothing further - the note already lives in Action.payload


def execute_action(db: Session, decision: AgentDecision) -> Action | None:
    action = db.query(Action).filter_by(decision_id=decision.id).one_or_none()
    if action is None or action.status != ActionStatus.PENDING:
        return action

    lead = db.get(Lead, action.lead_id)
    block_reason = check_execution_guardrail(db, lead, action)
    if block_reason is not None:
        action.status = ActionStatus.FAILED
        action.payload = {**action.payload, "blocked_reason": block_reason}
        db.commit()
        return action

    _apply_effect(db, lead, action, datetime.now(timezone.utc))
    action.status = ActionStatus.EXECUTED
    action.executed_at = datetime.now(timezone.utc)
    db.commit()
    return action
