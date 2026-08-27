import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, selectinload

from app.db import get_db
from app.models import Lead, Message, MessageDirection
from app.schemas import LeadCreate, LeadDetail, LeadRead, LeadUpdate

router = APIRouter(prefix="/leads", tags=["leads"])


@router.post("", response_model=LeadDetail, status_code=201)
def create_lead(payload: LeadCreate, db: Session = Depends(get_db)) -> Lead:
    """Ingest a lead from the landing page form, recording its initial message
    as the first inbound Message so it appears in the same timeline later
    replies will use."""
    lead = Lead(name=payload.name, email=payload.email, source=payload.source)
    lead.messages.append(Message(direction=MessageDirection.IN, body=payload.message))
    db.add(lead)
    db.commit()
    db.refresh(lead)
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
