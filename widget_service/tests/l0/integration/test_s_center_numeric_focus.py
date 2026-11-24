"""S-center 通用单数值、动态标题与基础 A2UI 输出回归。"""

import json
from typing import Any

import pytest

from services.card_validation import CompactDslValidationError, validate_compact_dsl
from services.card_validation.api import validate_card
from services.compact.compact_dsl_a2ui_converter import (
    CompactDslConversionError,
    convert_compact_dsl_to_a2ui,
)
from services.compact.components.compact_component_runtime import component_visual_recipe
from services.compact.layout.compact_region_layout import reference_region_boxes
from services.compact.planning.compact_plan import (
    compact_plan_required_route,
    parse_compact_plan_call,
)
from services.generation.generation_pipeline import DesignCompactProcessor, DslProcessingContext


def _source(props: dict[str, Any], *, subtitle_sample: str | None = "左耳") -> str:
    rows = [
        ["root", "Layout", {"layout": "S-center"}, ["display"]],
        ["display", "DataDisplay", {"label": "耳机电量", "value": 85, **props}],
        ["/data/subtitle", subtitle_sample],
        ["/data/value", 85],
    ]
    return "\n".join(json.dumps(row, ensure_ascii=False) for row in rows)


def _components(
    props: dict[str, Any], *, subtitle_sample: str | None = "左耳",
) -> dict[str, Any]:
    converted = convert_compact_dsl_to_a2ui(
        _source(props, subtitle_sample=subtitle_sample), size="2x2",
    )
    return _standard_components(converted)


def _standard_components(standard_dsl: str) -> dict[str, Any]:
    messages = [json.loads(line) for line in standard_dsl.splitlines()]
    assert len(messages) == 3
    update = messages[1].get("updateComponents")
    assert isinstance(update, dict)
    nodes = update.get("components")
    assert isinstance(nodes, list)
    result = {}
    for node in nodes:
        identifier = node.get("id")
        assert isinstance(identifier, str)
        result[identifier] = node
    return result


def _node(nodes: dict[str, Any], identifier: str) -> dict[str, Any]:
    node = nodes.get(identifier)
    assert isinstance(node, dict)
    return node


def _styles(nodes: dict[str, Any], identifier: str) -> dict[str, Any]:
    styles = _node(nodes, identifier).get("styles")
    assert isinstance(styles, dict)
    return styles


def _task() -> dict[str, Any]:
    return {
        "size": "2x2", "appVersion": "1.0.0", "eventCandidates": [],
        "userQuery": "耳机电量 左耳 85 %",
        "dataModelSchema": {"data": {
            "subtitle": {"type": "string", "sampleValue": "左耳"},
            "value": {"type": "integer", "sampleValue": 85},
        }},
    }


def _plan() -> dict[str, Any]:
    facts = []
    for text in ("耳机电量", "左耳", "85", "%"):
        facts.append({"requirement": text, "text": text, "priority": "must",
                      "componentHints": ["DataDisplay"]})
    core = facts[2]
    core.pop("text")
    core["dataId"] = "/data/value"
    return {"info_required": facts, "layoutHints": ["S-center"]}


@pytest.mark.parametrize("subtitle", [None, "", "  ", "左耳"])
def test_numeric_focus_title_geometry(subtitle: str | None) -> None:
    nodes = _components({"secondaryInfo": subtitle, "unit": "%"})
    assert _styles(nodes, "root").get("padding") == 12
    assert _styles(nodes, "display").get("height") == "matchParent"
    assert _styles(nodes, "display").get("justifyContent") == "center"
    assert _node(nodes, "display").get("itemMargin") == 0
    assert _styles(nodes, "display_value_row").get("height") == 62
    assert _node(nodes, "display_value_row").get("itemMargin") == 2
    assert _styles(nodes, "display_value").get("height") == 58
    area = _styles(nodes, "display_numeric_area")
    assert area.get("height") == "wrapContent"
    assert not area.get("padding")
    assert "layoutWeight" not in area
    assert "constraintSize" not in area
    assert area.get("justifyContent") == "center"
    label = _styles(nodes, "display_label")
    assert "height" not in label
    assert label.get("constraintSize") == {"minHeight": 21, "maxHeight": 42}
    assert label.get("maxLines") == 2
    assert "lineHeight" not in label
    assert label.get("fontSize") == 16
    assert label.get("fontWeight") == 500
    assert _styles(nodes, "display_value").get("fontSize") == 46
    assert _styles(nodes, "display_value").get("fontWeight") == 700
    assert _styles(nodes, "display_unit").get("fontSize") == 16
    assert _styles(nodes, "display_value_row").get("alignItems") == "bottom"
    assert _styles(nodes, "display_value_row").get("justifyContent") == "center"
    expected = ["display_main_group"]
    assert _node(nodes, "display_main_group").get("children") == [
        "display_title_group", "display_numeric_area",
    ]
    assert _styles(nodes, "display_main_group").get("layoutWeight") == 1
    assert _styles(nodes, "display_title_group").get("constraintSize") == {"minHeight": 32}
    assert _styles(nodes, "display_title_group").get("padding") == {"bottom": 6}
    assert _styles(nodes, "display_title_group").get("justifyContent") == "start"
    if subtitle == "左耳":
        expected.append("display_subtitle_group")
        assert not _styles(nodes, "display_subtitle_group").get("padding")
        assert _styles(nodes, "display_subtitle_group").get("height") == 16
        secondary = _styles(nodes, "display_secondary")
        assert secondary.get("height") == 16
        assert secondary.get("fontSize") == 12
        assert secondary.get("fontWeight") == 500
        assert secondary.get("maxLines") == 1
    assert _node(nodes, "display").get("children") == expected
    assert all(node.get("component") != "DataDisplay" for node in nodes.values())
    for node in nodes.values():
        if node.get("component") == "Text":
            styles = node.get("styles")
            assert isinstance(styles, dict)
            assert "lineHeight" not in styles


@pytest.mark.parametrize("height", [150, 200, 260])
@pytest.mark.parametrize("subtitle", [None, "左耳"])
def test_numeric_area_keeps_natural_height_in_centered_group(
    height: int, subtitle: str | None,
) -> None:
    nodes = _components({"secondaryInfo": subtitle, "unit": "%"})
    boxes = reference_region_boxes(
        list(nodes.values()), size="2x2",
        profile={"sizes": {"2x2": {"width": 150, "height": height}}},
    )
    display = boxes.get("display")
    area = boxes.get("display_numeric_area")
    row = boxes.get("display_value_row")
    assert display is not None and area is not None and row is not None
    assert display.height == height - 24
    assert area.height is None
    assert row.height == 62


@pytest.mark.parametrize("label,subtitle,required_height", [
    ("耳机电量", None, 118),
    ("耳机电量", "左耳", 134),
    ("运动会\n倒计时", None, 134),
    ("运动会\n倒计时", "目标日期", 150),
])
@pytest.mark.parametrize("height_delta,passes", [(0, True), (50, True), (-3, False)])
def test_numeric_focus_height_budget(
    label: str, subtitle: str | None, required_height: int, height_delta: int, passes: bool,
) -> None:
    height = required_height + height_delta
    source = _source({"label": label, "secondaryInfo": subtitle, "unit": "%"})
    context = {
        "task_spec": _task(), "card_spec": {"suggestSize": "2x2"},
        "layout_scope": "S-center",
        "protocol_profile": {"sizes": {"2x2": {"width": 150, "height": height}}},
    }
    if passes:
        validate_compact_dsl(source, **context)
    else:
        with pytest.raises(CompactDslValidationError, match="vertical layout"):
            validate_compact_dsl(source, **context)


def test_numeric_focus_without_unit_centers_value() -> None:
    nodes = _components({})
    assert _node(nodes, "display_value_row").get("children") == ["display_value"]
    assert "display_unit" not in nodes


def test_fixed_numeric_geometry_survives_validation() -> None:
    source = _source({"secondaryInfo": "左耳", "unit": "%"})
    result = DesignCompactProcessor().process(
        source,
        DslProcessingContext(
            size="2x2", task_spec=_task(), card_spec={"suggestSize": "2x2"},
            protocol_profile={"version": "v0.9"}, layout_scope="S-center",
        ),
    )
    assert not result.errors, result.errors
    nodes = _standard_components(result.standard_dsl)
    assert _styles(nodes, "display_value").get("height") == 58
    assert _styles(nodes, "display_value_row").get("height") == 62
    assert _styles(nodes, "display_numeric_area").get("height") == "wrapContent"
    assert _styles(nodes, "display_unit").get("margin") == {"bottom": 10}
    for identifier in ("display_value", "display_value_row", "display_numeric_area"):
        styles = _styles(nodes, identifier)
        assert "heightBudget" not in styles
        assert "lineHeight" not in styles


@pytest.mark.parametrize("height,passes", [(131, False), (134, True)])
def test_dynamic_title_reserves_two_lines_without_freezing_sample(
    height: int, passes: bool,
) -> None:
    source = _source({"label": {"path": "/data/subtitle"}, "unit": "%"})
    context = {
        "task_spec": _task(), "card_spec": {"suggestSize": "2x2"},
        "layout_scope": "S-center",
        "protocol_profile": {"sizes": {"2x2": {"width": 150, "height": height}}},
    }
    if passes:
        validate_compact_dsl(source, **context)
    else:
        with pytest.raises(CompactDslValidationError, match="vertical layout"):
            validate_compact_dsl(source, **context)


@pytest.mark.parametrize("label", [
    {"path": "/data/subtitle"},
    "{{ '电量 ' + ${/data/subtitle} }}",
])
def test_dynamic_title_keeps_binding(label: str | dict[str, str]) -> None:
    nodes = _components({"label": label})
    expected = label if isinstance(label, str) else "{{ ${/data/subtitle} }}"
    assert _node(nodes, "display_label").get("content") == expected


@pytest.mark.parametrize("subtitle_sample", ["左耳", "", None])
@pytest.mark.parametrize("subtitle", [
    {"path": "/data/subtitle"}, "{{ ${/data/subtitle} }}",
])
def test_dynamic_subtitle_keeps_binding_and_conditional_group(
    subtitle_sample: str | None, subtitle: Any,
) -> None:
    nodes = _components(
        {"secondaryInfo": subtitle, "unit": "%"},
        subtitle_sample=subtitle_sample,
    )
    assert _node(nodes, "display_secondary").get("content") == "{{ ${/data/subtitle} }}"
    visibility = _styles(nodes, "display_subtitle_group").get("visibility")
    assert isinstance(visibility, str)
    assert "${/data/subtitle}" in visibility
    assert "'visible' : 'none'" in visibility
    assert _node(nodes, "display").get("children") == [
        "display_main_group", "display_subtitle_group",
    ]


def test_legacy_numeric_supporting_text_is_not_guessed_as_unit() -> None:
    nodes = _components({"supportingText": "10:30 更新"})
    assert _node(nodes, "display_supporting").get("content") == "10:30 更新"
    assert _styles(nodes, "display_value").get("fontSize") == 48
    assert "display_unit" not in nodes


@pytest.mark.parametrize("props", [
    {"secondaryInfo": 7}, {"unit": False},
    {"supportingText": "天", "unit": "天"},
    {"value": "优", "unit": "分"},
])
def test_invalid_numeric_focus_props_are_rejected(props: dict[str, Any]) -> None:
    with pytest.raises(CompactDslConversionError):
        _components(props)


def test_public_double_line_title_recipe_is_unchanged() -> None:
    recipe = component_visual_recipe("DoubleLineTitle")
    parts = recipe.get("parts")
    assert isinstance(parts, dict)
    title = parts.get("title")
    assert isinstance(title, dict)
    assert title.get("styles", {}).get("fontSize") == 12
    root = parts.get("root")
    assert isinstance(root, dict)
    assert root.get("styles", {}).get("itemMargin") == 4


def test_single_fact_plan_locks_numeric_focus() -> None:
    plan = _plan()
    facts = plan.get("info_required")
    assert isinstance(facts, list)
    plan["info_required"] = [facts[2]]
    raw = json.dumps({"name": "submit_card_plan", "arguments": plan}, ensure_ascii=False)
    result = parse_compact_plan_call(raw, _task())
    assert compact_plan_required_route(result.plan, _task()) == {
        "layout": "S-center", "component": "DataDisplay",
    }


@pytest.mark.parametrize("props", [
    {"secondaryInfo": "这是超过小卡单行容量的很长副标题", "unit": "%"},
    {"value": 123456789, "unit": "步"},
])
def test_overflow_is_rejected_without_shrinking(props: dict[str, Any]) -> None:
    with pytest.raises(CompactDslValidationError):
        validate_compact_dsl(_source(props), task_spec=_task(),
                             card_spec={"suggestSize": "2x2"}, layout_scope="S-center")


def test_full_processor_accepts_generic_numeric_focus() -> None:
    result = DesignCompactProcessor().process(
        _source({"value": {"path": "/data/value"}, "secondaryInfo": "左耳", "unit": "%"}),
        DslProcessingContext(size="2x2", task_spec=_task(),
                             card_spec={"suggestSize": "2x2"},
                             protocol_profile={"version": "v0.9"},
                             design_profile_id="design-compact-dsl",
                             compact_plan=_plan(), layout_scope="S-center"),
    )
    assert not result.errors, result.errors
    assert '"fontSize":46' in result.standard_dsl.replace(" ", "")


@pytest.mark.parametrize("unit", ["天", "%", {"path": "/data/subtitle"}])
def test_numeric_unit_keeps_fixed_box_and_bottom_compensation(unit: Any) -> None:
    nodes = _components({"unit": unit})
    styles = _styles(nodes, "display_unit")
    assert styles.get("height") == 21
    assert styles.get("margin", {}).get("bottom") == 10
    assert styles.get("padding", {}).get("bottom", 0) == 0


def test_static_number_can_cover_accepted_fact() -> None:
    plan = _plan()
    facts = plan.get("info_required")
    assert isinstance(facts, list)
    core = facts[2]
    core.pop("dataId")
    core["text"] = "85"
    validate_compact_dsl(
        _source({"secondaryInfo": "左耳", "unit": "%"}),
        task_spec=_task(), card_spec={"suggestSize": "2x2"}, compact_plan=plan,
        layout_scope="S-center",
    )


@pytest.mark.parametrize("label", ["运动会倒计时提醒", "运动会\n倒计时"])
def test_numeric_title_accepts_two_lines(label: str) -> None:
    props = {"label": label, "secondaryInfo": "目标日期", "unit": "天"}
    result = DesignCompactProcessor().process(
        _source(props),
        DslProcessingContext(
            size="2x2", task_spec=_task(), card_spec={"suggestSize": "2x2"},
            layout_scope="S-center",
            protocol_profile={
                "version": "v0.9", "sizes": {"2x2": {"width": 150, "height": 150}},
            },
        ),
    )
    assert not result.errors, result.errors
    nodes = _standard_components(result.standard_dsl)
    assert _node(nodes, "display_label").get("content") == label
    assert "height" not in _styles(nodes, "display_label")


@pytest.mark.parametrize(("props", "message"), [
    ({"label": "甲\n乙\n丙"}, "main title exceeds two lines"),
    ({"label": "这是超出两行的主标题，这是超出两行的主标题"}, "main title exceeds two lines"),
    ({"secondaryInfo": "主行\n次行"}, "subtitle must be one line"),
])
def test_numeric_title_rejects_line_overflow(props: dict[str, Any], message: str) -> None:
    with pytest.raises(CompactDslValidationError, match=message):
        validate_compact_dsl(
            _source(props),
            task_spec=_task(), card_spec={"suggestSize": "2x2"}, layout_scope="S-center",
        )


def test_full_processor_preserves_dynamic_subtitle() -> None:
    plan = _plan()
    facts = plan.get("info_required")
    assert isinstance(facts, list)
    subtitle = facts[1]
    subtitle.pop("text")
    subtitle["dataId"] = "/data/subtitle"
    result = DesignCompactProcessor().process(
        _source({"value": {"path": "/data/value"},
                 "secondaryInfo": {"path": "/data/subtitle"}, "unit": "%"}),
        DslProcessingContext(size="2x2", task_spec=_task(),
                             card_spec={"suggestSize": "2x2"},
                             protocol_profile={"version": "v0.9"}, compact_plan=plan,
                             layout_scope="S-center"),
    )
    assert not result.errors, result.errors
    assert "visibility" in result.standard_dsl


def test_dynamic_unit_keeps_conditional_visibility() -> None:
    nodes = _components({"unit": {"path": "/data/subtitle"}})
    assert "${/data/subtitle}" in _styles(nodes, "display_unit").get("visibility", "")


@pytest.mark.parametrize("subtitle", [None, "左耳", {"path": "/data/subtitle"}])
def test_standard_a2ui_protocol_accepts_numeric_focus(subtitle: Any) -> None:
    converted = convert_compact_dsl_to_a2ui(
        _source({"secondaryInfo": subtitle, "unit": "%"}), size="2x2",
    )
    report = validate_card(dsl_text=converted)
    errors = []
    for diagnostic in report.diagnostics:
        if diagnostic.file_kind == "cardspec":
            continue
        if diagnostic.severity == "error":
            errors.append(diagnostic)
    assert not errors, errors


@pytest.mark.parametrize("subtitle_sample", ["左耳", ""])
@pytest.mark.parametrize("height,passes", [(147, False), (150, True)])
def test_dynamic_footer_reserves_visible_state_budget(
    subtitle_sample: str | None, height: int, passes: bool,
) -> None:
    source = _source({
        "label": {"path": "/data/subtitle"},
        "secondaryInfo": {"path": "/data/subtitle"}, "unit": "%",
    }, subtitle_sample=subtitle_sample)
    context = {
        "task_spec": _task(), "card_spec": {"suggestSize": "2x2"},
        "layout_scope": "S-center",
        "protocol_profile": {"sizes": {"2x2": {"width": 150, "height": height}}},
    }
    if passes:
        validate_compact_dsl(source, **context)
    else:
        with pytest.raises(CompactDslValidationError, match="vertical layout"):
            validate_compact_dsl(source, **context)
