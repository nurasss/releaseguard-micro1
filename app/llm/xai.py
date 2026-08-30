from __future__ import annotations

import copy
import json
import random
import time
from typing import Any, Callable

import httpx

from app.llm.errors import (
    LLMAuthError,
    LLMInvalidResponse,
    LLMRateLimited,
    LLMServerError,
    LLMTimeout,
)
from app.llm.types import LLMClient, LLMResponse, Message, ToolCall, ToolSpec, Usage


def _strict_json_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Return an xAI strict-mode schema without mutating the caller's object."""

    result = copy.deepcopy(schema)

    def visit(node: Any) -> None:
        if isinstance(node, dict):
            if node.get("type") == "object":
                node.setdefault("additionalProperties", False)
            for value in node.values():
                visit(value)
        elif isinstance(node, list):
            for value in node:
                visit(value)

    visit(result)
    return result


class XAIClient(LLMClient):
    """Client for xAI's OpenAI-compatible Chat Completions endpoint."""

    BASE_URL = "https://api.x.ai/v1"

    def __init__(
        self,
        api_key: str,
        model_id: str = "grok-4.6",
        timeout_s: int = 120,
        max_retries: int = 4,
        min_request_interval_ms: int = 0,
        reasoning_effort: str = "low",
        transport: httpx.BaseTransport | None = None,
        time_fn: Callable[[], float] = time.time,
        sleep_fn: Callable[[float], None] = time.sleep,
    ) -> None:
        self.api_key = api_key
        self.model_id = model_id
        self.timeout_s = timeout_s
        self.max_retries = max_retries
        self.min_request_interval_ms = min_request_interval_ms
        self.reasoning_effort = reasoning_effort
        self._time_fn = time_fn
        self._sleep_fn = sleep_fn
        self._last_request_time = 0.0
        self._client = httpx.Client(
            transport=transport,
            timeout=timeout_s,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> XAIClient:
        return self

    def __exit__(self, *exc_info: Any) -> None:
        self.close()

    def _sanitize(self, text: str) -> str:
        return text.replace(self.api_key, "[REDACTED]") if self.api_key else text

    def _enforce_rate_limit(self) -> None:
        if self.min_request_interval_ms <= 0 or self._last_request_time <= 0:
            self._last_request_time = self._time_fn()
            return
        now = self._time_fn()
        elapsed_ms = (now - self._last_request_time) * 1000.0
        if elapsed_ms < self.min_request_interval_ms:
            self._sleep_fn((self.min_request_interval_ms - elapsed_ms) / 1000.0)
        self._last_request_time = self._time_fn()

    @staticmethod
    def _messages(system: str, messages: list[Message]) -> list[dict[str, Any]]:
        rendered: list[dict[str, Any]] = []
        if system:
            rendered.append({"role": "system", "content": system})
        for message in messages:
            if message.role == "user":
                rendered.append({"role": "user", "content": message.content or ""})
            elif message.role == "model":
                item: dict[str, Any] = {
                    "role": "assistant",
                    "content": message.content,
                }
                if message.tool_calls:
                    item["tool_calls"] = [
                        {
                            "id": call.call_id,
                            "type": "function",
                            "function": {
                                "name": call.name,
                                "arguments": json.dumps(call.args, ensure_ascii=False),
                            },
                        }
                        for call in message.tool_calls
                    ]
                rendered.append(item)
            elif message.role == "tool":
                rendered.append(
                    {
                        "role": "tool",
                        "tool_call_id": message.tool_call_id or "",
                        "content": json.dumps(message.tool_response or {}, ensure_ascii=False),
                    }
                )
        return rendered

    def generate(
        self,
        system: str,
        messages: list[Message],
        tools: list[ToolSpec] | None = None,
        response_schema: dict | None = None,
        temperature: float = 0.0,
        max_output_tokens: int | None = None,
    ) -> LLMResponse:
        payload: dict[str, Any] = {
            "model": self.model_id,
            "messages": self._messages(system, messages),
            "reasoning_effort": self.reasoning_effort,
        }
        if temperature is not None:
            payload["temperature"] = temperature
        if max_output_tokens is not None:
            payload["max_tokens"] = max_output_tokens
        if tools:
            payload["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": tool.parameters,
                    },
                }
                for tool in tools
            ]
        if response_schema is not None:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "releaseguard_output",
                    "schema": _strict_json_schema(response_schema),
                    "strict": True,
                },
            }

        retries_done = 0
        start_time = self._time_fn()
        while True:
            self._enforce_rate_limit()
            try:
                response = self._client.post(f"{self.BASE_URL}/chat/completions", json=payload)
            except httpx.TimeoutException as exc:
                if retries_done < self.max_retries:
                    retries_done += 1
                    self._sleep_fn((2 ** (retries_done - 1)) + random.uniform(0.0, 0.25))
                    continue
                raise LLMTimeout(self._sanitize(f"LLM request timed out: {exc}")) from exc
            except httpx.RequestError as exc:
                if retries_done < self.max_retries:
                    retries_done += 1
                    self._sleep_fn((2 ** (retries_done - 1)) + random.uniform(0.0, 0.25))
                    continue
                raise LLMServerError(self._sanitize(f"Network error communicating with LLM: {exc}")) from exc

            status = response.status_code
            if status == 200:
                try:
                    data = response.json()
                    choice = data["choices"][0]
                    message = choice["message"]
                except (ValueError, KeyError, IndexError, TypeError) as exc:
                    raise LLMInvalidResponse("Invalid xAI response envelope") from exc

                tool_calls: list[ToolCall] = []
                for index, raw_call in enumerate(message.get("tool_calls") or []):
                    try:
                        function = raw_call["function"]
                        raw_args = function.get("arguments", "{}")
                        args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
                        if not isinstance(args, dict):
                            raise TypeError("tool arguments are not an object")
                        tool_calls.append(
                            ToolCall(
                                name=function["name"],
                                args=args,
                                call_id=str(raw_call.get("id") or f"{index}:{function['name']}"),
                            )
                        )
                    except (KeyError, TypeError, json.JSONDecodeError) as exc:
                        raise LLMInvalidResponse("Invalid tool call in xAI response") from exc

                content = message.get("content")
                if content is not None and not isinstance(content, str):
                    raise LLMInvalidResponse("Invalid content in xAI response")
                if not content and not tool_calls:
                    raise LLMInvalidResponse("xAI returned an empty response")

                usage_data = data.get("usage") or {}
                prompt_tokens = int(usage_data.get("prompt_tokens", 0))
                reported_completion_tokens = int(usage_data.get("completion_tokens", 0))
                total_tokens = int(
                    usage_data.get("total_tokens", prompt_tokens + reported_completion_tokens)
                )
                # xAI can report hidden reasoning separately from completion_tokens
                # while including it in total_tokens. Reasoning is billable output.
                output_tokens = max(reported_completion_tokens, total_tokens - prompt_tokens)
                usage = Usage(
                    prompt_tokens=prompt_tokens,
                    output_tokens=output_tokens,
                    total_tokens=total_tokens,
                )
                return LLMResponse(
                    text=content,
                    tool_calls=tool_calls,
                    usage=usage,
                    finish_reason=str(choice.get("finish_reason") or "stop"),
                    latency_ms=int((self._time_fn() - start_time) * 1000),
                    retries=retries_done,
                    model_id=str(data.get("model") or self.model_id),
                )

            retry_after_s: float | None = None
            if response.headers.get("Retry-After"):
                try:
                    retry_after_s = float(response.headers["Retry-After"])
                except ValueError:
                    pass
            if status == 429:
                if retries_done < self.max_retries:
                    retries_done += 1
                    self._sleep_fn(
                        retry_after_s
                        if retry_after_s is not None
                        else (15.0 * (2 ** (retries_done - 1))) + random.uniform(0.0, 0.25)
                    )
                    continue
                raise LLMRateLimited(
                    self._sanitize(f"Rate limit exceeded (429): {response.text[:200]}"),
                    retry_after_s=retry_after_s,
                )
            if status in (500, 502, 503, 504):
                if retries_done < self.max_retries:
                    retries_done += 1
                    self._sleep_fn((2 ** (retries_done - 1)) + random.uniform(0.0, 0.25))
                    continue
                raise LLMServerError(self._sanitize(f"Server error ({status}): {response.text[:200]}"))
            if status in (401, 403):
                raise LLMAuthError(self._sanitize(f"Authentication failed ({status}): {response.text[:200]}"))
            if status == 400:
                raise LLMInvalidResponse(self._sanitize(f"Bad request (400): {response.text[:200]}"))
            raise LLMInvalidResponse(
                self._sanitize(f"Unexpected HTTP status ({status}): {response.text[:200]}")
            )
