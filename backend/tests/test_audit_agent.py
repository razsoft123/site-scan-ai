from datetime import datetime, timezone
from typing import Any

from google.genai import types

from app.agents import audit_agent
from app.agents.audit_agent import (
    TOOL_DECLARATIONS,
    TOOL_REGISTRY,
    ToolExecutionRecord,
    WorkflowCallbacks,
    run_audit_workflow,
)
from app.schemas.audit import (
    AuditFinding,
    AuditReport,
    FindingCategory,
    FindingSeverity,
    ReleaseStatus,
)
from app.schemas.tool import ToolResult


class FakeModels:
    def __init__(self, responses: list[types.GenerateContentResponse]) -> None:
        self.responses = responses
        self.calls: list[dict[str, Any]] = []

    def generate_content(self, **kwargs: Any) -> types.GenerateContentResponse:
        recorded_call = dict(kwargs)
        recorded_call["contents"] = list(kwargs["contents"])
        self.calls.append(recorded_call)
        if not self.responses:
            raise AssertionError("Gemini was called more times than expected.")
        return self.responses.pop(0)


class FakeClient:
    def __init__(self, responses: list[types.GenerateContentResponse]) -> None:
        self.models = FakeModels(responses)


def model_response(*parts: types.Part) -> types.GenerateContentResponse:
    return types.GenerateContentResponse(
        candidates=[
            types.Candidate(
                content=types.Content(role="model", parts=list(parts)),
            )
        ]
    )


def function_call(name: str, arguments: dict[str, Any]) -> types.Part:
    return types.Part.from_function_call(name=name, args=arguments)


def report_response(report: AuditReport) -> types.GenerateContentResponse:
    return types.GenerateContentResponse(
        parsed=report,
        candidates=[
            types.Candidate(
                content=types.Content(
                    role="model",
                    parts=[types.Part.from_text(text=report.model_dump_json())],
                )
            )
        ],
    )


def empty_report() -> AuditReport:
    return AuditReport(
        overall_score=None,
        release_status=ReleaseStatus.UNKNOWN,
        executive_summary="No deterministic tool evidence was requested.",
        findings=[],
        screenshot_reference=None,
        generated_at=datetime.now(timezone.utc),
        schema_version="1.0",
        is_mock=False,
    )


def metadata_report() -> AuditReport:
    return AuditReport(
        overall_score=None,
        release_status=ReleaseStatus.NEEDS_ATTENTION,
        executive_summary="The metadata inspection found a missing description.",
        findings=[
            AuditFinding(
                id="metadata-description",
                category=FindingCategory.SEO,
                severity=FindingSeverity.MEDIUM,
                title="Meta description is missing",
                description="The metadata result contained no description.",
                evidence={"meta_description": None, "http_status": 200},
                recommended_fix="Add a concise meta description.",
                source_tool="inspect_metadata",
                is_release_blocker=False,
            )
        ],
        screenshot_reference=None,
        generated_at=datetime.now(timezone.utc),
        schema_version="1.0",
        is_mock=False,
    )


def test_tool_declarations_and_registry_are_explicit_and_aligned() -> None:
    expected_names = {
        "inspect_metadata",
        "inspect_security_headers",
        "check_broken_links",
        "inspect_browser",
    }

    assert set(TOOL_REGISTRY) == expected_names
    assert {declaration.name for declaration in TOOL_DECLARATIONS} == expected_names
    for declaration in TOOL_DECLARATIONS:
        assert declaration.description
        assert "Use it" in declaration.description
        assert declaration.parameters_json_schema["required"] == ["url"]
        assert declaration.parameters_json_schema["additionalProperties"] is False


def test_manual_tool_loop_executes_allowlisted_tool_and_returns_report(
    monkeypatch,
) -> None:
    requested_urls: list[str] = []

    def fake_metadata(url: str) -> ToolResult:
        requested_urls.append(url)
        return ToolResult(
            tool="inspect_metadata",
            success=True,
            duration_ms=3,
            data={"http_status": 200, "meta_description": None},
        )

    monkeypatch.setitem(TOOL_REGISTRY, "inspect_metadata", fake_metadata)
    client = FakeClient(
        [
            model_response(
                function_call(
                    "inspect_metadata",
                    {"url": "https://example.com/"},
                )
            ),
            model_response(types.Part.from_text(text="Evidence collected.")),
            report_response(metadata_report()),
        ]
    )
    selected: list[list[str]] = []
    completed: list[ToolExecutionRecord] = []

    report = run_audit_workflow(
        target_url="https://example.com/",
        instruction="Inspect the page metadata.",
        client=client,
        model="gemini-test",
        callbacks=WorkflowCallbacks(
            on_tools_selected=selected.append,
            on_tool_completed=completed.append,
        ),
    )

    assert report == metadata_report().model_copy(
        update={"generated_at": report.generated_at}
    )
    assert requested_urls == ["https://example.com/"]
    assert selected == [["inspect_metadata"]]
    assert completed[0].status == "completed"
    assert completed[0].result.success is True
    assert len(client.models.calls) == 3
    assert client.models.calls[0]["config"].automatic_function_calling.disable is True
    function_calling_config = (
        client.models.calls[0]["config"].tool_config.function_calling_config
    )
    assert function_calling_config.mode == types.FunctionCallingConfigMode.AUTO
    assert function_calling_config.allowed_function_names is None
    assert client.models.calls[-1]["config"].response_schema is None
    assert (
        client.models.calls[-1]["config"].response_json_schema
        == AuditReport.model_json_schema()
    )
    assert client.models.calls[-1]["config"].automatic_function_calling.disable is True

    tool_response_content = client.models.calls[1]["contents"][-1]
    returned_result = tool_response_content.parts[0].function_response.response
    assert returned_result["output"]["tool"] == "inspect_metadata"
    assert returned_result["output"]["data"]["http_status"] == 200


def test_unallowlisted_function_name_is_rejected_and_never_executed() -> None:
    client = FakeClient(
        [
            model_response(function_call("os_system", {"command": "whoami"})),
            model_response(types.Part.from_text(text="No allowed tool ran.")),
            report_response(empty_report()),
        ]
    )
    completed: list[ToolExecutionRecord] = []

    report = run_audit_workflow(
        target_url="https://example.com/",
        instruction="Inspect the site.",
        client=client,
        model="gemini-test",
        callbacks=WorkflowCallbacks(on_tool_completed=completed.append),
    )

    assert report.release_status == ReleaseStatus.UNKNOWN
    assert completed[0].tool_name == "os_system"
    assert completed[0].status == "rejected"
    assert completed[0].result.errors[0].code == "rejected_tool_call"


def test_compositional_rounds_can_run_sync_and_async_tools(monkeypatch) -> None:
    executed: list[str] = []

    def fake_metadata(url: str) -> ToolResult:
        executed.append("inspect_metadata")
        return ToolResult(
            tool="inspect_metadata",
            success=True,
            duration_ms=1,
            data={"http_status": 200},
        )

    async def fake_links(url: str) -> ToolResult:
        executed.append("check_broken_links")
        return ToolResult(
            tool="check_broken_links",
            success=True,
            duration_ms=2,
            data={"checked": 1, "broken": 0},
        )

    monkeypatch.setitem(TOOL_REGISTRY, "inspect_metadata", fake_metadata)
    monkeypatch.setitem(TOOL_REGISTRY, "check_broken_links", fake_links)
    final_report = empty_report().model_copy(
        update={
            "release_status": ReleaseStatus.READY,
            "executive_summary": "The selected deterministic checks completed.",
        }
    )
    client = FakeClient(
        [
            model_response(
                function_call(
                    "inspect_metadata",
                    {"url": "https://example.com/"},
                )
            ),
            model_response(
                function_call(
                    "check_broken_links",
                    {"url": "https://example.com/"},
                )
            ),
            model_response(types.Part.from_text(text="Checks complete.")),
            report_response(final_report),
        ]
    )
    selected: list[list[str]] = []

    report = run_audit_workflow(
        target_url="https://example.com/",
        instruction="Inspect metadata, then check links.",
        client=client,
        model="gemini-test",
        callbacks=WorkflowCallbacks(on_tools_selected=selected.append),
    )

    assert report.release_status == ReleaseStatus.READY
    assert executed == ["inspect_metadata", "check_broken_links"]
    assert selected == [["inspect_metadata"], ["check_broken_links"]]


def test_model_cannot_change_target_or_add_tool_arguments(monkeypatch) -> None:
    executed = False

    def fake_metadata(url: str) -> ToolResult:
        nonlocal executed
        executed = True
        return ToolResult(tool="inspect_metadata", success=True, duration_ms=1)

    monkeypatch.setitem(TOOL_REGISTRY, "inspect_metadata", fake_metadata)
    client = FakeClient(
        [
            model_response(
                function_call(
                    "inspect_metadata",
                    {
                        "url": "https://attacker.example/",
                        "timeout_seconds": 999,
                    },
                )
            ),
            model_response(types.Part.from_text(text="The call was rejected.")),
            report_response(empty_report()),
        ]
    )
    completed: list[ToolExecutionRecord] = []

    run_audit_workflow(
        target_url="https://example.com/",
        instruction="Inspect metadata.",
        client=client,
        model="gemini-test",
        callbacks=WorkflowCallbacks(on_tool_completed=completed.append),
    )

    assert executed is False
    assert completed[0].status == "rejected"


def test_invalid_evidence_report_is_sent_back_for_one_correction(
    monkeypatch,
) -> None:
    monkeypatch.setitem(
        TOOL_REGISTRY,
        "inspect_metadata",
        lambda url: ToolResult(
            tool="inspect_metadata",
            success=True,
            duration_ms=1,
            data={"http_status": 200, "meta_description": None},
        ),
    )
    invalid_report = metadata_report()
    invalid_report.findings[0].source_tool = "inspect_browser"
    client = FakeClient(
        [
            model_response(
                function_call(
                    "inspect_metadata",
                    {"url": "https://example.com/"},
                )
            ),
            model_response(types.Part.from_text(text="Evidence collected.")),
            report_response(invalid_report),
            report_response(metadata_report()),
        ]
    )

    report = run_audit_workflow(
        target_url="https://example.com/",
        instruction="Inspect metadata.",
        client=client,
        model="gemini-test",
    )

    assert report.findings[0].source_tool == "inspect_metadata"
    assert len(client.models.calls) == 4
    correction_prompt = client.models.calls[-1]["contents"][-1].parts[0].text
    assert "violated evidence validation" in correction_prompt


def test_score_and_unverified_screenshot_are_rejected_twice() -> None:
    invalid = empty_report().model_copy(
        update={"overall_score": 95, "screenshot_reference": "invented.png"}
    )
    client = FakeClient(
        [
            model_response(types.Part.from_text(text="No tools needed.")),
            report_response(invalid),
            report_response(invalid),
        ]
    )

    try:
        run_audit_workflow(
            target_url="https://example.com/",
            instruction="Say whether it is ready.",
            client=client,
            model="gemini-test",
        )
    except audit_agent.AuditWorkflowError as exc:
        assert "passed evidence validation" in str(exc)
    else:
        raise AssertionError("Unsupported report evidence was accepted.")
