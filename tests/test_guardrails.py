from app.agent.guardrails import MAX_DECISIONS_PER_LEAD, check_execution_guardrail, check_pre_llm_override
from app.models import Action, ActionStatus, AgentDecision, Lead, LeadStatus, Message, MessageDirection


def _make_lead(db_session, message_body="hello", status=LeadStatus.NEW):
    lead = Lead(name="Guardrail Lead", email="guardrail-test@example.com", status=status)
    lead.messages.append(Message(direction=MessageDirection.IN, body=message_body))
    db_session.add(lead)
    db_session.commit()
    db_session.refresh(lead)
    return lead


def _snapshot(lead):
    return {"messages": [{"direction": "in", "body": m.body} for m in lead.messages]}


def test_unsubscribe_phrase_bypasses_llm(db_session):
    lead = _make_lead(db_session, message_body="Please unsubscribe me from this list.")
    result = check_pre_llm_override(db_session, lead, "lead_created", _snapshot(lead))
    assert result is not None
    tool_name, validated = result
    assert tool_name == "update_lead_status"
    assert validated.status.value == "unsubscribed"


def test_escalation_phrase_bypasses_llm(db_session):
    lead = _make_lead(db_session, message_body="I want to speak to a human about this.")
    result = check_pre_llm_override(db_session, lead, "lead_created", _snapshot(lead))
    assert result is not None
    assert result[0] == "escalate_to_human"


def test_profanity_bypasses_llm(db_session):
    lead = _make_lead(db_session, message_body="This is a damn mess and I'm furious about it.")
    result = check_pre_llm_override(db_session, lead, "lead_created", _snapshot(lead))
    assert result is not None
    assert result[0] == "escalate_to_human"


def test_benign_message_does_not_bypass(db_session):
    lead = _make_lead(db_session, message_body="I'd like to learn more about pricing.")
    result = check_pre_llm_override(db_session, lead, "lead_created", _snapshot(lead))
    assert result is None


def test_non_lead_created_trigger_does_not_scan_message(db_session):
    lead = _make_lead(db_session, message_body="unsubscribe me now")
    result = check_pre_llm_override(db_session, lead, "followup_due", _snapshot(lead))
    assert result is None


def test_decision_budget_forces_escalation(db_session):
    lead = _make_lead(db_session, message_body="hi")
    for _ in range(MAX_DECISIONS_PER_LEAD):
        db_session.add(
            AgentDecision(
                lead_id=lead.id,
                trigger_event="followup_due",
                input_snapshot={},
                rationale_summary="r",
                decision="log_note",
            )
        )
    db_session.commit()

    result = check_pre_llm_override(db_session, lead, "followup_due", _snapshot(lead))
    assert result is not None
    assert result[0] == "escalate_to_human"


def test_execution_guardrail_allows_send_by_default(db_session):
    lead = _make_lead(db_session)
    action = Action(lead_id=lead.id, type="send_followup_email", payload={}, status=ActionStatus.PENDING)
    db_session.add(action)
    db_session.commit()
    assert check_execution_guardrail(db_session, lead, action) is None


def test_execution_guardrail_ignores_non_send_tools(db_session):
    lead = _make_lead(db_session, status=LeadStatus.ESCALATED)
    action = Action(lead_id=lead.id, type="log_note", payload={}, status=ActionStatus.PENDING)
    db_session.add(action)
    db_session.commit()
    assert check_execution_guardrail(db_session, lead, action) is None


def test_execution_guardrail_blocks_when_escalated(db_session):
    lead = _make_lead(db_session, status=LeadStatus.ESCALATED)
    action = Action(lead_id=lead.id, type="send_followup_email", payload={}, status=ActionStatus.PENDING)
    db_session.add(action)
    db_session.commit()
    assert check_execution_guardrail(db_session, lead, action) == "escalation_or_unsubscribe_lock"


def test_execution_guardrail_blocks_within_cooldown(db_session):
    lead = _make_lead(db_session)
    db_session.add(Message(lead_id=lead.id, direction=MessageDirection.OUT, body="prior send", subject="s"))
    db_session.commit()
    action = Action(lead_id=lead.id, type="send_followup_email", payload={}, status=ActionStatus.PENDING)
    db_session.add(action)
    db_session.commit()
    assert check_execution_guardrail(db_session, lead, action) == "cooldown_24h"


def test_execution_guardrail_blocks_at_hard_cap(db_session):
    lead = _make_lead(db_session)
    for _ in range(3):
        db_session.add(
            Action(lead_id=lead.id, type="send_followup_email", payload={}, status=ActionStatus.EXECUTED)
        )
    db_session.commit()
    action = Action(lead_id=lead.id, type="send_followup_email", payload={}, status=ActionStatus.PENDING)
    db_session.add(action)
    db_session.commit()
    assert check_execution_guardrail(db_session, lead, action) == "hard_cap_reached"
