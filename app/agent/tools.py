"""Builds Anthropic tool definitions from the Pydantic models in schemas.py -
see that module's docstring for why they're the single source of truth."""

from typing import Any

from app.agent.schemas import TOOL_REGISTRY

TOOL_DESCRIPTIONS: dict[str, str] = {
    "send_followup_email": "Send a follow-up email to the lead now.",
    "schedule_followup": "Schedule a follow-up check-in for later, without sending anything now.",
    "update_lead_status": "Update the lead's pipeline status.",
    "escalate_to_human": "Hand the lead off to a human for judgment the agent shouldn't make alone.",
    "log_note": "Record an internal note about the lead. Never sent to the lead.",
}


def _inline_refs(schema: dict[str, Any]) -> dict[str, Any]:
    """Pydantic emits enum fields as a $ref (or an allOf-wrapped $ref, when the
    field also carries a description) into $defs. Anthropic's strict tool
    schemas expect a flat object, so resolve those (shallow, one level) refs
    in place and drop $defs."""
    defs = schema.pop("$defs", {})
    if not defs:
        return schema

    def resolve(node: dict[str, Any]) -> dict[str, Any]:
        if "$ref" in node:
            ref_name = node["$ref"].rsplit("/", 1)[-1]
            resolved = dict(defs[ref_name])
            resolved.update({k: v for k, v in node.items() if k != "$ref"})
            return resolved
        if "allOf" in node and len(node["allOf"]) == 1 and "$ref" in node["allOf"][0]:
            ref_name = node["allOf"][0]["$ref"].rsplit("/", 1)[-1]
            resolved = dict(defs[ref_name])
            resolved.update({k: v for k, v in node.items() if k != "allOf"})
            return resolved
        return node

    schema["properties"] = {name: resolve(prop) for name, prop in schema["properties"].items()}
    return schema


def build_tool_definitions() -> list[dict[str, Any]]:
    tools = []
    for name, model in TOOL_REGISTRY.items():
        schema = _inline_refs(model.model_json_schema())
        tools.append(
            {
                "name": name,
                "description": TOOL_DESCRIPTIONS[name],
                "strict": True,
                "input_schema": schema,
            }
        )
    return tools
