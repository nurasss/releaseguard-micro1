# path: app/llm/types.py
from __future__ import annotations

from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field


class ToolSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    description: str
    parameters: dict = Field(default_factory=dict)


class ToolCall(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    args: dict = Field(default_factory=dict)
    call_id: str
    thought_signature: str | None = None


class Usage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prompt_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0


class LLMResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str | None = None
    tool_calls: list[ToolCall] = Field(default_factory=list)
    usage: Usage
    finish_reason: str
    latency_ms: int
    retries: int
    model_id: str


class Message(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["user", "model", "tool"]
    content: str | None = None
    tool_call_id: str | None = None
    tool_name: str | None = None
    tool_response: dict | None = None
    tool_calls: list[ToolCall] = Field(default_factory=list)


class LLMClient(Protocol):
    def generate(
        self,
        system: str,
        messages: list[Message],
        tools: list[ToolSpec] | None = None,
        response_schema: dict | None = None,
        temperature: float = 0.0,
        max_output_tokens: int | None = None,
    ) -> LLMResponse: ...
