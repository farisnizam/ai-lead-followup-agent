"""Pydantic models for each tool's input. These are the single source of truth
for both the Anthropic tool `input_schema` (see tools.py) and the defensive
validation that runs on whatever the model returns (see core.py) - the same
schema is used to build the request and to check the response, so there's no
gap between what we asked for and what we accept."""

from pydantic import BaseModel, ConfigDict, Field

from app.models import LeadIntent, LeadStatus


class ToolInputBase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intent: LeadIntent = Field(description="Classified intent of the lead based on their messages.")
    rationale: str = Field(
        min_length=1,
        max_length=500,
        description="1-3 sentences on what you saw and why you chose this action. "
        "A concise summary for a human reviewer, not a step-by-step reasoning transcript.",
    )


class SendFollowupEmailInput(ToolInputBase):
    subject: str = Field(min_length=1, max_length=255)
    body: str = Field(min_length=1, max_length=5000)


class ScheduleFollowupInput(ToolInputBase):
    days_from_now: int = Field(ge=1, le=14, description="How many days from now to follow up.")
    reason: str = Field(min_length=1, max_length=255)


class UpdateLeadStatusInput(ToolInputBase):
    status: LeadStatus


class EscalateToHumanInput(ToolInputBase):
    reason: str = Field(min_length=1, max_length=255)


class LogNoteInput(ToolInputBase):
    note: str = Field(min_length=1, max_length=2000)


TOOL_REGISTRY: dict[str, type[ToolInputBase]] = {
    "send_followup_email": SendFollowupEmailInput,
    "schedule_followup": ScheduleFollowupInput,
    "update_lead_status": UpdateLeadStatusInput,
    "escalate_to_human": EscalateToHumanInput,
    "log_note": LogNoteInput,
}
