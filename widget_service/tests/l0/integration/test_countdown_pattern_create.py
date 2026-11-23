"""覆盖 Fusion 图案倒计时的创建、布局与主题后交付。"""

import json
from dataclasses import replace
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from api.schemas import GenerateWidgetCardRequest
from config.config import get_settings
from core.date_counter import resolve_date_counter
from core.errors import GenerationStatus
from custom.a2ui_model_client import A2UIModelClient
from models.generation import CandidateDataBinding, CountdownPatternPreference
from services.artifacts.artifact_store import ArtifactStore
from services.compact.components.countdown_pattern import (
    COUNTDOWN_COMPONENTS,
    COUNTDOWN_LAYOUTS,
    PATTERN_PREFIX,
    CountdownPattern,
    authorize_pattern,
    countdown_prompt,
    paint_pattern,
)
from services.generation import generation_preflight
from services.generation.generation_pipeline import DesignCompactProcessor, DslProcessingContext
from services.generation.widget_generation_service import WidgetGenerationService
from services.themes import post_layout_theme
from services.themes.theme_countdown_pattern import countdown_pattern_evidence

ROOT = "/data/customCounter"


def _binding(**arguments) -> CandidateDataBinding:
    return CandidateDataBinding(
        capabilityId="GetDateCounter",
        arguments={"targetDate": "2026-11-20", **arguments},
        writeResultTo=ROOT,
        candidateOutputFields=["/days", "/relationText", "/intervalDays"],
    )


@pytest.mark.parametrize("kind", ["bars", "dots"])
def test_patterns_need_no_creation_day_evidence(kind):
    options = CountdownPatternPreference(kind=kind)
    selected = authorize_pattern(options, [_binding()], has_events=False)
    assert selected.days_path == ROOT + "/days"
    assert selected.total_path == ROOT + "/intervalDays"


@pytest.mark.parametrize(("name", "value"), [("remainingDays", 4), ("referenceDate", "2026-11-17")])
def test_removed_creation_evidence_parameters_are_rejected(name, value):
    with pytest.raises(ValidationError, match="Extra inputs"):
        CountdownPatternPreference.model_validate({"kind": "bars", name: value})


def test_pattern_requires_total_field_in_authorized_binding():
    binding = _binding()
    binding.candidateOutputFields = ["/days", "/relationText"]
    with pytest.raises(ValueError, match="intervalDays"):
        authorize_pattern(CountdownPatternPreference(kind="bars"), [binding], has_events=False)


def test_dots_have_no_day_gate_but_reject_recurrence():
    options = CountdownPatternPreference(kind="dots")
    assert authorize_pattern(options, [_binding()], has_events=False).kind == "dots"
    with pytest.raises(ValueError, match="周期"):
        authorize_pattern(options, [_binding(repeat={"unit": "month"})], has_events=False)


def _source(size, kind, *, days=3, relation="还剩", total=6, fixed_total=None, **extra) -> str:
    bindings = {
        "value": {"path": ROOT + "/days"},
        "relationValue": {"path": ROOT + "/relationText"},
    }
    denominator = fixed_total if fixed_total is not None else {"path": ROOT + "/intervalDays"}
    rows = [
        ["root", "Layout", {"layout": COUNTDOWN_LAYOUTS.get(size), **extra}, ["countdown"]],
        ["countdown", COUNTDOWN_COMPONENTS.get(size), {
            "label": "考试", "pattern": kind, **bindings,
            "totalValue": denominator,
        }],
        [ROOT + "/days", days],
        [ROOT + "/relationText", relation],
    ]
    if fixed_total is None:
        rows.append([ROOT + "/intervalDays", total])
    return "\n".join(json.dumps(row, ensure_ascii=False) for row in rows)


def _context(size, kind) -> DslProcessingContext:
    return DslProcessingContext(
        size=size,
        task_spec={
            "size": size,
            "appVersion": "11.7.9.300",
            "dataModelSchema": {"data": {"customCounter": {
                "days": {"type": "integer", "sampleValue": 3},
                "relationText": {"type": "string", "sampleValue": "还剩"},
                "intervalDays": {"type": "integer", "sampleValue": 6},
            }}},
        },
        card_spec={"suggestSize": size, "dataBindings": [_binding().model_dump()]},
        protocol_profile={"version": "v0.9"},
        design_profile_id="design-compact-dsl",
        countdown_pattern=CountdownPattern(kind, ROOT + "/days"),
        colorless_layout=True,
    )


@pytest.mark.parametrize(("size", "kind", "columns", "row_starts", "width", "height", "radius"), [
    ("2x2", "bars", 7, (1,), 10, 60, 5),
    ("2x4", "bars", 7, (1,), 30, 60, 15),
    ("2x2", "dots", 12, (37, 25, 13, 1), 8, 8, 4),
    ("2x4", "dots", 25, (76, 51, 26, 1), 8, 8, 4),
])
def test_processor_compiles_only_requested_geometry(
    size, kind, columns, row_starts, width, height, radius,
):
    context = _context(size, kind)
    result = DesignCompactProcessor().process(_source(size, kind), context)
    assert not result.errors, result.errors
    pattern = context.countdown_pattern
    assert pattern is not None
    painted = paint_pattern(result.standard_dsl, pattern, size)
    messages = [json.loads(line) for line in painted.splitlines()]
    update = messages[1].get("updateComponents")
    assert update is not None
    nodes = update.get("components")
    assert nodes is not None
    cells = []
    for node in nodes:
        if node.get("component") != "Stack":
            continue
        if node.get("id", "").startswith(PATTERN_PREFIX + "cell_"):
            cells.append(node)
    assert len(cells) == columns * len(row_starts)
    for position, node in enumerate(cells):
        row, column = divmod(position, columns)
        assert node.get("id") == f"{PATTERN_PREFIX}cell_{row}_{column}"
        styles = node.get("styles")
        assert styles is not None
        assert (styles.get("width"), styles.get("height"), styles.get("borderRadius")) == (
            width, height, radius,
        )
        assert styles.get("backgroundColor") == "#33FFFFFF"
        assert styles.get("clip") is True
        assert styles.get("alignContent") == "bottomStart"
        assert node.get("children") == [node.get("id") + "_fill"]
        fill = next(item for item in nodes if item.get("id") == node.get("id") + "_fill")
        fill_styles = fill.get("styles", {})
        assert fill_styles.get("backgroundColor") == "#FFFFFFFF"
        assert ROOT + "/intervalDays" in fill_styles.get("height", "")
        assert "? 0" in fill_styles.get("height", "")



@pytest.mark.parametrize("size", ["2x2", "2x4"])
@pytest.mark.parametrize("kind", ["bars", "dots"])
def test_today_first_frame_compiles_with_actual_date_counter_samples(size, kind):
    context = _context(size, kind)
    schema = context.task_spec.get("dataModelSchema", {})
    counter = schema.get("data", {}).get("customCounter", {})
    days_schema = counter.get("days")
    relation_schema = counter.get("relationText")
    assert days_schema is not None
    assert relation_schema is not None
    days_schema["sampleValue"] = 0
    relation_schema["sampleValue"] = "就是今天"
    result = DesignCompactProcessor().process(
        _source(size, kind, days=0, relation="就是今天"), context,
    )
    assert not result.errors, result.errors


def test_source_cannot_select_unauthorized_pattern_or_override_program_cells():
    context = _context("2x2", "bars")
    processor = DesignCompactProcessor()
    result = processor.process(_source("2x2", "dots"), context)
    assert any("未通过本轮创建准入" in issue.message for issue in result.errors)
    result = processor.process(_source("2x2", "bars", backgroundColor="#FFFF0000"), context)
    assert any("图案根只接受" in issue.message for issue in result.errors)
    injected_cell = json.dumps([PATTERN_PREFIX + "cell_0_0", "Column", {}])
    result = processor.process(_source("2x2", "bars") + "\n" + injected_cell, context)
    assert any("不允许直接声明" in issue.message for issue in result.errors)
    no_selection = replace(context, countdown_pattern=None)
    result = processor.process(_source("2x2", "bars"), no_selection)
    assert any("未通过本轮创建准入" in issue.message for issue in result.errors)


@pytest.mark.parametrize("size", ["2x2", "2x4"])
@pytest.mark.parametrize("kind", ["bars", "dots"])
def test_online_first_frame_does_not_treat_model_total_as_real_data(size, kind):
    context = replace(_context(size, kind), initialize_countdown_total=True)
    result = DesignCompactProcessor().process(_source(size, kind, total=91), context)
    assert not result.errors, result.errors
    messages = [json.loads(line) for line in result.standard_dsl.splitlines()]
    counter = messages[2].get("updateDataModel", {}).get("value", {}).get("data", {}).get(
        "customCounter", {},
    )
    assert counter.get("intervalDays") == 0
    rows = [json.loads(line) for line in result.source_dsl.splitlines()]
    assert [ROOT + "/intervalDays", 0] in rows


@pytest.mark.parametrize("size", ["2x2", "2x4"])
@pytest.mark.parametrize("kind", ["bars", "dots"])
@pytest.mark.parametrize("total", [0, 6, 91])
def test_long_countdown_compiles_without_creation_day_gate(size, kind, total):
    result = DesignCompactProcessor().process(
        _source(size, kind, days=91, total=total), _context(size, kind),
    )
    assert not result.errors, result.errors


@pytest.mark.parametrize("size", ["2x2", "2x4"])
@pytest.mark.parametrize("kind", ["bars", "dots"])
def test_old_root_source_is_rejected_without_compatibility(size, kind):
    source = json.dumps([
        "root", "Layout", {
            "layout": COUNTDOWN_LAYOUTS.get(size), "pattern": kind,
            "eventTitle": "考试", "value": {"path": ROOT + "/days"},
        },
    ], ensure_ascii=False)
    result = DesignCompactProcessor().process(source, _context(size, kind))
    assert any("不兼容旧源 DSL" in issue.message for issue in result.errors)


@pytest.mark.parametrize("size", ["2x2", "2x4"])
@pytest.mark.parametrize("kind", ["bars", "dots"])
def test_old_three_role_source_is_rejected_without_migration(size, kind):
    bindings = {
        "value": {"path": ROOT + "/days"},
        "relationValue": {"path": ROOT + "/relationText"},
    }
    rows = [
        ["root", "Layout", {"layout": COUNTDOWN_LAYOUTS.get(size)},
         ["mainTitle", "subtitle", "pattern"]],
        ["mainTitle", "CountdownReadout", bindings],
        ["subtitle", "SingleLineTitle", {"title": "考试"}],
        ["pattern", "CountdownPattern", {
            **bindings, "kind": kind, "fillMode": "ratio",
            "totalValue": {"path": ROOT + "/intervalDays"},
        }],
        [ROOT + "/days", 4],
        [ROOT + "/relationText", "还剩"],
        [ROOT + "/intervalDays", 6],
    ]
    source = "\n".join(json.dumps(row, ensure_ascii=False) for row in rows)
    result = DesignCompactProcessor().process(source, _context(size, kind))
    assert result.errors
    assert not result.standard_dsl


@pytest.mark.parametrize("size", ["2x2", "2x4"])
@pytest.mark.parametrize("kind", ["bars", "dots"])
@pytest.mark.parametrize("prop", ["label", "pattern", "value", "relationValue", "totalValue"])
def test_high_level_source_requires_all_business_props(size, kind, prop):
    rows = [json.loads(line) for line in _source(size, kind).splitlines()]
    rows[1][2].pop(prop)
    source = "\n".join(json.dumps(row, ensure_ascii=False) for row in rows)
    result = DesignCompactProcessor().process(source, _context(size, kind))
    assert result.errors


@pytest.mark.parametrize("size", ["2x2", "2x4"])
@pytest.mark.parametrize("label", ["", "  ", 123, {"path": ROOT + "/label"}, "{{ '考试' }}"])
def test_event_label_must_be_nonempty_static_text(size, label):
    rows = [json.loads(line) for line in _source(size, "bars").splitlines()]
    rows[1][2]["label"] = label
    source = "\n".join(json.dumps(row, ensure_ascii=False) for row in rows)
    result = DesignCompactProcessor().process(source, _context(size, "bars"))
    assert result.errors


@pytest.mark.parametrize("size", ["2x2", "2x4"])
@pytest.mark.parametrize("kind", ["bars", "dots"])
def test_generated_prompt_uses_one_size_specific_component(size, kind):
    prompt = countdown_prompt(CountdownPattern(kind, ROOT + "/days"), size)
    example = prompt.split("```jsonl\n", 1)[1].split("```", 1)[0]
    rows = [json.loads(line) for line in example.splitlines()]
    assert len(rows) == 2
    assert rows[0] == ["root", "Layout", {"layout": COUNTDOWN_LAYOUTS.get(size)}, ["countdown"]]
    assert rows[1][1] == COUNTDOWN_COMPONENTS.get(size)
    assert rows[1][2].get("pattern") == kind
    assert set(rows[1][2]) == {"label", "pattern", "value", "totalValue", "relationValue"}


@pytest.mark.parametrize("size", ["2x2", "2x4"])
@pytest.mark.parametrize("kind", ["bars", "dots"])
@pytest.mark.parametrize(("prop", "value"), [
    ("fontSize", 20),
    ("lineHeight", 1.35),
    ("fontColor", "#FFFFFFFF"),
    ("fillMode", "ratio"),
    ("unit", "天"),
    ("totalValue", {"path": "/data/other/intervalDays"}),
    ("height", 60),
])
def test_high_level_source_rejects_visual_and_ratio_overrides(size, kind, prop, value):
    rows = [json.loads(line) for line in _source(size, kind).splitlines()]
    role_props = rows[1][2]
    role_props[prop] = value
    source = "\n".join(json.dumps(row, ensure_ascii=False) for row in rows)
    result = DesignCompactProcessor().process(source, _context(size, kind))
    assert result.errors


@pytest.mark.parametrize("size", ["2x2", "2x4"])
@pytest.mark.parametrize("kind", ["bars", "dots"])
def test_component_id_is_reference_and_does_not_control_visual_specs(size, kind):
    source = _source(size, kind).replace('"countdown"', '"myDisplay"')
    result = DesignCompactProcessor().process(source, _context(size, kind))
    assert not result.errors, result.errors
    themed = post_layout_theme.apply_theme(
        result.standard_dsl, post_layout_theme.fallback_theme(None), {"size": size}, {},
    )
    _assert_square_countdown_titles(themed)


@pytest.mark.parametrize("size", ["2x2", "2x4"])
@pytest.mark.parametrize("kind", ["bars", "dots"])
@pytest.mark.parametrize("mutation", ["type", "missing", "extra", "days", "relation", "children"])
def test_component_structure_and_binding_mismatches_are_rejected(size, kind, mutation):
    rows = [json.loads(line) for line in _source(size, kind).splitlines()]
    if mutation == "type":
        rows[1][1] = "WCountdown" if size == "2x2" else "SCountdown"
    elif mutation == "missing":
        rows[0][3] = []
        rows.pop(1)
    elif mutation == "extra":
        rows.append(["extra", "SingleLineTitle", {"title": "额外文字"}])
    elif mutation == "days":
        rows[1][2]["value"] = {"path": "/data/other/days"}
    elif mutation == "relation":
        rows[1][2]["relationValue"] = {"path": "/data/other/relationText"}
    else:
        rows[1].append(["countdown"])
    source = "\n".join(json.dumps(row, ensure_ascii=False) for row in rows)
    result = DesignCompactProcessor().process(source, _context(size, kind))
    assert result.errors


@pytest.mark.parametrize("component_type", ["SCountdown", "WCountdown"])
def test_specialized_display_cannot_escape_pattern_layout(component_type):
    from services.compact.compact_dsl_a2ui_converter import (
        CompactDslConversionError,
        convert_compact_dsl_to_a2ui,
    )

    source = json.dumps(["root", component_type, {
        "value": {"path": ROOT + "/days"},
        "relationValue": {"path": ROOT + "/relationText"},
    }])
    with pytest.raises(CompactDslConversionError, match="专用组件只能用于"):
        convert_compact_dsl_to_a2ui(source, size="2x2")


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["bars", "dots"])
@pytest.mark.parametrize("size", ["2x2", "2x4"])
@pytest.mark.parametrize(("days", "relation"), [(3, "还剩"), (0, "就是今天"), (3, "已过")])
async def test_fusion_create_delivers_pattern_after_real_theme_validation(
    monkeypatch, kind, size, days, relation,
):
    settings = get_settings()
    monkeypatch.setattr(settings, "enable_a2ui_model_mock", False)
    monkeypatch.setattr(settings, "enable_artifact_validation", True)
    monkeypatch.setattr(
        WidgetGenerationService, "_enable_card_template", staticmethod(lambda: False),
    )
    stages = []
    artifacts = []

    async def generate(_client, prompt, profile=None, **_kwargs):
        assert "本轮已通过单次图案倒计时准入" in prompt[0].get("content", "")
        if (profile or {}).get("format") == "raw-json":
            stages.append("plan")
            return json.dumps({
                "name": "submit_card_plan",
                "arguments": {
                    "info_required": [
                        {"requirement": "考试", "priority": "must", "text": "考试"},
                        {"requirement": "天数", "priority": "must", "dataId": ROOT + "/days"},
                        {
                            "requirement": "日期关系", "priority": "must",
                            "dataId": ROOT + "/relationText",
                        },
                    ],
                },
            }, ensure_ascii=False)
        stages.append("dsl")
        return _source(size, kind, days=days, relation=relation)

    async def select(source, task, _client, **kwargs):
        assert "allow_expansion" not in kwargs
        stages.append("theme")
        theme = post_layout_theme.fallback_theme(None)
        return post_layout_theme.apply_theme(source, theme, task, {}), {"theme": theme}

    def save(_store, saved_artifact):
        stages.append("save")
        artifacts.append(saved_artifact)
        return SimpleNamespace(artifactUrl="https://artifact.test/countdown", artifactDigest="test")

    monkeypatch.setattr(A2UIModelClient, "generate", generate)
    monkeypatch.setattr(post_layout_theme, "select_theme", select)
    monkeypatch.setattr(ArtifactStore, "save", save)
    preference = {"kind": kind}
    request = GenerateWidgetCardRequest(
        uid="test-user", prdVer="11.7.9.300", device={"romVersion": "7.0"},
        userQuery=f"做张考试倒计时卡，考试{relation} {days} 天",
        title="考试", description="考试倒计时",
        size=size, candidateDataBindings=[_binding().model_dump()],
        options={"countdownPattern": preference},
    )
    response = await WidgetGenerationService().generate_widget_card_compact_dsl(request)
    assert response.status == GenerationStatus.SUCCESS, response
    assert stages == ["plan", "dsl", "theme", "save"]
    artifact = next(iter(artifacts))
    messages = [json.loads(line) for line in artifact.genui.splitlines()]
    data_update = messages[2].get("updateDataModel", {})
    counter = data_update.get("value", {}).get("data", {}).get("customCounter", {})
    assert counter.get("days") == days
    assert counter.get("relationText") == relation
    assert counter.get("intervalDays") == 0
    assert "#FFFFFFFF" in artifact.genui
    assert "#33FFFFFF" in artifact.genui
    assert "@theme:" not in artifact.genui
    _assert_square_countdown_titles(artifact.genui)


def _recorded_plan_attachment(
    trace_path: Path, records: list[dict], event: str, name: str,
):
    record = next(item for item in records if item.get("event") == event)
    contents = record.get("artifacts")
    assert isinstance(contents, dict)
    attachment = contents.get(name)
    assert isinstance(attachment, dict)
    relative_path = attachment.get("path")
    assert isinstance(relative_path, str)
    payload = json.loads((trace_path.parent / relative_path).read_text(encoding="utf-8"))
    return attachment, payload


@pytest.mark.asyncio
@pytest.mark.parametrize(("size", "kind", "recurring", "use_pattern"), [
    ("2x2", "bars", False, True),
    ("2x4", "bars", False, True),
    ("2x2", "dots", True, True),
    ("2x4", "dots", True, True),
    ("2x2", "bars", False, False),
])
async def test_automatic_plan_can_deliver_and_replay_its_pattern(
    monkeypatch, tmp_path, size, kind, recurring, use_pattern,
):
    settings = get_settings()
    monkeypatch.setattr(settings, "enable_a2ui_model_mock", False)
    monkeypatch.setattr(settings, "enable_artifact_validation", True)
    monkeypatch.setattr(settings, "enable_generation_trace_recording", True)
    monkeypatch.setattr(settings, "generation_trace_root", tmp_path)
    monkeypatch.setattr(
        WidgetGenerationService, "_enable_card_template", staticmethod(lambda: False),
    )

    def resolve_at_creation(arguments, **_kwargs):
        return resolve_date_counter(arguments, today=date(2026, 11, 23))

    monkeypatch.setattr(generation_preflight, "resolve_date_counter", resolve_at_creation)
    bindings = _binding(targetDate="2026-11-26")
    if recurring:
        bindings = _binding(targetDate="2026-10-26", repeat={"unit": "month"})
    else:
        bindings.candidateOutputFields = ["/days", "/relationText"]
    bindings.candidateOutputFields.append("/targetDateText")
    plan_facts = [
        {
            "requirement": "考试", "priority": "must", "text": "考试",
            "componentHints": ["SingleLineTitle"],
        },
        {"requirement": "天数", "priority": "must", "dataId": ROOT + "/days"},
        {"requirement": "日期关系", "priority": "must", "dataId": ROOT + "/relationText"},
        {"requirement": "考试日期", "priority": "must", "dataId": ROOT + "/targetDateText"},
    ]
    artifacts = []

    async def generate(_client, prompt, profile=None, **_kwargs):
        if (profile or {}).get("format") == "raw-json":
            return json.dumps({
                "name": "submit_card_plan",
                "arguments": {"info_required": plan_facts},
            }, ensure_ascii=False)
        assistant_messages = [item for item in prompt if item.get("role") == "assistant"]
        assert len(assistant_messages) == 1
        plan_submission = json.loads(assistant_messages[0].get("content", ""))
        assert plan_submission.get("name") == "submit_card_plan"
        effective_plan = plan_submission.get("arguments")
        assert isinstance(effective_plan, dict)
        assert "dateCounterPresentation" in effective_plan
        assert ROOT + "/targetDateText" not in json.dumps(effective_plan)
        assert "dateCounterPresentation" not in prompt[-1].get("content", "")
        if use_pattern:
            return _source(size, kind, fixed_total=None if recurring else 3)
        label = "{{ '考试 ' + ${/data/customCounter/relationText} }}"
        rows = [
            ["root", "Layout", {"layout": "S-center"}, ["content"]],
            ["content", "DataDisplay", {
                "label": label, "value": {"path": ROOT + "/days"}, "unit": "天",
            }],
            [ROOT + "/days", 3],
            [ROOT + "/relationText", "还剩"],
        ]
        return "\n".join(json.dumps(row, ensure_ascii=False) for row in rows)

    async def select(source, task, _client, **kwargs):
        if use_pattern:
            final_layout = kwargs.get("final_layout")
            assert isinstance(final_layout, str)
            messages = [json.loads(line) for line in source.splitlines()]
            nodes = messages[1].get("updateComponents", {}).get("components")
            data = messages[2].get("updateDataModel", {}).get("value")
            assert isinstance(nodes, list)
            assert isinstance(data, dict)
            evidence = countdown_pattern_evidence(final_layout, nodes, data, size)
            assert evidence.get("complete"), evidence
            if recurring:
                assert evidence.get("totalPath") == ROOT + "/intervalDays"
            else:
                assert evidence.get("totalValue") == 3
        theme = post_layout_theme.fallback_theme(None)
        return post_layout_theme.apply_theme(source, theme, task, {}), {"theme": theme}

    def save(_store, saved_artifact):
        artifacts.append(saved_artifact)
        return SimpleNamespace(artifactUrl="https://artifact.test/countdown", artifactDigest="test")

    monkeypatch.setattr(A2UIModelClient, "generate", generate)
    monkeypatch.setattr(post_layout_theme, "select_theme", select)
    monkeypatch.setattr(ArtifactStore, "save", save)
    request = GenerateWidgetCardRequest(
        uid="batch-countdow-00001-000", prdVer="11.9.9.342", device={"romVersion": "7.0"},
        userQuery="做张考试倒计时卡，显示考试日期", title="考试", description="考试倒计时",
        size=size, candidateDataBindings=[bindings.model_dump()],
    )
    response = await WidgetGenerationService().generate_widget_card_compact_dsl(request)
    assert response.status == GenerationStatus.SUCCESS, response
    trace_path, = tmp_path.rglob("trace.jsonl")
    records = [json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines()]
    _, original_plan = _recorded_plan_attachment(
        trace_path, records, "plan.validation.completed", "accepted_plan",
    )
    rewrite_step = next(
        record for record in records if record.get("event") == "plan.date_counter_presentation"
    )
    plan_span = next(record for record in records if record.get("operation") == "plan")
    assert rewrite_step.get("recordType") == "span"
    assert rewrite_step.get("parentSpanId") == plan_span.get("spanId")
    duration = rewrite_step.get("durationMs")
    assert isinstance(duration, (float, int)) and duration >= 0
    rewrite_ref, rewritten_plan = _recorded_plan_attachment(
        trace_path, records, "plan.date_counter_presentation", "rewritten_plan",
    )
    _, prompt_messages = _recorded_plan_attachment(
        trace_path, records, "dsl.prompt.finalized", "dsl_prompt_final",
    )
    assistant = next(message for message in prompt_messages if message.get("role") == "assistant")
    assert rewrite_ref.get("role") == "output"
    assert ROOT + "/targetDateText" in json.dumps(original_plan)
    assert ROOT + "/targetDateText" not in json.dumps(rewritten_plan)
    assert rewritten_plan == json.loads(assistant.get("content", "")).get("arguments")

    artifact = next(iter(artifacts))
    if use_pattern:
        assert PATTERN_PREFIX + "cell_0_0" in artifact.genui
        assert "#33FFFFFF" in artifact.genui
        if recurring:
            assert ROOT + "/intervalDays" in artifact.genui
        else:
            assert ROOT + "/intervalDays" not in artifact.genui
            assert "/ 3)" in artifact.genui
        context = replace(
            _context(size, kind), countdown_pattern=None, replay_countdown_pattern=True,
            card_spec=artifact.cardSpec, task_spec=artifact.taskSpec,
        )
        replay = DesignCompactProcessor().process(
            _source(size, kind, fixed_total=None if recurring else 3), context,
        )
        assert not replay.errors, replay.errors
    else:
        assert PATTERN_PREFIX not in artifact.genui


@pytest.mark.parametrize(("fixed_total", "kind"), [(None, "bars"), (4, "bars"), (3, "dots")])
def test_automatic_plan_rejects_pattern_with_different_mode_total_or_kind(fixed_total, kind):
    plan = {"dateCounterPresentation": {
        "layout": "S-countdown-pattern", "component": "SCountdown", "pattern": "bars",
        "value": {"path": ROOT + "/days"}, "totalValue": 3,
    }}
    context = replace(_context("2x2", kind), countdown_pattern=None, compact_plan=plan)
    source = _source("2x2", kind, fixed_total=fixed_total)
    result = DesignCompactProcessor().process(source, context)
    assert any("未通过本轮创建准入" in issue.message for issue in result.errors)


def _assert_square_countdown_titles(genui: str) -> None:
    components = json.loads(genui.splitlines()[1]).get("updateComponents", {}).get("components")
    assert components is not None
    nodes = {component.get("id"): component for component in components}
    root = nodes.get("root")
    assert root is not None
    root_styles = root.get("styles", {})
    assert root_styles.get("borderRadius") == 20
    assert root_styles.get("clip") is True
    labels = nodes.get(PATTERN_PREFIX + "labels")
    assert labels is not None
    assert labels.get("children") == [PATTERN_PREFIX + "readout", PATTERN_PREFIX + "title"]
    assert labels.get("itemMargin") == 2
    assert labels.get("styles", {}).get("height") == 50
    countdown = nodes.get(PATTERN_PREFIX + "day_count", {})
    today = nodes.get(PATTERN_PREFIX + "today", {})
    event = nodes.get(PATTERN_PREFIX + "title", {})
    assert ROOT + "/days" in countdown.get("content", "")
    assert today.get("content") == "就是今天"
    assert event.get("content") == "考试"
    theme_roles = post_layout_theme.fallback_theme(None).get("content", {}).get("roles", {})
    for node in (countdown, today):
        styles = node.get("styles", {})
        assert (styles.get("height"), styles.get("fontSize"), styles.get("fontWeight")) == (
            27, 20, 700,
        )
        assert styles.get("fontColor") == theme_roles.get("primary")
        assert "lineHeight" not in styles
    styles = event.get("styles", {})
    assert (styles.get("height"), styles.get("fontSize"), styles.get("fontWeight")) == (21, 16, 400)
    assert styles.get("fontColor") == theme_roles.get("secondary")
    assert "lineHeight" not in styles


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["bars", "dots"])
async def test_ineligible_create_stops_before_model(monkeypatch, kind):
    async def generate(*_args, **_kwargs):
        pytest.fail("不适用图案的请求不应调用模型")

    monkeypatch.setattr(A2UIModelClient, "generate", generate)
    request = GenerateWidgetCardRequest(
        uid="test-user", prdVer="11.7.9.300", device={"romVersion": "7.0"},
        userQuery="做张考试倒计时卡", title="考试", description="考试倒计时",
        size="2x2", candidateDataBindings=[_binding(repeat={"unit": "month"}).model_dump()],
        options={"countdownPattern": {"kind": kind}},
    )
    response = await WidgetGenerationService().generate_widget_card_compact_dsl(request)
    assert response.status == GenerationStatus.UNSUPPORTED
    assert "周期" in response.message
