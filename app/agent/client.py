"""Thin adapter over the Anthropic SDK. `decide_next_action` (core.py) only
ever sees a `ToolDecision` or an `AgentDecisionError` - never an Anthropic SDK
type - so tests can substitute a fake client without depending on the SDK,
and core.py's parsing logic doesn't need to know about API response
internals."""

from dataclasses import dataclass
from typing import Protocol

import anthropic

from app.agent.prompts import SYSTEM_PROMPT
from app.agent.tools import build_tool_definitions
from app.config import settings


@dataclass
class ToolDecision:
    tool_name: str
    tool_input: dict
    model_used: str


class AgentDecisionError(Exception):
    """Raised for any failure to get a usable tool call out of the model:
    API/auth/network errors, a refusal, or a response with no tool_use block.
    Callers (core.py) treat all of these the same way - log and degrade
    gracefully, never crash the caller."""


class AgentClient(Protocol):
    def decide(self, user_content: str) -> ToolDecision: ...


class AnthropicAgentClient:
    def __init__(self, api_key: str | None, model: str):
        self._client = anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()
        self._model = model
        self._tools = build_tool_definitions()

    def decide(self, user_content: str) -> ToolDecision:
        try:
            response = self._client.messages.create(
                model=self._model,
                max_tokens=1024,
                system=SYSTEM_PROMPT,
                tools=self._tools,
                tool_choice={"type": "any"},
                output_config={"effort": "low"},
                messages=[{"role": "user", "content": user_content}],
            )
        except (anthropic.APIError, TypeError) as exc:
            # anthropic.APIError covers request-time failures (auth rejected,
            # rate limit, network, ...). A plain TypeError is what the SDK
            # raises *before* a request is even attempted when no credentials
            # resolve at all (no API key configured) - just as much a "the
            # agent can't run right now" case, so it's normalized the same way.
            raise AgentDecisionError(f"Anthropic API call failed: {exc}") from exc

        if response.stop_reason == "refusal":
            category = getattr(response.stop_details, "category", None) if response.stop_details else None
            raise AgentDecisionError(f"Model refused to respond (category={category})")

        tool_use = next((block for block in response.content if block.type == "tool_use"), None)
        if tool_use is None:
            raise AgentDecisionError(f"No tool call in model response (stop_reason={response.stop_reason})")

        return ToolDecision(tool_name=tool_use.name, tool_input=tool_use.input, model_used=response.model)


def get_agent_client() -> AgentClient:
    return AnthropicAgentClient(api_key=settings.anthropic_api_key, model=settings.agent_model)
