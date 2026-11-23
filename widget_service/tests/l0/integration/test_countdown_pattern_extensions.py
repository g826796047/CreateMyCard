"""图案专用正文、三色纹理和沙漏扩展，不改变普通图片规则。"""

import copy
import json
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from test_countdown_pattern_photos import (
    ROOT,
    artifact,
    pattern_extensions,
    pattern_photos,
    processed,
)

from config.config import get_settings
from services import post_layout_theme as themes
from services import post_layout_theme_registry as registry
from services.content_business import BusinessContext, FinalBusinessContext, VisibleBusinesses
from services.countdown_pattern import CountdownPattern
from services.generation_pipeline import DesignCompactProcessor
from services.protocol_registry import A2UIProtocolRegistry
from services.theme_content_regions import photo_layout_evidence
from services.theme_photo_eligibility import fusion_photo_facts
from services.theme_photo_matching import (
    PhotoMatchFacts,
    PhotoScopeFacts,
    eligible_photos,
    photo_reason,
)
from services.validator import ArtifactValidator


def facts_for(size, kind, days=4, relation="还剩", total=6, root=ROOT, mutation=None):
    source, context, standard, data = processed(size, kind, days, relation, total=total)
    if root != ROOT:
        task = json.loads(json.dumps(context.task_spec).replace("customCounter", "otherCounter"))
        card = json.loads(json.dumps(context.card_spec).replace(ROOT, root))
        context = replace(
            context, task_spec=task, card_spec=card,
            countdown_pattern=CountdownPattern(kind, root + "/days"),
        )
        source = source.replace(ROOT, root)
        result = DesignCompactProcessor().process(source, context)
        assert not result.errors, result.errors
        standard = result.standard_dsl
        data = themes.decode(standard)[-1].get("updateDataModel", {}).get("value")
    nodes = themes.components(themes.decode(standard))
    assert isinstance(data, dict)
    if mutation == "geometry":
        nodes[0].get("styles", {})["padding"] = 0
    elif mutation == "extra":
        nodes.append({"id": "extra", "component": "Text", "content": "额外"})
    elif mutation == "hidden-node":
        # 通用统计可能因此得到已知行数，扩展仍必须因完整结构不符而拒绝。
        nodes = [node for node in nodes if not node.get("id", "").endswith("_today")]
    elif mutation == "total":
        counter = data.get("data", {}).get(root.rsplit("/", 1)[-1], {})
        counter.pop("intervalDays")
    elif mutation == "relation":
        counter = data.get("data", {}).get(root.rsplit("/", 1)[-1], {})
        counter["relationText"] = "未知"
    evidence = photo_layout_evidence(nodes, data, final_layout=source, size=size)
    catalog = BusinessContext(data={root + "/days": "countdown"})
    if mutation == "business":
        catalog = BusinessContext()
    return fusion_photo_facts(
        context.task_spec, evidence, source,
        business_context=FinalBusinessContext.from_layout(source, catalog),
    )


@pytest.mark.parametrize("size", ["2x2", "2x4"])
@pytest.mark.parametrize("kind", ["bars", "dots"])
@pytest.mark.parametrize(("days", "relation", "total"), [
    (4, "还剩", 6), (0, "就是今天", 6), (3, "已过", 6), (4, "还剩", 0),
])
@pytest.mark.parametrize("root", [ROOT, "/data/otherCounter"])
def test_patterns_match_all_registered_extensions(size, kind, days, relation, total, root):
    facts = facts_for(size, kind, days, relation, total, root)
    allowed, _ = eligible_photos(facts)
    expected = set()
    for photo in [*pattern_photos(size), *pattern_extensions(size)]:
        expected.add(photo.get("id"))
    assert {photo.get("id") for photo in allowed} == expected
    assert len(allowed) == (12 if size == "2x2" else 11)
    assert facts.countdown_pattern.get("bodyFlow") == {"lineCount": 1, "leftAligned": True}
    card = facts.scopes.get("card")
    assert card is not None
    assert card.texture_flow.get("lineCount") is None


@pytest.mark.parametrize("size", ["2x2", "2x4"])
@pytest.mark.parametrize("kind", ["bars", "dots"])
@pytest.mark.parametrize("mutation", [
    "geometry", "extra", "hidden-node", "total", "relation", "business",
])
def test_invalid_pattern_cannot_fall_back_to_uniform_extensions(size, kind, mutation):
    facts = facts_for(size, kind, mutation=mutation)
    for photo in pattern_extensions(size):
        assert photo_reason(photo, facts) is not None


@pytest.mark.parametrize("size", ["2x2", "2x4"])
@pytest.mark.parametrize("business", [
    "countdown", "sport", "sleep", "music", "earphone", "calendar", "weather", "settings",
])
def test_nonpattern_rules_are_identical_without_extension_config(size, business):
    visible = VisibleBusinesses(
        single=business, first=business, ordered=(business,),
        data_businesses=frozenset({business}), data_paths=frozenset(),
    )
    scope = PhotoScopeFacts(
        businesses=visible, body_flow={"lineCount": 1, "leftAligned": True},
        texture_flow={"lineCount": 1, "leftAligned": True},
    )
    facts = PhotoMatchFacts(
        size=size, scopes={"card": scope, "left-main-dual": scope, "top-focus": scope},
        layout_id="S-center" if size == "2x2" else "W-top-bottom",
    )
    for photo in registry.registered_themes():
        if photo.get("kind") != "photo":
            continue
        original = copy.deepcopy(photo)
        original.get("contentEligibility", {}).pop("patternLayouts", None)
        assert photo_reason(photo, facts) == photo_reason(original, facts)


def test_only_fifteen_registered_assets_gain_pattern_layouts():
    identities = set()
    for color in ("orange", "purple", "blue"):
        for shape in ("diamond", "diagonal"):
            for suffix in ("square", "wide"):
                identities.add(f"photo-ux-texture-{color}-{shape}-{suffix}")
    identities.update({
        "photo-ux-hourglass-square", "photo-ux-glass-hourglass-square",
        "photo-ux-glass-hourglass-wide",
    })
    actual = set()
    for photo in registry.registered_themes(include_disabled=True):
        layouts = photo.get("contentEligibility", {}).get("patternLayouts")
        if layouts:
            actual.add(photo.get("id"))
            assert photo.get("enabled") is True
            expected = (
                "S-countdown-pattern" if photo.get("size") == "2x2" else "W-countdown-pattern"
            )
            assert layouts == [expected]
    assert actual == identities


@pytest.mark.parametrize(("prop", "value"), [
    ("patternLayouts", []), ("patternLayouts", ["W-countdown-pattern"]),
    ("patternLayouts", ["S-center"]),
    ("patternLayouts", ["S-countdown-pattern", "W-countdown-pattern"]),
    ("businesses", ["weather"]),
])
def test_registry_rejects_invalid_pattern_extension(prop, value):
    config = registry.load_theme_registry()
    target = next(
        theme for theme in config.get("themes", [])
        if theme.get("id") == "photo-ux-glass-hourglass-square"
    )
    target.get("contentEligibility", {})[prop] = value
    with pytest.raises(ValueError):
        registry.validate_registry(config)


@pytest.mark.parametrize("size", ["2x2", "2x4"])
def test_circles_and_disabled_hourglass_remain_unavailable(size):
    facts = facts_for(size, "bars")
    allowed, _ = eligible_photos(facts)
    ids = {photo.get("id") for photo in allowed}
    assert not any("circles" in identity for identity in ids)
    assert "photo-ux-hourglass-wide" not in ids


EXTENSIONS = [*pattern_extensions("2x2"), *pattern_extensions("2x4")]


@pytest.mark.asyncio
@pytest.mark.parametrize("photo", EXTENSIONS, ids=lambda photo: photo.get("id"))
async def test_explicit_background_preference_delivers_each_extension(monkeypatch, photo):
    size = photo.get("size")
    source, context, standard, _ = processed(size, "dots")
    evidence = "背景使用" + photo.get("name")
    context.task_spec["userQuery"] = "考试倒计时，" + evidence
    saved = artifact()
    saved.genui = standard
    saved.cardSpec = {**context.card_spec, "title": "考试", "description": "图案背景验证"}
    saved.taskSpec = context.task_spec
    saved.effectiveCapabilities["data"] = [{"id": "GetDateCounter"}]
    monkeypatch.setattr(get_settings(), "enable_photo_background_theme", True)
    client = SimpleNamespace(generate=AsyncMock(return_value=json.dumps({
        "themeId": photo.get("id"),
        "preferences": [{
            "property": "themeId", "operator": "prefer",
            "value": photo.get("id"), "evidence": evidence,
        }],
    }, ensure_ascii=False)))
    delivered = await themes.theme_artifact(
        saved, context.task_spec, client, ArtifactValidator({}),
        A2UIProtocolRegistry(saved.meta.protocolProfileId).get_profile(),
        final_layout=source, countdown_pattern=context.countdown_pattern,
    )
    nodes = themes.components(themes.decode(delivered.genui))
    image = next(node for node in nodes if node.get("id") == "__post_theme_base")
    assert image.get("src") == photo.get("remoteUrl")
    assert themes.foreground_signature(delivered.genui) == themes.foreground_signature(standard)


@pytest.mark.asyncio
@pytest.mark.parametrize("size", ["2x2", "2x4"])
async def test_default_selection_keeps_subject_priority(monkeypatch, size):
    source, context, standard, _ = processed(size, "bars")
    monkeypatch.setattr(get_settings(), "enable_photo_background_theme", True)
    client = SimpleNamespace(generate=AsyncMock(return_value=json.dumps({
        "themeId": pattern_photos(size)[0].get("id"), "preferences": [],
    })))
    _, audit = await themes.select_theme(
        standard, context.task_spec, client, final_layout=source,
        business_context=BusinessContext(data={ROOT + "/days": "countdown"}),
    )
    expected = set()
    for photo in [*pattern_photos(size), *pattern_extensions(size)]:
        if photo.get("pool") == "photos":
            expected.add(photo.get("id"))
    assert set(audit.get("photoSelection", {}).get("eligible", [])) == expected
    assert len(expected) == (6 if size == "2x2" else 5)
