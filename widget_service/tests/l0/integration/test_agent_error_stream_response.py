"""内部错误经插件流出口投影为稳定的 Agent 可见合同。"""

import json

import pytest

from api.routes import _build_plugin_stream_response
from models.service import WidgetWebSocketErrorMessage, WidgetWebSocketResultMessage

_FIELDS = {"message", "retryable", "requiredActions", "agentInstruction", "issues"}


@pytest.mark.parametrize(
    "operation",
    [
        "getWidgetCapabilityOverview",
        "getDataCapabilitySchemas",
        "generateWidgetCard",
        "generateWidgetCardCompactDsl",
        "generateWidgetCardTerseDslNested2",
    ],
)
@pytest.mark.parametrize(
    "path,message,expected",
    [
        ("/size", "取值不合法。", "2x2 或 2x4"),
        ("/candidateDataBindings/0/arguments/limit", "类型不符合要求。", "整数，范围 1 至 5"),
        ("/candidateEventCandidates/0/action", "动作结构不合法。", "对象 {call,args}"),
    ],
)
def test_error_projection_keeps_paths_constraints_and_internal_diagnostics(
    operation: str,
    path: str,
    message: str,
    expected: str,
) -> None:
    issue = {
        "path": path,
        "message": message,
        "expected": expected,
        "repairInstruction": "按 expected 修正本项。",
        "actualType": "string",
        "code": "INVALID",
        "referenceSource": "本轮定义",
    }
    internal = WidgetWebSocketErrorMessage(
        operation=operation,
        errorCode="INVALID_ARGUMENTS",
        error={
            "message": "参数不合法。",
            "details": {
                "stage": "requestValidation",
                "modelCalled": False,
                "retryable": True,
                "requiredActions": ["FIX_AND_RETRY"],
                "agentInstruction": "修正后提交完整参数。",
                "issues": [issue],
            },
        },
    )
    original = internal.model_copy(deep=True)
    response = _build_plugin_stream_response(internal)
    view = json.loads(response.reply.streamInfo.streamContent)
    assert set(view) == _FIELDS
    assert view.get("retryable") is True
    assert view.get("requiredActions") == ["FIX_AND_RETRY"]
    issues = view.get("issues")
    assert isinstance(issues, list) and len(issues) == 1
    assert set(issues[0]) == {"path", "message"}
    assert issues[0].get("path") == path
    assert expected in issues[0].get("message", "")
    assert "按上述要求修正" not in issues[0].get("message", "")
    assert response.errorCode == "0"
    assert internal == original


@pytest.mark.parametrize("status", ["failed", "unsupported"])
def test_failed_result_excludes_artifact_urls_and_generated_content(status: str) -> None:
    internal = WidgetWebSocketResultMessage(
        operation="generateWidgetCardCompactDsl",
        status=status,
        errorCode="VALIDATION_FAILED",
        data={"artifactUrl": "secret-url", "dsl": "secret-dsl", "status": status},
        error={"message": "生成结果无效。"},
    )
    response = _build_plugin_stream_response(internal)
    raw = response.reply.streamInfo.streamContent
    view = json.loads(raw)
    assert set(view) == _FIELDS
    assert view.get("retryable") is False
    assert "secret-url" not in raw and "secret-dsl" not in raw
    if status == "unsupported":
        assert "不支持流程" in view.get("agentInstruction", "")
