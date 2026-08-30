# path: tests/test_verifier_agent.py
import json
from pathlib import Path
from typing import Any

import pytest

from app.agents.verifier import VerifierAgent
from app.evidence.store import EvidenceStore
from app.llm.errors import LLMServerError
from app.llm.types import LLMClient, LLMResponse, Message, ToolCall, ToolSpec, Usage
from app.schemas.enums import FindingCategory, Severity, VerifierStatus
from app.schemas.findings import Finding
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


def make_finding(finding_id: str = "F-001") -> Finding:
    return Finding(
        id=finding_id,
        audit_run_id="aud_test",
        category=FindingCategory.tests,
        title="Tests are failing on main",
        severity=Severity.critical,
        claim="The test suite has 3 failing tests on the main branch.",
        confidence=0.8,
        evidence_ids=["E-001"],
        recommended_action="Fix failing tests before release.",
        origin="analyzer",
    )


def make_env(tmp_path: Path, run_id: str):
    source = LocalFixtureSource(CASES_DIR / "case_01")
    resolved_ref = source.resolve_ref("main")
    store = EvidenceStore(audit_run_id=run_id, commit_sha=resolved_ref.commit_sha)
    dispatcher = ToolDispatcher(source=source, evidence=store)
    logger = TrajectoryLogger(audit_run_id=run_id, trajectories_dir=tmp_path / "trajectories")
    store.add(
        source_type="test_result",
        source_path="test_report.json",
        summary="Test execution report showing 3 failures",
        payload={"total": 10, "passed": 7, "failed": 3},
    )
    return source, store, dispatcher, logger


def final_llm_response(payload: dict) -> LLMResponse:
    return LLMResponse(
        text=json.dumps(payload),
        tool_calls=[],
        usage=Usage(prompt_tokens=50, output_tokens=20, total_tokens=70),
        finish_reason="STOP",
        latency_ms=30,
        retries=0,
        model_id="fake-model",
    )


def no_tool_calls_response(text: str = "No further tool calls needed.") -> LLMResponse:
    return LLMResponse(
        text=text,
        tool_calls=[],
        usage=Usage(prompt_tokens=30, output_tokens=10, total_tokens=40),
        finish_reason="STOP",
        latency_ms=15,
        retries=0,
        model_id="fake-model",
    )


def test_verifier_agent_successful_confirm(tmp_path: Path) -> None:
    source, store, dispatcher, logger = make_env(tmp_path, "aud_confirm")
    finding = make_finding()

    resp1 = no_tool_calls_response()
    final_payload = {
        "finding_id": "F-001",
        "status": "confirmed",
        "confidence": 0.9,
        "supporting_evidence": ["E-001"],
        "contradicting_evidence": [],
        "reason_summary": "Test report confirms 3 failing tests.",
    }
    resp2 = final_llm_response(final_payload)

    fake_llm = FakeLLMClient([resp1, resp2])
    agent = VerifierAgent(
        llm=fake_llm,
        source=source,
        dispatcher=dispatcher,
        evidence_store=store,
        logger=logger,
    )

    result = agent.verify(finding, audit_run_id="aud_confirm")

    assert result.status == VerifierStatus.confirmed
    assert result.finding_id == "F-001"
    assert result.verifier_error is None
    assert result.supporting_evidence == ["E-001"]

    # First call must not include the analyst's reasoning, only finding+evidence
    first_call_messages = fake_llm.recorded_calls[0]["messages"]
    first_user_content = first_call_messages[0].content
    assert "F-001" in first_user_content
    assert "E-001" in first_user_content


def test_verifier_agent_successful_reject(tmp_path: Path) -> None:
    source, store, dispatcher, logger = make_env(tmp_path, "aud_reject")
    finding = make_finding("F-002")

    resp1 = no_tool_calls_response()
    final_payload = {
        "finding_id": "F-002",
        "status": "rejected",
        "confidence": 0.85,
        "supporting_evidence": [],
        "contradicting_evidence": ["E-001"],
        "reason_summary": "Evidence shows all tests passed; claim is false.",
    }
    resp2 = final_llm_response(final_payload)

    fake_llm = FakeLLMClient([resp1, resp2])
    agent = VerifierAgent(
        llm=fake_llm,
        source=source,
        dispatcher=dispatcher,
        evidence_store=store,
        logger=logger,
    )

    result = agent.verify(finding, audit_run_id="aud_reject")

    assert result.status == VerifierStatus.rejected
    assert result.contradicting_evidence == ["E-001"]
    assert result.verifier_error is None


def test_verifier_agent_uncertain_from_model(tmp_path: Path) -> None:
    source, store, dispatcher, logger = make_env(tmp_path, "aud_uncertain")
    finding = make_finding("F-003")

    resp1 = no_tool_calls_response()
    final_payload = {
        "finding_id": "F-003",
        "status": "uncertain",
        "confidence": 0.4,
        "supporting_evidence": ["E-001"],
        "contradicting_evidence": [],
        "reason_summary": "Evidence is ambiguous about which branch was tested.",
    }
    resp2 = final_llm_response(final_payload)

    fake_llm = FakeLLMClient([resp1, resp2])
    agent = VerifierAgent(
        llm=fake_llm,
        source=source,
        dispatcher=dispatcher,
        evidence_store=store,
        logger=logger,
    )

    result = agent.verify(finding, audit_run_id="aud_uncertain")

    assert result.status == VerifierStatus.uncertain
    assert result.verifier_error is None
    assert result.reason_summary == "Evidence is ambiguous about which branch was tested."


def test_verifier_agent_llm_exception_on_final_call_forces_uncertain(tmp_path: Path) -> None:
    source, store, dispatcher, logger = make_env(tmp_path, "aud_llm_exc")
    finding = make_finding("F-004")

    resp1 = no_tool_calls_response()
    fake_llm = FakeLLMClient([resp1, LLMServerError("Upstream 500 error")])
    agent = VerifierAgent(
        llm=fake_llm,
        source=source,
        dispatcher=dispatcher,
        evidence_store=store,
        logger=logger,
    )

    result = agent.verify(finding, audit_run_id="aud_llm_exc")

    assert result.status == VerifierStatus.uncertain
    assert result.verifier_error is not None
    assert "Upstream 500 error" in result.verifier_error
    assert result.finding_id == "F-004"


def test_verifier_agent_invalid_json_forces_uncertain(tmp_path: Path) -> None:
    source, store, dispatcher, logger = make_env(tmp_path, "aud_invalid_json")
    finding = make_finding("F-005")

    resp1 = no_tool_calls_response()
    resp2 = LLMResponse(
        text="not valid json {status: confirmed}",
        tool_calls=[],
        usage=Usage(prompt_tokens=10, output_tokens=5, total_tokens=15),
        finish_reason="STOP",
        latency_ms=10,
        retries=0,
        model_id="fake-model",
    )

    fake_llm = FakeLLMClient([resp1, resp2])
    agent = VerifierAgent(
        llm=fake_llm,
        source=source,
        dispatcher=dispatcher,
        evidence_store=store,
        logger=logger,
    )

    result = agent.verify(finding, audit_run_id="aud_invalid_json")

    assert result.status == VerifierStatus.uncertain
    assert result.verifier_error is not None
    assert "Invalid JSON" in result.verifier_error
    assert result.finding_id == "F-005"


def test_verifier_agent_mismatched_finding_id_forces_uncertain(tmp_path: Path) -> None:
    source, store, dispatcher, logger = make_env(tmp_path, "aud_mismatch")
    finding = make_finding("F-006")

    resp1 = no_tool_calls_response()
    final_payload = {
        "finding_id": "F-999",  # wrong id, or a smuggled new finding
        "status": "confirmed",
        "confidence": 0.9,
        "supporting_evidence": ["E-001"],
        "contradicting_evidence": [],
        "reason_summary": "Trying to sneak in a different finding id.",
    }
    resp2 = final_llm_response(final_payload)

    fake_llm = FakeLLMClient([resp1, resp2])
    agent = VerifierAgent(
        llm=fake_llm,
        source=source,
        dispatcher=dispatcher,
        evidence_store=store,
        logger=logger,
    )

    result = agent.verify(finding, audit_run_id="aud_mismatch")

    assert result.status == VerifierStatus.uncertain
    assert result.verifier_error is not None
    assert "mismatch" in result.verifier_error.lower()
    assert result.finding_id == "F-006"


def test_verifier_agent_extra_tool_call_path(tmp_path: Path) -> None:
    source, store, dispatcher, logger = make_env(tmp_path, "aud_tool_call")
    finding = make_finding("F-007")

    # Model requests one extra tool call to re-check evidence before finalizing
    resp1 = LLMResponse(
        text=None,
        tool_calls=[ToolCall(name="get_test_report", args={}, call_id="1")],
        usage=Usage(prompt_tokens=40, output_tokens=15, total_tokens=55),
        finish_reason="STOP",
        latency_ms=20,
        retries=0,
        model_id="fake-model",
    )
    resp2 = no_tool_calls_response("Checked the test report directly.")
    final_payload = {
        "finding_id": "F-007",
        "status": "confirmed",
        "confidence": 0.92,
        "supporting_evidence": ["E-001"],
        "contradicting_evidence": [],
        "reason_summary": "Re-checked test report; failures are confirmed.",
    }
    resp3 = final_llm_response(final_payload)

    fake_llm = FakeLLMClient([resp1, resp2, resp3])
    agent = VerifierAgent(
        llm=fake_llm,
        source=source,
        dispatcher=dispatcher,
        evidence_store=store,
        logger=logger,
        max_extra_tool_calls=2,
    )

    result = agent.verify(finding, audit_run_id="aud_tool_call")

    assert result.status == VerifierStatus.confirmed
    assert result.verifier_error is None
    assert fake_llm.call_count == 3

    # Confirm the tool result was fed back into the conversation before the final call
    final_call_messages = fake_llm.recorded_calls[2]["messages"]
    tool_messages = [m for m in final_call_messages if m.role == "tool"]
    assert len(tool_messages) == 1
    assert tool_messages[0].tool_name == "get_test_report"


def test_verifier_agent_deadline_exceeded_forces_uncertain(tmp_path: Path) -> None:
    source, store, dispatcher, logger = make_env(tmp_path, "aud_timeout")
    finding = make_finding("F-008")

    fake_llm = FakeLLMClient([])
    agent = VerifierAgent(
        llm=fake_llm,
        source=source,
        dispatcher=dispatcher,
        evidence_store=store,
        logger=logger,
        deadline_s=-1,
    )

    result = agent.verify(finding, audit_run_id="aud_timeout")

    assert result.status == VerifierStatus.uncertain
    assert result.verifier_error == "timeout"
    assert fake_llm.call_count == 0
