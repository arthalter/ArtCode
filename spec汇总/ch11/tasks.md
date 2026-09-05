# ch11：Agent 评测与审计闭环 Tasks

## 执行原则

1. 严格按 T1 → T12 推进；T1～T4 完成前不启动真实 Agent。
2. 每项先补目标测试，再实现，再运行受影响测试；T12 前执行全量非 live、live、编译与构建。
3. 所有产物先脱敏再写盘，失败路径与成功路径使用同一数据模型。
4. 不修改现有 Benchmark Fixture，不复用用户 Session/Memory，不放宽生产权限和 Seatbelt。
5. 保留工作树中本章开始前已有的无关暂存、修改与未跟踪文件；提交只显式包含 ch11 文件。

## T1：建立评测模型与 Benchmark 严格解析

**影响文件：** `artcode/evaluation/models.py`、`artcode/evaluation/manifest.py`、`artcode/evaluation/__init__.py`、`tests/evaluation/test_manifest.py`、`tests/evaluation/test_models.py`

**依赖任务：** 无

**参考资料定位：** `spec.md` F1～F3、N3～N5、AC1；`plan.md`“Benchmark 格式”。

**完成结果：** 合法 Benchmark 得到不可变类型对象与稳定 SHA-256；非法结构和路径在运行前一次性报告。

**验证：** 运行 manifest/model 测试，覆盖合法文件、未知字段、重复 ID、边界限制、符号链接、`..`、指纹稳定与语义变化。

## T2：实现统一脱敏、有界预览与工作区快照

**影响文件：** `artcode/evaluation/redaction.py`、`artcode/evaluation/workspace.py`、`tests/evaluation/test_redaction.py`、`tests/evaluation/test_workspace.py`

**依赖任务：** T1

**参考资料定位：** `spec.md` F4、F8、N3、N6、AC2、AC11；`plan.md`“隔离与生命周期”“工作区变更证据”。

**完成结果：** API Key 与常见秘密形式在所有预览中归一化遮蔽；Fixture 可安全复制，前后文件清单可产生稳定变更摘要。

**验证：** 秘密探针扫描 Trace/JSON/Markdown 预备数据零命中；目录符号链接和文件符号链接越界均拒绝；复制不改变源目录哈希。

## T3：实现 Run Trace 记录器与过程指标

**影响文件：** `artcode/evaluation/trace.py`、`artcode/evaluation/metrics.py`、`tests/evaluation/test_trace.py`、`tests/evaluation/test_metrics.py`

**依赖任务：** T1、T2

**参考资料定位：** `spec.md` F7～F9、F12～F13、N4～N7；`plan.md`“Trace 模型”“指标定义”。

**完成结果：** AgentEvent 能转为有序 JSONL 证据；重复工具、权限拒绝、上下文前后 Token、模型 usage 和耗时使用唯一口径计算。

**验证：** 人工构造事件序列检查 sequence 连续、模型流不膨胀、参数指纹稳定、缺失 usage 为 null、异常结束仍有 finished 记录。

## T4：实现独立确定性 Verifier

**影响文件：** `artcode/evaluation/verifiers.py`、`tests/evaluation/test_verifiers.py`、`tests/evaluation/test_verifier_process.py`

**依赖任务：** T1～T3

**参考资料定位：** `spec.md` F10、N2～N3、N7、AC6；`plan.md`“Verifier 类型”。

**完成结果：** 文件存在/缺失、文本、命令、Trace 和指标六类验证器统一产生结构化结果，一项失败不跳过其余项。

**验证：** 同时覆盖通过、不通过、路径拒绝、UTF-8 错误、命令非零、命令不存在、超时与子进程回收。

## T5：实现聚合报告与原子产物

**影响文件：** `artcode/evaluation/report.py`、`tests/evaluation/test_report.py`、`tests/evaluation/test_report_atomicity.py`

**依赖任务：** T1～T4

**参考资料定位：** `spec.md` F13～F14、N5～N8、AC7、AC10～AC11；`plan.md`“报告与对比”。

**完成结果：** 每个 attempt 和整次运行都能输出口径一致的 JSON/Markdown；空指标为 null，局部写入失败不破坏上一个完整文件。

**验证：** JSON schema 字段、Markdown 数字、失败分布、样本数和原子替换故障测试全部通过，秘密扫描零命中。

## T6：实现隔离 Evaluation Runner

**影响文件：** `artcode/evaluation/runner.py`、`tests/evaluation/test_runner.py`、`tests/evaluation/test_runner_failures.py`

**依赖任务：** T1～T5

**参考资料定位：** `spec.md` F4～F6、N1～N4、N7；`plan.md`“隔离与生命周期”。

**完成结果：** 多任务、多重复尝试按稳定顺序运行；每次使用独立 Workspace/Home；超时、失败和取消都有局部状态与可读证据。

**验证：** Fake 执行边界验证重复隔离、任务失败继续、超时取消、KeyboardInterrupt 保留、输出不覆盖输入和临时目录清理。

## T7：接入生产 Bootstrap 与真实 AgentLoop

**影响文件：** `artcode/evaluation/runner.py`、必要时最小扩展 `artcode/bootstrap.py`、`tests/evaluation/test_production_runner.py`、`tests/integration/test_evaluation_agent_flow.py`

**依赖任务：** T6

**参考资料定位：** `spec.md` F5、N2、N9、AC3～AC5、AC12；`plan.md`“隔离与生命周期”。

**完成结果：** Eval 消费 `Bootstrap.build()` 返回的真实 AgentLoop，沿用生产工具、权限、上下文、Session、Memory、MCP 和资源关闭路径，不出现第二套 Agent 实现。

**验证：** 使用确定性 Provider/生产 AgentLoop 完成写文件、危险命令拒绝、上下文事件和自然结束场景；导入图确认生产模块不反向依赖 evaluation。

## T8：实现可选无工具 LLM Judge

**影响文件：** `artcode/evaluation/judge.py`、`tests/evaluation/test_judge.py`、`tests/evaluation/test_judge_failures.py`

**依赖任务：** T1、T2、T5、T7

**参考资料定位：** `spec.md` F11、N1、N5～N6、AC8；`plan.md`“LLM Judge”。

**完成结果：** Judge 只读取限定证据、无工具、Thinking 关闭，严格解析 0～100 分结构；任何失败返回 unavailable，不能覆盖 required Verifier。

**验证：** 合法结构、额外文本、多块标签、越界分数、缺字段、超时、Provider 错误和“Judge 100 但 Verifier 失败”全部通过。

## T9：实现报告对比

**影响文件：** `artcode/evaluation/compare.py`、`tests/evaluation/test_compare.py`

**依赖任务：** T5

**参考资料定位：** `spec.md` F15、AC9；`plan.md`“报告与对比”。

**完成结果：** 两份兼容报告产生总体和逐任务差异，改进/退化方向正确；不兼容报告默认拒绝并可显式降级比较共同任务。

**验证：** 成功率、Judge、Token、轮次、工具、重复调用和耗时的正负方向、null、缺任务与指纹不一致矩阵通过。

## T10：实现 CLI 与可运行 Benchmark

**影响文件：** `artcode/evaluation/cli.py`、`artcode/evaluation/__main__.py`、`pyproject.toml`、`benchmarks/agent_eval/benchmark.yml`、`benchmarks/agent_eval/fixtures/`、`tests/evaluation/test_cli.py`

**依赖任务：** T6～T9

**参考资料定位：** `spec.md` F14～F16、AC1、AC3；`plan.md`“CLI 合同”。

**完成结果：** `artcode-eval validate/run/compare` 和模块入口可用，退出码 0/1/2/130 可观察；官方 Benchmark 至少包含编码结果、权限边界和上下文治理任务。

**验证：** `--help`、三个子命令、非法参数、评测失败和中断退出码测试通过；官方 Benchmark validate 成功。

## T11：接入主流程

**影响文件：** `README.md`、`tests/integration/test_main_entry_flow.py`、`tests/integration/test_evaluation_agent_flow.py`、`spec汇总/ch11/{spec,plan,tasks,checklist}.md`

**依赖任务：** T1～T10

**参考资料定位：** `spec.md` N8～N10、AC12；`plan.md`“目录与依赖方向”“测试策略”。

**完成结果：** 评测作为独立入口随 wheel 安装，README 可复现最短命令；原 `artcode` 启动、Session、权限、Context 与 MCP 行为无回归。

**验证：** 全量非 live 回归、两个入口 smoke、wheel 临时安装、生产依赖方向和文档命令逐项通过。

## T12：端到端验证

**影响文件：** `tests/live/test_evaluation_live.py`、评测输出目录、`spec汇总/ch11/checklist.md`

**依赖任务：** T11

**参考资料定位：** `spec.md` AC1～AC12；`plan.md`“测试策略”。

**完成结果：** 真实 DeepSeek 至少完成一个官方编码任务；权限与上下文场景产生数字指标；报告可自比较；全量测试、编译和构建通过，验收清单以实际证据勾选。

**验证：** 执行 Benchmark validate、真实 Eval、report JSON/Markdown 审计、compare、全量 pytest、compileall、build、临时 wheel 安装和 Git 范围审计。真实数值必须来自产物，不能提前手填为完成。
