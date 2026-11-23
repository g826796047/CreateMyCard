"""微服务测试的公共夹具与测试分层标记。"""

from pathlib import Path

import pytest


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """按目录添加分层标记，并拒绝未归类的业务测试。"""
    for item in items:
        test_path = Path(str(item.path))
        path_parts = set(test_path.parts)
        if test_path.name == "compact_dsl_smoke.py" and test_path.parent.name == "tests":
            item.add_marker(pytest.mark.model_smoke)
            continue
        if "manual" in path_parts:
            item.add_marker(pytest.mark.manual)
            continue
        if "l1" in path_parts:
            item.add_marker(pytest.mark.l1)
            continue
        if "l0" not in path_parts:
            raise pytest.UsageError(f"测试文件尚未归类到 l0、l1 或 manual：{test_path}")
        item.add_marker(pytest.mark.l0)
        if "unit" in path_parts:
            item.add_marker(pytest.mark.unit)
            continue
        if "integration" in path_parts:
            item.add_marker(pytest.mark.integration)
            continue
        raise pytest.UsageError(f"L0 测试尚未归类到 unit 或 integration：{test_path}")


@pytest.fixture
def ids_retry_clock(monkeypatch):
    """IDS 退避使用虚拟单调时钟，不真实等待、不影响全局 time 模块。"""
    import time
    from types import SimpleNamespace

    from services.capabilities import ids_client

    clock = SimpleNamespace(now=0.0, sleeps=[])

    def sleep(delay):
        clock.sleeps.append(delay)
        clock.now += delay

    monkeypatch.setattr(ids_client, "time", SimpleNamespace(
        time=time.time, monotonic=lambda: clock.now, sleep=sleep,
    ))
    return clock


@pytest.fixture
def daily_usage_auth(monkeypatch):
    """每日次数 HTTP 测试使用独立假密钥，不访问真实 STS。"""
    from services.usage import daily_usage_api

    def load_secret(config_key):
        assert config_key == "hag.osms.sk"
        return b"usage-test-secret"

    monkeypatch.setattr(daily_usage_api.sts_config, "get_sts_config", load_secret)


@pytest.fixture
def isolated_theme_stage(monkeypatch):
    """Plan/repair tests use partial artifacts and finite layout-model responses."""
    async def theme(artifact, *_args, **_kwargs):
        return artifact

    monkeypatch.setattr("services.themes.post_layout_theme.theme_artifact", theme)


@pytest.fixture
def existing_generation_policy(monkeypatch):
    """既有创建链路测试显式隔离静态策略；静态专项继续验证默认准入。"""
    from config.config import get_settings

    monkeypatch.setattr(get_settings(), "enable_static_content_generation_policy", False)
