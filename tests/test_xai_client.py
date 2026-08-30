import json
from typing import Any

import httpx
import pytest

from app.llm.errors import LLMAuthError, LLMInvalidResponse, LLMRateLimited
from app.llm.types import Message, ToolCall, ToolSpec
from app.llm.xai import XAIClient


def create_client(handler: Any, *, api_key: str = "xai-test-key", max_retries: int = 0) -> XAIClient:
    return XAIClient(
        api_key=api_key,
        model_id="grok-4.6",
        max_retries=max_retries,
        transport=httpx.MockTransport(handler),
        time_fn=lambda: 100.0,
        sleep_fn=lambda _: None,
    )


def test_text_response_uses_xai_chat_completions_and_bearer_auth() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "https://api.x.ai/v1/chat/completions"
        assert request.headers["Authorization"] == "Bearer xai-test-key"
        body = json.loads(request.read())
        assert body["model"] == "grok-4.6"
        assert body["reasoning_effort"] == "low"
        assert body["messages"] == [
            {"role": "system", "content": "Be concise"},
            {"role": "user", "content": "Audit this"},
        ]
        return httpx.Response(
            200,
            json={
                "model": "grok-4.6",
                "choices": [{"message": {"role": "assistant", "content": "Ready"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 11, "completion_tokens": 4, "total_tokens": 15},
            },
        )

    response = create_client(handler).generate(
        system="Be concise",
        messages=[Message(role="user", content="Audit this")],
    )
    assert response.text == "Ready"
    assert response.model_id == "grok-4.6"
    assert response.usage.prompt_tokens == 11
    assert response.usage.output_tokens == 4


def test_usage_counts_hidden_reasoning_as_billable_output() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "303"}, "finish_reason": "stop"}],
                "usage": {
                    "prompt_tokens": 32,
                    "completion_tokens": 9,
                    "total_tokens": 135,
                    "completion_tokens_details": {"reasoning_tokens": 94},
                },
            },
        )

    response = create_client(handler).generate(
        system="",
        messages=[Message(role="user", content="101*3")],
    )
    assert response.usage.prompt_tokens == 32
    assert response.usage.output_tokens == 103
    assert response.usage.total_tokens == 135


def test_tools_are_serialized_and_tool_call_is_parsed() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.read())
        assert body["tools"][0]["type"] == "function"
        assert body["tools"][0]["function"]["name"] == "read_file"
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call_1",
                                    "type": "function",
                                    "function": {
                                        "name": "read_file",
                                        "arguments": '{"path":"pyproject.toml"}',
                                    },
                                }
                            ],
                        },
                        "finish_reason": "tool_calls",
                    }
                ],
                "usage": {},
            },
        )

    response = create_client(handler).generate(
        system="",
        messages=[Message(role="user", content="Inspect")],
        tools=[
            ToolSpec(
                name="read_file",
                description="Read one file",
                parameters={"type": "object", "properties": {"path": {"type": "string"}}},
            )
        ],
    )
    assert response.tool_calls == [
        ToolCall(name="read_file", args={"path": "pyproject.toml"}, call_id="call_1")
    ]


def test_prior_tool_cycle_and_strict_json_schema_are_serialized() -> None:
    source_schema = {
        "type": "object",
        "properties": {
            "result": {
                "type": "object",
                "properties": {"ok": {"type": "boolean"}},
                "required": ["ok"],
            }
        },
        "required": ["result"],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.read())
        assert body["messages"][1]["role"] == "assistant"
        assert body["messages"][1]["tool_calls"][0]["id"] == "call_1"
        assert body["messages"][2] == {
            "role": "tool",
            "tool_call_id": "call_1",
            "content": '{"content": "safe"}',
        }
        response_format = body["response_format"]
        assert response_format["type"] == "json_schema"
        assert response_format["json_schema"]["strict"] is True
        sent_schema = response_format["json_schema"]["schema"]
        assert sent_schema["additionalProperties"] is False
        assert sent_schema["properties"]["result"]["additionalProperties"] is False
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": '{"result":{"ok":true}}'}, "finish_reason": "stop"}],
                "usage": {},
            },
        )

    messages = [
        Message(role="user", content="Inspect"),
        Message(
            role="model",
            tool_calls=[ToolCall(name="read_file", args={"path": "README.md"}, call_id="call_1")],
        ),
        Message(
            role="tool",
            tool_call_id="call_1",
            tool_name="read_file",
            tool_response={"content": "safe"},
        ),
    ]
    response = create_client(handler).generate(
        system="",
        messages=messages,
        response_schema=source_schema,
        max_output_tokens=250,
    )
    assert response.text == '{"result":{"ok":true}}'
    assert "additionalProperties" not in source_schema


def test_invalid_tool_arguments_are_rejected() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "tool_calls": [
                                {"id": "bad", "function": {"name": "read_file", "arguments": "not-json"}}
                            ]
                        }
                    }
                ]
            },
        )

    with pytest.raises(LLMInvalidResponse):
        create_client(handler).generate(system="", messages=[Message(role="user", content="test")])


@pytest.mark.parametrize("status,error_type", [(401, LLMAuthError), (403, LLMAuthError), (429, LLMRateLimited)])
def test_provider_errors_redact_key(status: int, error_type: type[Exception]) -> None:
    secret = "xai-secret-that-must-not-leak"

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(status, text=f"provider echoed {secret}", headers={"Retry-After": "9"})

    with pytest.raises(error_type) as caught:
        create_client(handler, api_key=secret).generate(
            system="",
            messages=[Message(role="user", content="test")],
        )
    assert secret not in str(caught.value)
    assert "[REDACTED]" in str(caught.value)
    if status == 429:
        assert caught.value.retry_after_s == 9.0
