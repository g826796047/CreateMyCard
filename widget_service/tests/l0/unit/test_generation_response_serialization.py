"""生成响应模型的稳定序列化单元测试。"""

import pytest

from api.schemas import GenerateWidgetCardResponse
from core.errors import GenerationStatus
from models.service import WidgetWebSocketErrorMessage


@pytest.mark.parametrize("status", list(GenerationStatus))
def test_public_response_excludes_internal_message(status: GenerationStatus) -> None:
    response = GenerateWidgetCardResponse(
        status=status,
        suggestSize="2x2",
        message="内部生成结果说明",
        errorCode="TEST_ERROR" if status == GenerationStatus.FAILED else "",
    )

    payload = response.model_dump(mode="json", exclude_none=True)

    assert payload.get("status") == status.value
    assert payload.get("suggestSize") == "2x2"
    assert "message" not in payload

    if status in (GenerationStatus.SUCCESS, GenerationStatus.DEGRADED):
        instruction = payload.get("agentInstruction")
        assert isinstance(instruction, str)
        assert instruction
    else:
        assert "agentInstruction" not in payload


def test_public_response_omits_empty_optional_feedback() -> None:
    response = GenerateWidgetCardResponse(
        status=GenerationStatus.UNCHANGED,
        suggestSize="2x2",
        message="内部说明",
    )

    payload = response.model_dump(mode="json", exclude_none=True)

    assert "editFeedback" not in payload
    assert "omittedRequirements" not in payload


def test_public_response_preserves_non_empty_optional_feedback() -> None:
    response = GenerateWidgetCardResponse(
        status=GenerationStatus.UNCHANGED,
        suggestSize="2x2",
        message="内部说明",
        editFeedback="未产生有效修改",
        omittedRequirements=["缺少天气数据"],
    )

    payload = response.model_dump(mode="json", exclude_none=True)

    assert payload.get("editFeedback") == "未产生有效修改"
    assert payload.get("omittedRequirements") == ["缺少天气数据"]


def test_serialization_schema_excludes_internal_message() -> None:
    schema = GenerateWidgetCardResponse.model_json_schema(mode="serialization")
    properties = schema.get("properties")
    assert isinstance(properties, dict)
    assert "message" not in properties


def test_websocket_error_model_preserves_structured_diagnostic() -> None:
    response = WidgetWebSocketErrorMessage(
        operation="generateWidgetCardCompactDsl",
        errorCode="INVALID_ARGUMENTS",
        error={"message": "参数格式错误"},
    )

    payload = response.model_dump(mode="json", exclude_none=True)
    assert payload.get("error") == {"message": "参数格式错误"}
