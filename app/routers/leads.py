import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, selectinload

from app.agent.client import AgentClient, get_agent_client
from app.agent.core import handle_trigger
from app.db import get_db
from app.models import EscalationEvent, Lead, LeadStatus, Message, MessageDirection
from app.schemas import EscalateRequest, LeadCreate, LeadDetail, LeadRead, LeadUpdate, MessageCreate, ResolveRequest

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/leads", tags=["leads"])


@router.post("", response_model=LeadDetail, status_code=201)
def create_lead(
    payload: LeadCreate,
    db: Session = Depends(get_db),
    agent_client: AgentClient = Depends(get_agent_client),
) -> Lead:
    """Ingest a lead from the landing page form, recording its initial message
    as the first inbound Message so it appears in the same timeline later
    replies will use, then let the agent decide and execute the next action.

    Agent failures never fail lead ingestion: handle_trigger already catches
    its own failure modes and records them, but this still wraps the call as
    a second line of defense (e.g. against a DB error mid-decision) so a
    lead is never lost to an agent-side problem.
    """
    lead = Lead(name=payload.name, email=payload.email, source=payload.source)
    lead.messages.append(Message(direction=MessageDirection.IN, body=payload.message))
    db.add(lead)
    db.commit()
    db.refresh(lead)

    try:
        handle_trigger(db, lead, trigger_event="lead_created", client=agent_client)
        db.refresh(lead)
    except Exception:
        logger.exception("Agent decision failed for lead %s; lead was still created", lead.id)

    return lead


@router.get("", response_model=list[LeadRead])
def list_leads(db: Session = Depends(get_db)) -> list[Lead]:
    return list(db.query(Lead).order_by(Lead.created_at.desc()).all())


@router.get("/{lead_id}", response_model=LeadDetail)
def get_lead(lead_id: uuid.UUID, db: Session = Depends(get_db)) -> Lead:
    lead = (
        db.query(Lead)
        .options(selectinload(Lead.messages))
        .filter(Lead.id == lead_id)
        .first()
    )
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead not found")
    return lead


@router.patch("/{lead_id}", response_model=LeadRead)
def update_lead(lead_id: uuid.UUID, payload: LeadUpdate, db: Session = Depends(get_db)) -> Lead:
    lead = db.query(Lead).filter(Lead.id == lead_id).first()
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead not found")
    lead.status = payload.status
    db.commit()
    db.refresh(lead)
    return lead


def _get_lead_or_404(db: Session, lead_id: uuid.UUID) -> Lead:
    lead = db.query(Lead).filter(Lead.id == lead_id).first()
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead not found")
    return lead


@router.post("/{lead_id}/messages", response_model=LeadDetail, status_code=201)
def create_reply(
    lead_id: uuid.UUID,
    payload: MessageCreate,
    db: Session = Depends(get_db),
    agent_client: AgentClient = Depends(get_agent_client),
) -> Lead:
    """Simulate an inbound reply from the lead (the UI's "simulate reply"
    control), re-triggering the agent the same way a real reply would.
    Same resilience contract as create_lead: an agent failure never loses
    the reply itself.
    """
    lead = _get_lead_or_404(db, lead_id)
    lead.messages.append(Message(direction=MessageDirection.IN, body=payload.body))
    db.commit()
    db.refresh(lead)

    try:
        handle_trigger(db, lead, trigger_event="reply_received", client=agent_client)
        db.refresh(lead)
    except Exception:
        logger.exception("Agent decision failed for lead %s; reply was still recorded", lead.id)

    return lead


@router.post("/{lead_id}/escalate", response_model=LeadDetail, status_code=201)
def escalate_lead(lead_id: uuid.UUID, payload: EscalateRequest, db: Session = Depends(get_db)) -> Lead:
    """Human-initiated escalation - not an agent decision, so no
    AgentDecision/Action rows are written, just the EscalationEvent + status
    change those are for."""
    lead = _get_lead_or_404(db, lead_id)
    db.add(EscalationEvent(lead_id=lead.id, reason=payload.reason))
    lead.status = LeadStatus.ESCALATED
    db.commit()
    db.refresh(lead)
    return lead


@router.post("/{lead_id}/resolve", response_model=LeadDetail)
def resolve_escalation(lead_id: uuid.UUID, payload: ResolveRequest, db: Session = Depends(get_db)) -> Lead:
    lead = _get_lead_or_404(db, lead_id)
    open_escalation = (
        db.query(EscalationEvent)
        .filter(EscalationEvent.lead_id == lead.id, EscalationEvent.resolved_at.is_(None))
        .order_by(EscalationEvent.triggered_at.desc())
        .first()
    )
    if open_escalation is None:
        raise HTTPException(status_code=404, detail="No open escalation for this lead")

    open_escalation.resolved_at = datetime.now(timezone.utc)
    open_escalation.resolved_by = payload.resolved_by
    open_escalation.resolution_notes = payload.resolution_notes
    # Neutral post-resolution status - doesn't presume the outcome, and lifts
    # the escalation lock in check_execution_guardrail. Does not reset the
    # hard-cap send counter (deliberately conservative - see DESIGN notes).
    lead.status = LeadStatus.CONTACTED
    db.commit()
    db.refresh(lead)
    return lead
