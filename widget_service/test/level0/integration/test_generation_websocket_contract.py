"""进程内 WebSocket 路由与生成响应序列化的组件合同。"""

from fastapi.testclient import TestClient
from test.support.ws_response_parser import parse_legacy_stream_content

from api.schemas import GenerateWidgetCardResponse
from services.generation.widget_generation_service import WidgetGenerationService
from start_websocket_server import app


def _arguments() -> dict:
    return {
        "uid": "l0-websocket-contract",
        "device": {"romVersion": "7.0"},
        "userQuery": "展示我的日程",
        "title": "日程",
        "description": "日程安排",
    }


def _receive_final_result(websocket) -> dict:
    while True:
        frame = websocket.receive_json()
        reply = frame.get("reply")
        assert isinstance(reply, dict)
        stream_info = reply.get("streamInfo")
        assert isinstance(stream_info, dict)
        if stream_info.get("streamType") != "final":
            continue
        content = stream_info.get("streamContent")
        assert isinstance(content, str)
        return parse_legacy_stream_content(content)


def test_generation_response_keeps_public_contract_through_websocket(monkeypatch) -> None:
    async def generate(_service, _request, **_kwargs) -> GenerateWidgetCardResponse:
        return GenerateWidgetCardResponse(
            status="success",
            suggestSize="2x2",
            message="仅供服务内部使用",
            artifactUrl="https://artifact.test/l0-contract",
        )

    monkeypatch.setattr(
        WidgetGenerationService,
        "generate_widget_card_compact_dsl",
        generate,
    )

    with TestClient(app).websocket_connect(
        "/api/v1/ws/tools/generateWidgetCardCompactDsl"
    ) as websocket:
        websocket.send_json({"arguments": _arguments()})
        result = _receive_final_result(websocket)

    assert result.get("type") == "result"
    assert result.get("operation") == "generateWidgetCardCompactDsl"
    assert result.get("status") == "success"
    assert result.get("errorCode") == ""

    data = result.get("data")
    assert isinstance(data, dict)
    assert data.get("suggestSize") == "2x2"
    assert data.get("artifactUrl") == "https://artifact.test/l0-contract"
    assert "message" not in data
    instruction = data.get("agentInstruction")
    assert isinstance(instruction, str)
    assert instruction
