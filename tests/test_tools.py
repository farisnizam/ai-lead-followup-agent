"""Regression coverage for the tool schemas actually sent to Anthropic.
Fast and offline - would have caught the minimum/maximum bug (see dev-log,
Milestone 4 postscript) before it ever reached a real API call."""

from app.agent.tools import build_tool_definitions


def _walk_schema_values(node):
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _walk_schema_values(value)
    elif isinstance(node, list):
        for item in node:
            yield from _walk_schema_values(item)


def test_tool_schemas_have_five_tools():
    tools = build_tool_definitions()
    assert {t["name"] for t in tools} == {
        "send_followup_email",
        "schedule_followup",
        "update_lead_status",
        "escalate_to_human",
        "log_note",
    }


def test_tool_schemas_are_strict():
    for tool in build_tool_definitions():
        assert tool["strict"] is True
        assert tool["input_schema"]["additionalProperties"] is False


def test_tool_schemas_never_send_minimum_or_maximum():
    """Anthropic's strict tool schemas reject minimum/maximum on integer
    properties - confirmed against the live API. Pydantic's Field(ge=, le=)
    still enforces the same bound on our side (see test_agent.py's
    out-of-window schedule case); this only governs what's sent to Anthropic."""
    for tool in build_tool_definitions():
        for node in _walk_schema_values(tool["input_schema"]):
            assert "minimum" not in node, f"{tool['name']} schema still sends 'minimum'"
            assert "maximum" not in node, f"{tool['name']} schema still sends 'maximum'"
