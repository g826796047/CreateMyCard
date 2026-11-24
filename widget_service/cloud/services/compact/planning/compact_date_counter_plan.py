# -*- coding: utf-8 -*-
# Copyright (c) Huawei Technologies Co., Ltd. 2026-2026. All rights reserved.
"""根据日期试算结果调整已接受的单目标 Plan。"""

import re
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from core.date_counter import DateCounterResult
from services.compact.components.compact_high_level_components import ComponentRow

PRESENTATION = "dateCounterPresentation"


@dataclass(frozen=True)
class _Routes:
    number_layout: str
    number_component: str
    pattern_layout: str
    pattern_component: str
    dots_limit: int


_ROUTES = {
    "2x2": _Routes("S-center", "DataDisplay", "S-countdown-pattern", "SCountdown", 31),
    "2x4": _Routes("W-countdown-center", "InfoDisplay", "W-countdown-pattern", "WCountdown", 100),
}
DATE_COUNTER_LAYOUTS = (
    frozenset(route.number_layout for route in _ROUTES.values())
    | frozenset(route.pattern_layout for route in _ROUTES.values())
)
_DATE_COUNTER_LABEL_COMPONENTS = frozenset({
    "DataDisplay", "InfoDisplay", "SCountdown", "WCountdown",
})
_DEDICATED_COMPONENTS = _DATE_COUNTER_LABEL_COMPONENTS - {"DataDisplay"}
_DATE_COUNTER_LABEL = re.compile(
    r"""\{\{\s*(?:"(?P<double>[^"\\\r\n]*)"|'(?P<single>[^'\\\r\n]*)')"""
    r"\s*\+\s*\$\{/[^{}\s]+/relationText\}\s*\}\}"
)


@dataclass(frozen=True)
class DateCounterPlanResult:
    plan: dict[str, Any]
    reason: str


def _is_title(fact: dict[str, Any]) -> bool:
    if fact.get("dataDisplayRole") == "title":
        return True
    hints = fact.get("componentHints")
    return isinstance(hints, list) and hints[:1] == ["SingleLineTitle"]


def _matches_single_counter(
    facts: list[Any], root: str, *, supplemental_paths: tuple[str, ...],
) -> bool:
    days = f"{root}/days"
    relation = f"{root}/relationText"
    has_days = False
    has_title = False
    has_unit = False
    for fact in facts:
        if not isinstance(fact, dict) or "actionId" in fact:
            return False
        data_id = fact.get("dataId")
        if data_id == days:
            has_days = True
        elif data_id in (relation, *supplemental_paths):
            continue
        elif fact.get("text") == "天" and not has_unit:
            has_unit = True
        elif isinstance(fact.get("text"), str) and not has_title and _is_title(fact):
            has_title = True
        else:
            return False
    return has_days


def _number_roles_match(facts: list[dict[str, Any]], root: str, component: str) -> bool:
    roles = {f"{root}/days": "value", f"{root}/targetDateText": "subtitle"}
    for fact in facts:
        display_role = fact.get("dataDisplayRole")
        if display_role is None:
            continue
        if component != "DataDisplay":
            return False
        data_path = fact.get("dataId")
        if isinstance(data_path, str):
            expected = roles.get(data_path)
        else:
            expected = "unit" if fact.get("text") == "天" else "title"
        if display_role != expected:
            return False
    return True


def _selected_counter(facts: list[Any], counters: Mapping[str, DateCounterResult]) -> str | None:
    for fact in facts:
        path = fact.get("dataId") if isinstance(fact, dict) else None
        if isinstance(path, str) and path.endswith("/days"):
            root = path.removesuffix("/days")
            if root in counters:
                return root
    return None


def _pattern(
    result: DateCounterResult,
    routes: _Routes,
    *,
    allowed: bool,
) -> str | None:
    total_days = result.interval_days if result.interval_days is not None else result.days
    within_limit = 1 <= total_days <= routes.dots_limit
    pattern: str | None = None
    if allowed and result.relation == "today":
        pattern = "bars"
    elif allowed and result.relation == "countdown" and within_limit:
        pattern = "bars" if total_days <= 7 else "dots"
    return pattern


def _preferred(
    preferred: str, existing: Any, limit: int, excluded: frozenset[str],
) -> list[str]:
    hints = [preferred]
    if isinstance(existing, list):
        for candidate in existing:
            if isinstance(candidate, str) and candidate not in hints and candidate not in excluded:
                hints.append(candidate)
    return hints[:limit]


def apply_date_counter_plan(
    plan: dict[str, Any],
    size: str,
    data_paths: set[str],
    counters: Mapping[str, DateCounterResult],
    *,
    recurring_roots: frozenset[str] = frozenset(),
) -> DateCounterPlanResult:
    """以服务端试算为依据，只改写能由单个日期计数组件承载的计划。"""
    routes = _ROUTES.get(size)
    if routes is None or not counters:
        return DateCounterPlanResult(plan, "unsupported_size_or_counter_count")
    if plan.get("wholeCardActionId") is not None:
        return DateCounterPlanResult(plan, "action")
    facts = plan.get("info_required")
    if not isinstance(facts, list):
        return DateCounterPlanResult(plan, "missing_facts")
    root = _selected_counter(facts, counters)
    result = counters.get(root) if root is not None else None
    if root is None or result is None:
        return DateCounterPlanResult(plan, "incompatible_facts")

    days_path = f"{root}/days"
    relation_path = f"{root}/relationText"
    date_path = f"{root}/targetDateText"
    interval_path = f"{root}/intervalDays"
    if not {days_path, relation_path} <= data_paths:
        return DateCounterPlanResult(plan, "missing_core_bindings")

    recurring = root in recurring_roots or result.interval_days is not None
    interval_available = not recurring or interval_path in data_paths
    if result.relation == "today" and not interval_available:
        return DateCounterPlanResult(plan, "missing_pattern_interval_binding")
    pattern = _pattern(result, routes, allowed=interval_available)
    supplemental_paths = (date_path, interval_path) if pattern else (date_path,)
    if not _matches_single_counter(facts, root, supplemental_paths=supplemental_paths):
        return DateCounterPlanResult(plan, "incompatible_facts")
    if pattern is None:
        if date_path not in data_paths:
            return DateCounterPlanResult(plan, "missing_number_date_binding")
        if not _number_roles_match(facts, root, routes.number_component):
            return DateCounterPlanResult(plan, "incompatible_number_roles")

    updated = deepcopy(plan)
    layout = routes.pattern_layout if pattern else routes.number_layout
    component = routes.pattern_component if pattern else routes.number_component
    # 进入改写的是已归一化 Plan，普通候选已经过该尺寸的布局枚举过滤。
    layout_hints = _preferred(layout, plan.get("layoutHints"), 2, DATE_COUNTER_LAYOUTS)
    updated["layoutHints"] = layout_hints
    has_ordinary_layout = len(layout_hints) > 1
    assignments = updated.get("assetAssignments")
    if not has_ordinary_layout and isinstance(assignments, dict):
        title = assignments.get("title")
        if isinstance(title, dict) and title.get("assetId") is not None:
            assignments["title"] = {
                "assetId": None, "reason": "Selected date counter layout has no icon slot.",
            }
    presentation: dict[str, Any] = {
        "layout": layout,
        "component": component,
        "labelRelation": {"path": relation_path},
        "value": {"path": days_path},
    }
    if pattern:
        presentation["pattern"] = pattern
        # 当天的真实读数仍为 0，单次图案需要一个合法正分母。
        presentation["totalValue"] = {"path": interval_path} if recurring else max(1, result.days)
    else:
        presentation["secondaryInfo"] = {"path": date_path}
        presentation["unit"] = "天"
    updated[PRESENTATION] = presentation
    retained_facts = []
    for source_fact in facts:
        fact_path = source_fact.get("dataId")
        if pattern and fact_path in supplemental_paths:
            continue
        fact = deepcopy(source_fact)
        if has_ordinary_layout:
            fact["componentHints"] = _preferred(
                component, fact.get("componentHints"), 3, _DEDICATED_COMPONENTS,
            )
        else:
            fact["componentHints"] = [component]
        if pattern:
            fact.pop("dataDisplayRole", None)
        retained_facts.append(fact)
    updated["info_required"] = retained_facts
    return DateCounterPlanResult(updated, "selected")


def date_counter_label_prefix(component: ComponentRow) -> str | None:
    """仅把无条件拼接的事件名前缀计入日期组件的可见文字。"""
    is_title = component.component_type == "SingleLineTitle"
    label = component.props.get("title" if is_title else "label")
    prefix: str | None = None
    if (is_title or component.component_type in _DATE_COUNTER_LABEL_COMPONENTS) and isinstance(
        label, str,
    ):
        match = _DATE_COUNTER_LABEL.fullmatch(label.strip())
        if match is not None:
            prefix = match.group("double") or match.group("single")
    return prefix


def date_counter_plan_instruction(plan: dict[str, Any]) -> str:
    """供生成、修复与恢复使用同一份倒计时执行说明。"""
    if not isinstance(plan.get(PRESENTATION), dict):
        return ""
    return (
        "采用 S-center、S-countdown-pattern、W-countdown-center、W-countdown-pattern 之一时，"
        "必须使用 dateCounterPresentation 指定的布局、组件和绑定，不输出业务图标。"
        "图案组件自动展示单位‘天’，当天只显示‘就是今天’，不补单位节点。"
        "也可采用能承载本轮事实的合法普通布局，沿用普通布局的事实、容量和素材规则。"
        "Plan 的 DataDisplay 展示角色只约束选中的倒计时大数字布局。"
    )
