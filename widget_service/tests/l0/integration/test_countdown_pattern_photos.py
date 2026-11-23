"""图案布局图片准入、首帧事实、素材和最终交付回归。"""

import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from test_countdown_pattern_create import ROOT, _context, _source
from test_photo_asset_delivery import artifact

from config.config import get_settings
from services import post_layout_theme as themes
from services import post_layout_theme_registry as registry
from services.content_business import BusinessContext, FinalBusinessContext
from services.generation_pipeline import DesignCompactProcessor
from services.protocol_registry import A2UIProtocolRegistry
from services.theme_content_regions import photo_layout_evidence
from services.theme_countdown_pattern import countdown_pattern_evidence
from services.theme_photo_eligibility import fusion_photo_facts
from services.theme_photo_matching import eligible_photos
from services.validator import ArtifactValidator


def pattern_photos(size=None):
    result = []
    for photo in registry.registered_themes("photos"):
        if photo.get("contentEligibility", {}).get("kind") != "countdown-pattern":
            continue
        if size is None or photo.get("size") == size:
            result.append(photo)
    return result


def pattern_extensions(size):
    layout = "S-countdown-pattern" if size == "2x2" else "W-countdown-pattern"
    result = []
    for photo in registry.registered_themes():
        policy = photo.get("contentEligibility", {})
        if layout in policy.get("patternLayouts", []):
            result.append(photo)
    return result


def processed(size, kind, days=4, relation="还剩", total=6):
    context = _context(size, kind)
    counter = context.task_spec.get("dataModelSchema", {}).get("data", {}).get("customCounter", {})
    days_schema = counter.get("days")
    relation_schema = counter.get("relationText")
    assert days_schema is not None and relation_schema is not None
    days_schema["sampleValue"] = days
    relation_schema["sampleValue"] = relation
    total_schema = counter.get("intervalDays")
    assert total_schema is not None
    total_schema["sampleValue"] = total
    source = _source(size, kind, days=days, relation=relation, total=total)
    result = DesignCompactProcessor().process(source, context)
    assert not result.errors, result.errors
    records = themes.decode(result.standard_dsl)
    data = records[-1].get("updateDataModel", {}).get("value")
    return source, context, result.standard_dsl, data


@pytest.mark.parametrize("size", ["2x2", "2x4"])
@pytest.mark.parametrize("kind", ["bars", "dots"])
@pytest.mark.parametrize(("days", "relation"), [(4, "还剩"), (0, "就是今天"), (3, "已过")])
def test_pattern_matches_registered_photos_without_device_geometry(size, kind, days, relation):
    source, context, standard, data = processed(size, kind, days, relation)
    evidence = photo_layout_evidence(
        themes.components(themes.decode(standard)), data, final_layout=source, size=size,
    )
    pattern = evidence.get("countdownPattern", {})
    assert pattern.get("complete") is True
    assert pattern.get("bodyFlow") == {"lineCount": 1, "leftAligned": True}
    assert pattern.get("deviceGeometryKnown") is False
    catalog = BusinessContext(data={ROOT + "/days": "countdown"})
    facts = fusion_photo_facts(
        context.task_spec, evidence, source,
        business_context=FinalBusinessContext.from_layout(source, catalog),
    )
    allowed, rejected = eligible_photos(facts)
    expected = set()
    for photo in [*pattern_photos(size), *pattern_extensions(size)]:
        expected.add(photo.get("id"))
    assert {item.get("id") for item in allowed} == expected
    assert len(allowed) == (12 if size == "2x2" else 11)
    assert len(rejected) > 0


@pytest.mark.parametrize("mutation", ["source", "geometry", "extra", "missing", "relation"])
def test_untrusted_or_changed_foreground_cannot_claim_pattern_photo(mutation):
    source, _, standard, data = processed("2x2", "bars")
    nodes = themes.components(themes.decode(standard))
    if mutation == "source":
        source = source.replace("S-countdown-pattern", "S-center")
    elif mutation == "geometry":
        nodes[0].get("styles", {})["padding"] = 0
    elif mutation == "extra":
        nodes.append({"id": "extra", "component": "Text", "content": "多余"})
    elif mutation == "missing":
        data = {}
    else:
        data.get("data", {}).get("customCounter", {})["relationText"] = "未知"
    evidence = countdown_pattern_evidence(source, nodes, data, "2x2")
    assert evidence.get("complete") is False


def test_new_assets_have_matching_remote_and_repository_metadata():
    root = Path(__file__).resolve().parents[4]
    photos = pattern_photos()
    assert len(photos) == 8
    for photo in photos:
        src = photo.get("src")
        assert isinstance(src, str)
        local = (root / src).read_bytes()
        shared = (root / "debug_tools/a2ui_render/entry/src/main" / src).read_bytes()
        assert local == shared
        metadata = photo.get("source", {})
        assert hashlib.sha256(local).hexdigest() == metadata.get("assetSha256")
        assert len(local) == metadata.get("assetBytes")
        assert photo.get("remoteUrl", "").startswith("https://")


@pytest.mark.parametrize("size", ["2x2", "2x4"])
@pytest.mark.parametrize("kind", ["bars", "dots"])
@pytest.mark.asyncio
async def test_real_theme_selection_delivers_photo_and_keeps_day_colors(monkeypatch, size, kind):
    source, context, standard, _ = processed(size, kind)
    original = artifact()
    original.genui = standard
    original.cardSpec = {**context.card_spec, "title": "考试", "description": "考试倒计时"}
    original.taskSpec = context.task_spec
    original.effectiveCapabilities["data"] = [{"id": "GetDateCounter"}]
    monkeypatch.setattr(get_settings(), "enable_photo_background_theme", True)
    monkeypatch.setattr(themes.secrets, "choice", lambda items: items[0])
    client = SimpleNamespace(generate=AsyncMock(return_value=json.dumps({
        "themeId": pattern_photos(size)[0].get("id"), "preferences": [],
    })))
    delivered = await themes.theme_artifact(
        original, context.task_spec, client, ArtifactValidator({}),
        A2UIProtocolRegistry(original.meta.protocolProfileId).get_profile(),
        final_layout=source, countdown_pattern=context.countdown_pattern,
    )
    nodes = themes.components(themes.decode(delivered.genui))
    backgrounds = [node for node in nodes if node.get("id") == "__post_theme_base"]
    assert len(backgrounds) == 1
    subjects = [*pattern_photos(size)]
    for photo in pattern_extensions(size):
        if photo.get("pool") == "photos":
            subjects.append(photo)
    assert backgrounds[0].get("src") in {photo.get("remoteUrl") for photo in subjects}
    assert themes.foreground_signature(delivered.genui) == themes.foreground_signature(standard)
    cells = []
    for node in nodes:
        if node.get("id", "").startswith("__layout__root__countdown_cell_"):
            cells.append(node)
    assert cells
    for cell in cells:
        styles = cell.get("styles", {})
        if cell.get("component") == "Stack":
            assert styles.get("backgroundColor") == "#33FFFFFF"
        else:
            assert styles.get("backgroundColor") == "#FFFFFFFF"
            assert ROOT + "/intervalDays" in styles.get("height", "")
    assert client.generate.await_count == 1


def test_unknown_business_is_not_inferred_from_user_words():
    source, context, standard, data = processed("2x2", "bars")
    evidence = photo_layout_evidence(
        themes.components(themes.decode(standard)), data, final_layout=source, size="2x2",
    )
    context.task_spec["userQuery"] = "考试倒计时背景图"
    facts = fusion_photo_facts(context.task_spec, evidence, source)
    allowed, _ = eligible_photos(facts, pattern_photos())
    assert not allowed


def test_registry_rejects_pattern_policy_mixed_with_ordinary_layout_rules():
    config = registry.load_theme_registry()
    changed = copy.deepcopy(config)
    target = None
    for theme in changed.get("themes", []):
        if theme.get("contentEligibility", {}).get("kind") == "countdown-pattern":
            target = theme
            break
    assert target is not None
    target.get("contentEligibility", {})["wideLayout"] = "main-focus"
    with pytest.raises(ValueError, match="cannot mix"):
        registry.validate_registry(changed)
