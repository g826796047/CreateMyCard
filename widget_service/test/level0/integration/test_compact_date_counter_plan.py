# -*- coding: utf-8 -*-
# Copyright (c) Huawei Technologies Co., Ltd. 2026-2026. All rights reserved.
import json
from copy import deepcopy
from datetime import date

import pytest

from core.date_counter import DateCounterResult
from models.generation import TaskSpec
from services.compact.planning.compact_date_counter_plan import (
    PRESENTATION,
    apply_date_counter_plan,
)
from services.compact.planning.compact_plan import (
    CompactPlanValidationError,
    build_compact_plan_tool,
    build_compact_recovery_plan,
    compact_plan_recovery_facts,
    compact_plan_required_route,
    evaluate_compact_plan_coverage,
    parse_compact_plan_call,
)
from services.compact.repair.compact_repair_context import joint_repair_contract
from services.generation.generation_pipeline import DesignCompactProcessor, DslProcessingContext
from services.generation.prompt_builder import PromptBuilder

_ROOT = "/data/custom/timer"
_DAYS = f"{_ROOT}/days"
_RELATION = f"{_ROOT}/relationText"
_DATE = f"{_ROOT}/targetDateText"
_INTERVAL = f"{_ROOT}/intervalDays"
_PATHS = {_DAYS, _RELATION, _DATE, _INTERVAL}


def _plan(*, size="2x2", date_priority="must"):
    plan = {
        "layoutHints": ["S-center"],
        "info_required": [
            {"text": "考试", "requirement": "考试", "priority": "must",
             "componentHints": ["DataDisplay"], "dataDisplayRole": "title"},
            {"dataId": _DAYS, "requirement": "天数", "priority": "must",
             "componentHints": ["DataDisplay"], "dataDisplayRole": "value"},
            {"dataId": _RELATION, "requirement": "关系", "priority": "must"},
            {"dataId": _DATE, "requirement": "目标日期", "priority": date_priority,
             "componentHints": ["DataDisplay"], "dataDisplayRole": "subtitle"},
        ],
    }
    if size == "2x4":
        plan["layoutHints"] = ["W-countdown-center"]
        facts = plan["info_required"]
        for fact in facts:
            fact.pop("dataDisplayRole", None)
        facts[0]["componentHints"] = ["SingleLineTitle"]
    return plan


def _counter(relation="countdown", days=3, interval=None):
    return {_ROOT: DateCounterResult(relation, days, date(2026, 11, 20), interval)}


def _task(size="2x2"):
    return {
        "size": size,
        "userQuery": "考试还有几天",
        "dataModelSchema": {"data": {"custom": {"timer": {
            "days": {"type": "integer"},
            "relationText": {"type": "string"},
            "targetDateText": {"type": "string"},
            "intervalDays": {"type": "integer"},
        }}}},
    }


@pytest.mark.parametrize(
    ("size", "days", "layout", "component", "pattern"),
    [
        ("2x2", 1, "S-countdown-pattern", "SCountdown", "bars"),
        ("2x2", 7, "S-countdown-pattern", "SCountdown", "bars"),
        ("2x2", 8, "S-countdown-pattern", "SCountdown", "dots"),
        ("2x2", 31, "S-countdown-pattern", "SCountdown", "dots"),
        ("2x2", 32, "S-center", "DataDisplay", None),
        ("2x4", 7, "W-countdown-pattern", "WCountdown", "bars"),
        ("2x4", 8, "W-countdown-pattern", "WCountdown", "dots"),
        ("2x4", 100, "W-countdown-pattern", "WCountdown", "dots"),
        ("2x4", 101, "W-countdown-center", "InfoDisplay", None),
    ],
)
def test_selects_single_countdown_route_at_thresholds(size, days, layout, component, pattern):
    plan = _plan(size=size)
    if size == "2x2":
        previous_layout = "S-center" if pattern else "S-countdown-pattern"
        plan["layoutHints"] = ["S-title-content", previous_layout]
    else:
        previous_layout = "W-countdown-center" if pattern else "W-countdown-pattern"
        plan["layoutHints"] = ["W-top-bottom", previous_layout]
    original = deepcopy(plan)
    selected = apply_date_counter_plan(plan, size, _PATHS, _counter(days=days))
    assert selected.reason == "selected"
    assert plan == original
    assert selected.plan.get("layoutHints") == [layout]
    facts = selected.plan.get("info_required")
    assert isinstance(facts, list)
    assert all(fact.get("componentHints") == [component] for fact in facts)
    assert facts[1].get("dataDisplayRole") == ("value" if component == "DataDisplay" else None)
    recipe = selected.plan.get(PRESENTATION)
    assert isinstance(recipe, dict)
    assert recipe.get("value") == {"path": _DAYS}
    assert recipe.get("labelRelation") == {"path": _RELATION}
    assert recipe.get("pattern") == pattern
    if pattern is not None:
        assert recipe.get("totalValue") == days
        assert all(fact.get("dataId") != _DATE for fact in facts)
        assert "secondaryInfo" not in recipe
    if pattern is None:
        assert facts[-1].get("dataId") == _DATE
        assert facts[-1].get("priority") == "must"
        assert recipe.get("secondaryInfo") == {"path": _DATE}
        assert recipe.get("unit") == "天"


@pytest.mark.parametrize("interval_days", [None, 46])
def test_wide_dots_use_only_wcountdown_for_relation_and_days(interval_days):
    plan = _plan(size="2x4")
    source_facts = plan.get("info_required")
    assert isinstance(source_facts, list)
    for fact in source_facts:
        if fact.get("dataId") in (_RELATION, _DAYS):
            fact["componentHints"] = ["InfoDisplay", "EmphasizedData"]
    days = 46 if interval_days is None else 1
    selected = apply_date_counter_plan(
        plan, "2x4", _PATHS, _counter(days=days, interval=interval_days),
    )
    assert selected.reason == "selected"
    assert selected.plan.get("layoutHints") == ["W-countdown-pattern"]
    facts = selected.plan.get("info_required")
    assert isinstance(facts, list)
    assert facts[0].get("componentHints") == ["WCountdown"]
    readout_hints = {}
    for fact in facts:
        if fact.get("dataId") in (_RELATION, _DAYS):
            readout_hints[fact.get("dataId")] = fact.get("componentHints")
    assert readout_hints == {_RELATION: ["WCountdown"], _DAYS: ["WCountdown"]}


def test_pattern_keeps_interval_binding_only_as_the_denominator():
    plan = _plan()
    original_facts = plan.get("info_required")
    assert isinstance(original_facts, list)
    original_facts.append({"dataId": _INTERVAL, "requirement": "周期间隔", "priority": "must"})
    counters = _counter(days=2, interval=7)
    selected = apply_date_counter_plan(plan, "2x2", _PATHS, counters)
    updated_facts = selected.plan.get("info_required")
    presentation = selected.plan.get(PRESENTATION)
    assert isinstance(updated_facts, list)
    assert isinstance(presentation, dict)
    assert presentation.get("totalValue") == {"path": _INTERVAL}
    assert selected.plan.get("layoutHints") == ["S-countdown-pattern"]
    dynamic_facts = {fact.get("dataId") for fact in updated_facts if "dataId" in fact}
    assert dynamic_facts == {_DAYS, _RELATION}
    without_interval = apply_date_counter_plan(plan, "2x2", _PATHS - {_INTERVAL}, counters)
    assert without_interval.plan is plan


def test_repeat_threshold_uses_period_not_remaining_days_and_falls_back_without_binding():
    result = _counter(days=2, interval=32)
    narrow = apply_date_counter_plan(_plan(), "2x2", _PATHS, result)
    wide = apply_date_counter_plan(_plan(size="2x4"), "2x4", _PATHS, result)
    without_interval = apply_date_counter_plan(
        _plan(size="2x4"), "2x4", _PATHS - {_INTERVAL}, result,
    )
    assert narrow.plan.get("layoutHints", [])[:1] == ["S-center"]
    assert wide.plan.get("layoutHints", [])[:1] == ["W-countdown-pattern"]
    recipe = wide.plan.get(PRESENTATION)
    assert isinstance(recipe, dict)
    assert recipe.get("pattern") == "dots"
    assert recipe.get("totalValue") == {"path": _INTERVAL}
    assert without_interval.plan.get("layoutHints", [])[:1] == ["W-countdown-center"]


@pytest.mark.parametrize(("size", "layout"), [("2x2", "S-center"), ("2x4", "W-countdown-center")])
def test_countup_uses_number_even_when_only_one_day_has_elapsed(size, layout):
    selected = apply_date_counter_plan(_plan(size=size), size, _PATHS, _counter("countup", days=1))
    assert selected.plan.get("layoutHints", [])[:1] == [layout]


@pytest.mark.parametrize("priority", ["must", "should"])
def test_pattern_removes_date_even_when_the_query_explicitly_requires_display(priority):
    plan = _plan(date_priority=priority)
    task = {**_task(), "userQuery": "考试还有几天，务必显示目标日期"}
    output = json.dumps({"name": "submit_card_plan", "arguments": plan})
    accepted = parse_compact_plan_call(output, task).plan
    selected = apply_date_counter_plan(accepted, "2x2", _PATHS, _counter())
    assert selected.plan.get("layoutHints", [])[:1] == ["S-countdown-pattern"]
    assert _DATE not in json.dumps(selected.plan)
    selected_facts = selected.plan.get("info_required")
    assert isinstance(selected_facts, list)
    assert len(selected_facts) == 3
    assert all(fact.get("priority") == "must" for fact in selected_facts)


@pytest.mark.parametrize(
    "extra",
    [
        {"actionId": "open-app"},
        {"dataId": "/data/another/days"},
        {"dataId": "/data/another/targetDateText"},
        {"text": "提醒带身份证"},
    ],
)
def test_extra_facts_preserve_the_plan(extra):
    plan = _plan()
    facts = plan.get("info_required")
    assert isinstance(facts, list)
    facts.append({**extra, "requirement": "额外要求", "priority": "must"})
    assert apply_date_counter_plan(plan, "2x2", _PATHS, _counter()).plan is plan


def test_missing_auth_multiple_counters_and_assigned_asset_preserve_the_plan():
    plan = _plan()
    counters = _counter()
    multiple = {**counters, "/data/another": DateCounterResult("countdown", 2, date(2026, 11, 20))}
    with_asset = {**plan, "assetAssignments": {"title": {"assetId": "icon"}, "actions": []}}
    assert apply_date_counter_plan(plan, "2x2", _PATHS - {_RELATION}, counters).plan is plan
    assert apply_date_counter_plan(plan, "2x2", _PATHS, multiple).plan is plan
    assert apply_date_counter_plan(plan, "2x2", _PATHS, {}).plan is plan
    assert apply_date_counter_plan(with_asset, "2x2", _PATHS, counters).plan is with_asset


def _source(layout, component, *, include_date=False, include_unit=False, days=0):
    props = {
        "label": "{{ '考试 ' + ${" + _RELATION + "} }}",
        "value": {"path": _DAYS},
    }
    if include_date:
        props["secondaryInfo"] = {"path": _DATE}
    if include_unit:
        props["unit"] = "天"
    rows = [
        ["root", "Layout", {"layout": layout}, ["content"]],
        ["content", component, props],
        [_DAYS, days],
    ]
    return "\n".join(json.dumps(row, ensure_ascii=False) for row in rows)


@pytest.mark.parametrize("interval", [None, 7])
def test_today_keeps_regular_plan_and_coverage_for_zero_days_unit_and_date(interval):
    plan = _plan()
    facts = plan.get("info_required")
    assert isinstance(facts, list)
    facts.append({
        "text": "天", "requirement": "单位", "priority": "must",
        "componentHints": ["DataDisplay"], "dataDisplayRole": "unit",
    })
    selected = apply_date_counter_plan(plan, "2x2", _PATHS, _counter("today", 0, interval))
    assert selected.reason == "today"
    assert selected.plan is plan
    source = _source("S-center", "DataDisplay", include_date=True, include_unit=True)
    assert not evaluate_compact_plan_coverage(source, plan, _task()).errors


@pytest.mark.parametrize("had_rejected_plan", [False, True])
def test_effective_plan_used_for_dsl_repair_and_capacity_recovery_without_date(had_rejected_plan):
    plan = _plan()
    selection = apply_date_counter_plan(plan, "2x2", _PATHS, _counter())
    effective = selection.plan
    task = _task()
    task_model = TaskSpec.model_validate(task)
    messages = [
        {"role": "system", "content": "创建合同"},
        {"role": "user", "content": "考试还剩几天"},
        {"role": "user", "content": "提交计划"},
    ]
    original_submission = json.dumps({"name": "submit_card_plan", "arguments": plan})
    if had_rejected_plan:
        messages.extend([
            {"role": "assistant", "content": original_submission},
            {"role": "user", "content": "旧 Plan 校验失败，请重新提交"},
        ])
    messages.append({"role": "assistant", "content": original_submission})
    original_history = deepcopy(messages)
    continuation = PromptBuilder.build_compact_dsl_continuation(
        messages, task_model, effective, plan_warnings=("保留的告警",),
    )
    assert messages == original_history
    assert continuation[:3] == original_history[:3]
    assistant_messages = [item for item in continuation if item.get("role") == "assistant"]
    assert len(assistant_messages) == 1
    submission = json.loads(assistant_messages[0].get("content", ""))
    assert submission == {"name": "submit_card_plan", "arguments": effective}
    tool_message = json.loads(continuation[4].get("content", ""))
    assert tool_message.get("toolResult") == {
        "name": "submit_card_plan", "ok": True, "warnings": ["保留的告警"],
    }
    context = "\n".join(item.get("content", "") for item in continuation)
    assert context.count(PRESENTATION) == 1
    assert _DATE not in context
    assert "旧 Plan 校验失败" not in context
    assert _DATE not in json.dumps(joint_repair_contract(effective, task, []))

    number = _source("S-center", "DataDisplay", include_unit=True)
    assert not evaluate_compact_plan_coverage(number, effective, task).errors
    retained, omitted = compact_plan_recovery_facts(number, effective, task)
    assert not omitted
    assert len(retained) == 3
    recovery = build_compact_recovery_plan(effective, retained)
    assert recovery is not None
    assert recovery.get(PRESENTATION) == effective.get(PRESENTATION)
    assert recovery.get("layoutHints", [])[:1] == ["S-countdown-pattern"]
    assert _DATE not in json.dumps(recovery)
    wrong_relation = number.replace(_RELATION, "/data/unrelated")
    coverage = evaluate_compact_plan_coverage(wrong_relation, effective, task)
    assert any(_RELATION in error for error in coverage.errors)


def test_number_selection_does_not_infer_a_hard_lock_from_rewritten_hints():
    task = _task()
    original = {
        "layoutHints": ["S-title-content"],
        "info_required": [{
            "dataId": _DAYS, "requirement": "天数", "priority": "must",
            "componentHints": ["EmphasizedData"],
        }],
    }
    assert compact_plan_required_route(original, task) is None
    selected = apply_date_counter_plan(original, "2x2", _PATHS, _counter(days=32))
    assert selected.plan.get("layoutHints", [])[:2] == ["S-center", "S-title-content"]
    assert compact_plan_required_route(selected.plan, task) is None
    fallback = _source("S-center", "DataDisplay", include_date=True, include_unit=True)
    retained, _ = compact_plan_recovery_facts(fallback, selected.plan, task)
    recovery = build_compact_recovery_plan(selected.plan, retained)
    assert recovery is not None
    assert recovery.get("layoutHints") == ["S-center", "S-title-content"]
    assert compact_plan_required_route(recovery, task) is None

    locked = {**original, "layoutHints": ["S-center"], "info_required": [
        {"dataId": _DAYS, "requirement": "天数", "priority": "must",
         "componentHints": ["DataDisplay"]},
    ]}
    original_lock = compact_plan_required_route(locked, task)
    assert original_lock is not None
    selected = apply_date_counter_plan(locked, "2x2", _PATHS, _counter(days=32))
    assert compact_plan_required_route(selected.plan, task) is None


def _locked_countdown_plan():
    return {
        "layoutHints": ["S-center"],
        "info_required": [
            {"dataId": _DAYS, "requirement": "天数", "priority": "must",
             "componentHints": ["DataDisplay"], "dataDisplayRole": "value"},
            {"text": "天", "requirement": "单位", "priority": "must",
             "componentHints": ["DataDisplay"], "dataDisplayRole": "unit"},
        ],
    }


@pytest.mark.parametrize("interval", [None, 7])
def test_short_countdown_overrides_existing_lock_and_retains_unit_fact(interval):
    original = _locked_countdown_plan()
    assert compact_plan_required_route(original, _task()) is not None
    selected = apply_date_counter_plan(original, "2x2", _PATHS, _counter(days=7, interval=interval))
    assert selected.plan.get("layoutHints") == ["S-countdown-pattern"]
    assert compact_plan_required_route(selected.plan, _task()) is None
    facts = selected.plan.get("info_required")
    assert isinstance(facts, list)
    assert facts[-1].get("text") == "天"
    assert facts[-1].get("priority") == "must"
    assert all(fact.get("componentHints") == ["SCountdown"] for fact in facts)


def test_short_countdown_recommendation_does_not_block_other_legal_layouts():
    original = _locked_countdown_plan()
    plan = apply_date_counter_plan(original, "2x2", _PATHS, _counter()).plan
    context = DslProcessingContext(
        size="2x2",
        card_spec={"suggestSize": "2x2"},
        task_spec=TaskSpec.model_validate(_task()).model_dump(mode="json"),
        protocol_profile={"version": "v0.9"},
        compact_plan=plan,
    )
    rows = [
        ["root", "Layout", {"layout": "S-title-dual-content"}, ["title", "primary", "support"]],
        ["title", "SingleLineTitle", {"title": "考试", "fontSize": 12}],
        ["primary", "EmphasizedData", {"value": {"path": _DAYS}, "unit": "天", "fontSize": 30}],
        ["support", "SecondaryBody", {"items": [{"value": "备考"}], "columns": 1, "fontSize": 12}],
        [_DAYS, 3],
    ]
    alternative = "\n".join(json.dumps(row, ensure_ascii=False) for row in rows)
    number = "\n".join((
        _source("S-center", "DataDisplay", include_unit=True, days=3),
        json.dumps([_RELATION, "还剩"], ensure_ascii=False),
    ))
    processor = DesignCompactProcessor()
    for source in (number, alternative):
        result = processor.process(source, context)
        assert not result.errors, result.errors


def test_number_selection_preserves_plan_when_existing_display_role_conflicts():
    original = {"layoutHints": ["S-title-content"], "info_required": [
        {"dataId": _DAYS, "requirement": "天数", "priority": "must"},
        {"dataId": _RELATION, "requirement": "关系", "priority": "must",
         "componentHints": ["DataDisplay"], "dataDisplayRole": "subtitle"},
    ]}
    output = json.dumps({"name": "submit_card_plan", "arguments": original})
    plan = parse_compact_plan_call(output, _task()).plan
    selection = apply_date_counter_plan(plan, "2x2", _PATHS, _counter(days=32))
    assert selection.reason == "incompatible_number_roles"
    assert selection.plan is plan


def test_plan_schema_and_parser_do_not_accept_date_supplement_marker():
    marker = "dateCounterDateSupplement"
    assert marker not in json.dumps(build_compact_plan_tool(_task()))
    plan = _plan()
    facts = plan.get("info_required")
    assert isinstance(facts, list)
    facts[-1][marker] = True
    output = json.dumps({"name": "submit_card_plan", "arguments": plan})
    with pytest.raises(CompactPlanValidationError, match=marker):
        parse_compact_plan_call(output, _task())
