"""DSL 加载同尺寸完整案例，总开关关闭时不追加案例。"""

import json
import re

import pytest

from config.config import get_settings
from models.generation import TaskSpec
from services.card_validation import ValidationOptions, validate_card, validate_compact_dsl
from services.compact.compact_dsl_a2ui_converter import convert_compact_dsl_to_a2ui
from services.compact.planning.compact_date_counter_plan import PRESENTATION
from services.generation.prompt_builder import PromptBuilder
from services.protocols.protocol_registry import DESIGN_COMPACT_PROFILE_ID, A2UIProtocolRegistry


@pytest.mark.parametrize("size", ["2x2", "2x4"])
def test_dsl_uses_all_same_size_examples(monkeypatch, size):
    monkeypatch.setattr(get_settings(), "enable_design_compact_few_shots", True)
    task = TaskSpec(size=size, userQuery="显示天气", dataModelSchema={"data": {}})
    source = A2UIProtocolRegistry.read_design_few_shot(DESIGN_COMPACT_PROFILE_ID, size)
    context = PromptBuilder._compact_few_shot_context(task)
    identifiers = set(re.findall(r"\b2x[24]-V\d+\b", source))
    assert identifiers
    assert source in context
    assert set(re.findall(r"\b2x[24]-V\d+\b", context)) == identifiers
    other = "2x4" if size == "2x2" else "2x2"
    assert other + "-V" not in context
    assert "countdown-pattern" not in context


@pytest.mark.parametrize("size", ["2x2", "2x4"])
def test_examples_master_switch_still_disables_examples(monkeypatch, size):
    monkeypatch.setattr(get_settings(), "enable_design_compact_few_shots", False)
    task = TaskSpec(size=size, userQuery="显示天气", dataModelSchema={"data": {}})
    assert PromptBuilder._compact_few_shot_context(task) == ""


@pytest.mark.parametrize(
    ("size", "layout", "component_type", "example_id", "pattern", "counter_root"),
    [
        ("2x2", "S-center", "DataDisplay", "2x2-V01", None, "/data/dateCounter"),
        ("2x4", "W-countdown-center", "InfoDisplay", "2x4-V40", None, "/data/dateCounter"),
        ("2x2", "S-countdown-pattern", "SCountdown", "2x2-V20", "bars", "/data/swimCounter"),
        ("2x4", "W-countdown-pattern", "WCountdown", "2x4-V41", "dots", "/data/tripCounter"),
    ],
)
def test_dsl_injects_only_the_selected_countdown_example(
    monkeypatch, size, layout, component_type, example_id, pattern, counter_root,
):
    settings = get_settings()
    monkeypatch.setattr(settings, "enable_design_compact_few_shots", True)
    task = TaskSpec(size=size, userQuery="做张倒计时卡", dataModelSchema={"data": {}})
    presentation = {"layout": layout, "component": component_type}
    if pattern:
        presentation["pattern"] = pattern
    plan = {PRESENTATION: presentation, "layoutHints": [layout], "info_required": []}
    messages = [
        {"role": "system", "content": "创建合同"},
        {"role": "user", "content": "倒计时卡片"},
        {"role": "user", "content": "提交计划"},
        {"role": "assistant", "content": "{}"},
    ]
    continued = PromptBuilder.build_compact_dsl_continuation(messages, task, plan)
    context = continued[-1].get("content", "")
    assert re.findall(r"\b2x[24]-V\d+\b", context) == [example_id]
    if pattern:
        assert "本轮日期选型已开放" in context
        assert "relationValue" in context
    match = re.search(r"```json\s*\n(.*?)\n```", context, re.S)
    dsl_match = re.search(r"```genui\s*\n(.*?)\n```", context, re.S)
    assert match is not None
    assert dsl_match is not None
    example_task = json.loads(match.group(1))
    source = dsl_match.group(1)
    rows = [json.loads(line) for line in source.splitlines()]
    assert rows[0][2].get("layout") == layout
    assert rows[1][1] == component_type
    card = {"suggestSize": size}
    if pattern:
        assert not any("targetDateText" in json.dumps(row) for row in rows)
        arguments = {"targetDate": "2027-01-02"}
        if pattern == "bars":
            arguments["repeat"] = {"unit": "week"}
            assert rows[1][2].get("totalValue") == {"path": counter_root + "/intervalDays"}
        else:
            assert rows[1][2].get("totalValue") == 38
        card["dataBindings"] = [{
            "capabilityId": "GetDateCounter", "arguments": arguments, "writeResultTo": counter_root,
        }]
    result = validate_compact_dsl(
        source, task_spec=example_task, card_spec=card, enforce_model_component_types=True,
    )
    assert not result.warnings
    converted = convert_compact_dsl_to_a2ui(
        source, size=size, protocol_profile={"version": "v0.9", "appVersion": "11.9.9.342"},
    )
    report = validate_card(
        dsl_text=converted,
        effective_capabilities={"asset": example_task.get("assetCandidates", [])},
        options=ValidationOptions(stage="hard"),
    )
    assert not any(diagnostic.severity == "error" for diagnostic in report.diagnostics)
    monkeypatch.setattr(settings, "enable_design_compact_few_shots", False)
    assert PromptBuilder._compact_few_shot_context(task, compact_plan=plan) == ""
