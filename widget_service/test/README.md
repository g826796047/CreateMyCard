# 微服务测试目录

本目录按测试层级、执行方式和依赖类型组织，根目录只保留本说明与 pytest 公共配置。

| 目录 | 用途 | 默认进入 PR L0 |
| --- | --- | --- |
| `level0/unit/` | 单个函数、类或模块的确定性测试 | 是 |
| `level0/integration/` | 多个确定性组件之间的公开合同测试 | 是 |
| `level1/replay/` | 固定模型响应驱动的生产编排回放 | 否，当前手工执行 |
| `smoke/` | 启动主服务并调用真实模型的受控冒烟 | 否，仅手工触发 |
| `manual/` | 依赖已启动服务、设备或其它外部环境的联调与压测 | 否 |
| `fixtures/` | 测试输入、固定响应、样本构造器和规则回归数据 | 不单独执行 |
| `support/` | 测试客户端、响应解析等共享辅助逻辑 | 不单独执行 |

常用入口：

```text
python -m pytest test -m l0 -q -ra
python -m pytest test/level1 -m l1 -q -ra
python -m pytest test/smoke/compact_dsl_smoke.py -q
python -m test.manual.load.pressure_test_ws --help
```

`conftest.py` 统一添加并校验测试层级标记。新增测试文件必须进入 `level0`、`level1`、`smoke` 或
`manual`；共享数据和辅助代码不得伪装成 `test_*.py`。目录使用 `level0/level1` 提高可读性，
pytest 标记继续使用测试方案中的 `l0/l1`，便于命令行筛选和报告保持稳定。
