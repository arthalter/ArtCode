# chTA：Agent 系统效率与信息保真评测 Checklist

## A. 范围与证据纪律

- [x] A01：报告只包含 MCP、权限、SWE-bench-Live/信息保留三项实验，不出现八小时连续会话结论。
- [x] A02：每个实验锁定 baseline、candidate、任务、模型、预算、重复次数和代码/data revision，并生成清单指纹。
- [x] A03：最终百分比均能下钻到整数分子、整数分母和原始证据文件。
- [x] A04：静态单测、Fake Provider 和示例数据未进入“真实评测结果”字段。
- [x] A05：失败、超时、环境不兼容和 API 错误保留在分母或按预先声明规则标为 blocked，不在看到结果后删样本。
- [x] A06：运行产物对 API Key、Bearer、Authorization、secret 和 password 的原文扫描命中数为 0。

## B. MCP 延迟加载能力

- [x] B01：默认 eager 配置下，原有 MCP 启动、注册、审批、调用和关闭测试保持通过。
- [x] B02：lazy 配置下，Server 启动后完整工具 Adapter 存在于会话目录，但初始 Registry 不包含未激活 MCP 工具。
- [x] B03：lazy 初始 Registry 包含确定性工具检索入口，检索结果来自名称、描述和参数字段。
- [x] B04：目标工具激活后在下一轮模型请求中出现，并能通过原 MCP Adapter 调用真实 Server。
- [x] B05：重复激活不重复注册；无匹配、名称冲突和关闭期间激活均返回可观测结果。
- [x] B06：两个不同 Session 的已激活工具集合互不污染。
- [x] B07：百级 Fixture 实际暴露 120 个唯一工具定义，并至少有 5 个目标任务可唯一验证。
- [x] B08：eager 初始请求包含 120 个 MCP 工具定义；lazy 初始请求不包含这些未激活定义。

## C. MCP A/B 数据

- [x] C01：eager 与 lazy 使用相同的 5 个任务、相同模型与预算，每个任务各完成 3 次尝试或留下失败证据。
- [x] C02：每次模型请求记录实际工具定义数量、序列化字节、固定口径工具描述 Token 和请求指纹。
- [x] C03：每次真实模型调用记录 provider 返回的 prompt/completion/total Token；缺失 usage 显示 N/A。
- [x] C04：报告分别展示首轮工具描述 Token、累计工具描述 Token和累计 provider prompt Token，不混为一个指标。
- [x] C05：工具描述降幅按 `(eager-lazy)/eager` 计算，eager 为 0 时显示 N/A。
- [x] C06：报告同时展示成功率、模型轮次、检索调用、目标工具调用和耗时，不能只展示 Token 节省。
- [x] C07：任一 lazy 失败样本保留在成功率分母中，不因影响降幅而删除。

## D. 权限固定回放

- [x] D01：正常操作清单恰好包含 5 个不同精确权限目标，每个重复 6 次，总计 30 次。
- [x] D02：once 与 always 对照执行相同操作 ID、工具名、参数、顺序和工作区初始快照。
- [x] D03：正常操作全部通过真实 ToolExecutionService、PermissionService、PermissionEngine 和 RuleWriter。
- [x] D04：once 的审批器只返回 ALLOW_ONCE；always 对每个新目标首次返回 ALLOW_ALWAYS。
- [x] D05：`approval_requests` 来自 ApprovalPort 实际调用计数，并为每次调用保存脱敏事件。
- [x] D06：`rule_writes` 来自 RuleWriter 成功事件；`rule_hits` 来自 PermissionEngine ALLOW 事件，不能靠减法推算。
- [x] D07：在当前精确规则语义下，正常序列实测 once 审批请求为 30；不符时实验失败并展示实际值。
- [x] D08：在当前精确规则语义下，正常序列实测 always 审批请求为 5、规则命中为 25；不符时实验失败并展示实际值。
- [x] D09：审批请求降幅按 `(once-always)/once` 从事件实测值计算，不手填 83.3%。

## E. 权限安全边界

- [x] E01：危险命令负向控制被拒绝，禁止副作用不存在。
- [x] E02：与已授权路径相似但不相同的目标没有复用旧规则，必须重新审批或被拒绝。
- [x] E03：与已授权命令共享前缀但参数不同的命令没有复用旧规则。
- [x] E04：once 与 always 的误放行数均为 0；否则报告标记权限优化失败。
- [x] E05：规则写入失败不会把本次操作错误地标为持久授权，Trace 中存在失败事件。
- [x] E06：审批器异常、权限引擎异常和工具副作用失败均能区分，不合并成审批次数。

## F. SWE-bench-Live 环境与样本

- [x] F01：报告记录 SWE-bench-Live 官方仓库 revision、数据集 revision、split 和实例选择规则。
- [x] F02：Docker daemon、磁盘、网络、镜像架构和官方依赖预检均有日志。
- [x] F03：候选实例在看到 Agent 结果前按固定排序与固定种子确定。
- [ ] F04：每个计入分母的实例，其 gold patch 连续 3 次通过官方验证。
- [x] F05：最终锁定 6 个 gold-valid Python 实例；若不足 6 个，实验标记 blocked，不伪造分母。
- [x] F06：被排除实例只有清单预先允许的环境/gold 原因，并保留实例 ID 和日志。

## G. 历史版本与官方结果

- [x] G01：baseline 源码提交为 `a987d15`，candidate 源码提交为 `92a28a7`，提交对象校验成功。
- [x] G02：两个版本从 Git 对象创建独立源快照、依赖环境、ArtCode Home、Workspace 和输出目录。
- [x] G03：当前脏工作区文件未复制进任一历史版本运行目录。
- [x] G04：两个版本使用相同任务、模型、配置、最大轮次、超时和补丁验证命令。
- [x] G05：兼容驱动没有改写 `artcode/context_management/` 下任何被测文件；运行前后哈希一致。
- [ ] G06：每个实例保存 Agent Trace、生成补丁、官方测试日志和 resolved 布尔结果。
- [ ] G07：官方 resolve rate 的分母等于 F05 锁定的 gold-valid 实例数，失败与超时不被删除。
- [ ] G08：baseline/candidate resolved 数和 resolve rate 从官方验证结果聚合，未使用自定义 verifier 冒充。

## H. 信息保留探针

- [ ] H01：每个锁定实例至少包含原始问题要求、关键约束、相关文件和测试结论四类探针。
- [ ] H02：两个版本执行相同的任务派生上下文与相同压缩触发流程。
- [ ] H03：探针在压缩前全部可检索；压缩前失败的探针不进入实验并触发 Fixture 错误。
- [ ] H04：压缩后逐探针记录通过/失败、预期指纹和实际证据，不由 LLM Judge 主观打分。
- [ ] H05：信息保留率按 `通过探针数/全部有效探针数` 计算，并展示整数分子与分母。
- [ ] H06：信息保留率与 SWE-bench resolve rate 位于不同字段、表格和结论句中。

## I. 报告与简历映射

- [x] I01：同一次运行生成可解析的 `report.json`、`report.md` 和 `report.xlsx`。
- [x] I02：三种报告中的实验状态、样本数、原始计数、百分比和证据路径一致。
- [x] I03：工作簿至少包含总览、MCP 明细、权限事件、SWE-bench 实例、保留探针和证据索引。
- [x] I04：完整运行显示 complete；部分成功显示 partial；外部前置条件不满足显示 blocked。
- [x] I05：简历映射不把工具描述 Token 降幅写成总 Token 降幅。
- [x] I06：简历映射不把信息保留率写成 SWE-bench 官方解决率。
- [x] I07：只有真实 A/B、证据完整且安全负向控制通过的指标才生成可用于简历的数字句。
- [x] I08：八小时连续会话相关字段与简历句均不存在。

## J. 接入主流程与端到端验证

- [x] J01：`artcode-eval chTA validate` 能校验官方清单并打印指纹。
- [x] J02：`artcode-eval chTA run --experiment mcp` 能完成真实 API A/B 或保留明确 API 失败证据。
- [x] J03：`artcode-eval chTA run --experiment permission` 能在不调用模型的情况下完成确定性真实权限 A/B。
- [x] J04：`artcode-eval chTA run --experiment swebench` 能完成官方 pilot 或保留明确环境阻塞证据。
- [x] J05：`artcode-eval chTA run --experiment all` 在单项失败后继续其他实验并生成汇总报告。
- [x] J06：原 `artcode` CLI、MCP eager、权限、上下文、Session 和 ch11 evaluation 关键测试通过。
- [x] J07：新增单元、属性、集成、故障测试全部通过，`python -m compileall` 退出码为 0。
- [x] J08：最终真实运行目录、汇总报表和简历数据映射路径记录在本 Checklist 的实际验收区。

## 实际验收记录

| 项目 | 实测结果 | 证据路径 | 状态 |
|---|---|---|---|
| MCP eager/lazy | 2026-08-13/14 使用 `deepseek-chat` 完成 5 任务 × 3 重复 × 2 profile；30/30 成功。首轮工具描述 Token `187995 → 15225`（降低 91.9%），累计工具描述 Token `375990 → 48681`（降低 87.1%），provider prompt Token `408048 → 101661`（降低 75.1%）；lazy 每次多 1 个模型轮次和 1 次检索调用 | `outputs/chTA-real/20260813-234923-da1583d6/` | complete |
| 权限 once/always | 30 次真实生产链路回放；审批请求 `30 → 5`（降低 83.3%），规则写入 5、规则命中 25；危险命令、相似路径、共享前缀三类负向控制在两组中均 0 误放行 | `outputs/chTA-real/20260813-234833-da1583d6/` | complete |
| SWE-bench-Live gold pilot | Docker/Git/磁盘/官方仓库/固定数据集安装与 500 条 verified 导出成功；30 个固定候选各运行 3 次，共 90 次官方 gold 命令。Docker Hub 拉取 `starryzhang/sweb.eval.arm64.*` 时 EOF，gold-valid 为 `0/6` | `outputs/chTA-real/20260814-001219-da1583d6/swebench/` | blocked |
| 历史版本 resolve rate | 因 gold-valid 未锁满 6 个，按预先协议未启动 Agent 结果分母，未把外部镜像错误记为 unresolved/0% | `outputs/chTA-real/20260814-001219-da1583d6/swebench/gold-preflight/gold-lock.json` | N/A（上游 blocked） |
| 历史版本 retention rate | 必须与同一批 gold-valid 实例运行；因上游 `0/6`，未生成真实 benchmark 保留率，静态/Fixture 结果未进入正式报告 | `outputs/chTA-real/final-20260814-001900-da1583d6/report.json` | N/A（上游 blocked） |
| 汇总报告与简历映射 | 最终报告为 partial；只生成 MCP 与权限两条通过真实证据门的简历事实句，SWE/retention 显示 N/A，不包含八小时数据 | `outputs/chTA-real/final-20260814-001900-da1583d6/` | partial |
| 回归与静态验证 | 非 live/slow/soak 测试 `1549 passed, 67 deselected`；`python -m compileall` 与 `git diff --check` 退出码均为 0 | 全仓测试与源码 | complete |
| 敏感信息扫描 | 扫描真实运行目录 17,675 个文件，当前配置 API Key 原文命中 0；生成型日志/报告的结构化 credential literal 命中 0。上游只读 `verified.json` 中含公开的 `password: fake...` 测试文本，已按输入数据与运行泄露分开记录 | `outputs/chTA-real/` | complete |

未勾选的 F04、G06–G08、H01–H06 均依赖 6 个 gold-valid 实例；本次因 Docker Hub 官方评测镜像拉取 EOF 阻塞，按预先协议保留为 N/A，未伪造官方解决率或信息保留率。
