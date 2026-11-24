"""真实模型冒烟客户端的确定性响应解析测试。"""

from __future__ import annotations

import ast
import inspect
import json
from typing import Any

import pytest
from test.support import model_smoke_client


class _FakeWebSocket:
    def __init__(self, frames: list[dict[str, Any]]) -> None:
        self._frames = [json.dumps(frame, ensure_ascii=False) for frame in frames]
        self.sent: list[str] = []

    async def send(self, payload: str) -> None:
        self.sent.append(payload)

    async def recv(self) -> str:
        if not self._frames:
            raise AssertionError("测试响应帧已经耗尽")
        return self._frames.pop(0)


class _FakeConnection:
    def __init__(self, websocket: _FakeWebSocket) -> None:
        self._websocket = websocket

    async def __aenter__(self) -> _FakeWebSocket:
        return self._websocket

    async def __aexit__(self, *_args: Any) -> None:
        return None


def _payload() -> dict[str, Any]:
    return {
        "session": {
            "sessionId": "smoke-session",
            "interactionId": "create",
        },
        "content": {"userQuery": "欢迎回家"},
    }


def _frame(stream_type: str, content: str = "") -> dict[str, Any]:
    return {
        "errorCode": "0",
        "reply": {
            "streamInfo": {
                "streamType": stream_type,
                "streamContent": content,
            }
        },
    }


def _final_content(request_id: str) -> str:
    return json.dumps(
        {
            "type": "result",
            "tool": "generateWidgetCardCompactDsl",
            "operation": "generateWidgetCardCompactDsl",
            "requestId": request_id,
            "data": {"status": "success", "artifactUrl": "mock://artifact"},
            "status": "success",
            "errorCode": "",
            "error": {},
        },
        ensure_ascii=False,
    )


def test_invoke_generate_has_no_immediate_bare_reraise_handler() -> None:
    source = inspect.getsource(model_smoke_client.invoke_generate)
    tree = ast.parse(source)
    redundant_handlers: list[ast.ExceptHandler] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ExceptHandler):
            continue
        if len(node.body) != 1:
            continue
        statement = node.body[0]
        if isinstance(statement, ast.Raise) and statement.exc is None:
            redundant_handlers.append(node)
    assert redundant_handlers == []


@pytest.mark.asyncio
async def test_model_smoke_client_returns_matching_final_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    websocket = _FakeWebSocket(
        [
            _frame("start"),
            _frame("final", _final_content("smoke-session&create")),
        ]
    )
    monkeypatch.setattr(
        model_smoke_client.websockets,
        "connect",
        lambda *_args, **_kwargs: _FakeConnection(websocket),
    )

    result = await model_smoke_client.invoke_generate(
        "ws://127.0.0.1/generate",
        _payload(),
        timeout_seconds=1,
    )

    assert result.get("status") == "success"
    assert result.get("requestId") == "smoke-session&create"
    assert result.get("data") == {
        "status": "success",
        "artifactUrl": "mock://artifact",
    }
    assert len(result.get("frames", [])) == 2
    assert json.loads(websocket.sent[0]) == _payload()


@pytest.mark.asyncio
async def test_model_smoke_client_rejects_mismatched_request_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    websocket = _FakeWebSocket([_frame("final", _final_content("other&request"))])
    monkeypatch.setattr(
        model_smoke_client.websockets,
        "connect",
        lambda *_args, **_kwargs: _FakeConnection(websocket),
    )

    with pytest.raises(
        model_smoke_client.ModelSmokeClientError,
        match="requestId 与当前请求不匹配",
    ):
        await model_smoke_client.invoke_generate(
            "ws://127.0.0.1/generate",
            _payload(),
            timeout_seconds=1,
        )
