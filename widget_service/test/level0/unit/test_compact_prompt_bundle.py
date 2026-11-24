"""Compact 提示词源模块加载、路由与完整性回归；不调用线上模型。"""

import json
import shutil
from pathlib import Path

import pytest

from config.config import get_settings
from models.generation import TaskSpec
from services.compact.layout.compact_layout_runtime import layout_ids_for_size
from services.generation import prompt_builder
from services.generation.prompt_builder import PromptBuilder
from services.protocols.compact_prompt_loader import (
    FRAGMENT,
    PROMPT_NAMES,
    _cached_prompts,
    assemble_prompts,
    read_prompt,
)
from services.protocols.protocol_registry import (
    DESIGN_COMPACT_PROFILE_ID,
    A2UIProtocolRegistry,
)

DEFAULT_BUNDLE = (
    Path(__file__).resolve().parents[3] / "cloud/data/protocol_profiles/design-compact-dsl-fusion"
)
DEFAULT_SOURCE = DEFAULT_BUNDLE / "prompt_source"

CREATE_SOURCE_ORDER = (
    "core.md",
    "information/common.md",
    "information/2x2.md",
    "information/2x4.md",
    "components/common.md",
    "components/2x2.md",
    "components/2x4.md",
    "combinations/common.md",
    "combinations/2x2.md",
    "combinations/2x4.md",
    "composition.md",
    "layouts/common.md",
    "layouts/2x2.md",
    "layouts/2x4.md",
)


def test_assembled_prompts_are_model_facing() -> None:
    prompts = assemble_prompts(DEFAULT_SOURCE)
    assert set(prompts) == PROMPT_NAMES
    for content in prompts.values():
        assert "<!-- prompt:" not in content
        assert "维护源" not in content


@pytest.mark.parametrize("phase", ["create", "plan", "repair"])
def test_s_center_layout_rules_reach_model_facing_prompts(phase: str) -> None:
    prompt = read_prompt(DEFAULT_SOURCE, phase, size="2x2")
    assert "11vp" in prompt
    assert "两行6vp" in prompt
    assert "卡片底边12vp" in prompt
    assert "数值到副标题间距不固定" in prompt
    assert "副标题为空时" in prompt
    assert "整组" in prompt
    if phase == "plan":
        assert "S-center 单数值角色" in prompt
        assert "目标日期" in prompt
    elif phase == "repair":
        assert "可选副标题位于底部" in prompt
        assert "主内容组layoutWeight:1居中" in prompt
    else:
        assert "标题包装自然高度" in prompt
    if phase != "plan":
        assert "数字文字框58vp、数值行62vp，单位底部外边距10vp" in prompt
        assert "不输出lineHeight" in prompt
        assert "固定数值行62vp" in prompt
    for stale_rule in (
        "标题区60vp", "标题区固定60vp", "最小高62vp", "单位底部外边距12vp",
        "两处文字框间距均11vp", "121/142vp", "166vp参考高度",
    ):
        assert stale_rule not in prompt


def test_s_center_layout_rules_reach_runtime_continuation(monkeypatch) -> None:
    # 关闭示例，避免示例或历史源提示词中的相同文字掩盖运行时注入遗漏。
    monkeypatch.setattr(get_settings(), "enable_design_compact_few_shots", False)
    task = TaskSpec(size="2x2", userQuery="显示耳机电量", dataModelSchema={"data": {}})
    plan = {"layoutHints": ["S-center"], "info_required": []}
    conversation = [
        {"role": "system", "content": "创建合同"},
        {"role": "user", "content": "显示耳机电量"},
        {"role": "user", "content": "提交计划"},
        {"role": "assistant", "content": json.dumps(plan)},
    ]
    continued = PromptBuilder.build_compact_dsl_continuation(conversation, task, plan)
    prompt = continued[-1].get("content", "")
    assert continued[-1].get("role") == "user"
    assert "<agent_stage>compact_dsl</agent_stage>" in prompt
    for rule in (
        "S-center数值DataDisplay", "主标题16fp/500、最多两行",
        "底部副标题12fp/500、单行", "数值46fp及单位16fp",
        "标题到数值行间距一行11vp、两行6vp", "副标题框底边距卡片底边12vp",
        "标题和数值整组在剩余区域居中", "无副标题时占满内容区居中",
        "数值到副标题间距不固定", "不提交字号或内部布局",
    ):
        assert rule in prompt
    for stale_rule in ("标题区60vp", "标题区固定60vp", "两处文字框间距均11vp"):
        assert stale_rule not in prompt


def test_create_prompt_loads_each_source_as_one_complete_block() -> None:
    manifest = json.loads((DEFAULT_SOURCE / "manifest.yaml").read_text(encoding="utf-8"))
    prompts = manifest.get("prompts")
    assert isinstance(prompts, dict)
    references = prompts.get("create")
    assert isinstance(references, list)
    assert "countdown_layout" not in prompts

    expected_references = []
    for filename in CREATE_SOURCE_ORDER:
        content = (DEFAULT_SOURCE / filename).read_text(encoding="utf-8")
        fragment_names = [name for name, _body in FRAGMENT.findall(content)]
        assert fragment_names
        for name in fragment_names:
            expected_references.append(f"{filename}#{name}")

    assert references == expected_references


@pytest.mark.parametrize(
    ("size", "layout", "other_layout"),
    [
        ("2x2", "S-countdown-pattern", "W-countdown-pattern"),
        ("2x4", "W-countdown-pattern", "S-countdown-pattern"),
    ],
)
def test_countdown_layout_prompt_is_conditional_and_size_specific(
    size: str,
    layout: str,
    other_layout: str,
) -> None:
    prompts = assemble_prompts(DEFAULT_SOURCE, size)

    example_name = "countdown_fewshot_s_pattern" if size == "2x2" else "countdown_fewshot_w_pattern"
    for name, content in prompts.items():
        assert other_layout not in content
        assert (layout in content) == (name in {"create", example_name})
    create = prompts.get("create", "")
    component = "SCountdown" if size == "2x2" else "WCountdown"
    assert f"Layout＋{component}" in create
    assert f"根仅提交 layout，children 只引用一个 {component}" in create
    assert "自动单次图案的 totalValue 使用生效 Plan 指定的固定正整数" in create
    assert "周期图案的 totalValue 绑定同级 /intervalDays" in create
    assert "不提交 unit、fillMode、视觉属性" in create

    task = TaskSpec(size=size, userQuery="做张倒计时卡", dataModelSchema={"data": {}})
    prompt = PromptBuilder().build_design_token(
        task, create, DESIGN_COMPACT_PROFILE_ID, defer_compact_examples=True,
    )
    system = prompt[0].get("content", "")
    assert f"`{layout}` 仅在本轮生效 Plan 的日期选型选中时开放" in system
    assert system.count(f"`{layout}`：图案倒计时") == 1
    assert other_layout not in system


def test_info_block_contract_is_noninteractive() -> None:
    create_prompt = assemble_prompts(DEFAULT_SOURCE).get("create")

    assert isinstance(create_prompt, str)
    assert "InfoBlock.onClick" not in create_prompt
    assert "合法可点击 InfoBlock" not in create_prompt
    assert "外层和内部均不得写 `onClick`" in create_prompt
    plain_example = (
        '["weather","InfoBlock",'
        '{"primaryText":{"path":"/data/weather/current/temperatureText"}'
    )
    icon_example = (
        '"visual":{"type":"icon",'
        '"icon":"resources/base/media/moon_z_fill_1.svg"}'
    )
    progress_example = (
        '"visual":{"type":"progressCircle",'
        '"icon":"resources/base/media/battery_leaf_fill.svg"}'
    )
    assert plain_example in create_prompt
    assert icon_example in create_prompt
    assert progress_example in create_prompt
    assert "两个同级 InfoBlock 必须放入无标题的 S-dual-info" in create_prompt
    assert '"layout":"S-dual-info"' in create_prompt
    assert '"variant":"stacked","primaryText":"{{ \'明天 \' +' not in create_prompt
    assert "每行只承载一个动态业务值" in create_prompt


def test_single_line_title_icon_uses_semantic_match_and_button_priority() -> None:
    source = (DEFAULT_SOURCE / "core.md").read_text(encoding="utf-8")
    fragments = dict(FRAGMENT.findall(source))
    rules = fragments.get("input-candidates", "")
    assert "先给按钮分配准确动作图标" in rules
    assert "未占用候选给标题选匹配图标" in rules
    assert "不为标题撤掉准确按钮图标" in rules
    assert "默认同一 src 只用一次" in rules
    assert "同类对象" in rules
    assert "可选图标无匹配时省略" in rules


def test_card_button_icon_color_is_runtime_owned() -> None:
    common = (DEFAULT_SOURCE / "components/common.md").read_text(encoding="utf-8")
    two_by_four = (DEFAULT_SOURCE / "components/2x4.md").read_text(encoding="utf-8")
    rule = "不输出；单色 SVG 由运行时按按钮前景色自动染色，位图保留原色"

    assert rule in common
    assert rule in two_by_four
    assert '"CardButton",{"label":"蓝牙设置","icon":' in two_by_four
    explicit_color = (
        '"CardButton",{"label":"蓝牙设置",'
        '"icon":"resources/base/media/bluetooth_fill.svg","fillColor"'
    )
    assert explicit_color not in two_by_four


def test_anchor_layout_requires_main_and_nonempty_support_information() -> None:
    create = read_prompt(DEFAULT_SOURCE, "create", size="2x2")
    plan = read_prompt(DEFAULT_SOURCE, "plan", size="2x2")
    for rule in (
        "没有独立支撑事实时排除", "准确SVG", "至少有一个独立左下事实",
        "左下可用SecondaryBody", "其它位置已有核心信息组件", "标题、动作及只在标题",
    ):
        assert rule in create
    assert "缺独立支撑事实时排除它" in plan
    assert "不以 `PillButton` 无法闭合为前提" in create
    assert "不等于要求卡面显示动作文字" in create


def test_create_prompt_uses_unified_component_terms() -> None:
    create = read_prompt(DEFAULT_SOURCE, "create", size="2x2")
    assert "Row/Column/Stack" in create
    assert "| `Row` | 横向排列子组件 |" not in create
    for deprecated in ("基础组件", "高阶组件", "高级组件", "普通组件", "基础组合"):
        assert deprecated not in create


def test_secondary_body_contract_groups_related_items() -> None:
    prompt = read_prompt(DEFAULT_SOURCE, "create", size="2x4")

    assert "组件不区分 role" in prompt
    assert "多个短字段按原顺序放入一个实例" in prompt
    assert "两项同行用 14；两项 `columns:1` 分行用 12" in prompt
    assert "标题、Badge、按钮、布局容器和其它 `SecondaryBody`" in prompt


def test_wide_countdown_layout_reaches_online_generation_and_repair_prompts() -> None:
    task = TaskSpec(userQuery="运动会倒计时", size="2x4", dataModelSchema={"data": {}})
    create = read_prompt(DEFAULT_SOURCE, "create", size="2x4")
    plan = read_prompt(DEFAULT_SOURCE, "plan", size="2x4")
    builder = PromptBuilder()
    plan_messages = builder.build_compact_plan(task, create + "\n\n" + plan, "{}")
    generation = builder.build_design_token(
        task, create, DESIGN_COMPACT_PROFILE_ID,
        compact_plan={"layoutHints": ["W-countdown-center"], "info_required": []},
    )
    repair = builder.build_repair(
        generation, "invalid dsl", [], dsl_format=DESIGN_COMPACT_PROFILE_ID, task_spec=task,
    )

    assert "| W-countdown-center |" in create
    for messages in (plan_messages, generation, repair):
        system = messages[0].get("content")
        assert isinstance(system, str)
        assert "W-countdown-center" in system
    assert any(
        "W-countdown-center 槽位错误或内容超限" in message.get("content", "")
        for message in repair
    )


def test_static_explanation_preserves_dynamic_supporting_text_contract() -> None:
    component = (DEFAULT_SOURCE / "components/common.md").read_text(encoding="utf-8")
    repair = read_prompt(DEFAULT_SOURCE, "repair")
    assert "`secondaryText` 仅作静态说明时" in component
    assert "辅助行已有动态事实时不能覆盖它" in component
    assert "先按组件合同恢复读数与静态说明的分工" in repair
    assert "不得覆盖动态辅助值" in repair


@pytest.mark.parametrize("size", ["2x2", "2x4"])
def test_owned_action_layout_comparison_is_size_scoped_and_reaches_plan(size: str) -> None:
    create = read_prompt(DEFAULT_SOURCE, "create", size=size)
    rule = "先比较内容组与直属操作的归属，再比较操作数量"
    task = TaskSpec(userQuery="查看设备状态及操作", size=size, dataModelSchema={"data": {}})
    plan = read_prompt(DEFAULT_SOURCE, "plan", size=size)
    messages = PromptBuilder().build_compact_plan(task, create + "\n\n" + plan, "{}")
    system = messages[0].get("content")
    assert isinstance(system, str)
    assert (rule in create) == (size == "2x4")
    assert (rule in system) == (size == "2x4")
    assert "先判断事实在同组中是主值、标签、单位、补充还是事件要素" in system
    if size == "2x4":
        assert "左右Region容量不成立时仍比较其它合法布局，不强行分区" in system


def test_secondary_body_repair_does_not_add_non_core_companions() -> None:
    repair_prompt = read_prompt(DEFAULT_SOURCE, "repair", size="2x2")
    assert "SecondaryBody 不能成为整卡唯一正文核心" in repair_prompt
    assert "不用按钮/标题假充核心" in repair_prompt


def test_agent_stage_instruction_does_not_forbid_registered_semantic_layout() -> None:
    task = TaskSpec(userQuery="查看设备状态", size="2x4", dataModelSchema={"data": {}})
    scope = PromptBuilder._compact_generation_scope(task)
    assert "最终 DSL 使用 Layout" in scope
    assert "Region 选择内容变体" in scope
    assert "不输出布局 ID、Card 或 Region 节点" not in scope


@pytest.mark.parametrize("size", ["2x2", "2x4"])
def test_plan_prompt_contains_only_incremental_contract(size: str) -> None:
    plan_prompt = read_prompt(DEFAULT_SOURCE, "plan", size=size)

    assert "# Compact Info Plan" in plan_prompt
    assert "submit_card_plan" in plan_prompt
    assert "你是 HarmonyOS 桌面卡片极简协议 DSL 生成模型" not in plan_prompt
    assert "## 1. 组件总表" not in plan_prompt
    assert "## 2x2 组件选型" not in plan_prompt
    assert "## 2x4 组件选型" not in plan_prompt


def test_plan_prompt_requires_bounded_three_item_list_selection_without_runtime_cap() -> None:
    plan_prompt = read_prompt(DEFAULT_SOURCE, "plan", size="2x4")

    assert "2x4 有序列表的 Plan 容量例外" in plan_prompt
    assert "必须在 Plan 阶段只选入最多 3 个完整成员进入 `info_required`" in plan_prompt
    assert "不得将第 4 个及" in plan_prompt
    assert "后续成员写入 Plan" in plan_prompt
    assert "没有额外优先级时，按输入原始顺序保留前 3 个" in plan_prompt
    assert "Action 及其完整参数不适用此例外" in plan_prompt
    assert "不是 Runtime 对 `EventCard.items` 新增最多 3 项的硬上限" in plan_prompt


def test_repair_prompt_suggests_lossless_event_card_to_summary_list_compaction() -> None:
    repair_prompt = read_prompt(DEFAULT_SOURCE, "repair", size="2x4")

    assert "EventCard 总高超出父槽" in repair_prompt
    assert "accepted Plan 只保留 2–3 条同级短事件" in repair_prompt
    assert "优先比较改用 `SummaryList`" in repair_prompt
    assert "动态字段用 Expression 保留全部 PathBinding" in repair_prompt
    assert "2项按64vp、3项按102vp重算高度" in repair_prompt
    assert "超过3项、存在多行长地点" in repair_prompt


@pytest.mark.parametrize("size", ["2x2", "2x4"])
def test_plan_and_create_prompts_forbid_invented_advice_copy(size: str) -> None:
    create_prompt = read_prompt(DEFAULT_SOURCE, "create", size=size)
    plan_prompt = read_prompt(DEFAULT_SOURCE, "plan", size=size)
    invented_copy = "今天适合跑步吗？天气舒适，适合跑步"

    assert invented_copy in plan_prompt
    assert invented_copy in create_prompt
    assert "不得为填充支撑区" in plan_prompt
    assert "不在 `SecondaryBody.items[].value`" in create_prompt
    assert '"value":"补充说明"' not in create_prompt


def test_plan_manifest_only_registers_incremental_contract() -> None:
    manifest = json.loads((DEFAULT_SOURCE / "manifest.yaml").read_text(encoding="utf-8"))
    prompts = manifest.get("prompts")
    assert isinstance(prompts, dict)
    plan_references = prompts.get("plan")
    assert isinstance(plan_references, list)

    assert plan_references == ["plan.md#contract"]


def test_create_prompt_defers_output_format_to_latest_agent_stage() -> None:
    create = read_prompt(DEFAULT_SOURCE, "create", size="2x4")
    assert "最后一个 `<agent_stage>` 决定输出" in create
    assert "`plan`：按本轮工具 Schema 提交一次" in create
    assert "`compact_dsl` 或无标记" in create
    assert "两个阶段共用输入、组件和布局合同" in create


def test_core_does_not_repeat_final_prohibition_checklist() -> None:
    manifest = json.loads((DEFAULT_SOURCE / "manifest.yaml").read_text(encoding="utf-8"))
    create_references = manifest.get("prompts", {}).get("create")
    core_source = (DEFAULT_SOURCE / "core.md").read_text(encoding="utf-8")

    assert isinstance(create_references, list)
    assert "core.md#prohibitions-checks" not in create_references
    assert "prompt:prohibitions-checks" not in core_source
    assert "整卡编排与提交检查" in read_prompt(
        DEFAULT_SOURCE,
        "create",
        size="2x4",
    )


def test_two_by_two_layout_prompt_delegates_geometry_to_semantic_templates() -> None:
    source = (DEFAULT_SOURCE / "layouts/2x2.md").read_text(encoding="utf-8")
    layouts = dict(FRAGMENT.findall(source)).get("s-layouts", "")

    for removed_budget in (
        "20 + 6 + 100",
        "20 + 6 + 46 + 8 + 46",
        "20 + 6 + 56 + 8 + 36",
        "20 + 4 + 58 + 8 + 36",
        "38 + 8 + 36 + 8 + 36",
        '"layoutWeight":13',
        '"layoutWeight":10',
        '"height":20',
        "82vp` 文字组",
    ):
        assert removed_budget not in layouts

    for retained_contract in (
        "Layout是root",
        "不输出Row/Column/Stack",
        "padding8",
        "40×40槽居中",
        "按钮36vp",
        '"Layout"',
    ):
        assert retained_contract in layouts

    assert "[content, PillButton, PillButton]" in layouts
    assert '`variant:"actions-only"`，children 为 `[CardButton, CardButton]`' in layouts
    assert '`variant:"actions-only"`，children 为 `[PillButton, PillButton]`' not in layouts


def test_two_by_four_layout_prompt_delegates_geometry_to_semantic_templates() -> None:
    source = (DEFAULT_SOURCE / "layouts/2x4.md").read_text(encoding="utf-8")
    fragments = dict(FRAGMENT.findall(source))
    layouts = fragments.get("w-layouts", "")

    assert list(fragments) == ["w-layouts"]
    for removed_budget in (
        "132 + 12 + 132",
        "57 + 12 + 57",
        "70vp` 正文 + `4vp`",
        "4×16+3×2",
        "26 + 6 + 36 + 6 + 36",
        "38 + 8 + 36 + 8 + 36",
        "title 20 + 4 + body 86",
        '"layoutWeight":15',
        '"layoutWeight":8',
        '"height":20',
    ):
        assert removed_budget not in layouts

    for retained_contract in (
        "132×126vp",
        "132×57vp",
        "116×110vp",
        "W-split-panels.left/right Region主要角色间距6vp",
        "W-content-side-slots.content Region为8vp",
        '"Layout"',
        '"Region"',
    ):
        assert retained_contract in layouts

    for sub_layout in (
        "center",
        "title-content",
        "title-hero-support",
        "title-content-action",
        "title-two-ratios",
        "title-hero-support-action",
        "four-ratios",
        "four-items",
    ):
        assert sub_layout in layouts

    create_prompt = assemble_prompts(DEFAULT_SOURCE, size="2x4").get("create")
    assert isinstance(create_prompt, str)
    for naming_rule in (
        "不自行缩写、拼接或增删后缀",
        "Group 的 `hero-support` 只有 `[hero, support]`",
        "第四项 PillButton",
        "没有内部按钮时选择已登记的 `title-hero-support`",
    ):
        assert naming_rule in layouts
        assert naming_rule in create_prompt

    for example_rule in (
        "以下骨架只展示结构角色",
        "先选父区，再按直属角色选variant",
        "第二、第三个是固定槽，不是另外两个Region",
        "children数量按直属组件ID计",
        "W-split-panels.left/right 与 W-content-side-slots.content 都支持",
        "仅 W-content-side-slots.content 支持",
        "四行SecondaryBody至少占70vp",
        "四格，不是父布局W-four-slots",
    ):
        assert example_rule in layouts
        assert example_rule in create_prompt

    for parent_specific_rule in (
        "两个：left、right都是Region",
        "一个：只有content是Region",
        "upper/lower不能放Region、标题、详情组或PillButton",
        "禁止直接使用title-hero-support-action",
        "hero-support Group作为唯一content",
        "唯一content使用Group.hero-support",
        "不选择Region variant；直接使用InfoBlock或CardButton",
    ):
        assert parent_specific_rule in layouts
        assert parent_specific_rule in create_prompt

    combinations = (DEFAULT_SOURCE / "combinations/2x4.md").read_text(encoding="utf-8")
    assert "紧凑版" not in layouts
    assert "宽版" not in layouts
    assert "紧凑/宽版" not in combinations
    assert "W-content-side-slots.content独有的结构" in combinations

    for removed_preset in (
        "neutral-footer",
        "text-footer",
        "value-led",
        "metric-triple",
        "progress-detail",
        "ring-summary",
        "list-rows",
        "ring-detail",
        "agenda-cta",
        "受控内容预设",
    ):
        assert removed_preset not in layouts


@pytest.mark.parametrize("size", ["2x2", "2x4"])
def test_plan_prompt_does_not_duplicate_create_contract(size: str) -> None:
    create_prompt = read_prompt(DEFAULT_SOURCE, "create", size=size)
    plan_prompt = read_prompt(DEFAULT_SOURCE, "plan", size=size)

    heading = "## 1. 组件总表"
    assert create_prompt.count(heading) == 1
    assert plan_prompt.count(heading) == 0
    assert plan_prompt not in create_prompt


def test_common_component_contract_separates_shared_and_size_specific_rules() -> None:
    source = (DEFAULT_SOURCE / "components/common.md").read_text(encoding="utf-8")
    fragments = dict(FRAGMENT.findall(source))
    assert list(fragments) == ["selection", "catalog"]
    catalog = fragments.get("catalog", "")
    for shared in (
        "SingleLineTitle", "DoubleLineTitle", "Badge", "EmphasizedData", "EmphasisText",
        "SecondaryBody", "InfoBlock", "TableText", "ProgressCircle", "H_BarChart",
        "ProgressCircleSingle", "NumericRatioStack", "EventCard", "PillButton",
    ):
        assert f"`{shared}`" in catalog
    for exclusive in ("DataDisplay", "SummaryList", "ProgressLine2"):
        assert f" `{exclusive}`\n" not in catalog
    for forbidden in ("| `width`", "| `height`", "| `role`", "fontColor"):
        assert forbidden not in catalog
    assert "内部次字号、字重、颜色和几何不用输出" in catalog
    assert "多源时使用至少 2 个有序 PathBinding" in catalog
    assert "数组由转换器按顺序以 ` | ` 连接" in catalog
    assert "静态 / PathBinding；不接受 Expression" in catalog
    assert "| `items[].label` | 显示值 |" in catalog


def test_emphasis_text_prompt_limits_labels_to_wind_and_rain_probability() -> None:
    source = (DEFAULT_SOURCE / "components/common.md").read_text(encoding="utf-8")

    assert "不默认补充“当前温度”等冗余短标签" in source
    assert "当前仅风力与降雨概率" in source
    assert "风力 2级" in source
    assert "降雨概率 20%" in source
    assert "其它动态读数不主动添加短标签" in source
    assert "生成时需在 `mainText` 或 `secondaryText` 中附上" not in source
    assert "这只是生成提示，不属于 Plan 或 DSL 的强制校验。" in source


def test_button_label_contract_preserves_action_while_limiting_visible_text() -> None:
    common = (DEFAULT_SOURCE / "components/common.md").read_text(encoding="utf-8")
    wide = (DEFAULT_SOURCE / "components/2x4.md").read_text(encoding="utf-8")
    plan = (DEFAULT_SOURCE / "plan.md").read_text(encoding="utf-8")
    repair = (DEFAULT_SOURCE / "repair.md").read_text(encoding="utf-8")

    assert common.count("最多6个可见字符") >= 2
    assert "最多6个可见字符，保留动作与必要目标" in wide
    assert "Plan 中 Action 的 requirement 保留完整操作语义" in plan
    assert "一键导航去公司”改为“导航去公司" in repair
    assert "完整保留onClick、参数、真实目标" in repair


def test_two_peer_facts_use_equal_info_blocks_instead_of_fake_primary_support() -> None:
    common_components = (DEFAULT_SOURCE / "components/common.md").read_text(encoding="utf-8")
    small_components = (DEFAULT_SOURCE / "components/2x2.md").read_text(encoding="utf-8")
    combinations = (DEFAULT_SOURCE / "combinations/common.md").read_text(encoding="utf-8")
    plan = (DEFAULT_SOURCE / "plan.md").read_text(encoding="utf-8")
    create_prompt = read_prompt(DEFAULT_SOURCE, "create", size="2x2")

    assert "恰好两个等权、各自能够独立" in common_components
    assert "理解的短信息不是“核心 + 补充”" in common_components
    assert "各用一个 `InfoBlock` 并选择 `S-dual-info`" in small_components
    assert "不把其中一项降为" in common_components
    assert "`SecondaryBody`" in common_components
    assert "不先拆成一个强调值与另一个辅助值" in combinations
    assert "双信息块组合的事实首选 InfoBlock" in plan
    assert "两个等权短事实" in create_prompt
    assert "第二项独立事实或" not in small_components


def test_size_component_rules_separate_shared_and_dedicated_components() -> None:
    common = read_prompt(DEFAULT_SOURCE, "create", size="2x2")
    wide = read_prompt(DEFAULT_SOURCE, "create", size="2x4")
    for name in ("DataDisplay", "CircleButton"):
        assert f" `{name}`\n" in common
        assert f" `{name}`\n" not in wide
    for name in ("TextBlock", "TopTextBottomValue", "ProgressLine2", "SummaryList"):
        assert f" `{name}`\n" in wide
        assert f" `{name}`\n" not in common
    assert "只允许进入 `W-top-bottom` 的 details" in wide
    assert "整卡改选为 `W-top-bottom`" in wide
    assert "明细可为TextBlock/TopTextBottomValue/SummaryList/EventCard" in wide
    assert "可进入 W-top-bottom.primary/details" in wide
    assert "仅在 `W-top-bottom` 的primary和details" in wide
    assert "合法可点击 Row/Column" not in wide
    assert "写 `height:50`" not in common
    assert "| `items[].label` | 显示值 |" in wide


def test_runtime_does_not_depend_on_generated_products() -> None:
    assert not list((DEFAULT_BUNDLE / "generated").glob("*.md"))
    assert not (Path(__file__).resolve().parents[3] / "scripts/build_compact_prompts.py").exists()
    assert read_prompt(DEFAULT_SOURCE, "create") == assemble_prompts(DEFAULT_SOURCE).get("create")


def test_information_modules_keep_semantic_boundary() -> None:
    root = DEFAULT_BUNDLE / "prompt_source/information"
    expected_fragments = {
        "common.md": ["contract"],
        "2x2.md": ["capacity"],
        "2x4.md": ["capacity"],
    }
    prompt_bodies = []
    for filename, expected in expected_fragments.items():
        source = (root / filename).read_text(encoding="utf-8")
        fragments = dict(FRAGMENT.findall(source))
        assert list(fragments) == expected
        prompt_bodies.extend(fragments.values())

    information_prompt = "\n".join(prompt_bodies)
    for forbidden in (
        "SingleLineTitle",
        "Sub-118",
        "Sub-140",
        "S-dual-info",
        "W-content-side-slots",
        "fontSize",
        "fillColor",
        "vp",
        "fp",
    ):
        assert forbidden not in information_prompt

    for required in ("汇总—明细", "主体—属性", "同级并列", "事件—要素", "内容—操作"):
        assert required in information_prompt

    manifest_path = DEFAULT_BUNDLE / "prompt_source/manifest.yaml"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    prompts = manifest.get("prompts")
    assert isinstance(prompts, dict)
    references = prompts.get("create")
    assert isinstance(references, list)
    start = references.index("information/common.md#contract")
    assert references[start:start + 3] == [
        "information/common.md#contract",
        "information/2x2.md#capacity",
        "information/2x4.md#capacity",
    ]


def test_combination_modules_separate_semantics_from_size_mapping() -> None:
    root = DEFAULT_BUNDLE / "prompt_source/combinations"
    expected_fragments = {
        "common.md": ["selection", "contract"],
        "2x2.md": ["mapping"],
        "2x4.md": ["mapping"],
    }
    bodies = {}
    for filename, expected in expected_fragments.items():
        source = (root / filename).read_text(encoding="utf-8")
        fragments = dict(FRAGMENT.findall(source))
        assert list(fragments) == expected
        body_name = "contract" if filename == "common.md" else "mapping"
        body = fragments.get(body_name)
        assert isinstance(body, str)
        bodies[filename] = body

    common = bodies.get("common.md")
    assert isinstance(common, str)
    for required in (
        "标题与数量",
        "核心与补充",
        "核心、补充与操作",
        "单内容与操作",
        "双/三/四占比",
        "双信息块",
        "双操作",
    ):
        assert required in common
    for forbidden in (
        "S-dual-info",
        "W-content-side-slots",
        "Sub-118",
        "Sub-140",
        "fontSize",
        "backgroundColor",
        "vp",
        "fp",
    ):
        assert forbidden not in common

    combined = "\n".join(bodies.values())
    for forbidden in (
        "<Card",
        "<Region",
        '"composition":',
        '"Card"',
        '"Region"',
    ):
        assert forbidden not in combined

    two_by_two = bodies.get("2x2.md")
    two_by_four = bodies.get("2x4.md")
    assert isinstance(two_by_two, str)
    assert isinstance(two_by_four, str)
    for name in ("hero-support", "label-value", "peer-pair", "supporting-items"):
        assert name in two_by_two
    for name in ("hero-support", "label-value", "peer-pair", "title-count"):
        assert name in two_by_four
    for legacy in ("Sub-118", "Sub-140"):
        assert legacy not in combined
    for size in ("2x2", "2x4"):
        layouts = read_prompt(DEFAULT_SOURCE, "create", size=size)
        for layout_id in layout_ids_for_size(size):
            assert layout_id in layouts

    manifest_path = DEFAULT_BUNDLE / "prompt_source/manifest.yaml"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    prompts = manifest.get("prompts")
    assert isinstance(prompts, dict)
    references = prompts.get("create")
    assert isinstance(references, list)
    start = references.index("combinations/common.md#selection")
    assert references[start:start + 4] == [
        "combinations/common.md#selection",
        "combinations/common.md#contract",
        "combinations/2x2.md#mapping",
        "combinations/2x4.md#mapping",
    ]


@pytest.mark.parametrize("size", ["2x2", "2x4"])
def test_fewshot_source_is_one_document_per_size(size: str) -> None:
    source = DEFAULT_SOURCE / "fewshots" / f"{size}.md"
    assert not list((DEFAULT_SOURCE / "fewshots" / size).rglob("*.md"))
    source_content = source.read_text(encoding="utf-8")
    assert "fontColor" not in source_content
    fragments = dict(FRAGMENT.findall(source_content))
    expected = ["preamble"]
    if size == "2x2":
        expected.extend(
            f"example-v{index:02d}"
            for index in (1, 9, 15, 10, 19, 16, 12, 4, 11, 13, 5, 6, 2, 8, 14, 3, 17, 18, 7)
        )
    else:
        expected.extend(
            f"example-v{index:02d}"
            for index in (3, 16, 28, 39, 9, 8, 10, 23, 6, 19, 38)
        )
    if size == "2x4":
        expected.append("countdown-number")
    expected.append("countdown-pattern")
    assert list(fragments) == expected
    manifest = json.loads((DEFAULT_SOURCE / "manifest.yaml").read_text(encoding="utf-8"))
    modules = manifest.get("modules")
    assert isinstance(modules, list)
    size_sources = []
    for module in modules:
        filename = module.get("file")
        assert isinstance(filename, str)
        if filename.startswith(f"fewshots/{size}"):
            size_sources.append(filename)
    assert size_sources == [f"fewshots/{size}.md"]


@pytest.mark.parametrize("size", ["2x2", "2x4"])
@pytest.mark.parametrize("mutation", ["input", "output", "identifier"])
def test_merged_fewshot_checks_each_fragment(tmp_path: Path, size: str, mutation: str) -> None:
    source_root = tmp_path / "prompt_source"
    shutil.copytree(DEFAULT_SOURCE, source_root)
    source = source_root / "fewshots" / f"{size}.md"
    original = source.read_text(encoding="utf-8")
    fragments = dict(FRAGMENT.findall(original))
    example = "v01" if size == "2x2" else "v03"
    identifier = f"{size}-V{example[1:]}"
    body = fragments.get(f"example-{example}")
    assert isinstance(body, str)
    if mutation == "input":
        broken = body.replace("```json", "```text")
    elif mutation == "output":
        broken = body.replace("```genui", "```text")
    else:
        broken = body.replace(identifier, f"{size}-V99")
    assert broken != body
    source.write_text(original.replace(body, broken, 1), encoding="utf-8")
    with pytest.raises(ValueError, match=f"案例缺少完整输入/输出：{identifier}"):
        assemble_prompts(source_root)


@pytest.mark.parametrize(
    "method,name",
    [
        ("read_design_plan_prompt", "plan"),
        ("read_design_prompt", "create"),
        ("read_design_edit_prompt", "edit"),
        ("read_design_repair_prompt", "repair"),
        ("read_design_argument_repair_prompt", "argument_repair"),
    ],
)
def test_registry_reads_prompt_source(method: str, name: str, tmp_path: Path) -> None:
    old = tmp_path / DESIGN_COMPACT_PROFILE_ID
    old.mkdir()
    (old / "PROMPT.md").write_text("旧路径不得回退", encoding="utf-8")
    source = tmp_path / "design-compact-dsl-fusion/prompt_source"
    shutil.copytree(DEFAULT_SOURCE, source)
    read = getattr(A2UIProtocolRegistry, method)
    assert read(DESIGN_COMPACT_PROFILE_ID, tmp_path) == assemble_prompts(source).get(name)


@pytest.mark.parametrize("size", ["2x2", "2x4"])
def test_fewshot_uses_prompt_source(size: str) -> None:
    actual = A2UIProtocolRegistry.read_design_few_shot(DESIGN_COMPACT_PROFILE_ID, size)
    expected = assemble_prompts(DEFAULT_SOURCE).get(f"fewshot_{size}")
    assert actual == expected


def test_unknown_fewshot_size_is_rejected() -> None:
    with pytest.raises(ValueError, match="Unsupported"):
        A2UIProtocolRegistry.read_design_few_shot(DESIGN_COMPACT_PROFILE_ID, "../PROMPT")


def test_runtime_uses_registered_source_prompts() -> None:
    for constant, method in (
        ("SYSTEM_PROMPT", "read_design_prompt"),
        ("EDIT_SYSTEM_PROMPT", "read_design_edit_prompt"),
        ("REPAIR_SYSTEM_PROMPT", "read_design_repair_prompt"),
    ):
        assert getattr(prompt_builder, constant) == getattr(A2UIProtocolRegistry, method)(
            DESIGN_COMPACT_PROFILE_ID
        )


def test_source_edit_takes_effect_after_loader_restart(tmp_path: Path) -> None:
    source = tmp_path / "prompt_source"
    shutil.copytree(DEFAULT_SOURCE, source)
    original = read_prompt(source, "create")
    core = source / "core.md"
    content = core.read_text(encoding="utf-8")
    core.write_text(content.replace("你是 HarmonyOS", "你是测试 HarmonyOS", 1), encoding="utf-8")
    assert read_prompt(source, "create") == original
    _cached_prompts.cache_clear()
    assert read_prompt(source, "create") != original


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "escape", "size", "orphan"])
def test_invalid_manifest_is_rejected(tmp_path: Path, mutation: str) -> None:
    source = tmp_path / "prompt_source"
    shutil.copytree(DEFAULT_SOURCE, source)
    path = source / "manifest.yaml"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    prompts = manifest.get("prompts")
    modules = manifest.get("modules")
    assert isinstance(prompts, dict) and isinstance(modules, list)
    references = prompts.get("create")
    assert isinstance(references, list)
    if mutation == "missing":
        references[0] = "core.md#does-not-exist"
    elif mutation == "duplicate":
        references.append(references[0])
    elif mutation == "escape":
        modules[0]["file"] = "../../escape.md"
    elif mutation == "size":
        modules[0]["sizes"] = ["4x4"]
    else:
        orphaned_reference = references.pop(0)
        for prompt_name, prompt_references in prompts.items():
            if prompt_name == "create" or not isinstance(prompt_references, list):
                continue
            prompts[prompt_name] = [
                reference for reference in prompt_references if reference != orphaned_reference
            ]
    path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError):
        assemble_prompts(source)


def test_unclosed_fragment_is_rejected(tmp_path: Path) -> None:
    source = tmp_path / "prompt_source"
    shutil.copytree(DEFAULT_SOURCE, source)
    core = source / "core.md"
    original = core.read_text(encoding="utf-8")
    core.write_text(original.replace("<!-- /prompt:identity -->", "", 1), encoding="utf-8")
    with pytest.raises(ValueError, match="不闭合"):
        assemble_prompts(source)


def test_unregistered_source_is_rejected(tmp_path: Path) -> None:
    source = tmp_path / "prompt_source"
    shutil.copytree(DEFAULT_SOURCE, source)
    unregistered = source / "unregistered.md"
    unregistered.write_text(
        "<!-- prompt:new -->\n规则\n<!-- /prompt:new -->\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="未登记"):
        assemble_prompts(source)
