import uuid
from datetime import datetime, timedelta, timezone

from app.agent.core import handle_trigger
from app.agent.execution import execute_action
from app.models import (
    Action,
    ActionStatus,
    AgentDecision,
    EscalationEvent,
    FollowupSchedule,
    Lead,
    LeadStatus,
    Message,
    MessageDirection,
)
from tests.fakes import FakeAgentClient


def _make_lead(db_session, status=LeadStatus.NEW):
    lead = Lead(name="Exec Lead", email=f"exec-{uuid.uuid4()}@example.com", status=status)
    db_session.add(lead)
    db_session.commit()
    db_session.refresh(lead)
    return lead


def _make_decision(db_session, lead, tool_name, payload):
    decision = AgentDecision(
        lead_id=lead.id,
        trigger_event="lead_created",
        input_snapshot={},
        rationale_summary="r",
        decision=tool_name,
        model_used="fake-model",
    )
    db_session.add(decision)
    db_session.flush()
    action = Action(
        lead_id=lead.id, decision_id=decision.id, type=tool_name, payload=payload, status=ActionStatus.PENDING
    )
    db_session.add(action)
    db_session.commit()
    return decision, action


def test_send_followup_email_creates_outbound_message_and_bumps_status(db_session):
    lead = _make_lead(db_session)
    decision, _ = _make_decision(
        db_session, lead, "send_followup_email", {"subject": "Hi", "body": "Following up."}
    )

    executed = execute_action(db_session, decision)

    assert executed.status == ActionStatus.EXECUTED
    assert executed.executed_at is not None
    out_message = db_session.query(Message).filter_by(lead_id=lead.id, direction=MessageDirection.OUT).one()
    assert out_message.subject == "Hi"
    assert out_message.body == "Following up."
    db_session.refresh(lead)
    assert lead.status == LeadStatus.CONTACTED
    assert lead.last_contacted_at is not None


def test_schedule_followup_creates_followup_schedule(db_session):
    lead = _make_lead(db_session)
    decision, _ = _make_decision(
        db_session, lead, "schedule_followup", {"days_from_now": 5, "reason": "check back"}
    )

    executed = execute_action(db_session, decision)

    assert executed.status == ActionStatus.EXECUTED
    followup = db_session.query(FollowupSchedule).filter_by(lead_id=lead.id).one()
    assert followup.reason == "check back"
    expected = datetime.now(timezone.utc) + timedelta(days=5)
    assert abs((followup.scheduled_for - expected).total_seconds()) < 5


def test_update_lead_status_changes_status(db_session):
    lead = _make_lead(db_session)
    decision, _ = _make_decision(db_session, lead, "update_lead_status", {"status": "qualified"})

    executed = execute_action(db_session, decision)

    assert executed.status == ActionStatus.EXECUTED
    db_session.refresh(lead)
    assert lead.status == LeadStatus.QUALIFIED


def test_escalate_to_human_creates_escalation_event(db_session):
    lead = _make_lead(db_session)
    decision, _ = _make_decision(db_session, lead, "escalate_to_human", {"reason": "needs human"})

    executed = execute_action(db_session, decision)

    assert executed.status == ActionStatus.EXECUTED
    event = db_session.query(EscalationEvent).filter_by(lead_id=lead.id).one()
    assert event.reason == "needs human"
    db_session.refresh(lead)
    assert lead.status == LeadStatus.ESCALATED


def test_log_note_has_no_further_side_effect(db_session):
    lead = _make_lead(db_session)
    decision, _ = _make_decision(db_session, lead, "log_note", {"note": "internal note"})

    executed = execute_action(db_session, decision)

    assert executed.status == ActionStatus.EXECUTED
    db_session.refresh(lead)
    assert lead.status == LeadStatus.NEW
    assert db_session.query(Message).filter_by(lead_id=lead.id).count() == 0


def test_send_blocked_when_already_escalated(db_session):
    lead = _make_lead(db_session, status=LeadStatus.ESCALATED)
    decision, _ = _make_decision(db_session, lead, "send_followup_email", {"subject": "Hi", "body": "b"})

    executed = execute_action(db_session, decision)

    assert executed.status == ActionStatus.FAILED
    assert executed.payload["blocked_reason"] == "escalation_or_unsubscribe_lock"
    assert db_session.query(Message).filter_by(lead_id=lead.id, direction=MessageDirection.OUT).count() == 0


def test_send_blocked_within_cooldown(db_session):
    lead = _make_lead(db_session)
    db_session.add(Message(lead_id=lead.id, direction=MessageDirection.OUT, body="prior send", subject="s"))
    db_session.commit()
    decision, _ = _make_decision(db_session, lead, "send_followup_email", {"subject": "Hi", "body": "b"})

    executed = execute_action(db_session, decision)

    assert executed.status == ActionStatus.FAILED
    assert executed.payload["blocked_reason"] == "cooldown_24h"


def test_send_blocked_at_hard_cap(db_session):
    lead = _make_lead(db_session)
    for _ in range(3):
        db_session.add(
            Action(lead_id=lead.id, type="send_followup_email", payload={}, status=ActionStatus.EXECUTED)
        )
    db_session.commit()
    decision, _ = _make_decision(db_session, lead, "send_followup_email", {"subject": "Hi", "body": "b"})

    executed = execute_action(db_session, decision)

    assert executed.status == ActionStatus.FAILED
    assert executed.payload["blocked_reason"] == "hard_cap_reached"


def test_execute_action_is_idempotent(db_session):
    lead = _make_lead(db_session)
    decision, _ = _make_decision(db_session, lead, "send_followup_email", {"subject": "Hi", "body": "b"})

    execute_action(db_session, decision)
    execute_action(db_session, decision)  # second call must be a no-op

    count = db_session.query(Message).filter_by(lead_id=lead.id, direction=MessageDirection.OUT).count()
    assert count == 1


def test_hard_cap_forces_escalation_end_to_end(db_session):
    """Goes through handle_trigger (not just execute_action) to prove the
    blocked send is replaced with a real, persisted, executed escalation."""
    lead = _make_lead(db_session)
    for _ in range(3):
        db_session.add(
            Action(lead_id=lead.id, type="send_followup_email", payload={}, status=ActionStatus.EXECUTED)
        )
    db_session.commit()

    client = FakeAgentClient(
        tool_name="send_followup_email",
        tool_input={"intent": "interested", "rationale": "r", "subject": "Hi", "body": "Another email"},
    )

    decision = handle_trigger(db_session, lead, "followup_due", client)

    assert decision.decision == "escalate_to_human"
    assert decision.trigger_event == "guardrail_hard_cap"
    event = db_session.query(EscalationEvent).filter_by(lead_id=lead.id).one()
    assert event.reason == "Automated follow-up hard cap reached."
    db_session.refresh(lead)
    assert lead.status == LeadStatus.ESCALATED
