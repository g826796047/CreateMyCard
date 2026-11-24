"""真实模型冒烟使用的最小 WebSocket 工具客户端。"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import websockets

from test.support.ws_response_parser import parse_legacy_stream_content

_OPERATION = "generateWidgetCardCompactDsl"


class ModelSmokeClientError(RuntimeError):
    """真实模型冒烟客户端收到非法响应。"""


async def invoke_generate(
    endpoint: str,
    payload: dict[str, Any],
    timeout_seconds: float,
) -> dict[str, Any]:
    """调用生成接口并返回解析后的最终业务结果。"""
    request_id = _request_id(payload)
    frames: list[dict[str, Any]] = []
    try:
        async with websockets.connect(
            endpoint,
            open_timeout=15,
            close_timeout=5,
            ping_interval=None,
            ping_timeout=None,
        ) as websocket:
            await websocket.send(json.dumps(payload, ensure_ascii=False))
            while True:
                raw = await asyncio.wait_for(websocket.recv(), timeout_seconds)
                frame = _parse_frame(raw)
                frames.append(frame)
                final_result = _parse_final_result(frame, request_id)
                if final_result is None:
                    continue
                final_result["frames"] = frames
                return final_result
    except TimeoutError as exc:
        raise ModelSmokeClientError("生成接口 WebSocket 调用超时") from exc
    except json.JSONDecodeError as exc:
        raise ModelSmokeClientError("生成接口返回非法 JSON") from exc
    except (OSError, websockets.WebSocketException) as exc:
        error_type = type(exc).__name__
        raise ModelSmokeClientError(f"生成接口 WebSocket 调用失败：{error_type}") from exc


def _request_id(payload: dict[str, Any]) -> str:
    session = payload.get("session")
    if not isinstance(session, dict):
        raise ValueError("请求缺少 session")
    session_id = session.get("sessionId")
    interaction_id = session.get("interactionId")
    if not isinstance(session_id, str) or not session_id:
        raise ValueError("请求缺少 session.sessionId")
    if not isinstance(interaction_id, str) or not interaction_id:
        raise ValueError("请求缺少 session.interactionId")
    return f"{session_id}&{interaction_id}"


def _parse_frame(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, str):
        raise ModelSmokeClientError("生成接口返回非文本 WebSocket 帧")
    frame = json.loads(raw)
    if not isinstance(frame, dict):
        raise ModelSmokeClientError("生成接口返回帧不是对象")
    outer_error = frame.get("errorCode")
    if outer_error not in (None, "", "0", 0):
        raise ModelSmokeClientError(f"生成接口外层错误：{outer_error}")
    return frame


def _parse_final_result(
    frame: dict[str, Any],
    request_id: str,
) -> dict[str, Any] | None:
    reply = frame.get("reply")
    stream_info = reply.get("streamInfo") if isinstance(reply, dict) else None
    if not isinstance(stream_info, dict):
        raise ModelSmokeClientError("生成接口响应帧缺少 streamInfo")
    stream_type = stream_info.get("streamType")
    if stream_type in {"start", "partial", "command"}:
        return None
    if stream_type not in {"final", "final_error"}:
        raise ModelSmokeClientError("生成接口返回未知流类型")
    content = stream_info.get("streamContent")
    if not isinstance(content, str) or not content:
        raise ModelSmokeClientError("生成接口最终帧缺少 streamContent")
    parsed_content = parse_legacy_stream_content(content)
    if parsed_content.get("requestId") != request_id:
        raise ModelSmokeClientError("生成接口 requestId 与当前请求不匹配")
    if parsed_content.get("operation") != _OPERATION:
        raise ModelSmokeClientError("生成接口 operation 与当前请求不匹配")
    data = parsed_content.get("data")
    return {
        "requestId": request_id,
        "status": str(parsed_content.get("status") or "failed"),
        "errorCode": str(parsed_content.get("errorCode") or ""),
        "error": parsed_content.get("error"),
        "data": data if isinstance(data, dict) else {},
    }
