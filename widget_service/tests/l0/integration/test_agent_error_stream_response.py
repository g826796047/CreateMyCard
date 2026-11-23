"""内部错误经 WebSocket 公共入口投影为稳定的 Agent 可见合同。"""

import json

import pytest
from fastapi.testclient import TestClient

from api.schemas import GenerateWidgetCardResponse
from models.preflight import (
    AgentAction,
    GenerationPreflightError,
    GenerationPreflightResult,
    PreflightIssue,
)
from services.generation.widget_generation_service import WidgetGenerationService
from start_websocket_server import app

_FIELDS = {"message", "retryable", "requiredActions", "agentInstruction", "issues"}
_PATH = "/api/v1/ws/tools/generateWidgetCardCompactDsl"


def _arguments() -> dict:
    return {
        "uid": "agent-error-stream-test",
        "device": {"romVersion": "7.0"},
        "userQuery": "展示我的日程",
        "title": "日程",
        "description": "日程安排",
    }


def _receive_final_content(websocket) -> tuple[dict, str]:
    while True:
        response = websocket.receive_json()
        reply = response.get("reply")
        assert isinstance(reply, dict)
        stream_info = reply.get("streamInfo")
        assert isinstance(stream_info, dict)
        if stream_info.get("streamType") != "final":
            continue
        raw = stream_info.get("streamContent")
        assert isinstance(raw, str)
        return json.loads(raw), raw


def _preflight_error(issue: PreflightIssue) -> GenerationPreflightError:
    result = GenerationPreflightResult(
        effective_bindings=(),
        effective_data_capabilities=(),
        effective_events=(),
        effective_assets=(),
        removed_capabilities=(),
        blocking_issues=(issue,),
        warnings=(),
        card_spec=None,
        task_spec=None,
    )
    return GenerationPreflightError(result)


@pytest.mark.parametrize(
    "path,message,expected",
    [
        ("/size", "取值不合法。", "2x2 或 2x4"),
        ("/candidateDataBindings/0/arguments/limit", "类型不符合要求。", "整数，范围 1 至 5"),
        ("/candidateEventCandidates/0/action", "动作结构不合法。", "对象 {call,args}"),
    ],
)
def test_error_projection_keeps_paths_and_constraints_through_websocket(
    monkeypatch: pytest.MonkeyPatch,
    path: str,
    message: str,
    expected: str,
) -> None:
    issue = PreflightIssue(
        path=path,
        message=message,
        expected=expected,
        repairInstruction="按 expected 修正本项。",
        actualType="string",
        code="INVALID",
        referenceSource="本轮定义",
        agentAction=AgentAction.FIX_AND_RETRY,
        retryable=True,
    )

    async def generate(*_args, **_kwargs):
        raise _preflight_error(issue)

    monkeypatch.setattr(
        WidgetGenerationService,
        "generate_widget_card_compact_dsl",
        generate,
    )
    with TestClient(app).websocket_connect(_PATH) as websocket:
        websocket.send_json({"arguments": _arguments()})
        view, _raw = _receive_final_content(websocket)

    assert set(view) == _FIELDS
    assert view.get("retryable") is True
    assert view.get("requiredActions") == ["FIX_AND_RETRY"]
    issues = view.get("issues")
    assert isinstance(issues, list) and len(issues) == 1
    assert set(issues[0]) == {"path", "message"}
    assert issues[0].get("path") == path
    assert expected in issues[0].get("message", "")
    assert "按上述要求修正" not in issues[0].get("message", "")


@pytest.mark.parametrize("status", ["failed", "unsupported"])
def test_failed_result_excludes_artifact_urls_and_generated_content(
    monkeypatch: pytest.MonkeyPatch,
    status: str,
) -> None:
    async def generate(*_args, **_kwargs):
        return GenerateWidgetCardResponse(
            status=status,
            artifactUrl="secret-url",
            suggestSize="2x2",
            message="secret-dsl",
            errorCode="VALIDATION_FAILED",
        )

    monkeypatch.setattr(
        WidgetGenerationService,
        "generate_widget_card_compact_dsl",
        generate,
    )
    with TestClient(app).websocket_connect(_PATH) as websocket:
        websocket.send_json({"arguments": _arguments()})
        view, raw = _receive_final_content(websocket)

    assert set(view) == _FIELDS
    assert view.get("retryable") is False
    assert "secret-url" not in raw and "secret-dsl" not in raw
    if status == "unsupported":
        assert "不支持流程" in view.get("agentInstruction", "")
