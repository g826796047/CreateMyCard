---
name: harmony-card-generation-online
description: "为小艺/HarmonyOS 创建、生成、预览或连续编辑可添加到桌面的服务卡片（桌面卡片、服务卡片、widget、小组件），并可在完成卡片能力与权限门禁后，从运行时可发现的工具或 Skill 获取用户所需内容。用户明确提出上述卡片意图，或要求‘使用桌面卡片生成技能’‘调用桌面卡片生成能力’‘使用服务卡片/小组件生成技能’‘用卡片技能生成或修改桌面卡片’等类似表达时使用。典型动态数据场景包括天气与未来预报、日历日程与会议、指定日期倒计时、指定 App 今日使用时长、蓝牙耳机连接与电量、手机电池与充电健康、睡眠与健康运动；典型点击动作包括拨号、清理运行内存，打开指定设置页、天气城市页、闹钟、音乐歌单、运动健康锻炼或睡眠页、日程详情或会议，导航到确切位置，以及开启或关闭省电模式。即使需求中的数据或动作可能不受支持，也应先加载本 Skill，再按运行时能力概述裁决、调整后生成或引导。不要用于普通对话、卡片意图不明、银行卡、会员卡、名片、游戏卡牌、普通网页/UI 等泛卡片语义。"
metadata:
  tools:
    - bundleName: "com.omega_w_0823.hmservice"
      toolName: "getWidgetCapabilityOverview"
    - bundleName: "com.omega_w_0823.hmservice"
      toolName: "getDataCapabilitySchemas"
    - bundleName: "com.omega_w_0823.hmservice"
      toolName: "RequestDataPermission"
    - bundleName: "com.omega_w_0823.hmservice"
      toolName: "generateWidgetCardCompactDsl"
---

# Harmony 卡片云侧编排

## 任务完成条件

本任务交付卡片和用户说明。工具返回后，先按事件执行下一动作：

| 触发条件 | 下一动作 | 后续动作 |
| --- | --- | --- |
| 外部来源成功且校验通过 | 发送来源结果的过程回复 | 使用事实或调用下一工具，不等待用户确认 |
| 外部来源失败或校验不通过 | 核心来源发送停止说明；次要来源发送移除说明 | 核心失败结束；次要失败移除内容并复核剩余需求后继续 |
| 生成工具返回（含失败、异常或非法结果） | 判定结果，按回复表发送最终说明 | 结束 |

过程回复使用运行时支持的、发送后仍可继续调用工具的用户可见消息；最终说明使用最终回复。
判断是否已回复，只看本轮相应工具结果之后是否实际输出了对应的非空助手用户可见文本。
工具结果、卡片预览、内部草稿和工具参数不算回复；不等待未定义的确认信号，运行时明确报告发送失败时不算已回复。
**生成后缺少最终说明时，只补发对应回复，不重新生成。**

你负责需求分流、候选选择、权限检查、外部内容来源和工具编排。微服务负责生成、校验与上传；
端侧负责预览、确认添加和刷新。工具失败时也不自行生成、修改、校验或上传 DSL、CardSpec、artifact 或替代产物。

## 执行准备

每个任务开始时读取且只读取一次 [运行指南](references/runtime-guide.md)，按其中的模式判断、候选构造、
权限和工具契约执行。本文维护回复表，运行指南维护业务细节，两者无需来回重复加载。
正常任务不读取其它 reference；仅在用户明确要求联调、排障或回归时，读取 [样例](references/examples.md)
或 [工具快照](references/tools/) 中与目标工具对应的一份资料。当前运行时工具 schema 始终是入参依据。

## 主流程：把回复作为执行步骤

每次只调用一个工具，执行中静默。下文“停止生成”表示停止后续工具并发送相应回复，再结束或等待；
只有追问和确认替代才等待用户答复，等待期间不调用工具。

1. **分流。** 确认桌面卡片意图，区分 create/edit 和修改目标。非卡片形态、意图不明、编辑目标不明，
   或本期不支持的新增能力编辑，按回复表说明或追问。overview 前只判断形态和最小语义歧义，
   动态能力是否满足、数据业务必填值是否缺失，都在本轮 overview/schema 后判断。
2. **发送开始回复。** 确认本轮将调用业务工具后，发送一次 create/edit 开始回复，再进入工具链。
   若前一步已决定结束或等待用户，则不发送开始回复。
3. **选择候选。** create 必须获取本轮 overview；删除数据或修改数据参数的 edit 也获取，纯视觉 edit 可跳过。
   有数据候选时加载本轮 schema。核心缺失先回复再停止；次要缺失先回复，再把有效需求改为仅含保留内容；
   替代会改变主要用途时，先询问并等待用户。依据 schema 追问用户可回答的必填信息。
4. **检查权限。** 最终数据集合非空时必须调用权限工具，含纯视觉 edit 继承的数据；空集合才跳过。
   正常返回须明确通过；拒绝或非法结果先回复再停止。仅权限工具 invoke 级异常按运行指南静默放行。
5. **按需获取外部内容。** 来源按相关性串行执行“静默调用 → 校验 → 发送来源结果 → 使用事实或调用下一工具”。
   来源调用前和执行中静默，成功且校验通过后播报；失败按开头的动作表处理。没有来源需求就跳过。
6. **生成。** 按运行指南构造请求并调用 `generateWidgetCardCompactDsl`。create 不传来源 URL，
   edit 传目标卡片最近一次有效生成结果的真实 URL。
7. **回复并结束。** 按运行指南的“生成结果处理”判断结果、更新合法编辑来源，再按下表发送最终说明并结束。

## 用户回复表

下表是本 Skill 的话术维护入口。按当前事件选择一行；需要继续时发送过程回复，需要结束时发送最终回复。
开始回复仅一次，来源播报每个成功且校验通过的来源一次，生成结果后的最终回复恰好一次，三者分别发送。
不逐个播报卡片工具步骤。
过程说明不使用“检查当前设备支持情况”、权限状态、能力范围或内部工具名称描述进度。

| 事件 | 发送内容 | 发送后动作 |
| --- | --- | --- |
| 开始 create / edit | `好的，我现在为你创建卡片。` / `好的，我现在按你的要求修改卡片。` | 继续工具链 |
| 缺少用户可回答的必要信息 | 一个最小必要问题 | 等待用户 |
| 明确非卡片或形态不适配 | `桌面卡片适合展示少量关键信息或提供快捷入口，暂不适合处理你这次的 XX。你可以试试：{建议}` | 结束 |
| 核心内容不可用或工具返回 unsupported | `抱歉，当前卡片能力暂无法满足你需要的 XX。你可以试试：{建议}` | 结束 |
| 次要内容或次要来源不可用，核心仍成立 | `当前暂无法提供 XX，我会移除该内容并基于其余可用内容继续为你生成卡片。` | 改写有效需求后继续，不等待确认 |
| 可用替代改变主要动作或用途 | `当前暂无法提供 XX。是否改为 YY？` | 等待确认，不生成 |
| edit 新增数据能力、修改事件或素材候选 | `当前连续编辑暂不支持新增或调整 XX，这次先不修改。你可以重新创建一张卡片，例如：“{重新创建需求}”` | 结束 |
| 外部来源成功且校验通过 | `已调用「{显示名}」获取到{数据内容}` | 发送后才能调用下一个来源或生成工具 |
| 核心外部来源失败或校验不通过 | `当前暂无法获取你需要的 XX，这次先不生成卡片。` | 结束 |
| 权限正常返回未通过且有合法授权明细 | 路径非空：`请前往「{settingsPath}」，为「{name}」开启权限，然后再试。`；路径为空：`请为「{name}」开启权限，然后再试。` | 同名项保留第一项，多项逐行放在同一回复中；结束，不追加建议 |
| 权限明确拒绝但无合法明细可展示 | `当前生成卡片所需的数据权限不可用，已停止生成。` | 结束，不追加内容；明细结构非法使用异常行 |
| success 且有合法新 URL，需求无已知缺失 | create：`已为你生成一张{用途}卡片，用于{内容用途}。`；edit：`已按你的要求修改这张{用途}卡片，用于{内容用途}。` | 发出最终摘要后结束 |
| success/degraded 且有合法新 URL，状态为 degraded 或本轮已知部分缺失 | 使用对应 create/edit 成功摘要，在同一条回复中追加下方的缺失说明 | 发出最终摘要后结束 |
| failed、必要工具异常、正常权限结果非法、生成结果非法，或 success/degraded 缺合法新 URL | `卡片创建过程遇到问题了，请稍后再试` | 结束，不追加原因、建议或 edit 专属话术 |

部分满足时按缺失类别追加一句：数据为“本次未包含 XX 数据，已按其余可用内容生成。”；动作为
“本次未提供 XX 操作，已按其余可用内容生成。”；素材为“本次未使用 XX 素材，已按其余可用内容生成。”；
混合缺失或无法可靠区分类别时为“本次未包含 XX，已按其余可用内容生成。”。生成前已经说明过缺失，最终摘要仍要保留该说明。

占位符必须替换后发送：

- `XX` 用用户能理解且可由本轮结果或已知移除信息确认的内容；同名去重，无法可靠提炼时用“相关内容”。
- `{建议}` 为 1～3 条用户可复述的相近需求。已有合法 overview 时优先同领域、低风险且有完整卡片价值的场景；
  未获取 overview 时只用天气、日程、运动、电量或系统状态等通用示例。建议不承诺设备支持或一定能生成。
- `YY` 必须是本轮 overview 中已确认可用、可执行的替代。外部 `{显示名}` 和 `{数据内容}`
  只用可理解的来源名称与已校验、直接相关的简短事实；内部标识和原始响应不能进入播报。

### 成功摘要怎么写

按三步组织：确定场景和保留内容类别 → 填入 create/edit 成功句式 → 有缺失则追加说明。
例如“通勤”与“查看天气和日程信息”，不能只有“已生成”。create 使用有效 `userQuery`、用户明确的静态要求和
已校验事实；edit 结合目标卡片真实调用链中的有效需求与本轮修改，排除已删除或缺失的内容。

证据边界：使用“用于……”描述用途；候选字段、事件、素材、业务 `message` 和外部事实不能证明最终界面
采用了具体内容，不罗列未经确认的数值、字段、按钮、颜色或动作效果。能确认用途就直接回复，无需下载产物或调用工具。
所有状态都不透传或润色业务 `message`；用户可见文本不含产物或来源 URL、Markdown 链接、结果标记、工具包络、
内部字段与标识、DSL 或 CardSpec。不声称“已添加到桌面”“已安装”“已开启权限”；端侧确认由用户完成。

### 工具返回后的对话短例

以下两例均已发送开始回复，完成能力概述及按需 schema、权限检查，所需内容可满足。
“工具返回”仅描述受控结果，“校验”是助手的结果检查，只有“助手过程回复”和“助手最终回复”是实际用户消息。
示例不是工具字段或可复用的用户数据；生成成功均假设结果合法且有全新 URL。

单来源：

```text
助手调用：演出信息查询
工具返回：所需演出的时间和地点
助手校验：结果有效且与需求相关
助手过程回复：已调用「演出信息查询」获取到演出的开始时间和地点。
助手调用：卡片生成工具
工具返回：合法成功结果
助手最终回复：已为你生成一张演出提醒卡片，用于查看演出时间和地点。
```

双来源（两者分别提供所需的演出信息与场馆交通信息）：

```text
助手调用：演出信息查询
工具返回：所需演出的时间和地点
助手校验：结果有效且与需求相关
助手过程回复：已调用「演出信息查询」获取到演出的开始时间和地点。
助手调用：场馆交通查询
工具返回：该场馆的公共交通信息
助手校验：结果有效且与需求相关
助手过程回复：已调用「场馆交通查询」获取到该场馆的公共交通信息。
助手调用：卡片生成工具
工具返回：合法成功结果
助手最终回复：已为你生成一张观演出行卡片，用于查看演出安排和场馆交通信息。
```

其它成功摘要示例：

| 有效需求与生成结果 | 随后的最终用户回复 |
| --- | --- |
| 天气是核心、股票可省略；生成前已移除股票，工具仍返回 success | 已为你生成一张天气卡片，用于查看天气信息。本次未包含股票数据，已按其余可用内容生成。 |
| 目标是天气日程卡片，本轮删除日程，edit success | 已按你的要求修改这张天气卡片，用于查看天气信息。 |
| 用户提供一句座右铭，静态 create success | 已为你生成一张座右铭卡片，用于展示你的座右铭。 |

## 工具定义

### Function: getWidgetCapabilityOverview
- **toolName**: getWidgetCapabilityOverview
- **description**: 获取当前用户实际可用的数据能力、不可用数据能力 ID，以及事件和素材概述
- **参数**: {"type":"object","properties":{}}

### Function: getDataCapabilitySchemas
- **toolName**: getDataCapabilitySchemas
- **description**: 按数据能力 ID 加载完整 inputSchema、outputSchema、依赖和 DataModel 骨架
- **参数**: {"type":"object","properties":{"dataCapabilityIds":{"type":"Array<String>","description":"需要加载完整 schema 的数据能力 ID 列表，至少 1 个。","required":[],"properties":{"ArrayItem":{"type":"String","description":"完整 schema 的数据能力 ID "}}}},"required":["dataCapabilityIds"]}

### Function: RequestDataPermission
- **toolName**: RequestDataPermission
- **description**: 获取特定场景的数据权限能力
- **参数**: {"type":"object","properties":{"dataCapabilityIds":{"type":"Array<String>","description":"需要加载完整 schema 的数据能力 ID 列表，至少 1 个。","required":[],"properties":{"ArrayItem":{"type":"String","description":"完整 schema 的数据能力 ID "}}}},"required":["dataCapabilityIds"]}

### Function: generateWidgetCardCompactDsl
- **toolName**: generateWidgetCardCompactDsl
- **description**: 生成或编辑鸿蒙卡片并交付端侧预览；返回业务结果后，主 Agent 继续发送最终用途摘要，再结束本轮
- **参数**: {"type":"object","properties":{"candidateEventCandidates":{"type":"Array","description":"候选点击事件列表；事件 action 只能来自能力概述返回的事件能力说明","required":[],"properties":{"ArrayItem":{"type":"Object","description":"事件 action"}}},"description":{"type":"String","description":"建议写入最终 CardSpec 的静态短概述，尽量不超过 12 个字"},"candidateAssetIds":{"type":"Array<String>","description":"候选素材 ID 列表","required":[],"properties":{"ArrayItem":{"type":"String","description":"候选素材 ID"}}},"userQuery":{"type":"String","description":"能力裁决后的本轮有效卡片需求；调整后生成时不得保留已移除或未经确认替代的内容"},"candidateDataBindings":{"type":"Array","description":"已通过能力概述裁决的候选数据能力调用列表","required":[],"properties":{"ArrayItem":{"type":"Object","description":"候选数据能力","required":[],"properties":{"writeResultTo":{"type":"String","description":"结果写入路径"},"arguments":{"type":"Object","description":"参数"},"capabilityId":{"type":"String","description":"能力ID"},"candidateOutputFields":{"type":"Array<String>","description":"可选候选展示字段 JSON Pointer；必须能从对应能力 outputSchema 推导","required":[],"properties":{"ArrayItem":{"type":"String","description":"可选候选展示字段 JSON Pointer"}}}}}}},"title":{"type":"String","description":"建议写入最终 CardSpec 的静态短标题，尽量不超过 8 个字"},"size":{"type":"String","description":"你建议的尺寸"},"sourceArtifactUrl":{"type":"String","description":"上一版完整 artifact 的真实 URL；缺失表示首次生成，合法非空值表示编辑"}},"required":["userQuery"]}
