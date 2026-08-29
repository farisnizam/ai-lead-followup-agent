import uuid

from app.models import EscalationEvent, LeadStatus, Message, MessageDirection
from tests.fakes import FakeAgentClient


def _create_lead(client, email="actions-lead@example.com"):
    resp = client.post("/leads", json={"name": "Actions Lead", "email": email, "message": "hi"})
    assert resp.status_code == 201
    return resp.json()["id"]


def test_reply_creates_inbound_message_and_triggers_agent(client, fake_agent_client, db_session):
    lead_id = _create_lead(client, "reply-lead@example.com")

    fake_agent_client.current = FakeAgentClient(
        tool_name="log_note", tool_input={"intent": "interested", "rationale": "r", "note": "n"}
    )
    resp = client.post(f"/leads/{lead_id}/messages", json={"body": "Following up on my earlier note."})
    assert resp.status_code == 201

    lead_uuid = uuid.UUID(lead_id)
    messages = db_session.query(Message).filter_by(lead_id=lead_uuid, direction=MessageDirection.IN).all()
    assert len(messages) == 2  # initial + reply
    assert any(m.body == "Following up on my earlier note." for m in messages)

    decisions = resp.json()
    assert decisions["id"] == lead_id


def test_reply_on_unknown_lead_404s(client):
    resp = client.post(
        f"/leads/{uuid.uuid4()}/messages", json={"body": "hi"}
    )
    assert resp.status_code == 404


def test_escalate_creates_escalation_event_and_sets_status(client, db_session):
    lead_id = _create_lead(client, "escalate-lead@example.com")

    resp = client.post(f"/leads/{lead_id}/escalate", json={"reason": "Needs manual review."})
    assert resp.status_code == 201
    assert resp.json()["status"] == "escalated"

    event = db_session.query(EscalationEvent).filter_by(lead_id=uuid.UUID(lead_id)).one()
    assert event.reason == "Needs manual review."
    assert event.resolved_at is None


def test_escalate_on_unknown_lead_404s(client):
    resp = client.post(f"/leads/{uuid.uuid4()}/escalate", json={"reason": "x"})
    assert resp.status_code == 404


def test_resolve_clears_open_escalation_and_unblocks_status(client, db_session):
    lead_id = _create_lead(client, "resolve-lead@example.com")
    client.post(f"/leads/{lead_id}/escalate", json={"reason": "needs a human"})

    resp = client.post(
        f"/leads/{lead_id}/resolve", json={"resolved_by": "Jordan", "resolution_notes": "Handled by phone."}
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "contacted"

    event = db_session.query(EscalationEvent).filter_by(lead_id=uuid.UUID(lead_id)).one()
    assert event.resolved_at is not None
    assert event.resolved_by == "Jordan"
    assert event.resolution_notes == "Handled by phone."


def test_resolve_without_open_escalation_404s(client):
    lead_id = _create_lead(client, "no-escalation-lead@example.com")

    resp = client.post(f"/leads/{lead_id}/resolve", json={"resolved_by": "Jordan"})
    assert resp.status_code == 404


def test_resolve_on_unknown_lead_404s(client):
    resp = client.post(f"/leads/{uuid.uuid4()}/resolve", json={"resolved_by": "Jordan"})
    assert resp.status_code == 404
