"""Orchestrates one agent decision: build context, check deterministic
guardrails, call the model if needed, validate the result, persist the
outcome, and (via handle_trigger) execute it. Neither decide_next_action nor
handle_trigger ever raises - failures are recorded as an AgentDecision
(decision="invalid_output") or logged, never propagated, so a broken agent
call or execution failure never breaks the caller (see routers/leads.py)."""

import logging

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.agent.client import AgentClient, AgentDecisionError, ToolDecision
from app.agent.execution import execute_action
from app.agent.guardrails import MAX_AUTOMATED_FOLLOWUPS, check_pre_llm_override
from app.agent.prompts import render_lead_context
from app.agent.schemas import TOOL_REGISTRY, EscalateToHumanInput, ToolInputBase
from app.models import Action, ActionStatus, AgentDecision, Lead, LeadIntent

logger = logging.getLogger(__name__)


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


def _persist_decision(
    db: Session,
    lead: Lead,
    trigger_event: str,
    input_snapshot: dict,
    tool_name: str,
    validated: ToolInputBase,
    model_used: str | None,
) -> AgentDecision:
    lead.current_intent = validated.intent
    decision = AgentDecision(
        lead_id=lead.id,
        trigger_event=trigger_event,
        input_snapshot=input_snapshot,
        rationale_summary=validated.rationale,
        decision=tool_name,
        model_used=model_used,
    )
    db.add(decision)
    db.flush()

    action = Action(
        lead_id=lead.id,
        decision_id=decision.id,
        type=tool_name,
        payload=validated.model_dump(exclude={"intent", "rationale"}, mode="json"),
        status=ActionStatus.PENDING,
    )
    db.add(action)
    db.commit()
    db.refresh(decision)
    return decision


def _persist_failure(
    db: Session, lead: Lead, trigger_event: str, input_snapshot: dict, message: str
) -> AgentDecision:
    decision = AgentDecision(
        lead_id=lead.id,
        trigger_event=trigger_event,
        input_snapshot=input_snapshot,
        rationale_summary=message,
        decision="invalid_output",
        model_used=None,
    )
    db.add(decision)
    db.commit()
    db.refresh(decision)
    return decision


def decide_next_action(db: Session, lead: Lead, trigger_event: str, client: AgentClient) -> AgentDecision:
    input_snapshot = _build_snapshot(lead)

    bypass = check_pre_llm_override(db, lead, trigger_event, input_snapshot)
    if bypass is not None:
        tool_name, validated = bypass
        return _persist_decision(db, lead, trigger_event, input_snapshot, tool_name, validated, model_used=None)

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
        return _persist_failure(db, lead, trigger_event, input_snapshot, f"Agent output rejected: {exc}")

    return _persist_decision(
        db, lead, trigger_event, input_snapshot, result.tool_name, validated, model_used=result.model_used
    )


def handle_trigger(db: Session, lead: Lead, trigger_event: str, client: AgentClient) -> AgentDecision:
    """Decide, then execute the resulting Action (if any). Never raises."""
    decision = decide_next_action(db, lead, trigger_event, client)
    if decision.decision == "invalid_output":
        return decision

    try:
        action = execute_action(db, decision)
        if (
            action is not None
            and action.status == ActionStatus.FAILED
            and action.payload.get("blocked_reason") == "hard_cap_reached"
        ):
            # DESIGN.md §8: hard cap is "before mandatory escalation" - the
            # blocked send is replaced with a forced escalation, persisted
            # and executed the same way any other decision is.
            escalation = _persist_decision(
                db,
                lead,
                "guardrail_hard_cap",
                _build_snapshot(lead),
                "escalate_to_human",
                EscalateToHumanInput(
                    intent=lead.current_intent or LeadIntent.UNCLEAR,
                    rationale=(
                        f"Automated follow-up hard cap ({MAX_AUTOMATED_FOLLOWUPS}) reached; "
                        "escalating instead of sending."
                    ),
                    reason="Automated follow-up hard cap reached.",
                ),
                model_used=None,
            )
            execute_action(db, escalation)
            return escalation
    except Exception:
        logger.exception("Action execution failed for lead %s, decision %s", lead.id, decision.id)

    return decision
