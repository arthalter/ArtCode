# chTA：Agent 系统效率与信息保真评测 Tasks

## T1：锁定实验清单与结果模型

**影响文件：** `benchmarks/chTA/manifest.yml`、`artcode/evaluation/manifest.py`、`artcode/evaluation/models.py`、`tests/evaluation/test_chta_manifest.py`

**依赖任务：** 无

**参考资料定位：** `spec汇总/chTA/spec.md` 的“统一实验协议”；现有 `artcode/evaluation/manifest.py` 与 `models.py`。

**完成结果：** 支持 MCP、权限、SWE-bench-Live 三类实验声明、基线/候选公共配置、外部 revision、任务选择规则和指纹；拒绝未知字段、重复 ID、非法版本和不完整 A/B。

## T2：增加请求与权限审计事件

**影响文件：** `artcode/agent/events.py`、`artcode/agent/request.py`、`artcode/evaluation/trace.py`、`artcode/permissions/service.py`、`artcode/permissions/engine.py`、`tests/evaluation/test_chta_audit_events.py`

**依赖任务：** T1

**参考资料定位：** `spec汇总/chTA/plan.md` 的“统一事件与证据”；现有 `RunTraceRecorder` 和 `ApprovalPort`。

**完成结果：** 模型请求记录工具数量、序列化字节和固定口径 Token；权限链路可选地发出审批、规则写入、规则命中与拒绝事件。默认未配置审计接收器时行为不变，事件不含工具完整结果或秘密。

## T3：实现会话级 MCP 延迟加载

**影响文件：** `artcode/mcp/catalog.py`、`artcode/mcp/manager.py`、`artcode/mcp/models.py`、`artcode/mcp/config.py`、`artcode/config.py`、`artcode/bootstrap.py`、`artcode/tools/registry.py`、`tests/unit/test_mcp_lazy_catalog.py`

**依赖任务：** T2

**参考资料定位：** `spec汇总/chTA/plan.md` 的“MCP 延迟加载实现与实验”；现有 `McpManager.start/register_into`。

**完成结果：** eager 保持默认兼容；lazy 将完整 Adapter 留在会话目录，仅注册确定性检索工具和已激活工具；支持检索、激活、重复激活、名称冲突、无匹配和关闭边界。

## T4：构建百级 MCP Fixture 与确定性测试

**影响文件：** `tests/integration/fixtures/mcp_hundred_tools_server.py`、`tests/integration/test_mcp_lazy_loading_flow.py`、`tests/property/test_mcp_lazy_catalog_properties.py`、`tests/fault/test_mcp_lazy_loading_faults.py`

**依赖任务：** T3

**参考资料定位：** 现有 `tests/integration/fixtures/mcp_test_server.py` 和 MCP live tests。

**完成结果：** 本地 Server 稳定暴露 120 个工具；lazy 初始请求不包含未激活描述，检索后只激活匹配工具；eager/lazy 均能执行目标工具；顺序、重复查询和 Server 失败不破坏隔离。

## T5：实现 MCP A/B 运行器与指标

**影响文件：** `artcode/evaluation/chta/mcp_experiment.py`、`artcode/evaluation/metrics.py`、`benchmarks/chTA/mcp/`、`tests/evaluation/test_chta_mcp_experiment.py`、`tests/live/test_chta_mcp_live.py`

**依赖任务：** T4

**参考资料定位：** `spec汇总/chTA/plan.md` 的“MCP A/B 任务”。

**完成结果：** 5 个任务 × 3 次重复，以相同模型和预算运行 eager/lazy；产出首轮/累计工具描述 Token、provider prompt Token、轮次、调用、耗时、成功率和证据路径；任务失败仍保留数据。

## T6：实现权限固定回放与审计聚合

**影响文件：** `artcode/evaluation/chta/permission_experiment.py`、`benchmarks/chTA/permission/operations.yml`、`tests/evaluation/test_chta_permission_experiment.py`

**依赖任务：** T2

**参考资料定位：** `spec汇总/chTA/plan.md` 的“权限审批复用实验”；现有 `tests/integration/test_permissions_flow.py`。

**完成结果：** once/always 两个 profile 通过真实工具执行与权限链路回放相同的 30 次正常操作；直接统计审批接口调用、选择、规则写入、规则命中和副作用。

## T7：补齐权限负向控制与故障测试

**影响文件：** `tests/integration/test_chta_permission_reuse_flow.py`、`tests/property/test_chta_permission_boundaries.py`、`tests/fault/test_chta_permission_faults.py`

**依赖任务：** T6

**参考资料定位：** 现有 PermissionEngine、RuleWriter 和 Seatbelt 测试。

**完成结果：** 危险命令、相似路径和共享前缀命令均不能借用已有规则越权；验证误放行和误拒绝计数；规则写入失败、审批器异常与副作用失败均可观测。

## T8：接入 SWE-bench-Live 官方环境与 gold 预检

**影响文件：** `artcode/evaluation/chta/swebench_live.py`、`benchmarks/chTA/swebench/lock.yml`、`tests/evaluation/test_chta_swebench_adapter.py`、`tests/live/test_chta_swebench_preflight.py`

**依赖任务：** T1

**参考资料定位：** SWE-bench-Live 官方仓库的 dataset 与 evaluation 文档；`spec汇总/chTA/plan.md` 的“官方适配”。

**完成结果：** 固定官方 revision，检查 Docker/磁盘/架构，按固定规则选择候选，运行 gold patch 三次，锁定 6 个 gold-valid Python 实例；所有排除项有预先定义的原因和日志。

## T9：实现历史版本隔离执行器

**影响文件：** `artcode/evaluation/chta/version_runner.py`、`artcode/evaluation/chta/compat_driver.py`、`tests/integration/test_chta_version_runner.py`、`tests/fault/test_chta_version_runner_faults.py`

**依赖任务：** T8

**参考资料定位：** Git 提交 `a987d15`、`92a28a7`；`spec汇总/chTA/plan.md` 的“版本隔离”。

**完成结果：** 从 Git 对象创建两个独立源快照和 ArtCode Home；同一外部驱动调用两个版本；脏工作区不进入实验；兼容层不能覆盖或替换被测上下文文件。

## T10：运行官方补丁验证与信息保留探针

**影响文件：** `artcode/evaluation/chta/swebench_experiment.py`、`artcode/evaluation/chta/retention_probes.py`、`tests/evaluation/test_chta_retention_metrics.py`、`tests/live/test_chta_swebench_live.py`

**依赖任务：** T9

**参考资料定位：** SWE-bench-Live 官方补丁验证入口；提交 `92a28a7` 的用户消息保留测试。

**完成结果：** 两个版本对相同 gold-valid 实例生成补丁并运行官方验证；配套探针独立检查原始要求、约束、相关文件和测试结论；resolve rate 与 retention rate 分列，失败实例不从分母静默移除。

## T11：生成 JSON、Markdown 与表格报表

**影响文件：** `artcode/evaluation/report.py`、`artcode/evaluation/chta/report.py`、`artcode/evaluation/chta/workbook.py`、`tests/evaluation/test_chta_report.py`

**依赖任务：** T5、T7、T10

**参考资料定位：** `spec汇总/chTA/plan.md` 的“汇总报告与简历映射”；现有 `report.py`、`compare.py`。

**完成结果：** 输出统一 `report.json`、`report.md`、`report.xlsx`；包含三项实验总览、逐样本数据、失败分布、证据索引、公式和可用于简历的事实句；所有表间数字一致。

## T12：接入 CLI 与主流程

**影响文件：** `artcode/evaluation/cli.py`、`artcode/evaluation/chta/runner.py`、`README.md`、`tests/evaluation/test_chta_cli.py`

**依赖任务：** T11

**参考资料定位：** `spec汇总/chTA/plan.md` 的“CLI”；现有 `artcode-eval` 命令。

**完成结果：** `validate/run/report` 接入现有 `artcode-eval chTA`；支持逐项和 all；单项失败不删除其他产物；普通 `artcode` 与原 `artcode-eval run` 行为不变。

## T13：秘密、失败恢复与回归验证

**影响文件：** `tests/property/test_chta_redaction.py`、`tests/fault/test_chta_runner_faults.py`、现有相关回归测试

**依赖任务：** T12

**参考资料定位：** 现有 evaluation Redactor、MCP redaction、API 错误映射测试。

**完成结果：** API Key、Authorization 和敏感配置不进入产物；API、Docker、MCP 或报告失败时保留 partial 状态；原 MCP eager、权限、上下文、CLI 和 ch11 evaluation 回归通过。

## T14：端到端真实评测与简历数据交付

**影响文件：** `spec汇总/chTA/checklist.md`、`outputs/chTA-real/`、评测运行目录

**依赖任务：** T13

**参考资料定位：** 本清单的全部验收项。

**完成结果：** 使用真实 DeepSeek API 依次完成 MCP、权限和 SWE-bench-Live 实验；生成完整或诚实标记 partial/blocked 的报告；把通过证据门的真实数字填入简历文本，不填入八小时数据。

## 依赖图

```text
T1 清单与模型
├─ T2 审计事件
│  ├─ T3 MCP lazy → T4 MCP Fixture → T5 MCP A/B ─┐
│  └─ T6 权限回放 → T7 权限边界 ─────────────────┤
└─ T8 官方预检 → T9 版本隔离 → T10 官方/保留评测 ┤
                                                  └─ T11 报告
                                                      → T12 主流程
                                                      → T13 回归
                                                      → T14 真实端到端
```
