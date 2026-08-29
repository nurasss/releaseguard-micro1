# path: app/llm/gemini.py
from __future__ import annotations

import json
import random
import time
from typing import Any, Callable

import httpx

from app.llm.errors import (
    LLMAuthError,
    LLMError,
    LLMInvalidResponse,
    LLMRateLimited,
    LLMServerError,
    LLMTimeout,
)
from app.llm.types import LLMClient, LLMResponse, Message, ToolCall, ToolSpec, Usage


class GeminiClient(LLMClient):
    """Client for Google Gemini REST API via Google AI Studio."""

    BASE_URL = "https://generativelanguage.googleapis.com/v1beta"

    def __init__(
        self,
        api_key: str,
        model_id: str,
        timeout_s: int = 120,
        max_retries: int = 2,
        min_request_interval_ms: int = 0,
        transport: httpx.BaseTransport | None = None,
        time_fn: Callable[[], float] = time.time,
        sleep_fn: Callable[[float], None] = time.sleep,
    ) -> None:
        self.api_key = api_key
        self.model_id = model_id
        self.timeout_s = timeout_s
        self.max_retries = max_retries
        self.min_request_interval_ms = min_request_interval_ms
        self.transport = transport
        self._time_fn = time_fn
        self._sleep_fn = sleep_fn
        self._last_request_time: float = 0.0
        self._client = httpx.Client(
            transport=self.transport,
            timeout=self.timeout_s,
            headers={
                "x-goog-api-key": self.api_key,
                "Content-Type": "application/json",
            },
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> GeminiClient:
        return self

    def __exit__(self, *exc_info: Any) -> None:
        self.close()

    def _sanitize(self, text: str) -> str:
        if not self.api_key:
            return text
        return text.replace(self.api_key, "[REDACTED]")

    def _enforce_rate_limit(self) -> None:
        if self.min_request_interval_ms <= 0 or self._last_request_time <= 0:
            self._last_request_time = self._time_fn()
            return

        now = self._time_fn()
        elapsed_ms = (now - self._last_request_time) * 1000.0
        if elapsed_ms < self.min_request_interval_ms:
            wait_s = (self.min_request_interval_ms - elapsed_ms) / 1000.0
            self._sleep_fn(wait_s)
        self._last_request_time = self._time_fn()

    def generate(
        self,
        system: str,
        messages: list[Message],
        tools: list[ToolSpec] | None = None,
        response_schema: dict | None = None,
        temperature: float = 0.0,
        max_output_tokens: int | None = None,
    ) -> LLMResponse:
        if tools and response_schema:
            raise ValueError(
                "Gemini does not support function declarations and responseSchema in the same request. "
                "Use a two-phase approach: tool calling cycle first, followed by a schema-constrained final generation call without tools."
            )

        payload: dict = {}

        if system:
            payload["systemInstruction"] = {"parts": [{"text": system}]}

        contents: list[dict] = []
        for msg in messages:
            if msg.role == "user":
                contents.append({"role": "user", "parts": [{"text": msg.content or ""}]})
            elif msg.role == "model":
                parts: list[dict] = []
                if msg.content:
                    parts.append({"text": msg.content})
                for tc in msg.tool_calls:
                    fc_dict: dict[str, Any] = {"name": tc.name, "args": tc.args}
                    part_entry: dict[str, Any] = {"functionCall": fc_dict}
                    if tc.thought_signature is not None:
                        part_entry["thoughtSignature"] = tc.thought_signature
                    parts.append(part_entry)
                if not parts:
                    raise ValueError("Model message must contain at least one text part or tool_call")
                contents.append({"role": "model", "parts": parts})
            elif msg.role == "tool":
                # In Gemini REST API, function responses are submitted with role "user"
                fn_resp: dict[str, Any] = {
                    "name": msg.tool_name or "",
                    "response": msg.tool_response or {},
                }
                if msg.tool_call_id is not None:
                    fn_resp["id"] = msg.tool_call_id
                contents.append(
                    {
                        "role": "user",
                        "parts": [
                            {
                                "functionResponse": fn_resp,
                            }
                        ],
                    }
                )
        payload["contents"] = contents

        if tools:
            payload["tools"] = [
                {
                    "functionDeclarations": [
                        {
                            "name": t.name,
                            "description": t.description,
                            "parameters": t.parameters,
                        }
                        for t in tools
                    ]
                }
            ]

        generation_config: dict = {}
        if temperature is not None:
            generation_config["temperature"] = temperature
        if max_output_tokens is not None:
            generation_config["maxOutputTokens"] = max_output_tokens
        if response_schema is not None:
            generation_config["responseMimeType"] = "application/json"
            generation_config["responseSchema"] = response_schema

        if generation_config:
            payload["generationConfig"] = generation_config

        url = f"{self.BASE_URL}/models/{self.model_id}:generateContent"

        retries_done = 0
        start_time = self._time_fn()

        while True:
            self._enforce_rate_limit()
            try:
                response = self._client.post(url, json=payload)
            except httpx.TimeoutException as exc:
                if retries_done < self.max_retries:
                    retries_done += 1
                    backoff = (2 ** (retries_done - 1)) + random.uniform(0.0, 0.25)
                    self._sleep_fn(backoff)
                    continue
                raise LLMTimeout(self._sanitize(f"LLM request timed out: {exc}")) from exc
            except httpx.RequestError as exc:
                if retries_done < self.max_retries:
                    retries_done += 1
                    backoff = (2 ** (retries_done - 1)) + random.uniform(0.0, 0.25)
                    self._sleep_fn(backoff)
                    continue
                raise LLMServerError(self._sanitize(f"Network error communicating with LLM: {exc}")) from exc

            status = response.status_code

            if status == 200:
                try:
                    data = response.json()
                except Exception as exc:
                    raise LLMInvalidResponse("Invalid JSON in response body") from exc

                candidates = data.get("candidates")
                if not candidates or not isinstance(candidates, list):
                    block_reason = data.get("promptFeedback", {}).get("blockReason")
                    if block_reason:
                        raise LLMInvalidResponse(f"Gemini blocked prompt: {block_reason}")
                    raise LLMInvalidResponse("Response missing candidates list")

                candidate = candidates[0]
                finish_reason = candidate.get("finishReason", "STOP")
                content_obj = candidate.get("content", {})
                parts = content_obj.get("parts", []) if isinstance(content_obj, dict) else []

                text_parts: list[str] = []
                tool_calls: list[ToolCall] = []

                for idx, part in enumerate(parts):
                    if not isinstance(part, dict):
                        continue
                    if "text" in part and part["text"] is not None:
                        text_parts.append(part["text"])
                    if "functionCall" in part:
                        fc = part["functionCall"]
                        fc_name = fc.get("name", "")
                        fc_args = fc.get("args", {})
                        fc_id = fc.get("id")
                        call_id = str(fc_id) if fc_id is not None else f"{idx}:{fc_name}"
                        thought_sig = part.get("thoughtSignature")
                        tool_calls.append(
                            ToolCall(
                                name=fc_name,
                                args=fc_args,
                                call_id=call_id,
                                thought_signature=thought_sig,
                            )
                        )

                if not text_parts and not tool_calls:
                    raise LLMInvalidResponse(
                        f"Gemini returned empty candidate content (finishReason={finish_reason})"
                    )

                text_result = "".join(text_parts) if text_parts else None

                usage_meta = data.get("usageMetadata", {})
                prompt_tokens = usage_meta.get("promptTokenCount", 0)
                output_tokens = usage_meta.get("candidatesTokenCount", 0)
                total_tokens = usage_meta.get("totalTokenCount", prompt_tokens + output_tokens)

                usage = Usage(
                    prompt_tokens=prompt_tokens,
                    output_tokens=output_tokens,
                    total_tokens=total_tokens,
                )

                latency_ms = int((self._time_fn() - start_time) * 1000)

                return LLMResponse(
                    text=text_result,
                    tool_calls=tool_calls,
                    usage=usage,
                    finish_reason=finish_reason,
                    latency_ms=latency_ms,
                    retries=retries_done,
                    model_id=self.model_id,
                )

            # Handle 429 Rate Limited
            if status == 429:
                retry_after_s: float | None = None
                raw_retry_after = response.headers.get("Retry-After")
                if raw_retry_after:
                    try:
                        retry_after_s = float(raw_retry_after)
                    except ValueError:
                        pass

                if retries_done < self.max_retries:
                    retries_done += 1
                    backoff = retry_after_s if retry_after_s is not None else ((2 ** (retries_done - 1)) + random.uniform(0.0, 0.25))
                    self._sleep_fn(backoff)
                    continue

                raise LLMRateLimited(
                    self._sanitize(f"Rate limit exceeded (429): {response.text[:200]}"),
                    retry_after_s=retry_after_s,
                )

            # Handle 5xx Server Errors
            if status in (500, 502, 503, 504):
                if retries_done < self.max_retries:
                    retries_done += 1
                    backoff = (2 ** (retries_done - 1)) + random.uniform(0.0, 0.25)
                    self._sleep_fn(backoff)
                    continue
                raise LLMServerError(self._sanitize(f"Server error ({status}): {response.text[:200]}"))

            # Handle 401/403 Auth Errors
            if status in (401, 403):
                raise LLMAuthError(self._sanitize(f"Authentication failed ({status}): {response.text[:200]}"))

            # Handle 400 Bad Request
            if status == 400:
                raise LLMInvalidResponse(self._sanitize(f"Bad request (400): {response.text[:200]}"))

            # Any other status
            raise LLMInvalidResponse(self._sanitize(f"Unexpected HTTP status ({status}): {response.text[:200]}"))
