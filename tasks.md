# ch14：ArtCode 语义统一与破坏性整体重写 Tasks

## 执行原则

1. 严格按依赖关系推进；每个任务先写目标 Interface 的失败测试，再实现，再运行本任务验证。
2. 八个深模块各自只暴露一个公开 Interface；内部允许私有 seam，但调用方和跨模块测试不得穿透它们。
3. 新核心在 `artcode/core/` 独立建设，在 T14 前不得被旧生产入口导入，也不得反向导入旧 Runtime、Conversation、Prompt、Permission、Background 等业务实现。
4. 外部依赖只在真实变化 seam 上使用 Adapter；生产 Adapter 与测试 Adapter 共用同一 Interface，不为单一实现制造转发层。
5. 新 Interface 测试取得等价行为覆盖后，必须在所属模块任务内删除穿透旧私有实现的测试；不把这类删除统一拖到切换阶段，也不长期叠加两套契约。
6. Plan Run 的 Tool 目录、执行入口和审批路径都必须拒绝 `change`、`external` 与 `control`，任何规则或人工批准都不能解除。
7. Provider 的一次 Model 调用只发起一次底层请求；不得保留首事件前透明自动重试。
8. T13 的切换前就绪条件全部通过后才能进入 T14；T14 必须一次性切换并删除旧核心、兼容路径和临时开发入口，入口等价与删除结果在 T14 验证。
9. 旧 Session、记忆、权限和派生运行数据不迁移；包含未提交修改或未安全交接提交的 Worktree 始终按成果保护规则保留。
10. 每个任务运行目标测试和受影响的非 live 回归；真实 Provider、MCP、Git、进程与 Seatbelt 验证分别归入其模块任务，T15 只复跑固定验收并汇总证据。
11. T2～T12 在实现自身 Spec 范围时同步更新 `tests/behavior/ch14_matrix.yml`，并在取得等价覆盖后执行该范围登记的旧测试处置；T13 只审计结果，不集中补做。

## 参考资料索引

- **需求基线：** 根目录 `spec.md`，以及 GitHub Issue #14。
- **实现设计：** 根目录 `plan.md`，重点参考“目标结构”“状态所有权”“八个深模块”“开发隔离与一次性切换”“删除清单”和“切换门槛”。
- **领域语言：** 根目录 `CONTEXT.md`。
- **架构决策：** `docs/adr/0001-comprehensive-local-learning-assistant.md`、`docs/adr/0002-one-time-breaking-rewrite.md`。
- **现役行为证据：** `spec汇总/ch02/` 至 `spec汇总/ch12/`、ch13 根文档的 Git 历史、`README.md`、现有自动测试及 `tests/manual/`。
- **旧生产入口：** `artcode/cli.py`、`artcode/__main__.py`、`artcode/bootstrap.py`、`artcode/runtime/app.py`。

## T1：建立行为矩阵骨架与核心架构护栏

**影响文件：** `artcode/core/__init__.py`、`tests/behavior/ch14_matrix.yml`、`tests/tools/verify_ch14_matrix.py`、`tests/architecture/test_core_dependencies.py`、`pyproject.toml`

**依赖任务：** 无

**参考资料定位：** Spec F93～F98、N1～N4、N7、N13、N15～N16、AC22～AC25；Plan“目标结构”“状态所有权”“测试策略”。

**完成结果：** 可机读行为矩阵的字段、校验器和增量填写规则固定；本任务只录入 F93～F98、架构相关非功能要求及 AC22～AC25，其他需求由 T2～T12 随对应 Interface 和真实测试一起落表，核心依赖方向可自动检查。

**实施要点：**

1. 固化八个模块的状态所有者和允许依赖，不在本任务提前定义八套完整 Interface；各模块的公开 Interface 由对应 T2～T12 测试先行冻结。
2. 定义每行必须包含的需求编号、状态所有者、实施任务、验收路径、验证类型和旧测试处置字段；先录入架构与切换规则作为样例。
3. 校验重复编号、无效任务、无效测试定位、循环任务依赖和缺少处置任务的旧私有 seam 测试；允许尚未开始的模块行标记为待所属任务填写。
4. 建立可增量生效的导入规则：核心模块不依赖 CLI/TUI、旧业务包、具体 Provider、具体持久格式或测试替身。

**验证：** 运行 `pytest tests/architecture/test_core_dependencies.py -q` 和 `python tests/tools/verify_ch14_matrix.py --stage T1`；确认矩阵 Schema、架构需求样例和增量完整性规则有效，未开始的模块不会被误报为已经验收。

## T2：实现 Workspace 的路径、文件与结果存储 Interface

**影响文件：** `artcode/core/workspace.py`、`artcode/_workspace/__init__.py`、`artcode/_workspace/paths.py`、`artcode/_workspace/files.py`、`artcode/_workspace/results.py`、`tests/contracts/test_workspace_interface.py`、`tests/property/test_core_workspace_paths.py`、`tests/fault/test_core_workspace_files.py`、`tests/integration/test_core_workspace_file_flow.py`、`tests/behavior/ch14_matrix.yml`，以及矩阵分配给本任务替换的旧 Workspace 私有 seam 测试

**依赖任务：** T1

**参考资料定位：** Spec F32～F37、F43、F52～F53、N5、N7、N9～N12、AC5～AC6、AC11；Plan“Workspace”“大 Tool Result”。

**完成结果：** Workspace scope 以显式根目录完成范围读取、文件发现、普通文本搜索、原子创建、明确覆盖、唯一编辑及大型结果存储和分段回读；Tool 准备阶段得到的可审核目标在真正执行前由 Workspace 再次验证。

**实施要点：**

1. 路径规范化、敏感路径、父级跳转、绝对路径、符号链接和目标替换检查全部隐藏在 Workspace Interface 后。
2. 新文件可创建 Workspace 内缺失的父目录；已有文件没有明确覆盖意图时拒绝，唯一编辑匹配数不为一时不写入。
3. 大内容只返回有界预览和稳定引用，完整结果保存在当前 scope 的内部临时区；分段回读必须显式给出范围。
4. 缓存键同时包含 scope 身份和规范化绝对路径，不使用 `Path.cwd()` 或进程级目录作为隐式输入。

**验证：** 运行 `pytest tests/contracts/test_workspace_interface.py tests/property/test_core_workspace_paths.py tests/fault/test_core_workspace_files.py tests/integration/test_core_workspace_file_flow.py -q`；覆盖越界、符号链接竞态、原子写入故障、重复匹配、大文件和两个 scope 同名路径隔离。

## T3：实现 Workspace 的进程、Seatbelt 与 Worktree 生命周期

**影响文件：** `artcode/core/workspace.py`、`artcode/_workspace/processes.py`、`artcode/_workspace/seatbelt.py`、`artcode/_workspace/seatbelt.sb`、`artcode/_workspace/git.py`、`artcode/_workspace/worktrees.py`、`artcode/_workspace/worktree_metadata.py`、`tests/contracts/test_workspace_process_interface.py`、`tests/contracts/test_workspace_worktree_interface.py`、`tests/fault/test_core_process_cleanup.py`、`tests/fault/test_core_worktree_protection.py`、`tests/integration/test_core_seatbelt.py`、`tests/integration/test_core_worktree_flow.py`、`tests/behavior/ch14_matrix.yml`，以及矩阵分配给本任务替换的旧进程、Seatbelt 与 Worktree 私有 seam 测试

**依赖任务：** T2

**参考资料定位：** Spec F38、F42、F89～F92、N5～N7、N9、N11、AC7～AC8、AC20～AC21；Plan“Workspace”“Subagent Task”“不得删除”。

**完成结果：** Workspace Interface 能执行和取消完整进程树、在 macOS 上强制应用无网络 Seatbelt，并基于冻结提交创建、检查、交接和安全清理 Worktree lease；不确定或含成果状态一律保留。

**实施要点：**

1. 命令使用显式 scope 和参数，不改变进程 cwd；完成、超时、取消和关闭都回收整个进程组及输出资源。
2. Seatbelt 不可用时失败关闭，脱离隔离只能通过显式运行上下文进入，不能由低层 Adapter 自行降级。
3. Worktree 基准在任务入队时冻结，不复制主 Workspace 未提交内容；主 Workspace、两个 Worktree 和托管元数据互相隔离。
4. 自动清理只删除可证明无文件变化、无新增提交且无活跃 lease 的系统临时 Worktree；危险丢弃必须绑定用户确认的精确目标。

**验证：** 运行 `pytest tests/contracts/test_workspace_process_interface.py tests/contracts/test_workspace_worktree_interface.py tests/fault/test_core_process_cleanup.py tests/fault/test_core_worktree_protection.py tests/integration/test_core_seatbelt.py tests/integration/test_core_worktree_flow.py -q`；使用真实进程、真实 Git 与可用 Seatbelt 验证资源回收和成果保护。

## T4：实现单请求 Model Interface 与 Provider Adapter

**影响文件：** `artcode/core/model.py`、`artcode/_model/__init__.py`、`artcode/_model/deepseek.py`、`artcode/_model/sse.py`、`artcode/_model/tool_calls.py`、`artcode/_model/redaction.py`、`tests/contracts/test_model_interface.py`、`tests/property/test_core_sse.py`、`tests/fault/test_core_model_failures.py`、`tests/integration/test_core_model_flow.py`、`tests/live/test_core_deepseek.py`、`tests/behavior/ch14_matrix.yml`，以及矩阵分配给本任务替换的旧 Provider 私有 seam 测试

**依赖任务：** T1

**参考资料定位：** Spec F20～F24、F51、N6～N7、N10～N11、AC3、AC11；Plan“Model”“Provider 自动重试次数为零”。

**完成结果：** Model 接收不可变请求并产出类型化文本、Tool Request、结束原因、真实 usage 与不透明 Protocol Metadata；Provider 协议、SSE、Thinking、连接管理、错误映射和脱敏全部由实现隐藏。

**实施要点：**

1. 一次 Model Interface 调用只能发起一次底层请求；连接、空响应、解码、超时和流中断均直接形成可区分失败。
2. Thinking 只参与 Provider 请求，不进入普通文本、终端输出、Summary 或记忆输入。
3. Tool 增量与 Protocol Metadata 在 Adapter 内组装为稳定领域事件，调用方不接触 Provider 原始字段。
4. Model 只报告 Provider 实际 usage，不估算、不跨请求累计；所有错误与状态快照经过秘密脱敏。

**验证：** 运行 `pytest tests/contracts/test_model_interface.py tests/property/test_core_sse.py tests/fault/test_core_model_failures.py tests/integration/test_core_model_flow.py -q`；通过计数 Adapter 证明每次调用仅一次请求，并在配置可用时运行 `pytest tests/live/test_core_deepseek.py -q`。

## T5：实现 Tool 目录、权限策略与批次执行 Interface

**影响文件：** `artcode/core/tool.py`、`artcode/_tool/__init__.py`、`artcode/_tool/catalog.py`、`artcode/_tool/builtin.py`、`artcode/_tool/policy.py`、`artcode/_tool/permissions.py`、`artcode/_tool/batch.py`、`artcode/_tool/results.py`、`artcode/_tool/dangerous_commands.yml`、`tests/contracts/test_tool_interface.py`、`tests/property/test_core_tool_policy.py`、`tests/fault/test_core_tool_batch.py`、`tests/integration/test_core_tool_workspace_flow.py`、`tests/behavior/ch14_matrix.yml`，以及矩阵分配给本任务替换的旧 Tool、权限与 Shell 策略私有 seam 测试

**依赖任务：** T3

**参考资料定位：** Spec F25～F43、N2、N6～N10、N13、AC4～AC8；Plan“Tool”“Plan 固定规则”。

**完成结果：** Tool Interface 统一模型可见描述、Tool Effect、Run Mode、能力收窄、权限决定、人工审批、批次计划与结构化结果；内置 Tool 的本地效果全部委托 Workspace。

**实施要点：**

1. Tool 拥有目录、Effect 分类、权限模式、Shell 策略和精确持久规则，Agent、TUI 与 Subagent 不维护重复清单。
2. 权限顺序固定为硬约束、显式规则、Run Mode 或 Shell 策略、人工审批；低层允许不能覆盖高层拒绝。
3. Plan 的目录只暴露内置 `observe` Tool，执行入口再次拒绝伪造的写入、Shell、MCP 和 Subagent 调用，审批不能解锁。
4. 相邻无依赖 `observe` Tool 并发，其他效果按原请求顺序执行；局部失败不取消无关已启动观察，结果始终按请求顺序返回。

**验证：** 运行 `pytest tests/contracts/test_tool_interface.py tests/property/test_core_tool_policy.py tests/fault/test_core_tool_batch.py tests/integration/test_core_tool_workspace_flow.py -q`；覆盖四类权限决定、策略冲突、审批后目标变化、Plan 三重防线、并发和局部失败。

## T6：把 MCP 作为 Tool 内部 Adapter 接入

**影响文件：** `artcode/core/tool.py`、`artcode/_tool/mcp.py`、`artcode/_tool/mcp_config.py`、`artcode/_tool/mcp_transport.py`、`artcode/_tool/mcp_results.py`、`tests/contracts/test_tool_mcp_interface.py`、`tests/property/test_core_mcp_isolation.py`、`tests/fault/test_core_mcp_failures.py`、`tests/integration/test_core_mcp_stdio.py`、`tests/integration/test_core_mcp_http.py`、`tests/behavior/ch14_matrix.yml`，以及矩阵分配给本任务替换的旧 MCP 私有 seam 测试

**依赖任务：** T4、T5

**参考资料定位：** Spec F44～F50、N4、N6、N10～N12、AC9～AC10；Plan“Tool”“MCP Adapter”。

**完成结果：** 用户级与项目级 MCP 配置、stdio 与 Streamable HTTP、分页发现、全量/按需激活、会话复用、项目确认、逐调用权限及有序关闭全部隐藏在 Tool Interface 内；单 Server 故障保持局部。

**实施要点：**

1. 项目配置按确定规则整体覆盖同名用户配置，并在产生外部效果前确认。
2. 内置与 MCP Tool 使用同一描述、Effect、策略、批次和结果语义；Plan 中 MCP 既不暴露也不能伪造执行。
3. 已激活目录在当前 Session 后续 Run 可用，完整目录与按需目录不形成两套执行路径。
4. 文本和结构化结果可进入受控上下文，二进制内容只返回有界元数据；连接、协议、超时、取消与关闭错误不影响其他 Tool。

**验证：** 运行 `pytest tests/contracts/test_tool_mcp_interface.py tests/property/test_core_mcp_isolation.py tests/fault/test_core_mcp_failures.py tests/integration/test_core_mcp_stdio.py tests/integration/test_core_mcp_http.py -q`；集成测试使用真实本地 stdio 与 Streamable HTTP 测试 Server。

## T7：实现 Session 的 Transcript、持久化与恢复

**影响文件：** `artcode/core/session.py`、`artcode/_session/__init__.py`、`artcode/_session/transcript.py`、`artcode/_session/storage.py`、`artcode/_session/locking.py`、`artcode/_session/recovery.py`、`artcode/_session/paths.py`、`tests/contracts/test_session_interface.py`、`tests/property/test_core_transcript.py`、`tests/fault/test_core_session_storage.py`、`tests/integration/test_core_session_recovery.py`、`tests/behavior/ch14_matrix.yml`，以及矩阵分配给本任务替换的旧 Session 持久化与恢复私有 seam 测试

**依赖任务：** T1

**参考资料定位：** Spec F4、F8～F10、F14～F15、F58～F61、N2、N5～N7、N10～N11、AC1～AC2、AC13；Plan“Session”“配置与持久化策略”。

**完成结果：** Session 成为 Transcript、Session lock 与恢复状态的唯一所有者；新格式以完整领域记录同步追加，能够新建、恢复最近可写 Session 或选择指定 Session，并隔离局部损坏。

**实施要点：**

1. Transcript 只保存已提交事实；User、Assistant 与完整 Tool exchange 具有明确提交语义，Protocol Metadata 作为不透明 envelope 原样保存。
2. Tool exchange 单条记录包含请求和全部结果，取消时补齐结构化取消结果，恢复不会产生孤立 Tool Result。
3. 写入使用可检测完整性的同步追加；坏独立记录可隔离，坏尾部可截断，不完整协议回退到最近安全前缀。
4. 新版本使用独立持久命名空间且不加载旧格式；并发进程不能写入同一 Session，只读查询和失败恢复不改变原文件。

**验证：** 运行 `pytest tests/contracts/test_session_interface.py tests/property/test_core_transcript.py tests/fault/test_core_session_storage.py tests/integration/test_core_session_recovery.py -q`；覆盖原子追加故障、坏记录、坏尾部、协议不完整、进程锁、旧格式拒绝和只读恢复。

## T8：实现 Session 的 Prompt、上下文治理与长期记忆

**影响文件：** `artcode/core/session.py`、`artcode/_session/prompt.py`、`artcode/_session/notices.py`、`artcode/_session/summaries.py`、`artcode/_session/instructions.py`、`artcode/_session/results.py`、`artcode/_session/memory.py`、`tests/contracts/test_session_prompt_interface.py`、`tests/property/test_core_user_retention.py`、`tests/fault/test_core_context_governance.py`、`tests/fault/test_core_memory.py`、`tests/integration/test_core_session_prompt_flow.py`、`tests/behavior/ch14_matrix.yml`，以及矩阵分配给本任务替换的旧 Prompt、上下文治理与记忆私有 seam 测试

**依赖任务：** T2、T4、T5、T7

**参考资料定位：** Spec F10～F15、F51～F64、N2、N5～N7、N10～N12、AC2、AC11～AC14；Plan“Session”“普通 Run”。

**完成结果：** Session 能打开不可变 Run lease，并把 Transcript、指令、Notice、Summary、记忆、Skill contribution 与 ToolSnapshot 投影为 Prompt；所有 User 原文始终独立、逐字、有序保留，派生内容失败不破坏权威历史。

**实施要点：**

1. Notice 只在请求真正 dispatch 时消费一次；状态查询、Prompt 预览和失败准备不得提前消费。
2. 上下文预算优先使用真实 usage，缺失时采用可解释估算；自动、强制、紧急和手动压缩均有界且不会形成重试循环。
3. Summary 只替代较早的非 User 历史，不破坏 Tool 协议，不解释 Protocol Metadata；生成失败继续使用旧历史。
4. 长期记忆区分用户偏好与项目事实，只有自然完成的不可变 Run 快照进入串行异步更新，失败与取消不影响后续 Run。

**验证：** 运行 `pytest tests/contracts/test_session_prompt_interface.py tests/property/test_core_user_retention.py tests/fault/test_core_context_governance.py tests/fault/test_core_memory.py tests/integration/test_core_session_prompt_flow.py -q`；覆盖重复压缩、usage 缺失、大结果引用、Notice 时机、指令循环、记忆故障和逐字 User 保留。

## T9：实现唯一 Agent Run 状态机

**影响文件：** `artcode/core/agent.py`、`artcode/_agent/__init__.py`、`artcode/_agent/runner.py`、`artcode/_agent/events.py`、`artcode/_agent/usage.py`、`tests/contracts/test_agent_interface.py`、`tests/property/test_core_agent_protocol.py`、`tests/fault/test_core_agent_failures.py`、`tests/integration/test_core_agent_run.py`、`tests/behavior/ch14_matrix.yml`，以及矩阵分配给本任务替换的旧 Agent 私有 seam 测试

**依赖任务：** T4、T5、T7、T8

**参考资料定位：** Spec F16～F31、N2、N5～N8、N10～N13、AC3～AC4；Plan“Agent”“普通 Run”。

**完成结果：** Agent 只依赖 Model、Tool 与 Run lease 推进一次 Run，持续产生类型化 RunEvent，并以可区分 Stop Reason 和累计 usage 结束；普通 Run 无产品级固定轮次，受控执行可显式限制。

**实施要点：**

1. 文本增量只作为临时事件展示；自然完成和长度结束按 Session 规则提交，取消、请求失败和流中断不提交半截 Assistant 文本。
2. 每个 Model 响应中的 Tool 请求作为完整批次执行并提交闭合协议，再进入下一轮 Model 请求。
3. 自然完成、达到限制、用户取消、请求失败、长度结束和不可继续分别映射为稳定 Stop Reason。
4. Agent 的 Run usage 只聚合 Model 报告的真实字段；Session 的确定性估算只服务上下文预算并保留来源，不得混入 Run usage。取消在可提交协议点停止并交还资源。

**验证：** 运行 `pytest tests/contracts/test_agent_interface.py tests/property/test_core_agent_protocol.py tests/fault/test_core_agent_failures.py tests/integration/test_core_agent_run.py -q`；覆盖长工具链、显式上限、多 Tool、局部失败、长度结束、流错误、取消和协议闭合。

## T10：实现 Skill 深模块

**影响文件：** `artcode/core/skill.py`、`artcode/_skill/__init__.py`、`artcode/_skill/discovery.py`、`artcode/_skill/parsing.py`、`artcode/_skill/catalog.py`、`artcode/_skill/execution.py`、`artcode/_skill/builtin/.gitkeep`、`tests/contracts/test_skill_interface.py`、`tests/property/test_core_skill_capabilities.py`、`tests/fault/test_core_skill_refresh.py`、`tests/integration/test_core_skill_flow.py`、`tests/behavior/ch14_matrix.yml`、`pyproject.toml`，以及矩阵分配给本任务替换的旧 Skill 私有 seam 测试

**依赖任务：** T5、T8、T9

**参考资料定位：** Spec F68、F71～F79、N2、N6～N7、N10、N12～N13、AC15～AC17；Plan“Skill”。

**完成结果：** Skill Interface 独立拥有发现、覆盖、激活、热更新和最后有效版本，为 Run 生成冻结的 SOP、Tool 收窄和模型选择 contribution；Shared 与 Isolated 执行保持不同语义。

**实施要点：**

1. 项目、用户、内置和扩展来源按确定优先级整体覆盖；无效高优先级定义阻断同名回退但不影响其他 Skill。
2. 启动目录只加载选择信息，激活时加载完整 SOP；自然语言和明确命令共用同一激活状态所有者。
3. 多个 Skill 的 Tool 范围取交集，不能绕过 Run Mode、权限、路径、危险命令、隔离或 MCP 确认；模型不可用时明确失败。
4. Shared Skill 使用主 Run；Isolated Skill 使用临时 Transcript 并只返回最终总结，不创建 Task、后台状态或 Worktree。

**验证：** 运行 `pytest tests/contracts/test_skill_interface.py tests/property/test_core_skill_capabilities.py tests/fault/test_core_skill_refresh.py tests/integration/test_core_skill_flow.py -q`；覆盖来源覆盖、坏候选、两阶段加载、清除、热更新、白名单交集及 Shared/Isolated 差异。

## T11：实现 Subagent、Task 与通知深模块

**影响文件：** `artcode/core/subagent.py`、`artcode/_subagent/__init__.py`、`artcode/_subagent/roles.py`、`artcode/_subagent/tasks.py`、`artcode/_subagent/scheduler.py`、`artcode/_subagent/notifications.py`、`artcode/_subagent/execution.py`、`artcode/_subagent/builtin/.gitkeep`、`tests/contracts/test_subagent_interface.py`、`tests/property/test_core_subagent_capabilities.py`、`tests/fault/test_core_subagent_failures.py`、`tests/integration/test_core_subagent_flow.py`、`tests/integration/test_core_parallel_worktrees.py`、`tests/behavior/ch14_matrix.yml`、`pyproject.toml`，以及矩阵分配给本任务替换的旧 Subagent 与 Task 私有 seam 测试

**依赖任务：** T3、T4、T5、T8、T9

**参考资料定位：** Spec F80～F92、N2、N5～N13、AC18～AC21；Plan“Subagent”“Subagent Task”。

**完成结果：** Subagent Interface 统一定义式与 Fork 式创建、Role 解析、子 Run、Task 排队与并发、前后台切换、查看、取消、通知和成果交接；子 Run 复用唯一 Agent、Model、Tool Interface。

**实施要点：**

1. 定义式从干净 Transcript 和 Role 启动；Fork 式冻结父 Prompt 与 ToolSnapshot 并始终后台执行。
2. 子执行拥有独立 Run 状态、权限事件、上下文与 usage；能力只被父上限、Role 和后台策略收窄，不能递归委派、询问用户或继承临时批准。
3. 写任务在首次 Model 请求前取得基于入队提交的 Worktree lease；失败时不降级到主 Workspace。
4. Task 只存在当前进程；完成通知按完成顺序在父 Run 安全 Prompt 边界投递一次，只含结论、状态、usage 与 handoff。

**验证：** 运行 `pytest tests/contracts/test_subagent_interface.py tests/property/test_core_subagent_capabilities.py tests/fault/test_core_subagent_failures.py tests/integration/test_core_subagent_flow.py tests/integration/test_core_parallel_worktrees.py -q`；覆盖定义/Fork、状态隔离、并发、前后台、取消、重启、通知时机和双 Worktree。

## T12：实现独立的新 Application 与 CLI/TUI Adapter

**影响文件：** `artcode/core/application.py`、`artcode/_application/__init__.py`、`artcode/_application/config.py`、`artcode/_application/lifecycle.py`、`artcode/_application/commands.py`、`artcode/_application/events.py`、`artcode/adapters/__init__.py`、`artcode/adapters/terminal.py`、`tests/application/conftest.py`、`tests/application/test_startup.py`、`tests/application/test_commands.py`、`tests/application/test_run_flow.py`、`tests/application/test_state_views.py`、`tests/application/test_shutdown.py`、`tests/behavior/ch14_matrix.yml`，以及矩阵分配给本任务替换的旧 Application、命令与 TUI 私有 seam 测试

**依赖任务：** T6、T10、T11

**参考资料定位：** Spec F1～F7、F25～F27、F65～F70、F93～F94、N1～N16、AC1、AC4、AC15、AC22；Plan“Application”“本地命令与 TUI”“Application 接入”。

**完成结果：** 新 Application 可从测试入口独立组装八个模块、接受用户输入、分流本地命令或 Run、输出有序终端事件、聚合只读状态并有序关闭；旧生产入口仍保持未切换。

**实施要点：**

1. 配置在产生外部效果前完成用户级/项目级严格校验和确定合成，一次报告同层可发现问题并全程脱敏。
2. Application 只协调生命周期和当前前台操作，不复制 Transcript、权限、Skill、Task、Workspace 或 usage 状态。
3. 未知/非法命令不调用 Model、不写 Transcript；状态命令只读，清屏只影响显示并清除 Skill 激活。
4. 独立的 terminal Adapter 依赖 Application Interface，负责多行、流式事件、取消、审批、usage 与 Task 控制；Application 核心不反向导入终端实现。启动中途失败和所有关闭路径按所有权逆序回收资源。

**验证：** 运行 `pytest tests/application -q`；覆盖新建/恢复/选择 Session、普通多轮、Plan/Act、命令分流、状态只读、前后台 Task、启动失败和关闭资源回收。

## T13：验证切换前就绪条件并冻结删除清单

**影响文件：** `tests/behavior/ch14_matrix.yml`、`tests/tools/verify_ch14_matrix.py`、`tests/tools/verify_core_imports.py`、`tests/architecture/test_core_dependencies.py`、`tests/manual/ch14_cutover_gate.md`

**依赖任务：** T1～T12

**参考资料定位：** Spec F1～F98、N1～N16、AC1～AC24；Plan“测试策略”“删除清单”“切换门槛”。

**完成结果：** 新核心已独立通过全部切换前验证，行为矩阵中的测试证据均可定位，状态所有权和依赖方向符合设计，T14 的精确删除清单被冻结；旧生产入口尚未改动，入口等价、旧核心删除和最终导入无残留不作为本任务的前置条件。

**实施要点：**

1. 汇总 T2～T12 已产生的 Interface、Application、属性、故障、压力和真实集成结果，不在本任务临时补建新的测试体系。
2. 复核 Plan 无外部效果、单请求无重试、Transcript 协议完整、旧数据不加载、普通路径无额外步骤、双 Worktree 隔离和关闭零遗留资源。
3. 通过导入审计证明新核心不依赖旧业务包，状态所有权与 `plan.md` 表格一致，并确认已获等价覆盖的旧私有 seam 测试已在所属任务删除。
4. 冻结 T14 要删除的旧模块、兼容路径、孤立测试与旧运行数据清单，同时把需保护的 Worktree 精确排除在自动删除范围外。

**验证：** 运行全部非 live 测试、`python tests/tools/verify_ch14_matrix.py` 和 `python tests/tools/verify_core_imports.py`；确认切换前就绪条件通过并生成精确删除清单后进入 T14，最终入口与删除条件留在 T14 验证。

## T14：接入主流程

**影响文件：** `artcode/cli.py`、`artcode/__main__.py`、`artcode/__init__.py`、`artcode/core/application.py`、`artcode/adapters/terminal.py`、`README.md`、`config.example.yml`、`pyproject.toml`；按 T13 清单删除旧 `artcode/agent/`、`artcode/background/`、`artcode/commands/`、`artcode/context_management/`、`artcode/conversation/`、`artcode/mcp/`、`artcode/permissions/`、`artcode/persistence/`、`artcode/prompting/`、`artcode/providers/`、`artcode/runtime/`、`artcode/sandbox/`、`artcode/security/`、`artcode/skills/`、`artcode/subagents/`、`artcode/tools/`、`artcode/tui/`、`artcode/worktrees/`、`artcode/bootstrap.py`、`artcode/config.py`、`artcode/errors.py`、`artcode/prompts.py`、`artcode/workspace.py` 及切换后失去调用方的孤立测试

**依赖任务：** T13

**参考资料定位：** Spec F2～F7、F65～F70、F93～F97、N2～N4、N11、N16、AC1、AC15、AC22～AC24；Plan“开发隔离与一次性切换”“删除清单”“切换门槛”。

**完成结果：** `python -m artcode` 与安装后的 `artcode` 命令同时进入唯一新 Application；仓库只保留一条生产路径，旧核心、重复状态、兼容读取、章节式产品文本、Provider 自动重试和失去调用方的浅转发模块全部删除。

**实施要点：**

1. 在一个切换阶段同时替换源码与安装入口，不引入 Feature Flag、双写、旧格式回退或长期兼容层。
2. 按 T13 冻结的清单删除旧业务实现、兼容路径和切换后失去调用方的孤立测试；旧私有 seam 测试应已在对应模块任务删除，T14 只审计残留。
3. 删除 `MAX_STREAM_ATTEMPTS`、重试循环及“首事件前成功重试”断言，保留单次传输失败直接报告且不污染 Transcript 的契约测试。
4. 清理旧运行数据时不得触碰普通用户文件；Worktree 只在可证明无成果时自动清理，否则保留并展示位置。

**验证：** 运行全部非 live 测试、`python tests/tools/verify_ch14_matrix.py`、`python tests/tools/verify_core_imports.py`、`python -m compileall -q artcode tests` 和项目构建；分别从源码入口与临时 wheel 安装入口执行等价启动、Run、Session 与退出路径。

## T15：端到端验证

**影响文件：** `tests/manual/ch14_acceptance.md`、`tests/manual/ch14_results.md`、`checklist.md`、`README.md`、`CONTEXT.md`、`docs/adr/0003-core-contract-freeze.md`

**依赖任务：** T14

**参考资料定位：** Spec AC1～AC25、N1～N16；Checklist 全部验收项；Plan“最终验收与冻结”“切换门槛”。

**完成结果：** 复跑 T2～T14 已建立的固定验收集合并汇总证据，完成 Application 人工关键路径和文档一致性核对；不在最终验收阶段临时设计新的功能或测试体系，领域语言与外部契约随后正式冻结。

**实施要点：**

1. 复跑已经在 T3、T4、T6 与 T11 建立的 Seatbelt/Git、DeepSeek、MCP 和双 Worktree 真实集成，不新增另一套重复 live 测试。
2. 从 Application 入口执行固定人工清单，覆盖普通对话、Plan/Act、文件与命令、Session 恢复、压缩、记忆、Skill、Subagent、Task、状态查询和关闭。
3. 逐项汇总全量测试、构建、临时安装、源码/安装入口等价和 T14 删除审计结果；环境阻塞与产品失败分别记载。
4. 确认代码、README、CONTEXT、Spec、Tasks、Checklist 和公开 Interface 一致后记录核心冻结 ADR。

**验证：** 运行 `pytest -q`，复跑 `tests/live/test_core_deepseek.py`、`tests/integration/test_core_mcp_stdio.py`、`tests/integration/test_core_mcp_http.py`、`tests/integration/test_core_seatbelt.py`、`tests/integration/test_core_parallel_worktrees.py`，再执行 `python -m compileall -q artcode tests`、项目构建和临时安装验证；按 `tests/manual/ch14_acceptance.md` 完成人工验收，确保 `checklist.md` 每一项都有可观测证据。

## 执行顺序

```text
T1 → T2 → T3 → T5 → T6
T1 → T4 ─────────────→ T6
T1 → T7
T2 + T4 + T5 + T7 → T8 → T9 → T10
T3 + T4 + T5 + T8 + T9 → T11
T6 + T10 + T11 → T12 → T13 → T14 → T15
```
