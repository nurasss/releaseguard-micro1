# path: tests/test_llm_client.py
import json
from typing import Any

import httpx
import pytest

from app.llm.errors import (
    LLMAuthError,
    LLMError,
    LLMInvalidResponse,
    LLMRateLimited,
    LLMServerError,
    LLMTimeout,
)
from app.llm.gemini import GeminiClient
from app.llm.pricing import PRICES, estimate_cost_usd
from app.llm.types import Message, ToolCall, ToolSpec, Usage


def create_mock_client(
    handler: Any,
    api_key: str = "test-api-key",
    model_id: str = "gemini-2.5-flash",
    timeout_s: int = 120,
    max_retries: int = 2,
    min_request_interval_ms: int = 0,
    time_fn: Any = None,
    sleep_fn: Any = None,
) -> GeminiClient:
    transport = httpx.MockTransport(handler)
    current_time = [1000.0]

    def default_time_fn() -> float:
        return current_time[0]

    def default_sleep_fn(seconds: float) -> None:
        current_time[0] += seconds

    return GeminiClient(
        api_key=api_key,
        model_id=model_id,
        timeout_s=timeout_s,
        max_retries=max_retries,
        min_request_interval_ms=min_request_interval_ms,
        transport=transport,
        time_fn=time_fn or default_time_fn,
        sleep_fn=sleep_fn or default_sleep_fn,
    )


def test_successful_text_response_and_usage() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.read())
        assert body["contents"][0]["parts"][0]["text"] == "Hello Gemini"
        response_data = {
            "candidates": [
                {
                    "content": {
                        "parts": [{"text": "Hello human"}],
                        "role": "model",
                    },
                    "finishReason": "STOP",
                }
            ],
            "usageMetadata": {
                "promptTokenCount": 12,
                "candidatesTokenCount": 8,
                "totalTokenCount": 20,
            },
        }
        return httpx.Response(200, json=response_data)

    client = create_mock_client(handler)
    res = client.generate(
        system="You are a helper",
        messages=[Message(role="user", content="Hello Gemini")],
    )

    assert res.text == "Hello human"
    assert res.tool_calls == []
    assert res.finish_reason == "STOP"
    assert res.usage.prompt_tokens == 12
    assert res.usage.output_tokens == 8
    assert res.usage.total_tokens == 20
    assert res.retries == 0
    assert res.model_id == "gemini-2.5-flash"


def test_response_with_function_call_parsed_to_tool_call() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        response_data = {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {
                                "functionCall": {
                                    "name": "check_file_syntax",
                                    "args": {"path": "src/main.py"},
                                }
                            }
                        ],
                        "role": "model",
                    },
                    "finishReason": "STOP",
                }
            ],
            "usageMetadata": {
                "promptTokenCount": 15,
                "candidatesTokenCount": 5,
                "totalTokenCount": 20,
            },
        }
        return httpx.Response(200, json=response_data)

    client = create_mock_client(handler)
    tools = [
        ToolSpec(
            name="check_file_syntax",
            description="Check syntax of a file",
            parameters={
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        )
    ]
    res = client.generate(
        system="",
        messages=[Message(role="user", content="Check main.py")],
        tools=tools,
    )

    assert res.text is None
    assert len(res.tool_calls) == 1
    call = res.tool_calls[0]
    assert call.name == "check_file_syntax"
    assert call.args == {"path": "src/main.py"}
    assert call.call_id == "0:check_file_syntax"
    assert call.thought_signature is None


def test_response_with_model_id_and_thought_signature() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        response_data = {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {
                                "functionCall": {
                                    "name": "f",
                                    "args": {},
                                    "id": "call_1",
                                },
                                "thoughtSignature": "SIG",
                            }
                        ],
                        "role": "model",
                    },
                    "finishReason": "STOP",
                }
            ],
            "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 5, "totalTokenCount": 15},
        }
        return httpx.Response(200, json=response_data)

    client = create_mock_client(handler)
    res = client.generate(
        system="",
        messages=[Message(role="user", content="run f")],
        tools=[ToolSpec(name="f", description="test tool", parameters={"type": "object"})],
    )

    assert len(res.tool_calls) == 1
    tc = res.tool_calls[0]
    assert tc.name == "f"
    assert tc.call_id == "call_1"
    assert tc.thought_signature == "SIG"


def test_model_and_tool_serialization_with_thought_signatures_and_ids() -> None:
    captured_payload = {}

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured_payload
        captured_payload = json.loads(request.read())
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "content": {"parts": [{"text": "Done."}]},
                        "finishReason": "STOP",
                    }
                ],
                "usageMetadata": {"promptTokenCount": 20, "candidatesTokenCount": 2, "totalTokenCount": 22},
            },
        )

    client = create_mock_client(handler)

    tc_with_sig = ToolCall(name="f1", args={"x": 1}, call_id="call_101", thought_signature="SIG_A")
    tc_without_sig = ToolCall(name="f2", args={"y": 2}, call_id="call_102", thought_signature=None)

    history = [
        Message(role="user", content="Run parallel tools"),
        Message(role="model", tool_calls=[tc_with_sig, tc_without_sig]),
        Message(role="tool", tool_name="f1", tool_call_id="call_101", tool_response={"out": 1}),
        Message(role="tool", tool_name="f2", tool_call_id="call_102", tool_response={"out": 2}),
    ]

    res = client.generate(system="Auditor", messages=history)
    assert res.text == "Done."

    contents = captured_payload["contents"]
    assert len(contents) == 4

    # Turn 1: user
    assert contents[0]["role"] == "user"

    # Turn 2: model with 2 parallel calls
    model_turn = contents[1]
    assert model_turn["role"] == "model"
    parts = model_turn["parts"]
    assert len(parts) == 2

    # Part 1: has thoughtSignature at part level beside functionCall
    assert parts[0]["functionCall"] == {"name": "f1", "args": {"x": 1}}
    assert parts[0]["thoughtSignature"] == "SIG_A"
    assert "thoughtSignature" not in parts[0]["functionCall"]

    # Part 2: has no thoughtSignature key at all
    assert parts[1]["functionCall"] == {"name": "f2", "args": {"y": 2}}
    assert "thoughtSignature" not in parts[1]

    # Turn 3: tool 1 response includes "id": "call_101"
    tool1_turn = contents[2]
    assert tool1_turn["role"] == "user"
    assert tool1_turn["parts"][0]["functionResponse"] == {
        "id": "call_101",
        "name": "f1",
        "response": {"out": 1},
    }

    # Turn 4: tool 2 response includes "id": "call_102"
    tool2_turn = contents[3]
    assert tool2_turn["role"] == "user"
    assert tool2_turn["parts"][0]["functionResponse"] == {
        "id": "call_102",
        "name": "f2",
        "response": {"out": 2},
    }


def test_three_turn_cycle_with_parallel_tools_and_signatures() -> None:
    # Full roundtrip: user -> model (2 tool calls with sigs) -> 2 tool responses -> model final text
    captured_payloads: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.read())
        captured_payloads.append(body)
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "content": {"parts": [{"text": "All tools completed."}]},
                        "finishReason": "STOP",
                    }
                ],
                "usageMetadata": {"promptTokenCount": 50, "candidatesTokenCount": 5, "totalTokenCount": 55},
            },
        )

    client = create_mock_client(handler)

    history = [
        Message(role="user", content="Inspect repo"),
        Message(
            role="model",
            tool_calls=[
                ToolCall(name="get_tree", args={}, call_id="call_t1", thought_signature="SIG_TREE"),
                ToolCall(name="get_repository_metadata", args={}, call_id="call_m1", thought_signature="SIG_META"),
            ],
        ),
        Message(
            role="tool",
            tool_name="get_tree",
            tool_call_id="call_t1",
            tool_response={"files": ["a.py"]},
        ),
        Message(
            role="tool",
            tool_name="get_repository_metadata",
            tool_call_id="call_m1",
            tool_response={"default_branch": "main"},
        ),
    ]

    res = client.generate(system="Auditor", messages=history)
    assert res.text == "All tools completed."

    sent_contents = captured_payloads[0]["contents"]
    assert len(sent_contents) == 4

    # Check model turn
    assert sent_contents[1]["parts"][0]["thoughtSignature"] == "SIG_TREE"
    assert sent_contents[1]["parts"][1]["thoughtSignature"] == "SIG_META"

    # Check tool response turns
    assert sent_contents[2]["parts"][0]["functionResponse"]["id"] == "call_t1"
    assert sent_contents[3]["parts"][0]["functionResponse"]["id"] == "call_m1"


def test_tool_calling_cycle_serialization_roles_and_parts() -> None:
    captured_payload = {}

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured_payload
        captured_payload = json.loads(request.read())
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "content": {"parts": [{"text": "Found 2 files."}]},
                        "finishReason": "STOP",
                    }
                ],
                "usageMetadata": {"promptTokenCount": 30, "candidatesTokenCount": 10, "totalTokenCount": 40},
            },
        )

    client = create_mock_client(handler)
    history = [
        Message(role="user", content="Find python files"),
        Message(
            role="model",
            content=None,
            tool_calls=[ToolCall(name="glob_files", args={"pattern": "*.py"}, call_id="0:glob_files")],
        ),
        Message(
            role="tool",
            tool_name="glob_files",
            tool_call_id="0:glob_files",
            tool_response={"files": ["app/main.py", "app/config.py"]},
        ),
    ]

    res = client.generate(system="You are an auditor", messages=history)
    assert res.text == "Found 2 files."

    contents = captured_payload["contents"]
    assert len(contents) == 3

    # Turn 1: user text
    assert contents[0]["role"] == "user"
    assert contents[0]["parts"] == [{"text": "Find python files"}]

    # Turn 2: model with tool call
    assert contents[1]["role"] == "model"
    assert contents[1]["parts"] == [{"functionCall": {"name": "glob_files", "args": {"pattern": "*.py"}}}]

    # Turn 3: tool result sent with role "user"
    assert contents[2]["role"] == "user"
    assert contents[2]["parts"] == [
        {"functionResponse": {"id": "0:glob_files", "name": "glob_files", "response": {"files": ["app/main.py", "app/config.py"]}}}
    ]

    # Verify no disallowed roles and no empty parts exist in any turn
    for turn in contents:
        assert turn["role"] in {"user", "model"}
        assert len(turn["parts"]) > 0


def test_empty_model_message_raises_value_error() -> None:
    client = create_mock_client(lambda r: httpx.Response(200))
    empty_model_msg = Message(role="model", content=None, tool_calls=[])

    with pytest.raises(ValueError, match="Model message must contain at least one text part or tool_call"):
        client.generate(system="", messages=[empty_model_msg])


def test_simultaneous_tools_and_response_schema_raises_value_error() -> None:
    client = create_mock_client(lambda r: httpx.Response(200))
    tools = [ToolSpec(name="f", description="d", parameters={})]
    schema = {"type": "object"}

    with pytest.raises(ValueError, match="two-phase approach"):
        client.generate(
            system="",
            messages=[Message(role="user", content="test")],
            tools=tools,
            response_schema=schema,
        )


def test_response_schema_sent_in_generation_config() -> None:
    captured_payload = {}

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured_payload
        captured_payload = json.loads(request.read())
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "content": {"parts": [{"text": '{"result": true}'}]},
                        "finishReason": "STOP",
                    }
                ],
                "usageMetadata": {"promptTokenCount": 5, "candidatesTokenCount": 5, "totalTokenCount": 10},
            },
        )

    client = create_mock_client(handler)
    schema = {"type": "object", "properties": {"result": {"type": "boolean"}}}
    res = client.generate(
        system="",
        messages=[Message(role="user", content="Validate")],
        response_schema=schema,
    )

    assert captured_payload["generationConfig"]["responseMimeType"] == "application/json"
    assert captured_payload["generationConfig"]["responseSchema"] == schema
    assert res.text == '{"result": true}'


def test_api_key_in_header_not_in_url() -> None:
    api_key_secret = "secret-key-12345"
    captured_url = ""
    captured_headers = {}

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured_url, captured_headers
        captured_url = str(request.url)
        captured_headers = dict(request.headers)
        return httpx.Response(
            200,
            json={
                "candidates": [{"content": {"parts": [{"text": "ok"}]}}],
                "usageMetadata": {"promptTokenCount": 1, "candidatesTokenCount": 1, "totalTokenCount": 2},
            },
        )

    client = create_mock_client(handler, api_key=api_key_secret)
    client.generate(system="", messages=[Message(role="user", content="ping")])

    assert api_key_secret not in captured_url
    assert captured_headers.get("x-goog-api-key") == api_key_secret


def test_429_with_retry_after_retries_and_succeeds() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(429, headers={"Retry-After": "1.5"}, text="Rate limit exceeded")
        return httpx.Response(
            200,
            json={
                "candidates": [{"content": {"parts": [{"text": "recovered"}]}}],
                "usageMetadata": {"promptTokenCount": 1, "candidatesTokenCount": 1, "totalTokenCount": 2},
            },
        )

    client = create_mock_client(handler, max_retries=2)
    res = client.generate(system="", messages=[Message(role="user", content="retry test")])

    assert attempts == 2
    assert res.retries == 1
    assert res.text == "recovered"


def test_429_with_body_retry_delay() -> None:
    attempts = 0
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            error_body = {
                "error": {
                    "code": 429,
                    "message": "Resource has been exhausted (e.g. check quota).",
                    "status": "RESOURCE_EXHAUSTED",
                    "details": [
                        {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "23s"}
                    ],
                }
            }
            return httpx.Response(429, json=error_body)
        return httpx.Response(
            200,
            json={
                "candidates": [{"content": {"parts": [{"text": "recovered"}]}}],
                "usageMetadata": {"promptTokenCount": 1, "candidatesTokenCount": 1, "totalTokenCount": 2},
            },
        )

    def sleep_track(s: float) -> None:
        sleeps.append(s)

    client = create_mock_client(handler, max_retries=2, sleep_fn=sleep_track)
    res = client.generate(system="", messages=[Message(role="user", content="retry test")])

    assert attempts == 2
    assert res.retries == 1
    assert len(sleeps) == 1
    assert sleeps[0] == pytest.approx(23.0)


def test_429_exponential_backoff_sequence_without_retry_info() -> None:
    attempts = 0
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts <= 2:
            return httpx.Response(429, text="Quota exceeded without retry delay")
        return httpx.Response(
            200,
            json={
                "candidates": [{"content": {"parts": [{"text": "recovered"}]}}],
                "usageMetadata": {"promptTokenCount": 1, "candidatesTokenCount": 1, "totalTokenCount": 2},
            },
        )

    def sleep_track(s: float) -> None:
        sleeps.append(s)

    client = create_mock_client(handler, max_retries=3, sleep_fn=sleep_track)
    res = client.generate(system="", messages=[Message(role="user", content="test")])

    assert attempts == 3
    assert res.retries == 2
    assert len(sleeps) == 2
    assert 15.0 <= sleeps[0] <= 15.5
    assert 30.0 <= sleeps[1] <= 30.5


def test_429_exceeding_max_retries_raises_rate_limited() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={"Retry-After": "2.0"}, text="Quota exceeded")

    client = create_mock_client(handler, max_retries=1)
    with pytest.raises(LLMRateLimited) as exc_info:
        client.generate(system="", messages=[Message(role="user", content="fail")])

    assert exc_info.value.retry_after_s == 2.0


def test_503_retries_and_succeeds() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(503, text="Service Unavailable")
        return httpx.Response(
            200,
            json={
                "candidates": [{"content": {"parts": [{"text": "success"}]}}],
                "usageMetadata": {"promptTokenCount": 2, "candidatesTokenCount": 2, "totalTokenCount": 4},
            },
        )

    client = create_mock_client(handler, max_retries=2)
    res = client.generate(system="", messages=[Message(role="user", content="server retry")])

    assert attempts == 2
    assert res.retries == 1
    assert res.text == "success"


def test_timeout_retry_success_on_second_attempt() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise httpx.ReadTimeout("Read timed out")
        return httpx.Response(
            200,
            json={
                "candidates": [{"content": {"parts": [{"text": "recovered after timeout"}]}}],
                "usageMetadata": {"promptTokenCount": 2, "candidatesTokenCount": 3, "totalTokenCount": 5},
            },
        )

    client = create_mock_client(handler, max_retries=2)
    res = client.generate(system="", messages=[Message(role="user", content="timeout retry test")])

    assert attempts == 2
    assert res.retries == 1
    assert res.text == "recovered after timeout"


def test_timeout_exceeding_max_retries_raises_llm_timeout() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("Connection timed out")

    client = create_mock_client(handler, max_retries=2)
    with pytest.raises(LLMTimeout):
        client.generate(system="", messages=[Message(role="user", content="fail")])


def test_network_request_error_retries_and_raises_server_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.NetworkError("Network socket broken")

    client = create_mock_client(handler, max_retries=1)
    with pytest.raises(LLMServerError, match="Network error"):
        client.generate(system="", messages=[Message(role="user", content="net fail")])


def test_401_raises_auth_error_without_retry() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(401, text="API key invalid")

    client = create_mock_client(handler, max_retries=3)
    with pytest.raises(LLAuthError if False else LLMAuthError):
        client.generate(system="", messages=[Message(role="user", content="auth test")])

    assert attempts == 1


def test_400_raises_invalid_response_without_retry() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(400, text="Invalid argument")

    client = create_mock_client(handler, max_retries=3)
    with pytest.raises(LLMInvalidResponse):
        client.generate(system="", messages=[Message(role="user", content="bad request")])

    assert attempts == 1


def test_empty_candidates_without_prompt_feedback_raises_invalid_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"candidates": [], "usageMetadata": {}})

    client = create_mock_client(handler)
    with pytest.raises(LLMInvalidResponse, match="candidates"):
        client.generate(system="", messages=[Message(role="user", content="test")])


def test_empty_candidates_with_prompt_feedback_block_reason_raises_invalid_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "candidates": [],
                "promptFeedback": {"blockReason": "OTHER"},
                "usageMetadata": {},
            },
        )

    client = create_mock_client(handler)
    with pytest.raises(LLMInvalidResponse, match="OTHER"):
        client.generate(system="", messages=[Message(role="user", content="test")])


def test_candidate_empty_content_with_safety_finish_reason_raises_invalid_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "finishReason": "SAFETY",
                        "content": {"parts": []},
                    }
                ],
                "usageMetadata": {},
            },
        )

    client = create_mock_client(handler)
    with pytest.raises(LLMInvalidResponse, match="SAFETY"):
        client.generate(system="", messages=[Message(role="user", content="test")])


def test_invalid_json_body_raises_invalid_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"not-json-content")

    client = create_mock_client(handler)
    with pytest.raises(LLMInvalidResponse, match="Invalid JSON"):
        client.generate(system="", messages=[Message(role="user", content="test")])


def test_error_messages_do_not_contain_api_key() -> None:
    secret_key = "SECRET-KEY-DO-NOT-LEAK"

    # 1. 401 error containing key in response body
    def handler_401(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text=f"Invalid key: {secret_key}")

    client = create_mock_client(handler_401, api_key=secret_key, max_retries=0)
    with pytest.raises(LLMAuthError) as exc_info:
        client.generate(system="", messages=[Message(role="user", content="test")])
    assert secret_key not in str(exc_info.value)
    assert "[REDACTED]" in str(exc_info.value)

    # 2. 500 error containing key in response body
    def handler_500(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text=f"Internal crash with key {secret_key}")

    client = create_mock_client(handler_500, api_key=secret_key, max_retries=0)
    with pytest.raises(LLMServerError) as exc_info:
        client.generate(system="", messages=[Message(role="user", content="test")])
    assert secret_key not in str(exc_info.value)
    assert "[REDACTED]" in str(exc_info.value)

    # 3. 429 error containing key in response body
    def handler_429(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, text=f"Quota exhausted for key {secret_key}")

    client = create_mock_client(handler_429, api_key=secret_key, max_retries=0)
    with pytest.raises(LLMRateLimited) as exc_info:
        client.generate(system="", messages=[Message(role="user", content="test")])
    assert secret_key not in str(exc_info.value)
    assert "[REDACTED]" in str(exc_info.value)


def test_estimate_cost_usd_unknown_and_known_models() -> None:
    usage = Usage(prompt_tokens=1_000_000, output_tokens=500_000, total_tokens=1_500_000)

    # Unknown model must return None, not 0.0 or fabricated number
    assert estimate_cost_usd("unknown-gemini-model", usage) is None

    # Known model configured in PRICES
    PRICES["test-paid-model"] = (1.50, 3.00)
    try:
        cost = estimate_cost_usd("test-paid-model", usage)
        assert cost is not None
        # 1.0 * 1.50 + 0.5 * 3.00 = 1.50 + 1.50 = 3.00
        assert cost == pytest.approx(3.00)
    finally:
        PRICES.pop("test-paid-model", None)


def test_min_request_interval_enforces_delay() -> None:
    virtual_time = 100.0
    sleeps_recorded: list[float] = []

    def time_source() -> float:
        return virtual_time

    def sleep_source(duration: float) -> None:
        nonlocal virtual_time
        sleeps_recorded.append(duration)
        virtual_time += duration

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "candidates": [{"content": {"parts": [{"text": "ok"}]}}],
                "usageMetadata": {"promptTokenCount": 1, "candidatesTokenCount": 1, "totalTokenCount": 2},
            },
        )

    # 500ms interval
    client = create_mock_client(
        handler,
        min_request_interval_ms=500,
        time_fn=time_source,
        sleep_fn=sleep_source,
    )

    # First request does not sleep
    client.generate(system="", messages=[Message(role="user", content="r1")])
    assert len(sleeps_recorded) == 0

    # Advance virtual time by only 100ms
    virtual_time += 0.1

    # Second request must sleep for remaining 400ms (0.4s)
    client.generate(system="", messages=[Message(role="user", content="r2")])
    assert len(sleeps_recorded) == 1
    assert sleeps_recorded[0] == pytest.approx(0.4)


def test_client_context_manager_and_close() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "candidates": [{"content": {"parts": [{"text": "closed test"}]}}],
                "usageMetadata": {},
            },
        )

    with create_mock_client(handler) as client:
        res = client.generate(system="", messages=[Message(role="user", content="test")])
        assert res.text == "closed test"

    assert client._client.is_closed
