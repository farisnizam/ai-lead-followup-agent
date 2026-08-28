"""Finds due follow-ups and fires the agent for each. The testable core of
the scheduler - scripts/run_scheduler.py is just a thin loop around this."""

import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.agent.client import AgentClient
from app.agent.core import handle_trigger
from app.models import AgentDecision, FollowupSchedule, FollowupStatus, Lead

logger = logging.getLogger(__name__)


def process_due_followups(db: Session, client: AgentClient) -> list[AgentDecision]:
    due = (
        db.query(FollowupSchedule)
        .filter(
            FollowupSchedule.status == FollowupStatus.PENDING,
            FollowupSchedule.scheduled_for <= datetime.now(timezone.utc),
        )
        .all()
    )

    decisions = []
    for followup in due:
        # Mark fired before processing - if something crashes mid-batch, a
        # restart won't reprocess (and re-trigger the agent for) this one.
        followup.status = FollowupStatus.FIRED
        db.commit()

        lead = db.get(Lead, followup.lead_id)
        try:
            decisions.append(handle_trigger(db, lead, trigger_event="followup_due", client=client))
        except Exception:
            logger.exception("Failed to process followup %s for lead %s", followup.id, lead.id)

    return decisions
