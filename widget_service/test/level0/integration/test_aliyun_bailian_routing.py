"""百炼通道经统一模型运行时参与主备路由的组件合同。"""

import httpx
import pytest

from config.config import Settings
from custom.aliyun_bailian_transport import AliyunBailianHttpTransport
from custom.model_runtime import ModelExecutionRuntime
from custom.model_transport import ModelTransportError
from custom.unified_model_client import UnifiedModelClient


def _settings(**overrides: object) -> Settings:
    values = {
        "_env_file": None,
        "openai_master_client": "aliyun_bailian",
        "aliyun_bailian_base_url": "https://deployment.example/compatible-mode/v1",
        "aliyun_bailian_api_key": "bailian-test-secret",
        "aliyun_bailian_model": "deepseek-v4.1-flash",
        "deepseek_official_http_api_key": "different-official-secret",
    }
    values.update(overrides)
    return Settings(**values)


@pytest.mark.asyncio
async def test_bailian_uses_runtime_routing_and_closes_owned_client() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": "OK"}}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        settings = _settings(enable_model_failure_retry=False)
        transport = AliyunBailianHttpTransport(settings, http_client=client)
        runtime = ModelExecutionRuntime(settings, aliyun_bailian_transport=transport)
        try:
            router = UnifiedModelClient(settings, runtime, operation_name="compact")
            assert await router.generate("openai", [], None, phase="initial") == "OK"
        finally:
            await runtime.aclose()
    owned = AliyunBailianHttpTransport(_settings())
    await owned.aclose()
    assert owned.http_client.is_closed


@pytest.mark.asyncio
async def test_bailian_can_be_explicit_fallback_without_changing_retry_contract() -> None:
    calls = []

    class FailedOfficial:
        async def generate(self, messages, request_context=None):
            calls.append("official")
            raise ModelTransportError("official unavailable", code="MODEL_HTTP_STATUS")

        async def aclose(self):
            return None

    def handler(_: httpx.Request) -> httpx.Response:
        calls.append("bailian")
        return httpx.Response(200, json={"choices": [{"message": {"content": "recovered"}}]})

    settings = _settings(
        openai_master_client="deepseek_official_http",
        openai_fallback_client="aliyun_bailian",
        enable_model_failure_retry=True,
        enable_openai_fallback=True,
        model_failure_max_retry_attempts=0,
        fallback_model_failure_max_retry_attempts=0,
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        runtime = ModelExecutionRuntime(
            settings,
            deepseek_official_http_transport=FailedOfficial(),
            aliyun_bailian_transport=AliyunBailianHttpTransport(settings, http_client=client),
        )
        try:
            router = UnifiedModelClient(settings, runtime, operation_name="compact")
            assert await router.generate("openai", [], None, phase="initial") == "recovered"
            assert router.retry_count == 1
        finally:
            await runtime.aclose()
    assert calls == ["official", "bailian"]
