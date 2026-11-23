# -*- coding: utf-8 -*-
# Copyright (c) Huawei Technologies Co., Ltd. 2026-2026. All rights reserved.
"""根据日期试算结果调整已接受的单目标 Plan。"""

import re
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from core.date_counter import DateCounterResult
from services.compact_high_level_components import ComponentRow

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
_DATE_COUNTER_LAYOUTS = (
    frozenset(route.number_layout for route in _ROUTES.values())
    | frozenset(route.pattern_layout for route in _ROUTES.values())
)
_DATE_COUNTER_LABEL_COMPONENTS = frozenset({
    "DataDisplay", "InfoDisplay", "SCountdown", "WCountdown",
})
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


def _has_assigned_asset(plan: dict[str, Any]) -> bool:
    assignments = plan.get("assetAssignments")
    if not isinstance(assignments, dict):
        return False
    slots = [assignments.get("title"), *assignments.get("actions", [])]
    return any(isinstance(slot, dict) and slot.get("assetId") is not None for slot in slots)


def _pattern(
    result: DateCounterResult,
    routes: _Routes,
    *,
    allowed: bool,
) -> str | None:
    total_days = result.interval_days if result.interval_days is not None else result.days
    within_limit = 1 <= total_days <= routes.dots_limit
    pattern: str | None = None
    if allowed and result.relation == "countdown" and within_limit:
        pattern = "bars" if total_days <= 7 else "dots"
    return pattern


def _preferred(preferred: str, existing: Any, limit: int) -> list[str]:
    hints = [preferred]
    if isinstance(existing, list):
        for candidate in existing:
            if isinstance(candidate, str) and candidate not in hints:
                hints.append(candidate)
    return hints[:limit]


def apply_date_counter_plan(
    plan: dict[str, Any],
    size: str,
    data_paths: set[str],
    counters: Mapping[str, DateCounterResult],
) -> DateCounterPlanResult:
    """以服务端试算为依据，只改写能由单个日期计数组件承载的计划。"""
    routes = _ROUTES.get(size)
    if routes is None or len(counters) != 1:
        return DateCounterPlanResult(plan, "unsupported_size_or_counter_count")
    root, result = next(iter(counters.items()))
    if result.relation == "today":
        return DateCounterPlanResult(plan, "today")
    if plan.get("wholeCardActionId") is not None or _has_assigned_asset(plan):
        return DateCounterPlanResult(plan, "action_or_asset")
    facts = plan.get("info_required")
    if not isinstance(facts, list):
        return DateCounterPlanResult(plan, "missing_facts")

    days_path = f"{root}/days"
    relation_path = f"{root}/relationText"
    date_path = f"{root}/targetDateText"
    interval_path = f"{root}/intervalDays"
    if not {days_path, relation_path} <= data_paths:
        return DateCounterPlanResult(plan, "missing_core_bindings")

    interval_available = result.interval_days is None or interval_path in data_paths
    pattern = _pattern(result, routes, allowed=interval_available)
    has_unit = any(isinstance(fact, dict) and fact.get("text") == "天" for fact in facts)
    if pattern == "dots" and has_unit:
        pattern = None
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
    layout_hints = plan.get("layoutHints")
    has_countdown_layout = isinstance(layout_hints, list) and any(
        hint in _DATE_COUNTER_LAYOUTS for hint in layout_hints if isinstance(hint, str)
    )
    replace_hints = has_countdown_layout or pattern == "bars"
    updated["layoutHints"] = [layout] if replace_hints else _preferred(layout, layout_hints, 2)
    presentation: dict[str, Any] = {
        "layout": layout,
        "component": component,
        "labelRelation": {"path": relation_path},
        "value": {"path": days_path},
    }
    if pattern:
        presentation["pattern"] = pattern
        presentation["totalValue"] = (
            result.days if result.interval_days is None else {"path": interval_path}
        )
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
        wide_countdown_readout = (
            component == "WCountdown" and fact_path in (days_path, relation_path)
        )
        if replace_hints or wide_countdown_readout:
            fact["componentHints"] = [component]
        else:
            fact["componentHints"] = _preferred(component, fact.get("componentHints"), 3)
        if pattern:
            fact.pop("dataDisplayRole", None)
        retained_facts.append(fact)
    updated["info_required"] = retained_facts
    return DateCounterPlanResult(updated, "selected")


def date_counter_label_prefix(component: ComponentRow) -> str | None:
    """仅把无条件拼接的事件名前缀计入日期组件的可见文字。"""
    label = component.props.get("label")
    prefix: str | None = None
    if component.component_type in _DATE_COUNTER_LABEL_COMPONENTS and isinstance(label, str):
        match = _DATE_COUNTER_LABEL.fullmatch(label.strip())
        if match is not None:
            prefix = match.group("double") or match.group("single")
    return prefix
