"""Compact DSL 转换与最终 A2UI 校验的组件合同。"""

import json

from services.card_validation import validate_card
from services.compact.compact_dsl_a2ui_converter import convert_compact_dsl_to_a2ui


def _compact_source() -> str:
    rows = [
        ["root", "Layout", {"layout": "S-center"}, ["display"]],
        [
            "display",
            "DataDisplay",
            {
                "label": "耳机电量",
                "value": {"path": "/data/value"},
                "unit": "%",
            },
        ],
        ["/data/value", 85],
    ]
    values = []
    for row in rows:
        values.append(json.dumps(row, ensure_ascii=False))
    return "\n".join(values)


def test_compact_conversion_produces_valid_a2ui_contract() -> None:
    converted = convert_compact_dsl_to_a2ui(_compact_source(), size="2x2")
    messages = [json.loads(line) for line in converted.splitlines()]

    assert len(messages) == 3
    assert "createSurface" in messages[0]
    assert "updateComponents" in messages[1]
    assert "updateDataModel" in messages[2]
    assert "${/data/value}" in json.dumps(messages[1], ensure_ascii=False)

    data_update = messages[2].get("updateDataModel")
    assert isinstance(data_update, dict)
    value = data_update.get("value")
    assert isinstance(value, dict)
    data = value.get("data")
    assert isinstance(data, dict)
    assert data.get("value") == 85

    report = validate_card(dsl_text=converted)
    errors = []
    for diagnostic in report.diagnostics:
        if diagnostic.file_kind == "cardspec":
            continue
        if diagnostic.severity == "error":
            errors.append(diagnostic)
    assert not errors, errors
