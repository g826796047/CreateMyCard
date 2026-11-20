"""从当前检出启动主服务，真实生成并校验一张欢迎卡片。"""

import asyncio
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit

import pytest
import requests
from debug_tools.batch_testing.runner import invoke_generate

from config.config import get_settings
from services.card_validation import ValidationOptions, validate_card
from services.source_artifact_repository import SourceArtifactRepository, calculate_artifact_digest

SERVICE = Path(__file__).resolve().parents[1]
HOST = "127.0.0.1"


@pytest.fixture
def service_url(tmp_path, monkeypatch):
    existing_no_proxy = os.environ.get("NO_PROXY", "")
    local_bypass = ",".join(filter(None, (existing_no_proxy, HOST, "localhost")))
    monkeypatch.setenv("NO_PROXY", local_bypass)
    monkeypatch.setenv("no_proxy", local_bypass)
    with socket.socket() as probe:
        probe.bind((HOST, 0))
        port = probe.getsockname()[1]
    env = {
        **os.environ,
        "WIDGET_SERVICE_SERVER_HOST": HOST,
        "WIDGET_SERVICE_SERVER_PORT": str(port),
        "WIDGET_SERVICE_WORKSPACE_ROOT": str(tmp_path),
        "WIDGET_SERVICE_ENABLE_GENERATION_TRACE_RECORDING": "false",
        "WIDGET_SERVICE_ENABLE_A2UI_MODEL_MOCK": "false",
        "WIDGET_SERVICE_ENABLE_ARTIFACT_VALIDATION": "true",
        "WIDGET_SERVICE_ENABLE_IDS_MOCK": "true",
        "WIDGET_SERVICE_ENABLE_DAILY_USAGE_LIMIT": "false",
        "PYTHONUTF8": "1",
    }
    health_session = requests.Session()
    health_session.trust_env = False
    with subprocess.Popen(
        [sys.executable, str(SERVICE / "cloud/start_websocket_server.py")],
        cwd=SERVICE,
        env=env,
    ) as server:
        try:
            deadline = time.monotonic() + 45
            while time.monotonic() < deadline:
                if server.poll() is not None:
                    pytest.fail(f"主服务启动失败，退出码 {server.returncode}")
                try:
                    health = health_session.get(f"http://{HOST}:{port}/health", timeout=1)
                except requests.ConnectionError:
                    time.sleep(0.2)
                    continue
                health.raise_for_status()
                assert health.json() == {"status": "ok"}
                break
            else:
                pytest.fail("主服务在 45 秒内未就绪")
            yield f"ws://{HOST}:{port}/api/v1/ws/tools/generateWidgetCardCompactDsl"
        finally:
            health_session.close()
            server.terminate()
            try:
                server.wait(timeout=5)
            except subprocess.TimeoutExpired:
                server.kill()


@pytest.mark.asyncio
async def test_generate_and_validate_compact_dsl(service_url, tmp_path):
    query = "欢迎回家"
    payload = {
        "content": {
            "userQuery": query,
            "title": "欢迎回家",
            "description": "静态欢迎卡片",
            "size": "2x2",
            "candidateDataBindings": [],
            "candidateEventCandidates": [],
            "candidateAssetIds": [],
        },
        "deviceInfo": {"prdVer": "11.7.7.300", "romVersion": "7.0"},
        "session": {"sessionId": "compact-smoke", "interactionId": "create"},
        "userAuth": {"user": {"userId": "smoke-test"}},
        "utterance": {"original": query, "type": "text"},
    }
    async with asyncio.timeout(300):
        result = await invoke_generate(service_url, payload, timeout_seconds=60)
    assert result.get("status") == "success", (result.get("errorCode"), result.get("error"))
    data = result.get("data")
    assert isinstance(data, dict)
    assert data.get("status") == "success", data.get("status")
    url = data.get("artifactUrl")
    assert isinstance(url, str) and url
    uploaded = tmp_path / "mock_obs" / Path(urlsplit(url).path).name
    artifact = (
        SourceArtifactRepository().parse_document(uploaded.read_text(encoding="utf-8")).artifact
    )
    assert calculate_artifact_digest(artifact) == data.get("artifactDigest")
    assert artifact.genui.strip()
    options = ValidationOptions(
        capabilities_dir=SERVICE
        / "cloud/data/capabilities"
        / artifact.meta.capabilityRegistryVersion,
        asset_src_url_mapping=get_settings().asset_src_url_mapping,
    )
    report = validate_card(
        artifact=artifact.model_dump(mode="json", exclude_none=True), options=options
    )
    assert report.error_count == 0, report.render_text()
