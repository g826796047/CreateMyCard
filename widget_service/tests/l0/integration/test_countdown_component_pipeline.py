"""倒计时与 DataDisplay 共用两阶段展开，保持业务和几何边界。"""

import json

import pytest
from test_countdown_pattern_create import ROOT, _source

from services.compact_dsl_a2ui_converter import (
    CompactDslConversionError,
    ComponentRow,
    convert_compact_dsl_to_a2ui,
    expand_compact_semantic_layout,
    parse_compact_dsl_rows,
)
from services.compact_high_level_components import expand_high_level_component_rows
from services.compact_plan import _compact_visible_state
from services.content_business import BusinessContext, FinalBusinessContext
from services.countdown_pattern import COUNTDOWN_COMPONENTS, PATTERN_PREFIX


@pytest.mark.parametrize("size", ["2x2", "2x4"])
@pytest.mark.parametrize("kind", ["bars", "dots"])
@pytest.mark.parametrize("identity", ["countdown", "exam_counter"])
def test_layout_retains_display_and_common_expander_builds_internals(size, kind, identity):
    source = _source(size, kind).replace('"countdown"', json.dumps(identity))
    expanded, origins = expand_compact_semantic_layout(source, size=size)
    assert json.loads(expanded.splitlines()[1])[1] == COUNTDOWN_COMPONENTS.get(size)
    rows = parse_compact_dsl_rows(source, size=size)
    components = [row for row in rows if isinstance(row, ComponentRow)]
    assert len(components) == 2
    root = next(row for row in components if row.component_id == "root")
    display = next(row for row in components if row.component_id == identity)
    assert root.component_type == "Column"
    assert root.children == (identity,)
    assert display.component_type == COUNTDOWN_COMPONENTS.get(size)
    assert display.children == ()
    assert origins.get("root") == "root"
    native = expand_high_level_component_rows(components, size=size)
    assert all(row.component_type not in {"SCountdown", "WCountdown"} for row in native)
    display_root = next(row for row in native if row.component_id == identity)
    assert display_root.component_type == "Column"
    assert display_root.props.get("justifyContent") == "spaceBetween"
    assert "padding" not in display_root.props
    assert root.props.get("padding") == 12
    assert root.props.get("borderRadius") == 20
    assert root.props.get("clip") is True
    labels = next(row for row in native if row.component_id == PATTERN_PREFIX + "labels")
    assert labels.props.get("height") == 50
    cells = [row for row in native if row.component_id.startswith(PATTERN_PREFIX + "cell_")]
    count = 7 if kind == "bars" else 48 if size == "2x2" else 100
    assert len(cells) == count * 2


@pytest.mark.parametrize("size", ["2x2", "2x4"])
@pytest.mark.parametrize("kind", ["bars", "dots"])
def test_pattern_component_cannot_be_placed_in_plain_native_container(size, kind):
    rows = parse_compact_dsl_rows(_source(size, kind), expand_layouts=False)
    display = None
    for row in rows:
        if isinstance(row, ComponentRow) and row.component_id != "root":
            display = row
    assert display is not None
    root = ComponentRow("root", "Column", {}, (display.component_id,))
    with pytest.raises(CompactDslConversionError, match="专用组件只能用于"):
        expand_high_level_component_rows([root, display], size=size)


@pytest.mark.parametrize("size", ["2x2", "2x4"])
@pytest.mark.parametrize("kind", ["bars", "dots"])
def test_plan_sees_relation_but_not_fill_denominator(size, kind):
    rows = parse_compact_dsl_rows(_source(size, kind))
    components = [row for row in rows if isinstance(row, ComponentRow)]
    state = _compact_visible_state(components)
    assert ROOT + "/days" in state.paths
    assert ROOT + "/relationText" in state.paths
    assert ROOT + "/intervalDays" not in state.paths


@pytest.mark.parametrize("root", [ROOT, "/data/anotherCounter"])
def test_only_same_source_date_relation_inherits_confirmed_day_business(root):
    source = _source("2x2", "bars").replace(ROOT, root)
    catalog = BusinessContext(data={root + "/days": "countdown"})
    assert FinalBusinessContext.from_layout(source, catalog).scope().single == "countdown"
    unknown = BusinessContext()
    assert FinalBusinessContext.from_layout(source, unknown).scope().single is None
    malformed = source.replace(root + "/relationText", "/data/other/relationText")
    assert FinalBusinessContext.from_layout(malformed, catalog).scope().single is None


def test_center_data_display_remains_in_common_pipeline():
    source = '\n'.join([
        '["root","Layout",{"layout":"S-center"},["display"]]',
        '["display","DataDisplay",{"label":"考试","value":{"path":"/data/days"},"unit":"天"}]',
        '["/data/days",4]',
    ])
    expanded, _ = expand_compact_semantic_layout(source, size="2x2")
    rows = parse_compact_dsl_rows(expanded, expand_layouts=False)
    types = [row.component_type for row in rows if isinstance(row, ComponentRow)]
    assert "DataDisplay" in types
    result = convert_compact_dsl_to_a2ui(source, size="2x2")
    messages = [json.loads(line) for line in result.splitlines()]
    section = messages[1].get("updateComponents")
    assert section is not None
    assert all(node.get("component") != "DataDisplay" for node in section.get("components", []))
