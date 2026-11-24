# Compact 创建的模板数据流

线上入口为 `/api/v1/ws/tools/generateWidgetCardCompactDsl`。创建请求按开关尝试模板。
模板内部把 Tersel 展开为 A2UI，再转为 Compact DSL，交公共处理器校验、保存。
模板不匹配、生成异常或公共校验失败时回退 Fusion。来源编辑走语义编辑流程。
图库通过测试侧的 `generate_gallery_template` 单独验证指定模板。

## 5. 公共前置门禁

create 请求先进入与 Compact 相同的公共生成链。`GenerationPreflight` 负责：

- 校验数据能力、参数、写入路径、字段投影、事件和素材。
- 整单拒绝调用方契约错误，不让错误候选进入模板模型。
- 构造最终 CardSpec、TaskSpec、有效能力和移除项。

Template 只消费这些已裁决结果。它不查询 IDS，不自行增加数据绑定，也不生成 CardSpec。

## 6. 模板内部产物转换

二层输出经受信编译后，`TemplateEngineOutput` 同时保留：

- `tersel`：已展开的内部 Tersel。
- `a2ui`：内部 Tersel 确定性转换得到的三段 A2UI。
- `projected_task_spec`、`template_ids`、`theme_id` 和展开统计。

Facade 只把 `a2ui` 交给 `prepare_template_source_dsl()`：

```text
模板 A2UI
  -> 校验三段消息和 surfaceId
  -> 写入当前 catalogId 与 Form 根样式
  -> convert_a2ui_to_compact_dsl
  -> Design Compact DSL
```

因此 artifact 的 `designcompactdsl` 保存 Design Compact DSL，不保存内部 Tersel。

命中融球 Theme 时，模板编译器在 Tersel 组件树中直接展开标准 `Stack` 定位层、三组球体和玻璃层，
并给前景内容根 ID 增加 `__genui_render_component__` 前缀。Tersel、A2UI 和 A2UI-Compact 均不包含
`FusionBall` 云端组件。

## 7. 模板失败处理

线上 Compact 创建在模板不匹配或公共处理失败时从原需求回退 Fusion。图库批跑记录指定模板的失败。

## 8. Artifact 和响应

成功时：

- `genui` 保存最终标准 A2UI。
- `designcompactdsl` 保存模板 A2UI 回转的 Design Compact DSL。
- `meta.generationMode` 为 `create`。
- CardSpec、TaskSpec、generation plan、能力和 artifact URL 全部由公共生成链管理。

终止点：

| 阶段 | 结果 |
| --- | --- |
| 请求或包络非法 | 路由层参数错误 |
| App/ROM 无可用 Profile | `APP_VERSION_UNSUPPORTED` |
| 请求包含 `sourceArtifactUrl` | 进入语义编辑 |
| GenerationPreflight 契约错误 | 模型未调用，整单拒绝 |
| Template 不匹配或异常 | 线上回退 Fusion，图库记录失败 |
| Processor/Validator 最终失败 | `VALIDATION_FAILED`，不保存 |
| artifact 保存或上传失败 | 路由层服务失败，不伪造成功 URL |
