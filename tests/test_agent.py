import uuid

import pytest

from app.agent.client import AgentDecisionError, AnthropicAgentClient
from app.models import (
    Action,
    ActionStatus,
    AgentDecision,
    EscalationEvent,
    FollowupSchedule,
    Lead,
    LeadIntent,
    LeadStatus,
    Message,
    MessageDirection,
)
from tests.fakes import FakeAgentClient


def test_classification_updates_lead_intent(client, fake_agent_client, db_session):
    fake_agent_client.current = FakeAgentClient(
        tool_name="log_note",
        tool_input={
            "intent": "objection",
            "rationale": "Lead pushed back on price before any pitch was made.",
            "note": "Pricing objection surfaced immediately.",
        },
    )

    resp = client.post(
        "/leads",
        json={"name": "Obj Lead", "email": "obj@example.com", "message": "That's too expensive."},
    )
    assert resp.status_code == 201
    lead_id = uuid.UUID(resp.json()["id"])

    lead = db_session.get(Lead, lead_id)
    assert lead.current_intent == LeadIntent.OBJECTION

    decision = db_session.query(AgentDecision).filter_by(lead_id=lead_id).one()
    assert decision.trigger_event == "lead_created"
    assert decision.input_snapshot["messages"] == [{"direction": "in", "body": "That's too expensive."}]


VALID_TOOL_CASES = [
    ("send_followup_email", {"intent": "interested", "rationale": "r", "subject": "Hi", "body": "Following up."}),
    ("schedule_followup", {"intent": "interested", "rationale": "r", "days_from_now": 3, "reason": "check back"}),
    ("update_lead_status", {"intent": "interested", "rationale": "r", "status": "qualified"}),
    ("escalate_to_human", {"intent": "objection", "rationale": "r", "reason": "needs human"}),
    ("log_note", {"intent": "unclear", "rationale": "r", "note": "note text"}),
]


@pytest.mark.parametrize("tool_name,tool_input", VALID_TOOL_CASES)
def test_valid_action_selection_creates_stub_action_only(
    client, fake_agent_client, db_session, tool_name, tool_input
):
    fake_agent_client.current = FakeAgentClient(tool_name=tool_name, tool_input=tool_input)

    resp = client.post(
        "/leads",
        json={"name": "Action Lead", "email": f"{tool_name}@example.com", "message": "hi"},
    )
    assert resp.status_code == 201
    lead_id = uuid.UUID(resp.json()["id"])

    action = db_session.query(Action).filter_by(lead_id=lead_id).one()
    assert action.type == tool_name
    assert action.status == ActionStatus.PENDING
    assert action.payload == {k: v for k, v in tool_input.items() if k not in ("intent", "rationale")}

    decision = db_session.query(AgentDecision).filter_by(lead_id=lead_id).one()
    assert decision.decision == tool_name
    assert decision.rationale_summary == "r"
    assert decision.model_used == "fake-model"

    # Stubbed/logged-only: no tool produces a real side effect this milestone,
    # regardless of which one the agent picked.
    lead = db_session.get(Lead, lead_id)
    assert lead.status == LeadStatus.NEW
    assert db_session.query(Message).filter_by(lead_id=lead_id, direction=MessageDirection.OUT).count() == 0
    assert db_session.query(FollowupSchedule).filter_by(lead_id=lead_id).count() == 0
    assert db_session.query(EscalationEvent).filter_by(lead_id=lead_id).count() == 0


MALFORMED_CASES = [
    ("unknown tool name", "not_a_real_tool", {"intent": "interested", "rationale": "r"}),
    (
        "out-of-window schedule",
        "schedule_followup",
        {"intent": "interested", "rationale": "r", "days_from_now": 999, "reason": "too far out"},
    ),
    (
        "missing required field",
        "send_followup_email",
        {"intent": "interested", "rationale": "r", "subject": "Hi"},
    ),
]


@pytest.mark.parametrize("case_name,tool_name,tool_input", MALFORMED_CASES, ids=[c[0] for c in MALFORMED_CASES])
def test_malformed_model_output_is_rejected_and_logged(
    client, fake_agent_client, db_session, case_name, tool_name, tool_input
):
    fake_agent_client.current = FakeAgentClient(tool_name=tool_name, tool_input=tool_input)

    resp = client.post(
        "/leads",
        json={"name": "Bad Output Lead", "email": f"bad-{hash(case_name)}@example.com", "message": "hi"},
    )
    assert resp.status_code == 201  # ingestion still succeeds
    lead_id = uuid.UUID(resp.json()["id"])

    decision = db_session.query(AgentDecision).filter_by(lead_id=lead_id).one()
    assert decision.decision == "invalid_output"
    assert decision.rationale_summary

    assert db_session.query(Action).filter_by(lead_id=lead_id).count() == 0
    lead = db_session.get(Lead, lead_id)
    assert lead.current_intent is None


def test_real_client_without_credentials_raises_agent_decision_error(monkeypatch):
    """Regression test: the Anthropic SDK raises a plain TypeError (not an
    anthropic.APIError subclass) when no credentials resolve at all, from
    header validation before any request is sent - so it's fast/offline and
    safe to run here. Caught live via a manual smoke test against the real
    client with no ANTHROPIC_API_KEY set; AnthropicAgentClient.decide must
    normalize it to AgentDecisionError like every other failure mode, or
    decide_next_action never gets a chance to log the failed decision."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("ANTHROPIC_PROFILE", raising=False)

    real_client = AnthropicAgentClient(api_key=None, model="claude-sonnet-5")
    with pytest.raises(AgentDecisionError):
        real_client.decide("test context")


def test_agent_client_failure_does_not_block_lead_creation(client, fake_agent_client, db_session):
    fake_agent_client.current = FakeAgentClient(error=AgentDecisionError("simulated auth failure"))

    resp = client.post(
        "/leads",
        json={"name": "Resilience Lead", "email": "resilience@example.com", "message": "hi"},
    )
    assert resp.status_code == 201
    lead_id = uuid.UUID(resp.json()["id"])

    decision = db_session.query(AgentDecision).filter_by(lead_id=lead_id).one()
    assert decision.decision == "invalid_output"
    assert "simulated auth failure" in decision.rationale_summary
    assert db_session.query(Action).filter_by(lead_id=lead_id).count() == 0
