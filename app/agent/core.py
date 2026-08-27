"""Orchestrates one agent decision: build context, call the model, validate
the result, persist the outcome. Never raises - a failure at any stage is
recorded as an AgentDecision with decision="invalid_output" rather than
propagated, so a broken agent call never breaks the caller (see
routers/leads.py)."""

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.agent.client import AgentClient, AgentDecisionError, ToolDecision
from app.agent.prompts import render_lead_context
from app.agent.schemas import TOOL_REGISTRY, ToolInputBase
from app.models import Action, ActionStatus, AgentDecision, Lead


class InvalidToolCallError(ValueError):
    """Raised when the model names a tool outside the fixed set (§7)."""


def _build_snapshot(lead: Lead) -> dict:
    return {
        "lead_id": str(lead.id),
        "status": lead.status.value,
        "current_intent": lead.current_intent.value if lead.current_intent else None,
        "messages": [
            {"direction": m.direction.value, "body": m.body}
            for m in sorted(lead.messages, key=lambda m: m.created_at)
        ],
    }


def _validate_tool_call(tool_name: str, tool_input: dict) -> ToolInputBase:
    model = TOOL_REGISTRY.get(tool_name)
    if model is None:
        raise InvalidToolCallError(f"Unknown tool: {tool_name!r}")
    return model.model_validate(tool_input)


def decide_next_action(db: Session, lead: Lead, trigger_event: str, client: AgentClient) -> AgentDecision:
    input_snapshot = _build_snapshot(lead)

    try:
        result: ToolDecision = client.decide(
            render_lead_context(
                lead.name,
                lead.status.value,
                lead.current_intent.value if lead.current_intent else None,
                input_snapshot["messages"],
            )
        )
        validated = _validate_tool_call(result.tool_name, result.tool_input)
    except (AgentDecisionError, ValidationError, InvalidToolCallError) as exc:
        decision = AgentDecision(
            lead_id=lead.id,
            trigger_event=trigger_event,
            input_snapshot=input_snapshot,
            rationale_summary=f"Agent output rejected: {exc}",
            decision="invalid_output",
            model_used=None,
        )
        db.add(decision)
        db.commit()
        db.refresh(decision)
        return decision

    lead.current_intent = validated.intent
    decision = AgentDecision(
        lead_id=lead.id,
        trigger_event=trigger_event,
        input_snapshot=input_snapshot,
        rationale_summary=validated.rationale,
        decision=result.tool_name,
        model_used=result.model_used,
    )
    db.add(decision)
    db.flush()

    action = Action(
        lead_id=lead.id,
        decision_id=decision.id,
        type=result.tool_name,
        payload=validated.model_dump(exclude={"intent", "rationale"}, mode="json"),
        status=ActionStatus.PENDING,
    )
    db.add(action)
    db.commit()
    db.refresh(decision)
    return decision
