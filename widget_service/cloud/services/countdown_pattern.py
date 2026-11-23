"""倒计时的图案准入与确定性布局。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Literal

from models.generation import CandidateDataBinding, CountdownPatternPreference
from services.compact_component_runtime import component_visual_recipe, visual_recipe_part
from services.compact_dsl_a2ui_converter import (
    CompactDslConversionError,
    CompactRow,
    ComponentRow,
    DataRow,
)

COUNTDOWN_LAYOUTS = {"2x2": "S-countdown-pattern", "2x4": "W-countdown-pattern"}
COUNTDOWN_COMPONENTS = {"2x2": "SCountdown", "2x4": "WCountdown"}
PATTERN_PREFIX = "__layout__root__countdown_"
_COLORS = component_visual_recipe("CountdownPattern").get("colors", {})
ACTIVE_COLOR = _COLORS.get("active")
INACTIVE_COLOR = _COLORS.get("inactive")
if not isinstance(ACTIVE_COLOR, str) or not isinstance(INACTIVE_COLOR, str):
    raise ValueError("图案配方缺少亮暗颜色。")


@dataclass(frozen=True)
class CountdownPattern:
    kind: Literal["bars", "dots"]
    days_path: str
    fixed_total: int | None = None

    @property
    def total_path(self) -> str:
        return self.days_path.removesuffix("/days") + "/intervalDays"

    @property
    def relation_path(self) -> str:
        return self.days_path.removesuffix("/days") + "/relationText"


@dataclass(frozen=True)
class PatternGeometry:
    rows: int
    columns: int
    width: int
    height: int
    gap: float
    row_gap: int
    radius: int

    @property
    def group_width(self) -> float:
        return round(self.columns * self.width + (self.columns - 1) * self.gap, 2)

    @property
    def group_height(self) -> int:
        return self.rows * self.height + (self.rows - 1) * self.row_gap


def _load_geometry() -> dict[tuple[str, str], PatternGeometry]:
    result = {}
    for size in COUNTDOWN_LAYOUTS:
        geometries = component_visual_recipe("CountdownPattern", size=size).get("geometry")
        if not isinstance(geometries, dict):
            raise ValueError("图案配方缺少几何规格。")
        for kind in ("bars", "dots"):
            geometry = geometries.get(kind)
            if not isinstance(geometry, dict):
                raise ValueError("图案配方缺少对应类型的几何规格。")
            result[(size, kind)] = PatternGeometry(**geometry)
    return result


GEOMETRY = _load_geometry()


def authorize_pattern(
    preference: CountdownPatternPreference,
    bindings: list[CandidateDataBinding],
    *,
    has_events: bool,
) -> CountdownPattern:
    if len(bindings) != 1 or has_events:
        raise ValueError("图案倒计时只支持一个日期计数目标和无动作布局。")
    binding = next(iter(bindings))
    if binding.capabilityId != "GetDateCounter" or binding.arguments.get("repeat") is not None:
        raise ValueError("图案只用于单次倒计时，周期倒计时可使用普通样式。")
    required = {"/days", "/relationText", "/intervalDays"}
    if not required.issubset(binding.candidateOutputFields):
        raise ValueError("比例图案需要日期计数的天数、日期关系和 intervalDays。")
    return CountdownPattern(preference.kind, binding.writeResultTo.rstrip("/") + "/days")


def pattern_layout(rows: tuple[CompactRow, ...]) -> ComponentRow | None:
    result: ComponentRow | None = None
    for row in rows:
        if isinstance(row, ComponentRow) and row.component_id == "root":
            name = row.props.get("layout")
            if row.component_type == "Layout" and name in COUNTDOWN_LAYOUTS.values():
                result = row
            break
    return result


def _date_path(component: ComponentRow) -> str:
    value = component.props.get("value")
    path = value.get("path") if isinstance(value, dict) and set(value) == {"path"} else None
    if not isinstance(path, str) or not path.startswith("/data/") or not path.endswith("/days"):
        raise CompactDslConversionError("图案需要合法日期计数 /days 路径。")
    if any(char in path for char in "{}\n\r"):
        raise CompactDslConversionError("图案需要合法日期计数 /days 路径。")
    relation = component.props.get("relationValue")
    expected = {"path": path.removesuffix("/days") + "/relationText"}
    if relation != expected:
        raise CompactDslConversionError("日期关系必须绑定同一日期计数的 /relationText。")
    return path


def _source_display(root: ComponentRow, rows: tuple[CompactRow, ...]) -> ComponentRow:
    if set(root.props) != {"layout"} or len(root.children) != 1:
        raise CompactDslConversionError("图案根只接受 layout 和一个高阶组件，不兼容旧源 DSL。")
    components = {}
    for row in rows:
        if isinstance(row, ComponentRow):
            components[row.component_id] = row
    if set(components) != {root.component_id, *root.children}:
        raise CompactDslConversionError("图案布局不接收额外组件。")
    expected = "SCountdown" if root.props.get("layout") == "S-countdown-pattern" else "WCountdown"
    component = components.get(root.children[0])
    if component is None or component.component_type != expected:
        raise CompactDslConversionError("图案布局必须使用对应的 SCountdown 或 WCountdown。")
    if component.children:
        raise CompactDslConversionError("图案高阶组件内部子组件由程序生成。")
    return component


def pattern_from_source(root: ComponentRow, rows: tuple[CompactRow, ...]) -> CountdownPattern:
    display = _source_display(root, rows)
    return pattern_from_display(display)


def pattern_from_display(display: ComponentRow) -> CountdownPattern:
    allowed = {"label", "pattern", "value", "totalValue", "relationValue"}
    if set(display.props) != allowed:
        raise CompactDslConversionError(
            "图案高阶组件只接受 label、pattern、value、totalValue、relationValue。"
        )
    title = display.props.get("label")
    if not isinstance(title, str) or not title.strip():
        raise CompactDslConversionError("图案倒计时需要非空事件名称。")
    if any(marker in title for marker in ("{{", "}}", "${")):
        raise CompactDslConversionError("图案倒计时事件名称必须是静态文字。")
    path = _date_path(display)
    kind = display.props.get("pattern")
    if kind not in ("bars", "dots"):
        raise CompactDslConversionError("图案类型只允许 bars 或 dots。")
    return _pattern_with_total(kind, path, display.props.get("totalValue"))


def _pattern_with_total(
    kind: Literal["bars", "dots"], days_path: str, total: object,
) -> CountdownPattern:
    fixed_total: int | None = None
    if isinstance(total, int) and not isinstance(total, bool) and total > 0:
        fixed_total = total
    pattern = CountdownPattern(kind, days_path, fixed_total)
    if fixed_total is None and total != {"path": pattern.total_path}:
        raise CompactDslConversionError(
            "总量必须为创建时的正整数或绑定同一日期计数的 /intervalDays。"
        )
    return pattern


def pattern_from_plan(presentation: object, size: str) -> CountdownPattern | None:
    """读取本轮服务端追加的图案推荐，普通布局没有图案准入。"""
    pattern: CountdownPattern | None = None
    if isinstance(presentation, dict) and size in COUNTDOWN_LAYOUTS:
        kind = presentation.get("pattern")
        value = presentation.get("value")
        matches_size = (
            presentation.get("layout") == COUNTDOWN_LAYOUTS.get(size)
            and presentation.get("component") == COUNTDOWN_COMPONENTS.get(size)
        )
        if matches_size and kind in ("bars", "dots") and isinstance(value, dict):
            path = value.get("path")
            if isinstance(path, str):
                pattern = _pattern_with_total(kind, path, presentation.get("totalValue"))
    return pattern


def check_pattern_binding(pattern: CountdownPattern, card_spec: dict) -> None:
    bindings = card_spec.get("dataBindings")
    if not isinstance(bindings, list) or len(bindings) != 1:
        raise CompactDslConversionError("图案需要一个已授权的日期计数绑定。")
    binding = next(iter(bindings))
    if not isinstance(binding, dict) or binding.get("capabilityId") != "GetDateCounter":
        raise CompactDslConversionError("图案需要已授权的日期计数能力。")
    arguments = binding.get("arguments")
    if not isinstance(arguments, dict):
        raise CompactDslConversionError("图案缺少有效的日期计数参数。")
    if arguments.get("repeat") is not None and pattern.fixed_total is not None:
        raise CompactDslConversionError("周期图案总量必须绑定同一日期计数的 /intervalDays。")
    root = binding.get("writeResultTo")
    if not isinstance(root, str) or root.rstrip("/") + "/days" != pattern.days_path:
        raise CompactDslConversionError("图案必须绑定当前目标对应的数值天数。")


def countdown_prompt(pattern: CountdownPattern, size: str) -> str:
    layout = COUNTDOWN_LAYOUTS.get(size)
    bindings = {
        "value": {"path": pattern.days_path},
        "relationValue": {"path": pattern.relation_path},
    }
    template = [
        ["root", "Layout", {"layout": layout}, ["countdown"]],
        ["countdown", COUNTDOWN_COMPONENTS.get(size), {
            "label": "本轮事件名称", "pattern": pattern.kind, **bindings,
            "totalValue": {"path": pattern.total_path},
        }],
    ]
    source = "\n".join(json.dumps(row, ensure_ascii=False) for row in template)
    return (
        "本轮已通过单次图案倒计时准入。\n\n"
        f"本轮源组件结构为：\n```jsonl\n{source}\n```\n"
        "intervalDays 必须有首帧数据行；尚未取得本轮真实值时填 0，不能复制能力样例作为真实总量。"
    )


def _visual_styles(size: str, slot: str) -> dict:
    references = {
        "labels": ("CountdownPattern", "labels"),
        "readout": ("CountdownReadout", "root"),
        "readoutText": ("CountdownReadout", "text"),
        "subtitle": ("SingleLineTitle", "countdownSubtitle"),
        "cell": ("CountdownPattern", "cell"),
        "fill": ("CountdownPattern", "fill"),
        "row": ("CountdownPattern", "row"),
        "group": ("CountdownPattern", "group"),
    }
    reference = references.get(slot)
    if reference is None:
        raise CompactDslConversionError("图案组件缺少视觉配方引用。")
    _, styles = visual_recipe_part(*reference, size=size)
    return styles


def _pattern_row(
    index: int, geometry: PatternGeometry, size: str,
    pattern: CountdownPattern,
) -> list[ComponentRow]:
    result = []
    ids = []
    cell_styles = _visual_styles(size, "cell")
    fill_styles = _visual_styles(size, "fill")
    for number in range(geometry.columns):
        identifier = f"{PATTERN_PREFIX}cell_{index}_{number}"
        ids.append(identifier)
        fill_id = identifier + "_fill"
        result.append(ComponentRow(identifier, "Stack", {
            **cell_styles,
            "width": geometry.width,
            "height": geometry.height,
            "borderRadius": geometry.radius,
        }, (fill_id,)))
        unit_index = (geometry.rows - 1 - index) * geometry.columns + number
        result.append(ComponentRow(fill_id, "Divider", {
            **fill_styles,
            "width": geometry.width,
            "height": pattern_fill_height(pattern, unit_index, geometry),
            "visibility": pattern_fill_visibility(pattern, unit_index, geometry),
        }, ()))
    result.append(ComponentRow(f"{PATTERN_PREFIX}row_{index}", "Row", {
        **_visual_styles(size, "row"),
        "width": geometry.group_width,
        "height": geometry.height,
        "itemMargin": geometry.gap,
    }, tuple(ids)))
    return result


def expanded_pattern_rows(
    root: ComponentRow, rows: tuple[CompactRow, ...], size: str,
) -> tuple[CompactRow, ...]:
    """前景核对复用正式的布局和高阶组件两阶段展开，不另编译整卡。"""
    from services.compact_high_level_components import expand_high_level_component_rows
    from services.compact_semantic_layout import expand_semantic_layout_rows

    if root.props.get("layout") != COUNTDOWN_LAYOUTS.get(size):
        raise CompactDslConversionError("图案倒计时布局与卡片尺寸不一致。")
    expansion = expand_semantic_layout_rows(rows, size=size)
    components = []
    data_rows = []
    for row in expansion.rows:
        if isinstance(row, ComponentRow):
            components.append(row)
        else:
            data_rows.append(row)
    expanded = expand_high_level_component_rows(components, size=size)
    return tuple(expanded + data_rows)


def expand_countdown_display(display: ComponentRow, size: str) -> list[ComponentRow]:
    """由通用高阶组件入口调用；只展开组件内部，不生成布局根。"""
    if display.component_type != COUNTDOWN_COMPONENTS.get(size):
        raise CompactDslConversionError("图案倒计时组件与卡片尺寸不一致。")
    if display.children:
        raise CompactDslConversionError("图案高阶组件内部子组件由程序生成。")
    pattern = pattern_from_display(display)
    title = display.props.get("label")
    geometry = GEOMETRY.get((size, pattern.kind))
    if geometry is None:
        raise CompactDslConversionError("图案倒计时缺少对应规格。")
    title_id = PATTERN_PREFIX + "title"
    readout_id = PATTERN_PREFIX + "readout"
    labels_id = PATTERN_PREFIX + "labels"
    group_id = PATTERN_PREFIX + "group"
    relation = "${" + pattern.relation_path + "}"
    days = "${" + pattern.days_path + "}"
    text = "{{ " + relation + " + ' ' + " + days + " + ' 天' }}"
    today = relation + " == '就是今天'"
    today_id = PATTERN_PREFIX + "today"
    count_id = PATTERN_PREFIX + "day_count"
    _, root_styles = visual_recipe_part(display.component_type, "root", size=size)
    title_styles = _visual_styles(size, "subtitle")
    readout_styles = _visual_styles(size, "readoutText")
    label_children = (readout_id, title_id)
    created: list[ComponentRow] = [
        ComponentRow(display.component_id, "Column", root_styles, (labels_id, group_id)),
        ComponentRow(labels_id, "Column", _visual_styles(size, "labels"), label_children),
        ComponentRow(title_id, "Text", {
            **title_styles, "content": title,
        }, ()),
        ComponentRow(readout_id, "Stack", _visual_styles(size, "readout"),
                     (count_id, today_id)),
        ComponentRow(count_id, "Text", {
            **readout_styles, "content": text,
            "visibility": "{{ " + today + " ? 'none' : 'visible' }}",
        }, ()),
        ComponentRow(today_id, "Text", {
            **readout_styles, "content": "就是今天",
            "visibility": "{{ " + today + " ? 'visible' : 'none' }}",
        }, ()),
    ]
    row_ids = []
    for index in range(geometry.rows):
        group_row = _pattern_row(index, geometry, size, pattern)
        row_ids.append(f"{PATTERN_PREFIX}row_{index}")
        created.extend(group_row)
    created.append(ComponentRow(group_id, "Column", {
        **_visual_styles(size, "group"),
        "width": geometry.group_width, "height": geometry.group_height,
        "itemMargin": geometry.row_gap,
    }, tuple(row_ids)))
    return created


def _fill_height_body(pattern: CountdownPattern, index: int, geometry: PatternGeometry) -> str:
    days = "${" + pattern.days_path + "}"
    total = (
        str(pattern.fixed_total) if pattern.fixed_total is not None
        else "${" + pattern.total_path + "}"
    )
    relation = "${" + pattern.relation_path + "}"
    amount = f"({days} * {geometry.rows * geometry.columns} / {total})"
    return (
        f"{relation} == '还剩' && {total} && {days} && {total} > 0 && {days} > 0 ? "
        f"({amount} <= {index} ? 0 : ({amount} >= {index + 1} ? {geometry.height} : "
        f"({amount} - {index}) * {geometry.height})) : 0"
    )


def pattern_fill_height(pattern: CountdownPattern, index: int, geometry: PatternGeometry) -> str:
    return "{{ " + _fill_height_body(pattern, index, geometry) + " }}"


def pattern_fill_visibility(
    pattern: CountdownPattern, index: int, geometry: PatternGeometry,
) -> str:
    body = _fill_height_body(pattern, index, geometry)
    return "{{ (" + body + ") > 0 ? 'visible' : 'none' }}"


def initialize_pattern_total(source: str, pattern: CountdownPattern) -> str:
    """在线新建尚无真实总量，确定性置零；保留绑定，等待端侧刷新。"""
    from services.compact_dsl_a2ui_converter import _serialize_repaired_rows, parse_compact_dsl_rows

    rows = parse_compact_dsl_rows(source, expand_layouts=False)
    initialized = []
    for row in rows:
        if isinstance(row, DataRow) and row.path == pattern.total_path:
            continue
        initialized.append(row)
    initialized.append(DataRow(pattern.total_path, 0))
    return _serialize_repaired_rows(initialized)


def paint_pattern(source: str, pattern: CountdownPattern, size: str) -> str:
    """主题后恢复轨道和填充色，固定连续比例表达式，不改变几何。"""
    geometry = GEOMETRY.get((size, pattern.kind))
    if geometry is None:
        raise ValueError("图案配色缺少对应规格。")
    targets = {}
    for row_index in range(geometry.rows):
        for column_index in range(geometry.columns):
            key = f"{PATTERN_PREFIX}cell_{row_index}_{column_index}"
            index = (geometry.rows - 1 - row_index) * geometry.columns + column_index
            targets[key] = ("Stack", {"backgroundColor": INACTIVE_COLOR})
            targets[key + "_fill"] = ("Divider", {
                "backgroundColor": ACTIVE_COLOR, "color": "#00000000",
                "height": pattern_fill_height(pattern, index, geometry),
                "visibility": pattern_fill_visibility(pattern, index, geometry),
            })
    messages = [json.loads(line) for line in source.splitlines() if line.strip()]
    for message in messages:
        section = message.get("updateComponents")
        if not isinstance(section, dict):
            continue
        nodes = section.get("components")
        if not isinstance(nodes, list):
            continue
        for node in nodes:
            _paint_cell(node, targets)
    if targets:
        raise ValueError("图案配色目标丢失。")
    return "\n".join(
        json.dumps(message, ensure_ascii=False, separators=(",", ":")) for message in messages
    )


def _paint_cell(node: dict, targets: dict) -> None:
    key = node.get("id")
    if not isinstance(key, str) or not key.startswith(PATTERN_PREFIX + "cell_"):
        return
    target = targets.pop(key, None)
    styles = node.get("styles")
    if target is None or not isinstance(styles, dict):
        raise ValueError("图案配色目标与布局不一致。")
    component, properties = target
    if node.get("component") != component:
        raise ValueError("图案配色目标组件类型不一致。")
    styles.update(properties)
