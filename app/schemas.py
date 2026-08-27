import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr

from app.models import LeadIntent, LeadStatus, MessageDirection, MessageSentBy, MessageStatus


class MessageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    direction: MessageDirection
    subject: str | None
    body: str
    sent_by: MessageSentBy | None
    status: MessageStatus | None
    created_at: datetime


class LeadCreate(BaseModel):
    name: str
    email: EmailStr
    source: str | None = None
    message: str


class LeadUpdate(BaseModel):
    status: LeadStatus


class LeadRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    email: str
    source: str | None
    status: LeadStatus
    current_intent: LeadIntent | None
    owner: str
    last_contacted_at: datetime | None
    next_followup_at: datetime | None
    created_at: datetime


class LeadDetail(LeadRead):
    messages: list[MessageRead] = []
