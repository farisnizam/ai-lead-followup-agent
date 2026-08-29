"""Server-rendered HTML pages (DESIGN.md §5). These query the DB directly
rather than going through the JSON API's response schemas - the JSON API
stays a minimal contract for programmatic use, while templates render ORM
objects (and their relationships) directly. Interactivity is small inline
fetch() calls to the JSON API followed by a page reload (see base.html) -
no SPA framework, no client-side state to keep in sync."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session, selectinload

from app.db import get_db
from app.models import FollowupStatus, Lead, Message, MessageDirection

router = APIRouter(tags=["pages"])
templates = Jinja2Templates(directory="templates")


@router.get("/")
def landing_page(request: Request):
    return templates.TemplateResponse(request, "landing.html", {})


@router.get("/dashboard")
def dashboard_page(request: Request, db: Session = Depends(get_db)):
    leads = db.query(Lead).order_by(Lead.created_at.desc()).all()
    return templates.TemplateResponse(request, "dashboard.html", {"leads": leads})


@router.get("/dashboard/{lead_id}")
def lead_detail_page(request: Request, lead_id: uuid.UUID, db: Session = Depends(get_db)):
    lead = (
        db.query(Lead)
        .options(
            selectinload(Lead.messages),
            selectinload(Lead.decisions),
            selectinload(Lead.actions),
            selectinload(Lead.followups),
            selectinload(Lead.escalations),
        )
        .filter(Lead.id == lead_id)
        .first()
    )
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead not found")

    next_followup = next(
        (
            f
            for f in sorted(lead.followups, key=lambda f: f.scheduled_for)
            if f.status == FollowupStatus.PENDING
        ),
        None,
    )
    open_escalation = next(
        (e for e in sorted(lead.escalations, key=lambda e: e.triggered_at, reverse=True) if e.resolved_at is None),
        None,
    )

    context = {
        "lead": lead,
        "messages": sorted(lead.messages, key=lambda m: m.created_at),
        "decisions": sorted(lead.decisions, key=lambda d: d.created_at, reverse=True),
        "actions": sorted(lead.actions, key=lambda a: a.created_at, reverse=True),
        "escalations": sorted(lead.escalations, key=lambda e: e.triggered_at, reverse=True),
        "next_followup": next_followup,
        "open_escalation": open_escalation,
    }
    return templates.TemplateResponse(request, "lead_detail.html", context)


@router.get("/outbox")
def outbox_page(request: Request, db: Session = Depends(get_db)):
    messages = (
        db.query(Message)
        .options(selectinload(Message.lead))
        .filter(Message.direction == MessageDirection.OUT)
        .order_by(Message.created_at.desc())
        .all()
    )
    return templates.TemplateResponse(request, "outbox.html", {"messages": messages})
