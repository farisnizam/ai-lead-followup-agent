from app.agent.client import AgentDecisionError, ToolDecision


class FakeAgentClient:
    """Deterministic, offline stand-in for AnthropicAgentClient. Configure
    either `error` (to simulate a client-level failure - auth, network,
    refusal, no tool call) or `tool_name`/`tool_input` (to simulate a
    response - deliberately malformed inputs are how tests exercise our own
    defensive validation in core.py, not just Anthropic's)."""

    def __init__(
        self,
        tool_name: str | None = None,
        tool_input: dict | None = None,
        error: Exception | None = None,
        model_used: str = "fake-model",
    ):
        self.tool_name = tool_name
        self.tool_input = tool_input or {}
        self.error = error
        self.model_used = model_used

    def decide(self, user_content: str) -> ToolDecision:
        if self.error is not None:
            raise self.error
        return ToolDecision(tool_name=self.tool_name, tool_input=self.tool_input, model_used=self.model_used)


def always_fails() -> FakeAgentClient:
    return FakeAgentClient(error=AgentDecisionError("no agent client configured for this test"))
