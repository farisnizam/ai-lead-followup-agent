import uuid
from datetime import datetime, timedelta, timezone

from app.agent.followups import process_due_followups
from app.models import FollowupSchedule, FollowupStatus, Lead, LeadStatus
from tests.fakes import FakeAgentClient


def _make_lead(db_session):
    lead = Lead(name="Followup Lead", email=f"followup-{uuid.uuid4()}@example.com", status=LeadStatus.ENGAGED)
    db_session.add(lead)
    db_session.commit()
    db_session.refresh(lead)
    return lead


def test_due_followup_is_processed(db_session):
    lead = _make_lead(db_session)
    followup = FollowupSchedule(
        lead_id=lead.id,
        scheduled_for=datetime.now(timezone.utc) - timedelta(minutes=5),
        reason="check back",
        status=FollowupStatus.PENDING,
    )
    db_session.add(followup)
    db_session.commit()

    client = FakeAgentClient(
        tool_name="log_note", tool_input={"intent": "interested", "rationale": "r", "note": "n"}
    )
    decisions = process_due_followups(db_session, client)

    assert len(decisions) == 1
    assert decisions[0].trigger_event == "followup_due"
    db_session.refresh(followup)
    assert followup.status == FollowupStatus.FIRED


def test_future_followup_is_not_processed(db_session):
    lead = _make_lead(db_session)
    followup = FollowupSchedule(
        lead_id=lead.id,
        scheduled_for=datetime.now(timezone.utc) + timedelta(days=1),
        reason="future",
        status=FollowupStatus.PENDING,
    )
    db_session.add(followup)
    db_session.commit()

    decisions = process_due_followups(db_session, FakeAgentClient())

    assert decisions == []
    db_session.refresh(followup)
    assert followup.status == FollowupStatus.PENDING


def test_already_fired_followup_is_ignored(db_session):
    lead = _make_lead(db_session)
    followup = FollowupSchedule(
        lead_id=lead.id,
        scheduled_for=datetime.now(timezone.utc) - timedelta(days=1),
        reason="old",
        status=FollowupStatus.FIRED,
    )
    db_session.add(followup)
    db_session.commit()

    decisions = process_due_followups(db_session, FakeAgentClient())

    assert decisions == []
