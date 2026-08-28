import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, selectinload

from app.agent.client import AgentClient, get_agent_client
from app.agent.core import handle_trigger
from app.db import get_db
from app.models import Lead, Message, MessageDirection
from app.schemas import LeadCreate, LeadDetail, LeadRead, LeadUpdate

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
