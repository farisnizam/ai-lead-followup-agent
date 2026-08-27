import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum as SAEnum, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


def str_enum(python_enum: type[enum.Enum], **kwargs):
    """Enum stored as VARCHAR + CHECK constraint (not a native Postgres enum type),
    so adding/removing values later is a plain migration, not an ALTER TYPE dance."""
    return SAEnum(python_enum, native_enum=False, values_callable=lambda e: [m.value for m in e], **kwargs)


class LeadStatus(str, enum.Enum):
    NEW = "new"
    CONTACTED = "contacted"
    ENGAGED = "engaged"
    QUALIFIED = "qualified"
    ESCALATED = "escalated"
    CLOSED_WON = "closed_won"
    CLOSED_LOST = "closed_lost"
    UNSUBSCRIBED = "unsubscribed"


class LeadIntent(str, enum.Enum):
    INTERESTED = "interested"
    QUESTION = "question"
    OBJECTION = "objection"
    PRICING = "pricing"
    NOT_INTERESTED = "not_interested"
    UNSUBSCRIBE = "unsubscribe"
    SPAM = "spam"
    UNCLEAR = "unclear"


class MessageDirection(str, enum.Enum):
    IN = "in"
    OUT = "out"


class MessageSentBy(str, enum.Enum):
    AGENT = "agent"
    HUMAN = "human"


class MessageStatus(str, enum.Enum):
    QUEUED = "queued"
    SENT = "sent"
    FAILED = "failed"


class ActionStatus(str, enum.Enum):
    PENDING = "pending"
    EXECUTED = "executed"
    FAILED = "failed"


class FollowupStatus(str, enum.Enum):
    PENDING = "pending"
    CANCELLED = "cancelled"
    FIRED = "fired"


class Lead(Base):
    __tablename__ = "leads"

    id: Mapped[uuid.UUID] = _uuid_pk()
    name: Mapped[str] = mapped_column(String(255))
    email: Mapped[str] = mapped_column(String(255), index=True)
    source: Mapped[str | None] = mapped_column(String(100), nullable=True)
    status: Mapped[LeadStatus] = mapped_column(str_enum(LeadStatus), default=LeadStatus.NEW, nullable=False)
    current_intent: Mapped[LeadIntent | None] = mapped_column(str_enum(LeadIntent), nullable=True)
    owner: Mapped[str] = mapped_column(String(100), default="agent", nullable=False)
    last_contacted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_followup_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lead_metadata: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    messages: Mapped[list["Message"]] = relationship(back_populates="lead", cascade="all, delete-orphan")
    decisions: Mapped[list["AgentDecision"]] = relationship(back_populates="lead", cascade="all, delete-orphan")
    actions: Mapped[list["Action"]] = relationship(back_populates="lead", cascade="all, delete-orphan")
    followups: Mapped[list["FollowupSchedule"]] = relationship(back_populates="lead", cascade="all, delete-orphan")
    escalations: Mapped[list["EscalationEvent"]] = relationship(back_populates="lead", cascade="all, delete-orphan")


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[uuid.UUID] = _uuid_pk()
    lead_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("leads.id"), nullable=False)
    direction: Mapped[MessageDirection] = mapped_column(str_enum(MessageDirection), nullable=False)
    subject: Mapped[str | None] = mapped_column(String(255), nullable=True)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    sent_by: Mapped[MessageSentBy | None] = mapped_column(str_enum(MessageSentBy), nullable=True)
    status: Mapped[MessageStatus | None] = mapped_column(str_enum(MessageStatus), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    lead: Mapped["Lead"] = relationship(back_populates="messages")


class AgentDecision(Base):
    __tablename__ = "agent_decisions"

    id: Mapped[uuid.UUID] = _uuid_pk()
    lead_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("leads.id"), nullable=False)
    trigger_event: Mapped[str] = mapped_column(String(100), nullable=False)
    input_snapshot: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    rationale_summary: Mapped[str] = mapped_column(Text, nullable=False)
    decision: Mapped[str] = mapped_column(String(100), nullable=False)
    model_used: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    lead: Mapped["Lead"] = relationship(back_populates="decisions")
    actions: Mapped[list["Action"]] = relationship(back_populates="decision")


class Action(Base):
    __tablename__ = "actions"

    id: Mapped[uuid.UUID] = _uuid_pk()
    lead_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("leads.id"), nullable=False)
    decision_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_decisions.id"), nullable=True
    )
    type: Mapped[str] = mapped_column(String(100), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    status: Mapped[ActionStatus] = mapped_column(str_enum(ActionStatus), default=ActionStatus.PENDING, nullable=False)
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    lead: Mapped["Lead"] = relationship(back_populates="actions")
    decision: Mapped["AgentDecision | None"] = relationship(back_populates="actions")


class FollowupSchedule(Base):
    __tablename__ = "followup_schedules"

    id: Mapped[uuid.UUID] = _uuid_pk()
    lead_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("leads.id"), nullable=False)
    scheduled_for: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[FollowupStatus] = mapped_column(
        str_enum(FollowupStatus), default=FollowupStatus.PENDING, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    lead: Mapped["Lead"] = relationship(back_populates="followups")


class EscalationEvent(Base):
    __tablename__ = "escalation_events"

    id: Mapped[uuid.UUID] = _uuid_pk()
    lead_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("leads.id"), nullable=False)
    reason: Mapped[str] = mapped_column(String(255), nullable=False)
    triggered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    resolution_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    lead: Mapped["Lead"] = relationship(back_populates="escalations")
