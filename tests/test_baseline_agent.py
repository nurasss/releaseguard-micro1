# path: tests/test_baseline_agent.py
import json
import time
from pathlib import Path
from typing import Any

import pytest

from app.agents.baseline import BaselineAgent, BaselineOutcome
from app.evidence.store import EvidenceStore
from app.llm.errors import LLMServerError
from app.llm.types import LLMClient, LLMResponse, Message, ToolCall, ToolSpec, Usage
from app.sources.base import ResolvedRef
from app.sources.fixture import LocalFixtureSource
from app.tools.dispatch import ToolDispatcher
from app.trajectory.logger import TrajectoryLogger


CASES_DIR = Path(__file__).resolve().parents[1] / "eval" / "cases"


class FakeLLMClient(LLMClient):
    def __init__(self, responses: list[LLMResponse | Exception]) -> None:
        self.responses = list(responses)
        self.call_count = 0
        self.recorded_calls: list[dict[str, Any]] = []

    def generate(
        self,
        system: str,
        messages: list[Message],
        tools: list[ToolSpec] | None = None,
        response_schema: dict | None = None,
        temperature: float = 0.0,
        max_output_tokens: int | None = None,
    ) -> LLMResponse:
        self.call_count += 1
        self.recorded_calls.append(
            {
                "system": system,
                "messages": list(messages),
                "tools": tools,
                "response_schema": response_schema,
            }
        )
        if not self.responses:
            raise RuntimeError("FakeLLMClient ran out of queued responses")

        resp = self.responses.pop(0)
        if isinstance(resp, Exception):
            raise resp
        return resp


def test_baseline_agent_successful_run(tmp_path: Path) -> None:
    source = LocalFixtureSource(CASES_DIR / "case_01")
    resolved_ref = source.resolve_ref("main")
    run_id = "aud_test_success"
    store = EvidenceStore(audit_run_id=run_id, commit_sha=resolved_ref.commit_sha)
    dispatcher = ToolDispatcher(source=source, evidence=store)
    logger = TrajectoryLogger(audit_run_id=run_id, trajectories_dir=tmp_path / "trajectories")

    # Turn 1: model asks to read pyproject.toml
    resp1 = LLMResponse(
        text=None,
        tool_calls=[ToolCall(name="read_file", args={"path": "pyproject.toml"}, call_id="1")],
        usage=Usage(prompt_tokens=100, output_tokens=20, total_tokens=120),
        finish_reason="STOP",
        latency_ms=50,
        retries=0,
        model_id="fake-model",
    )
    # Turn 2: model has no more tool calls
    resp2 = LLMResponse(
        text="I have inspected the manifest.",
        tool_calls=[],
        usage=Usage(prompt_tokens=120, output_tokens=10, total_tokens=130),
        finish_reason="STOP",
        latency_ms=40,
        retries=0,
        model_id="fake-model",
    )
    # Phase 2: model returns structured final JSON
    final_payload = {
        "decision": "GO",
        "executive_summary": "Release is clean.",
        "findings": [
            {
                "category": "release_metadata",
                "title": "Version is valid",
                "severity": "info",
                "claim": "pyproject.toml version matches expected version.",
                "confidence": 0.95,
                "evidence_ids": ["E-001"],
                "recommended_action": "Proceed with release.",
            }
        ],
    }
    resp3 = LLMResponse(
        text=json.dumps(final_payload),
        tool_calls=[],
        usage=Usage(prompt_tokens=200, output_tokens=50, total_tokens=250),
        finish_reason="STOP",
        latency_ms=80,
        retries=0,
        model_id="fake-model",
    )

    fake_llm = FakeLLMClient([resp1, resp2, resp3])
    agent = BaselineAgent(
        llm=fake_llm,
        source=source,
        dispatcher=dispatcher,
        evidence_store=store,
        logger=logger,
        max_turns=5,
    )

    outcome = agent.run(
        repository_url="https://github.com/test/repo",
        resolved_ref=resolved_ref,
        audit_run_id=run_id,
    )

    assert outcome.status == "success"
    assert outcome.failure_reason is None
    assert outcome.findings_payload == final_payload
    assert outcome.usage_prompt_tokens == 420  # 100 + 120 + 200
    assert outcome.usage_output_tokens == 80   # 20 + 10 + 50
    assert outcome.usage_total_tokens == 500   # 120 + 130 + 250
    assert len(store.all()) == 1  # 1 tool call executed
    assert len(logger.steps()) >= 3


def test_baseline_agent_token_breakdown_summation_across_three_turns(tmp_path: Path) -> None:
    source = LocalFixtureSource(CASES_DIR / "case_01")
    resolved_ref = source.resolve_ref("main")
    run_id = "aud_test_tokens"
    store = EvidenceStore(audit_run_id=run_id, commit_sha=resolved_ref.commit_sha)
    dispatcher = ToolDispatcher(source=source, evidence=store)
    logger = TrajectoryLogger(audit_run_id=run_id, trajectories_dir=tmp_path / "trajectories")

    # Turn 1: 50 prompt, 15 output -> 65 total
    resp1 = LLMResponse(
        text=None,
        tool_calls=[ToolCall(name="get_tree", args={}, call_id="1")],
        usage=Usage(prompt_tokens=50, output_tokens=15, total_tokens=65),
        finish_reason="STOP",
        latency_ms=20,
        retries=0,
        model_id="fake-model",
    )
    # Turn 2: 70 prompt, 25 output -> 95 total
    resp2 = LLMResponse(
        text="Done with tree inspection.",
        tool_calls=[],
        usage=Usage(prompt_tokens=70, output_tokens=25, total_tokens=95),
        finish_reason="STOP",
        latency_ms=20,
        retries=0,
        model_id="fake-model",
    )
    # Phase 2: 100 prompt, 40 output -> 140 total
    resp3 = LLMResponse(
        text=json.dumps({"decision": "GO", "executive_summary": "Summed tokens test", "findings": []}),
        tool_calls=[],
        usage=Usage(prompt_tokens=100, output_tokens=40, total_tokens=140),
        finish_reason="STOP",
        latency_ms=30,
        retries=0,
        model_id="fake-model",
    )

    fake_llm = FakeLLMClient([resp1, resp2, resp3])
    agent = BaselineAgent(
        llm=fake_llm,
        source=source,
        dispatcher=dispatcher,
        evidence_store=store,
        logger=logger,
    )

    outcome = agent.run(
        repository_url="https://github.com/test/repo",
        resolved_ref=resolved_ref,
        audit_run_id=run_id,
    )

    assert outcome.status == "success"
    assert outcome.usage_prompt_tokens == 220  # 50 + 70 + 100
    assert outcome.usage_output_tokens == 80   # 15 + 25 + 40
    assert outcome.usage_total_tokens == 300   # 65 + 95 + 140


def test_baseline_agent_phase2_explicit_user_instruction(tmp_path: Path) -> None:
    source = LocalFixtureSource(CASES_DIR / "case_01")
    resolved_ref = source.resolve_ref("main")
    run_id = "aud_test_user_instruction"
    store = EvidenceStore(audit_run_id=run_id, commit_sha=resolved_ref.commit_sha)
    dispatcher = ToolDispatcher(source=source, evidence=store)
    logger = TrajectoryLogger(audit_run_id=run_id, trajectories_dir=tmp_path / "trajectories")

    # Turn 1: model stops tool exploration
    resp1 = LLMResponse(
        text="Finished tools.",
        tool_calls=[],
        usage=Usage(prompt_tokens=10, output_tokens=5, total_tokens=15),
        finish_reason="STOP",
        latency_ms=10,
        retries=0,
        model_id="fake-model",
    )
    # Phase 2: schema generation
    resp2 = LLMResponse(
        text=json.dumps({"decision": "GO", "executive_summary": "All good", "findings": []}),
        tool_calls=[],
        usage=Usage(prompt_tokens=10, output_tokens=5, total_tokens=15),
        finish_reason="STOP",
        latency_ms=10,
        retries=0,
        model_id="fake-model",
    )

    fake_llm = FakeLLMClient([resp1, resp2])
    agent = BaselineAgent(
        llm=fake_llm,
        source=source,
        dispatcher=dispatcher,
        evidence_store=store,
        logger=logger,
    )

    outcome = agent.run(
        repository_url="https://github.com/test/repo",
        resolved_ref=resolved_ref,
        audit_run_id=run_id,
    )

    assert outcome.status == "success"
    assert len(fake_llm.recorded_calls) == 2

    # Verify that in the second call (Phase 2), the last message is a user message
    phase2_messages = fake_llm.recorded_calls[1]["messages"]
    last_msg = phase2_messages[-1]
    assert last_msg.role == "user"
    assert "final release readiness" in last_msg.content.lower()


def test_baseline_agent_max_turns_exhaustion(tmp_path: Path) -> None:
    source = LocalFixtureSource(CASES_DIR / "case_01")
    resolved_ref = source.resolve_ref("main")
    run_id = "aud_test_max_turns"
    store = EvidenceStore(audit_run_id=run_id, commit_sha=resolved_ref.commit_sha)
    dispatcher = ToolDispatcher(source=source, evidence=store)
    logger = TrajectoryLogger(audit_run_id=run_id, trajectories_dir=tmp_path / "trajectories")

    # Repeats tool calls for 2 turns (max_turns=2)
    resp_loop1 = LLMResponse(
        text=None,
        tool_calls=[ToolCall(name="get_repository_metadata", args={}, call_id="1")],
        usage=Usage(prompt_tokens=10, output_tokens=10, total_tokens=20),
        finish_reason="STOP",
        latency_ms=10,
        retries=0,
        model_id="fake-model",
    )
    resp_loop2 = LLMResponse(
        text=None,
        tool_calls=[ToolCall(name="get_tree", args={}, call_id="2")],
        usage=Usage(prompt_tokens=10, output_tokens=10, total_tokens=20),
        finish_reason="STOP",
        latency_ms=10,
        retries=0,
        model_id="fake-model",
    )
    resp_final = LLMResponse(
        text=json.dumps({"decision": "REVIEW", "executive_summary": "Max turns reached", "findings": []}),
        tool_calls=[],
        usage=Usage(prompt_tokens=10, output_tokens=10, total_tokens=20),
        finish_reason="STOP",
        latency_ms=10,
        retries=0,
        model_id="fake-model",
    )

    fake_llm = FakeLLMClient([resp_loop1, resp_loop2, resp_final])
    agent = BaselineAgent(
        llm=fake_llm,
        source=source,
        dispatcher=dispatcher,
        evidence_store=store,
        logger=logger,
        max_turns=2,
    )

    outcome = agent.run(
        repository_url="https://github.com/test/repo",
        resolved_ref=resolved_ref,
        audit_run_id=run_id,
    )

    assert outcome.status == "success"
    assert outcome.findings_payload["decision"] == "REVIEW"


def test_baseline_agent_timeout(tmp_path: Path) -> None:
    source = LocalFixtureSource(CASES_DIR / "case_01")
    resolved_ref = source.resolve_ref("main")
    run_id = "aud_test_timeout"
    store = EvidenceStore(audit_run_id=run_id, commit_sha=resolved_ref.commit_sha)
    dispatcher = ToolDispatcher(source=source, evidence=store)
    logger = TrajectoryLogger(audit_run_id=run_id, trajectories_dir=tmp_path / "trajectories")

    fake_llm = FakeLLMClient([])
    agent = BaselineAgent(
        llm=fake_llm,
        source=source,
        dispatcher=dispatcher,
        evidence_store=store,
        logger=logger,
        deadline_s=-1,  # immediate timeout
    )

    outcome = agent.run(
        repository_url="https://github.com/test/repo",
        resolved_ref=resolved_ref,
        audit_run_id=run_id,
    )

    assert outcome.status == "failed"
    assert outcome.failure_reason == "timeout"


def test_baseline_agent_invalid_json_final_generation(tmp_path: Path) -> None:
    source = LocalFixtureSource(CASES_DIR / "case_01")
    resolved_ref = source.resolve_ref("main")
    run_id = "aud_test_invalid_json"
    store = EvidenceStore(audit_run_id=run_id, commit_sha=resolved_ref.commit_sha)
    dispatcher = ToolDispatcher(source=source, evidence=store)
    logger = TrajectoryLogger(audit_run_id=run_id, trajectories_dir=tmp_path / "trajectories")

    # Turn 1: model stops tool exploration
    resp1 = LLMResponse(
        text="Done inspecting.",
        tool_calls=[],
        usage=Usage(prompt_tokens=10, output_tokens=5, total_tokens=15),
        finish_reason="STOP",
        latency_ms=10,
        retries=0,
        model_id="fake-model",
    )
    # Phase 2: returns non-JSON text
    resp2 = LLMResponse(
        text="Sorry, I am not valid JSON {decision: GO}",
        tool_calls=[],
        usage=Usage(prompt_tokens=10, output_tokens=5, total_tokens=15),
        finish_reason="STOP",
        latency_ms=10,
        retries=0,
        model_id="fake-model",
    )

    fake_llm = FakeLLMClient([resp1, resp2])
    agent = BaselineAgent(
        llm=fake_llm,
        source=source,
        dispatcher=dispatcher,
        evidence_store=store,
        logger=logger,
    )

    outcome = agent.run(
        repository_url="https://github.com/test/repo",
        resolved_ref=resolved_ref,
        audit_run_id=run_id,
    )

    assert outcome.status == "failed"
    assert "Invalid JSON" in (outcome.failure_reason or "")


def test_baseline_agent_tool_error_graceful_handling(tmp_path: Path) -> None:
    source = LocalFixtureSource(CASES_DIR / "case_01")
    resolved_ref = source.resolve_ref("main")
    run_id = "aud_test_tool_error"
    store = EvidenceStore(audit_run_id=run_id, commit_sha=resolved_ref.commit_sha)
    dispatcher = ToolDispatcher(source=source, evidence=store)
    logger = TrajectoryLogger(audit_run_id=run_id, trajectories_dir=tmp_path / "trajectories")

    # Turn 1: model asks for a file that triggers an error (escape attempt)
    resp1 = LLMResponse(
        text=None,
        tool_calls=[ToolCall(name="read_file", args={"path": "../case.json"}, call_id="1")],
        usage=Usage(prompt_tokens=10, output_tokens=5, total_tokens=15),
        finish_reason="STOP",
        latency_ms=10,
        retries=0,
        model_id="fake-model",
    )
    # Turn 2: model sees error and finishes
    resp2 = LLMResponse(
        text="Recognized error.",
        tool_calls=[],
        usage=Usage(prompt_tokens=10, output_tokens=5, total_tokens=15),
        finish_reason="STOP",
        latency_ms=10,
        retries=0,
        model_id="fake-model",
    )
    # Phase 2: returns structured response
    resp3 = LLMResponse(
        text=json.dumps({"decision": "REVIEW", "executive_summary": "Path error occurred", "findings": []}),
        tool_calls=[],
        usage=Usage(prompt_tokens=10, output_tokens=5, total_tokens=15),
        finish_reason="STOP",
        latency_ms=10,
        retries=0,
        model_id="fake-model",
    )

    fake_llm = FakeLLMClient([resp1, resp2, resp3])
    agent = BaselineAgent(
        llm=fake_llm,
        source=source,
        dispatcher=dispatcher,
        evidence_store=store,
        logger=logger,
    )

    outcome = agent.run(
        repository_url="https://github.com/test/repo",
        resolved_ref=resolved_ref,
        audit_run_id=run_id,
    )

    assert outcome.status == "success"
    assert outcome.findings_payload["decision"] == "REVIEW"


def test_baseline_agent_llm_exception_produces_failed_status(tmp_path: Path) -> None:
    source = LocalFixtureSource(CASES_DIR / "case_01")
    resolved_ref = source.resolve_ref("main")
    run_id = "aud_test_llm_exc"
    store = EvidenceStore(audit_run_id=run_id, commit_sha=resolved_ref.commit_sha)
    dispatcher = ToolDispatcher(source=source, evidence=store)
    logger = TrajectoryLogger(audit_run_id=run_id, trajectories_dir=tmp_path / "trajectories")

    fake_llm = FakeLLMClient([LLMServerError("Upstream 500 error")])
    agent = BaselineAgent(
        llm=fake_llm,
        source=source,
        dispatcher=dispatcher,
        evidence_store=store,
        logger=logger,
    )

    outcome = agent.run(
        repository_url="https://github.com/test/repo",
        resolved_ref=resolved_ref,
        audit_run_id=run_id,
    )

    assert outcome.status == "failed"
    assert "Upstream 500 error" in (outcome.failure_reason or "")
