---
name: harmony-card-generation-online
description: "用户提出创建、修改卡片或指定使用“桌面卡片生成技能”时，使用本 Skill。用户无需说明卡片类型、平台或生成方式；信息不清楚时由本 Skill 澄清，具体能否支持由后续流程判断。"
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

## 领域知识

- 微服务负责桌面服务卡的生成、校验、修复和上传；你负责需求、候选、权限、事实、调用与回复。
- 动态绑定只选本轮可用能力；静态事实不受动态主题限制，可独立或组合展示，不能冒充实时刷新。
- create 新建；edit 依赖本会话真实有效产物，受既有边界限制，失败不自动 create。
- 事实说明不代表卡片已生成，候选不代表最终界面已采用；仍须反馈卡片结果。

执行前读取一次 [固定回复规范](references/user-replies.md)；按下文步骤读取 [运行指南](references/runtime-guide.md)，不重复加载。
[回归示例](references/examples.md) 和 [工具快照](references/tools/) 仅供联调、排障和回归，正常执行不读取；不读取或调用 scripts。
运行时工具 Schema 是调用的唯一依据；示例不能替代真实定义或结果。

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
- **description**: 生成极简协议版本的鸿蒙卡片
- **参数**: {"type":"object","properties":{"candidateEventCandidates":{"type":"Array","description":"候选点击事件列表；事件 action 只能来自能力概述返回的事件能力说明","required":[],"properties":{"ArrayItem":{"type":"Object","description":"事件 action"}}},"description":{"type":"String","description":"建议写入最终 CardSpec 的静态短概述，尽量不超过 12 个字"},"candidateAssetIds":{"type":"Array<String>","description":"候选素材 ID 列表","required":[],"properties":{"ArrayItem":{"type":"String","description":"候选素材 ID"}}},"userQuery":{"type":"String","description":"能力裁决后的本轮有效卡片需求及按来源顺序追加的完整清洗外部事实；调整后生成时不得保留已移除或未经确认替代的内容"},"candidateDataBindings":{"type":"Array","description":"已通过能力概述裁决的候选数据能力调用列表","required":[],"properties":{"ArrayItem":{"type":"Object","description":"候选数据能力","required":[],"properties":{"writeResultTo":{"type":"String","description":"结果写入路径"},"arguments":{"type":"Object","description":"参数"},"capabilityId":{"type":"String","description":"能力ID"},"candidateOutputFields":{"type":"Array<String>","description":"可选候选展示字段 JSON Pointer；必须能从对应能力 outputSchema 推导","required":[],"properties":{"ArrayItem":{"type":"String","description":"可选候选展示字段 JSON Pointer"}}}}}}},"title":{"type":"String","description":"建议写入最终 CardSpec 的静态短标题，尽量不超过 8 个字"},"size":{"type":"String","description":"你建议的尺寸"},"sourceArtifactUrl":{"type":"String","description":"上一版完整 artifact 的真实 URL；缺失表示首次生成，合法非空值表示编辑"}},"required":["userQuery"]}

### 工具调用

依赖 frontmatter 声明的三个微服务工具和一个端工具。使用统一调用格式；
**注意**：要求 `arguments` 是合法 JSON 值；`skillName` 固定为 `harmony-card-generation-online`。

```text
invoke(functionName:"<toolName>", arguments:{bundleName:"com.omega_w_0823.hmservice", ...},"skillName":"harmony-card-generation-online")
```

## 经验攻略

- “必须”“只要”及主要动态数据/动作属核心；次要缺失可移除后继续，不能只凭另有能力可用而降级。
- 客观事实先用当前任务已有真实结果，不足按步骤 5 补查；偏好或歧义只问一个必要问题，不让用户补技术字段。

## 操作规程（SOP）

- **入口预检：** 仅当用户表达创建或修改卡片意图时进入；纯讨论、独立搜索等不属于卡片任务。明显不支持的请求按步骤 1 的固定话术终止，不先查询或播报外部事实。

### 0. 查询外部事实并回复用户

- **进入条件：** 入口预检已确认卡片创建或修改意图，且不是明显不支持的请求；用户需求依赖客观事实、明确引用最近一条助手答案或任务已有相关外部结果时进入，否则直接进入步骤 1。
- **来源与检查：** 按 query 查询或处理真实 WebSearch、其它工具/Skill 结果（含加载前）；前文仅取用户明确引用的本会话最近一条实际助手自然语言答案。
  按指南“参数补全与外部事实”校验相关性、结构、类型、业务含义和时效，清洗后保留独立完整清单供步骤 6；本步不回填参数。
- **用户回复：** 采用后实际发送尚未告知的完整事实：WebSearch 用 R16W，其它用 R16，不总结或描述获取过程；草稿、工具返回和参数不算回复。
- **调用示例：** 按真实运行时外部工具定义调用；示意为 `query ← 用户 query 中待查询的客观事实`，不虚构工具名或接口。
- **继续或停止：** 事实回复后进入步骤 1；核心事实无法校验用 R17 停止，次要事实按 R08C/R08E；前文答案为空、仅失败话术或无法安全提取时用 R05/R14。

### 1. 判断触发范围与 create/edit

- **进入条件：** 创建/修改卡片即触发，包括未指定类型、平台、形态及连续修改；不在触发阶段按卡片类型排除，普通讨论或独立搜索不触发。
- **用户回复：** 意图不明 R03、编辑对象不明 R04、修改内容不明 R05、不适合卡片承载 R06。明确不支持时只发送 R06/R07/R10 并结束，不发事实、R01/R02 或调用工具。
- **工具与模式：** 零调用，只检查形态、静态范围和最小歧义，不提前猜动态能力或追问参数。创建、再做一张、重新创建为 create；已有卡片改颜色、背景、布局、文案、尺寸、删除或替换内容为 edit，即使省略“卡片”。
- **继续或停止：** create 进入步骤 2；edit 先读运行指南“编辑继承”。纯视觉、删除数据、修改已有参数按支持范围继续；新增/跨数据能力替换、修改事件或素材候选用 R10，真实来源无法恢复用 R14；不自动 create。

### 2. 获取能力概述和数据定义

- **进入条件：** 每个 create 或删除数据/修改参数的 edit；读指南“工具契约与字段来源”，不新增话术。
- **概述调用示例：**

```text
invoke(functionName:"getWidgetCapabilityOverview", arguments:{
  bundleName:"com.omega_w_0823.hmservice"
},"skillName":"harmony-card-generation-online")
```

- **概述检查：** 动态绑定取本轮合法 dataCapabilities，事件、素材取同轮概述；非法返回 R14，不用历史、缓存或示例补齐。立即建需求数据清单，逐项判断动态满足度。
  明确要求实时/动态绑定而核心能力缺失时 R07 停止；次要缺失记录待移除项；改变主要用途的替代 R09 等待。只要求静态内容且事实尚未取得时留待步骤 5，不因生成模型可能补齐而视为满足。
- **数据定义示例：** 仅加载本轮概述选中的可用 ID；无数据跳过、不传空数组。

```text
invoke(functionName:"getDataCapabilitySchemas", arguments:{
  bundleName:"com.omega_w_0823.hmservice",
  dataCapabilityIds:["ViewWeather"]
},"skillName":"harmony-card-generation-online")
```

- **模拟返回：** ViewWeather 的 prefectureName 为必填字符串、districtName 可选字符串、forecastDays 为整数，默认路径 /data/weather，输出含 /current/temperatureText。
  用户指定上海青浦今日天气，故值为上海市、青浦区、1；无匹配事件/素材，候选为空。仅模拟来源关系，不替代真实完整返回。
- **Schema 检查：** 返回后再次逐项核对必填参数、类型、输出字段和写入路径，移除 missingCapabilityIds 后复核核心目标。用户明确值和已校验事实只能提供业务值，不能新增能力或字段。
- **继续或停止：** 明确要求动态/实时时，最后一个核心动态能力消失用 R07；次要缺失步骤 3 告知移除；技术必填缺失或 Schema 非法 R14。静态事实尚缺留待步骤 5：无来源 R07，核心来源失败或不可校验 R17；其余步骤 3。

### 3. 规划候选与必要追问

- **进入条件：** 已得本轮概述和所需 Schema；读取运行指南“满足度、尺寸与候选构造”。
- **用户回复：** 偏好、歧义目标或必要动作对象缺失用 R05 并等待；次要缺失 R08C/R08E 后继续；主要用途替代 R09 等待；必须包含的核心内容不可用 R07 停止。
- **调用示例：** 零调用、不猜参数。可由已有或可发现来源补事实且不影响能力集合时留待步骤 5。
- **参数检查：** 数据 ID、参数名/类型/路径只取本轮定义；事件候选使用对应能力 ID 和完整复制的 actionTemplate，仅替换 dynamicArguments 声明位置，保留 intentName、空字符串等全部固定字段；素材只传本轮概述中语义匹配的 ID，不伪造路径，布局与染色细则按指南。
  outputSchema 的 array 投影必须带明确非负整数下标，同一数组多个可点击展示项的事件引用各自下标；具体路径及相对 writeResultTo 的关系按指南。
- **默认详情：** create、2x2、单业务天气或单条日程且目标唯一、未禁止点击、无其它必要动作时，优先提供同对象只读详情候选；未提按钮不等于不要点击。2x4 或目标歧义不自动补，明确按钮要求仍保留；不改需求、不加调用，微服务裁决承载。
- **需求来源清单：** 数据、指标、状态、时间、地点和限制逐项对应动态能力/Schema 字段与参数，或完整事实/用户明确值；意图、标题、说明、模型常识或候选描述不是来源。核心无来源停止、次要移除、用途替代确认。
- **尺寸与继续：** 用户本轮明确指定且受支持的尺寸时，create/edit 的生成调用必须将该尺寸原样写入 `size`；不得被默认值、服务端建议或模型推荐覆盖。未指定时才从 2x2 开始，含数据且至少两个点击能力时建议 2x4；按指南预算，不为填满版面加能力。最终完整去重集合确定后进入步骤 4，技术缺口 R14。

### 4. 检查数据权限

- **进入条件：** 最终数据集合确定；读取运行指南“权限结果判定”。create 从最终 candidateDataBindings[].capabilityId 构造；数据 edit 取替换后完整列表；纯视觉 edit 取真实有效链的 effectiveCapabilities.data 或恢复完整集合。ID 有序去重，非空必须显式传，空集合跳过、不传空数组。
- **调用示例：** 延续模拟计划；多能力须传完整集合。

```text
invoke(functionName:"RequestDataPermission", arguments:{
  bundleName:"com.omega_w_0823.hmservice",
  dataCapabilityIds:["ViewWeather"]
},"skillName":"harmony-card-generation-online")
```

- **正常判定：** stateOfPermission:true、无 authorized:false、nonAuthStatus 缺失或 [] 且结构/类型合法才通过。如 {"result":{"stateOfPermission":true,"nonAuthStatus":[]}}。
  明确拒绝或非空待授权明细用 R11/R12，无有效明细 R13；其它正常非法结果 R14；均停止。
- **一次重试：** 正常返回 result.errorMessage 精确等于“不能传入空的dataCapabilityIds，请重新调用工具”时，不发中间回复，重新核对并显式传同一份合法非空 ID 集合，最多一次；不从错误文本猜 ID，无法恢复集合按权限/编辑来源失败停止。

```text
返回:{"result":{"errorMessage":"不能传入空的dataCapabilityIds，请重新调用工具"}}
重试 invoke(functionName:"RequestDataPermission", arguments:{
  bundleName:"com.omega_w_0823.hmservice",
  dataCapabilityIds:["ViewWeather"]
},"skillName":"harmony-card-generation-online")
```

- **继续或停止：** 重试合法结果按正常判定；调用失败、仍为该错误或其它非法结果用 R14 实际回复并终止，不进步骤 5、不生成。正常错误不属 invoke 异常。
  仅首次 invoke 级失败静默默认放行，不重试、不伪造权限结果；正常通过、首次默认放行或空集合跳过后进入步骤 5。

### 5. 检查已有外部来源结果，按需补查

- **进入条件：** 权限阶段允许继续；步骤 0 已采用的事实仍须进入步骤 6。没有采用事实且无需补查时才可进入步骤 7。
- **来源与调用：** 先用当前任务真实外部结果（含加载前），不重查步骤 0 已处理内容；仅对不足事实按运行时 Schema 和有效需求串行补查，不新增固定依赖或虚构接口。新补查须在权限阶段之后。
- **用户回复：** 不发调用前进度。采用后立即实际发送尚未告知的完整事实 R16/R16W，再到步骤 6；已告知事实不重复，助手回复也是告知证据。
- **调用示例：** 映射示意，外部工具使用自己的真实协议。

```text
已有外部来源：步骤 0 已校验并说明 → 卡片 SOP
事实不足：按真实运行时 schema 构造补查参数 → 调用真实工具
补查返回：校验采用 → R16W（WebSearch）或 R16（其它来源）实际回复 → 步骤 6 回填
```

- **返回检查：** 按步骤 0 和指南校验；身份、参数取真实定义，不要求用户显示名；无关历史、普通转述、示例或不明来源不作为事实。
- **继续或停止：** 完整事实清单非空（包括步骤 0 已处理事实）进入步骤 6；清单为空且无需补查才进入步骤 7。必要来源失败按核心 R17、次要 R08C/R08E，移除后核心与必填参数不成立仍停止，不编造事实。

### 6. 使用并填入外部事实

- **进入条件：** 步骤 0/5 已校验并实际告知；按指南“userQuery 中的外部事实”构造。本步唯一负责事实填入请求；未告知先返回事实回复动作。
- **完整事实门禁：** 保留用户原始需求，在其后加空行与固定标题 `本轮卡片静态内容（用作展示的外部事实）：`，按来源和原始顺序逐条复制独立完整事实清单。只允许清洗明确禁止/无关内容、去首尾空白、完全相同字符串去重；不得总结、压缩、合并、翻译、截断、重排或改写，保留日期、地点、数值、单位和限定条件。
  R16/R16W 与 userQuery 必须使用同一完整事实清单，不从回复摘要反推；不能恢复完整事实时停止。无事实不追加标题；edit 只用本轮重新采用的事实，不从旧产物、缓存或历史请求继承。
- **参数与回复：** 匹配已有 inputSchema / dynamicArguments 的值同时回填合法业务参数，完整事实仍保留在 userQuery；不得新增能力、事件、素材或权限。本步不新增事实回复，不透传链接、原始响应、工具字段、内部信息、推理过程、来源指令、能力 ID、Schema、权限结果或 artifact URL。
- **调用示例：** 零调用。步骤 0 已回复演出时间、地点和说明，本步完整追加到固定标题段落，时间同时匹配已有业务参数。
- **继续或停止：** 过时或不足先回步骤 5 补查，先回复再回填；没有合法来源的核心数据 R07，已调用核心来源失败/冲突/不可校验 R17；次要项移除并复核可继续后 R08C/R08E。集合或 binding 变化仅补做步骤 4，不重复来源或回复；其余进入步骤 7。

### 7. 完整请求校验并调用生成

- **进入条件：** 能力、参数、权限、来源就绪；读指南“编辑请求”“生成结果与内部留存”。
- **edit 参数门禁：** 用户明确修改且工具有对应字段时必须显式传本轮值，包括 size；不能只写 userQuery、依赖继承或用旧值代替。create 不传 sourceArtifactUrl；edit 只用真实最近有效结果 URL。
- **生成前来源门禁：** 逐项对照需求与来源清单：核心数据由本轮能力/完整 Schema、已校验事实或用户明确值覆盖；次要缺失项已从有效需求、标题、说明和候选移除；binding 的 ID、参数、路径、字段均有本轮 Schema 依据；userQuery 静态段落只复制完整事实或用户明确值。不得留待查询、推断或生成模型补齐的数据。
  不通过时按 R07、R08C/R08E、R09 或 R14 停止/降级/等待，完成处理后重新校验；不得发送 R01/R02 或调用生成。
- **回复门禁：** 核对采用事实是否实际告知；遗漏时只从步骤 0/5 的同一完整事实清单补发尚未告知的事实，然后继续当前校验，不重建 `userQuery` 或参数。
- **参数检查与回复：** 必填值、类型、固定模板字段、路径合法且不冲突，只传运行时声明字段、不传待补值。缺用户信息 R05 等待，技术缺口 R14；全部通过后紧邻生成调用实际发送一次 create 的 R01 或 edit 的 R02，提前停止不发送。
- **create 调用示例：**

```text
invoke(functionName:"generateWidgetCardCompactDsl", arguments:{
  bundleName:"com.omega_w_0823.hmservice",
  userQuery:"做一张 2x4 尺寸的上海青浦今日天气卡片。\n\n本轮卡片静态内容（用作展示的外部事实）：\n今日上海市青浦区适合穿着短袖",
  title:"今日天气",
  description:"青浦天气速览",
  size:"2x4",
  candidateDataBindings:[
    {"capabilityId":"ViewWeather","arguments":{"prefectureName":"上海市","districtName":"青浦区","forecastDays":1},
     "writeResultTo":"/data/weather","candidateOutputFields":["/current/temperatureText"]}
  ],
  candidateEventCandidates:[],
  candidateAssetIds:[]
},"skillName":"harmony-card-generation-online")
```

- **纯视觉 edit 示例：** 占位符须换为最近有效业务结果原始 URL；不能提交占位符或回复 URL。

```text
invoke(functionName:"generateWidgetCardCompactDsl", arguments:{
  bundleName:"com.omega_w_0823.hmservice",
  userQuery:"把背景改成蓝色。",
  sourceArtifactUrl:"<本会话目标卡片最近有效工具结果的原始 artifactUrl>"
},"skillName":"harmony-card-generation-online")
```

- **尺寸 edit 示例：** 显式传本轮 size，不能只写 userQuery。

```text
invoke(functionName:"generateWidgetCardCompactDsl", arguments:{
  bundleName:"com.omega_w_0823.hmservice",
  userQuery:"把已有卡片改成 2x4 尺寸。",
  size:"2x4",
  sourceArtifactUrl:"<本会话目标卡片最近有效工具结果的原始 artifactUrl>"
},"skillName":"harmony-card-generation-online")
```

- **数据参数替换 edit 示例：** 刷新概述/Schema、校验完整列表并授权后改为北京天气，删除旧青浦区参数。

```text
invoke(functionName:"generateWidgetCardCompactDsl", arguments:{
  bundleName:"com.omega_w_0823.hmservice",
  userQuery:"将已有天气改为北京市今日天气。",
  sourceArtifactUrl:"<本会话目标卡片最近有效工具结果的原始 artifactUrl>",
  candidateDataBindings:[
    {"capabilityId":"ViewWeather","arguments":{"prefectureName":"北京市","forecastDays":1},
     "writeResultTo":"/data/weather","candidateOutputFields":["/current/temperatureText"]}
  ]
},"skillName":"harmony-card-generation-online")
```

- **删除全部数据 edit 示例：** 源卡仅天气，刷新概述后显式传空数据列表，不调空 Schema/权限。

```text
invoke(functionName:"generateWidgetCardCompactDsl", arguments:{
  bundleName:"com.omega_w_0823.hmservice",
  userQuery:"移除动态天气，改为只显示文字：今天也要有好心情。",
  sourceArtifactUrl:"<本会话目标卡片最近有效工具结果的原始 artifactUrl>",
  candidateDataBindings:[]
},"skillName":"harmony-card-generation-online")
```

- **继续或停止：** `success`、`degraded`、`unsupported` 为终态，进入步骤 8；无合法新 URL、工具不可用、调用失败/超时/传输失败、状态不确定或返回结构非法时按现有异常话术 R14 结束，不重试。仅当本次工具响应 `reply.streamInfo.streamContent` 中的当前业务错误 JSON 可无歧义解析，且解析出的消息顶层 `status` 为 `failed`、`error.details.retryable` 为 Boolean `true`、`requiredActions` 恰为 `["FIX_AND_RETRY"]`、`agentInstruction` 给出可直接执行的修正方式、`issues` 至少含一项 `agentAction: "FIX_AND_RETRY"`、`retryable: true` 且带非空 `repairInstruction` 时，才允许修正重试。插件外层响应没有业务 `status`；`streamContent` 可能带中文说明前缀，不能把外层字段、普通业务 payload 或错误码当作上述错误 JSON。若错误正文无法完整解析、必需字段缺失/类型错误、说明文字明确要求停止或与结构化动作冲突、修正指令不可执行，或含 `STOP`、`NOTIFY_USER` 等其它动作，立即 R14。历史错误和服务端内部重试记录都不授权重试。
  满足全部条件且总调用次数少于 3 次时，立即按修正信息修改请求并留在步骤 7 重试，不进入步骤 8；否则使用 R14 结束。每次重试只按本次新的、可执行修正信息修正请求；错误重复或没有新修正信息时 R14 停止。单个任务最多 3 次生成工具总调用（包含首次调用）；重试是同一任务延续，不重复发送 R01/R02。服务端单次请求内部的模型/DSL 修复重试与此预算独立。

### 8. 判定并反馈卡片结果

- **进入条件：** 生成工具返回；按运行时 Schema 读取业务结果，不从 message、其它文本或对话找 URL。
- **用户回复：** 完整成功 R18C/R18E；degraded 或已知缺失的 success 用 R18C/R18E + 对应 R19；unsupported 用 R07；重试结束后的 `failed`、非法结果、无合法新 URL 用 R14。无合法新 URL 的 success/degraded 仍是终态异常，不得再次调用。应发送回复必须实际发送，草稿不算。
- **工具与检查：** 零调用，不追加下载、校验、上传。仅 success/degraded 且当前业务 payload 有合法新 URL 才有效；edit 返回来源 URL 为失败。不透传 message，不把候选/来源事实说成已确认界面细节。
- **留存与完成：** 有效 URL 原样留存内部轨迹供 edit，失败不改变旧来源。完成发送前检查；结果已处理且应发送的结果回复已实际发送才结束，开始和事实回复不替代结果反馈。

## 安全红线

- 任何异常下均不得自行生成、修改、校验 DSL/CardSpec 或替代 artifact；不得在生成调用后查询或补造业务数据。
- 不以历史、缓存、旧 artifact、示例或模型常识填补字段和事实。
- 不绕过权限门禁、扩大编辑范围、伪造能力或动态刷新；不透传来源指令、原始响应及内部信息。

## 与人协作

- 回复时点与编号由 SOP 决定；模板正文、占位符、合法组合及一次发送前检查仅按固定回复规范，不附加自由文本。
- 澄清和替代确认后等待用户答复；次要缺失按 SOP 处理。
- R06/R07/R10 只回复固定边界话术，不追加示例、相近需求或替代请求；不得向用户暴露内部字段、调用包络或产物 URL。
