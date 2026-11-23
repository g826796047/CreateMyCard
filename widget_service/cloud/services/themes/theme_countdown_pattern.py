"""从合法图案源及定稿前景提取图片事实，不推测画布像素。"""

from services.card_validation.base import read_pointer
from services.compact.compact_dsl_a2ui_converter import (
    CompactDslConversionError,
    ComponentRow,
    parse_compact_dsl_rows,
)
from services.compact.components.countdown_pattern import (
    COUNTDOWN_LAYOUTS,
    PATTERN_PREFIX,
    expanded_pattern_rows,
    pattern_from_source,
    pattern_layout,
)
from services.compact.components.display_text import current_display_text

_THEMED_PROPERTIES = frozenset({"fontColor", "backgroundColor", "color"})


def _matches_foreground(expected: ComponentRow, actual: dict) -> bool:
    if actual.get("component") != expected.component_type:
        return False
    if actual.get("children", []) != list(expected.children):
        return False
    styles = actual.get("styles", {})
    for key, value in expected.props.items():
        if key.startswith("_") or key in _THEMED_PROPERTIES:
            continue
        if actual.get(key, styles.get(key)) != value:
            return False
    return True


def countdown_pattern_evidence(
    source: str | None, nodes: list[dict], data: dict | None, size: str | None,
) -> dict:
    """按单一高阶组件复用编译合同；正文仍为可见读数一行，副标题及图案不计。"""
    result = {"complete": False, "reason": "缺少合法图案布局或日期首帧"}
    if not source or data is None or size not in COUNTDOWN_LAYOUTS:
        return result
    try:
        rows = parse_compact_dsl_rows(source, expand_layouts=False)
        root = pattern_layout(rows)
        if root is None:
            return result
        expected_rows = expanded_pattern_rows(root, rows, size)
        pattern = pattern_from_source(root, rows)
    except CompactDslConversionError as exc:
        return {"complete": False, "reason": str(exc)}
    by_id = {}
    for node in nodes:
        identity = node.get("id")
        if not isinstance(identity, str) or identity in by_id:
            return {"complete": False, "reason": "图案前景节点标识无效或重复"}
        by_id[identity] = node
    expected_ids = set()
    for expected in expected_rows:
        if not isinstance(expected, ComponentRow):
            continue
        expected_ids.add(expected.component_id)
        actual = by_id.get(expected.component_id)
        if actual is None or not _matches_foreground(expected, actual):
            return {"complete": False, "reason": "图案源与定稿前景不一致"}
    if set(by_id) != expected_ids:
        return {"complete": False, "reason": "图案前景包含额外组件"}
    _, days = read_pointer(data, pattern.days_path)
    _, relation = read_pointer(data, pattern.relation_path)
    total = pattern.fixed_total
    if total is None:
        _, total = read_pointer(data, pattern.total_path)
    if type(total) is not int or total < 0:
        return result
    if type(days) is not int or days < 0:
        return result
    if relation not in ("还剩", "已过", "就是今天"):
        return result
    suffix = "today" if relation == "就是今天" else "day_count"
    readout = by_id.get(PATTERN_PREFIX + suffix, {})

    def lookup(path: str):
        _, value = read_pointer(data, path)
        return value

    text = current_display_text(readout.get("content"), lookup)
    if not isinstance(text, str) or not text.strip():
        return {"complete": False, "reason": "无法确认图案可见读数"}
    result = {
        "complete": True, "layout": root.props.get("layout"), "kind": pattern.kind,
        "daysPath": pattern.days_path, "relationPath": pattern.relation_path,
        "bodyFlow": {"lineCount": 1, "leftAligned": True},
        "textPlacement": "top-left", "graphicPlacement": "bottom-center",
        "basis": "validated-pattern-layout", "deviceGeometryKnown": False,
    }
    if pattern.fixed_total is None:
        result["totalPath"] = pattern.total_path
    else:
        result["totalValue"] = pattern.fixed_total
    return result
