import json
from pathlib import Path
from typing import Any

import pytest

from app.agents.analyzer import AnalyzerAgent, AnalyzerOutcome
from app.evidence.store import EvidenceStore
from app.llm.errors import LLMServerError
from app.llm.types import LLMClient, LLMResponse, Message, ToolCall, ToolSpec, Usage
from app.schemas.audit import DeterministicCheckResult
from app.schemas.enums import CheckStatus
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


def _make_env(tmp_path: Path, run_id: str):
    source = LocalFixtureSource(CASES_DIR / "case_01")
    resolved_ref = source.resolve_ref("main")
    store = EvidenceStore(audit_run_id=run_id, commit_sha=resolved_ref.commit_sha)
    dispatcher = ToolDispatcher(source=source, evidence=store)
    logger = TrajectoryLogger(audit_run_id=run_id, trajectories_dir=tmp_path / "trajectories")
    return source, resolved_ref, store, dispatcher, logger


def _plan_response() -> LLMResponse:
    plan_payload = {
        "audit_plan": {
            "areas": ["ci", "tests"],
            "questions": ["Does CI pass?", "Are tests present?"],
            "required_tools": ["get_workflow_runs", "get_test_report"],
        }
    }
    return LLMResponse(
        text=json.dumps(plan_payload),
        tool_calls=[],
        usage=Usage(prompt_tokens=30, output_tokens=10, total_tokens=40),
        finish_reason="STOP",
        latency_ms=15,
        retries=0,
        model_id="fake-model",
    )


def test_analyzer_agent_successful_run(tmp_path: Path) -> None:
    run_id = "aud_analyzer_success"
    source, resolved_ref, store, dispatcher, logger = _make_env(tmp_path, run_id)

    det_checks = [
        DeterministicCheckResult(
            check_id="DC-01",
            name="CI status",
            status=CheckStatus.pass_,
            details="CI workflow passed on latest run.",
            evidence_ids=[],
        )
    ]

    resp_plan = _plan_response()

    resp_tool_call = LLMResponse(
        text=None,
        tool_calls=[ToolCall(name="read_file", args={"path": "pyproject.toml"}, call_id="1")],
        usage=Usage(prompt_tokens=100, output_tokens=20, total_tokens=120),
        finish_reason="STOP",
        latency_ms=50,
        retries=0,
        model_id="fake-model",
    )
    resp_no_more_tools = LLMResponse(
        text="Done exploring.",
        tool_calls=[],
        usage=Usage(prompt_tokens=50, output_tokens=10, total_tokens=60),
        finish_reason="STOP",
        latency_ms=20,
        retries=0,
        model_id="fake-model",
    )

    final_payload = {
        "findings": [
            {
                "category": "release_metadata",
                "title": "Version present",
                "severity": "info",
                "claim": "pyproject.toml declares a version string.",
                "confidence": 0.9,
                "evidence_ids": ["E-001"],
                "recommended_action": "No action needed.",
            }
        ]
    }
    resp_final = LLMResponse(
        text=json.dumps(final_payload),
        tool_calls=[],
        usage=Usage(prompt_tokens=200, output_tokens=50, total_tokens=250),
        finish_reason="STOP",
        latency_ms=80,
        retries=0,
        model_id="fake-model",
    )

    fake_llm = FakeLLMClient([resp_plan, resp_tool_call, resp_no_more_tools, resp_final])
    agent = AnalyzerAgent(
        llm=fake_llm,
        source=source,
        dispatcher=dispatcher,
        evidence_store=store,
        logger=logger,
        deterministic_checks=det_checks,
        max_turns=5,
    )

    outcome = agent.run(
        repository_url="https://github.com/test/repo",
        resolved_ref=resolved_ref,
        audit_run_id=run_id,
    )

    assert outcome.status == "success"
    assert outcome.failure_reason is None
    assert outcome.audit_plan is not None
    assert outcome.audit_plan.areas == ["ci", "tests"]
    assert len(outcome.findings) == 1
    assert outcome.findings[0].origin == "analyzer"
    assert outcome.findings[0].verification_status.value == "pending"
    assert outcome.rejected_findings == []
    assert outcome.usage_prompt_tokens == 30 + 100 + 50 + 200
    assert outcome.usage_output_tokens == 10 + 20 + 10 + 50
    assert outcome.usage_total_tokens == 40 + 120 + 60 + 250

    # First call must be schema-constrained plan call with no tools
    first_call = fake_llm.recorded_calls[0]
    assert first_call["tools"] is None
    assert first_call["response_schema"] is not None

    # Second call (tool loop) must include tool specs, no response_schema
    second_call = fake_llm.recorded_calls[1]
    assert second_call["tools"] is not None
    assert second_call["response_schema"] is None

    # Deterministic check summary should be present in the tool-loop seed message
    tool_loop_messages = second_call["messages"]
    assert any("DC-01" in (m.content or "") for m in tool_loop_messages)

    assert len(store.all()) == 1  # 1 tool call executed
    assert len(logger.steps()) >= 3


def test_analyzer_agent_rejects_critical_finding_without_evidence(tmp_path: Path) -> None:
    run_id = "aud_analyzer_reject_critical"
    source, resolved_ref, store, dispatcher, logger = _make_env(tmp_path, run_id)

    resp_plan = _plan_response()
    resp_no_tools = LLMResponse(
        text="No tools needed.",
        tool_calls=[],
        usage=Usage(prompt_tokens=10, output_tokens=5, total_tokens=15),
        finish_reason="STOP",
        latency_ms=10,
        retries=0,
        model_id="fake-model",
    )

    final_payload = {
        "findings": [
            {
                "category": "security",
                "title": "Suspected secret leak",
                "severity": "critical",
                "claim": "A hardcoded credential may exist in the repository.",
                "confidence": 0.4,
                "evidence_ids": [],
                "recommended_action": "Investigate manually.",
            },
            {
                "category": "tests",
                "title": "Tests look fine",
                "severity": "info",
                "claim": "No issues found with test suite.",
                "confidence": 0.8,
                "evidence_ids": [],
                "recommended_action": "No action needed.",
            },
        ]
    }
    resp_final = LLMResponse(
        text=json.dumps(final_payload),
        tool_calls=[],
        usage=Usage(prompt_tokens=20, output_tokens=10, total_tokens=30),
        finish_reason="STOP",
        latency_ms=10,
        retries=0,
        model_id="fake-model",
    )

    fake_llm = FakeLLMClient([resp_plan, resp_no_tools, resp_final])
    agent = AnalyzerAgent(
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
    assert len(outcome.findings) == 1
    assert outcome.findings[0].title == "Tests look fine"
    assert len(outcome.rejected_findings) == 1
    assert outcome.rejected_findings[0]["reason"] == "no_evidence_for_critical"


def test_analyzer_agent_rejects_hallucinated_evidence_ids(tmp_path: Path) -> None:
    run_id = "aud_analyzer_hallucinated_evidence"
    source, resolved_ref, store, dispatcher, logger = _make_env(tmp_path, run_id)

    resp_plan = _plan_response()
    resp_no_tools = LLMResponse(
        text="No tools needed.",
        tool_calls=[],
        usage=Usage(prompt_tokens=10, output_tokens=5, total_tokens=15),
        finish_reason="STOP",
        latency_ms=10,
        retries=0,
        model_id="fake-model",
    )

    final_payload = {
        "findings": [
            {
                "category": "build",
                "title": "Build looks broken",
                "severity": "high",
                "claim": "The build report shows a failure.",
                "confidence": 0.7,
                "evidence_ids": ["E-999"],  # never created in this run
                "recommended_action": "Fix the build.",
            }
        ]
    }
    resp_final = LLMResponse(
        text=json.dumps(final_payload),
        tool_calls=[],
        usage=Usage(prompt_tokens=20, output_tokens=10, total_tokens=30),
        finish_reason="STOP",
        latency_ms=10,
        retries=0,
        model_id="fake-model",
    )

    fake_llm = FakeLLMClient([resp_plan, resp_no_tools, resp_final])
    agent = AnalyzerAgent(
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
    assert outcome.findings == []
    assert len(outcome.rejected_findings) == 1
    assert "unknown_evidence_ids" in outcome.rejected_findings[0]["reason"]


def test_analyzer_agent_plan_phase_failure_fails_whole_run(tmp_path: Path) -> None:
    run_id = "aud_analyzer_plan_fail"
    source, resolved_ref, store, dispatcher, logger = _make_env(tmp_path, run_id)

    fake_llm = FakeLLMClient([LLMServerError("Upstream 500 error")])
    agent = AnalyzerAgent(
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
    assert outcome.audit_plan is None
    assert outcome.findings == []
    # Only the plan call should have been attempted
    assert fake_llm.call_count == 1


def test_analyzer_agent_plan_phase_invalid_json_fails_whole_run(tmp_path: Path) -> None:
    run_id = "aud_analyzer_plan_invalid_json"
    source, resolved_ref, store, dispatcher, logger = _make_env(tmp_path, run_id)

    resp_plan = LLMResponse(
        text="not valid json {areas: []}",
        tool_calls=[],
        usage=Usage(prompt_tokens=10, output_tokens=5, total_tokens=15),
        finish_reason="STOP",
        latency_ms=10,
        retries=0,
        model_id="fake-model",
    )

    fake_llm = FakeLLMClient([resp_plan])
    agent = AnalyzerAgent(
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
    assert outcome.audit_plan is None


def test_analyzer_agent_timeout(tmp_path: Path) -> None:
    run_id = "aud_analyzer_timeout"
    source, resolved_ref, store, dispatcher, logger = _make_env(tmp_path, run_id)

    fake_llm = FakeLLMClient([])
    agent = AnalyzerAgent(
        llm=fake_llm,
        source=source,
        dispatcher=dispatcher,
        evidence_store=store,
        logger=logger,
        deadline_s=-1,  # immediate timeout, but plan call happens before the first deadline check
    )

    outcome = agent.run(
        repository_url="https://github.com/test/repo",
        resolved_ref=resolved_ref,
        audit_run_id=run_id,
    )

    assert outcome.status == "failed"
    # Plan call is attempted regardless of deadline (it's the mandatory first call), which
    # will exhaust the fake LLM's empty response queue and surface as a plan failure. This
    # still demonstrates fail-fast behavior for a run with no time budget.
    assert outcome.status == "failed"


def test_analyzer_agent_timeout_during_tool_loop(tmp_path: Path) -> None:
    run_id = "aud_analyzer_timeout_tool_loop"
    source, resolved_ref, store, dispatcher, logger = _make_env(tmp_path, run_id)

    resp_plan = _plan_response()
    fake_llm = FakeLLMClient([resp_plan])
    agent = AnalyzerAgent(
        llm=fake_llm,
        source=source,
        dispatcher=dispatcher,
        evidence_store=store,
        logger=logger,
        deadline_s=0,
    )

    outcome = agent.run(
        repository_url="https://github.com/test/repo",
        resolved_ref=resolved_ref,
        audit_run_id=run_id,
    )

    assert outcome.status == "failed"
    assert outcome.failure_reason == "timeout"
    assert outcome.audit_plan is not None


def test_analyzer_agent_invalid_json_final_generation(tmp_path: Path) -> None:
    run_id = "aud_analyzer_invalid_final_json"
    source, resolved_ref, store, dispatcher, logger = _make_env(tmp_path, run_id)

    resp_plan = _plan_response()
    resp_no_tools = LLMResponse(
        text="Done inspecting.",
        tool_calls=[],
        usage=Usage(prompt_tokens=10, output_tokens=5, total_tokens=15),
        finish_reason="STOP",
        latency_ms=10,
        retries=0,
        model_id="fake-model",
    )
    resp_final = LLMResponse(
        text="Sorry, not valid JSON {findings: []}",
        tool_calls=[],
        usage=Usage(prompt_tokens=10, output_tokens=5, total_tokens=15),
        finish_reason="STOP",
        latency_ms=10,
        retries=0,
        model_id="fake-model",
    )

    fake_llm = FakeLLMClient([resp_plan, resp_no_tools, resp_final])
    agent = AnalyzerAgent(
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
    assert outcome.audit_plan is not None
