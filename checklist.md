# ch14：ArtCode 语义统一与破坏性整体重写 Checklist

> 机器可追溯映射见 `tests/behavior/ch14_matrix.yml`；完整运行结果见 `tests/manual/ch14_results.md`。

## A. 核心结构与切换

- [x] A01：公开核心精确包含 Application、Session、Agent、Model、Tool、Workspace、Skill、Subagent 八个 Interface 文件。（验证：架构测试与导入审计。）
- [x] A02：八个模块的状态所有权无重复，允许依赖图无环。（验证：`test_core_dependencies.py` 4 项。）
- [x] A03：新核心与私有实现不导入旧业务包或测试替身。（验证：T14 导入审计。）
- [x] A04：源码入口和 console script 使用同一 CLI/Application 路径。（验证：帮助文本逐字相同及两个新 Session `/exit` 黑盒测试。）
- [x] A05：旧核心包、旧顶层模块、兼容层和章节式生产入口已删除。（验证：T14 导入审计与 wheel 内容审计。）
- [x] A06：wheel 版本为 `0.3.0`，归档 85 个文件且旧核心残留为 0。（验证：zip 内容检查。）

## B. Model、Agent 与停止语义

- [x] B01：每次 Model Interface 调用只发起一次底层 HTTP 请求；首事件前传输错误不透明重试。（验证：四类传输异常的请求计数均为 1。）
- [x] B02：认证、网络、超时、上下文窗口、协议和 Thinking 不支持错误可区分且不泄露 API Key。（验证：故障矩阵。）
- [x] B03：Thinking 不生成 TextDelta；Tool 续接所需内容只进入不透明 Protocol Metadata。（验证：两轮 Tool 请求 payload。）
- [x] B04：Model 只报告 Provider 返回的 usage，不估算、不跨请求累计。（验证：Model 契约测试。）
- [x] B05：普通 Agent Run 连续执行 56 轮后自然结束，没有固定产品轮次上限。（验证：长工具链测试。）
- [x] B06：受控 Run 可显式设置正整数轮次上限；无 Role Fork 上限固定为 50，Role 上限范围为 1～100。（验证：Agent/Role 契约。）
- [x] B07：natural、limit、cancelled、model_failure、length、cannot_continue 六类 Stop Reason 可观察。（验证：Agent 契约与故障测试。）
- [x] B08：流中断或取消前显示的临时 Assistant 文本不提交 Transcript；length 文本提交并标记长度结束。（验证：Agent 契约。）
- [x] B09：同一响应的多个 Tool Request 以完整批次提交，结果顺序与请求顺序一致。（验证：属性测试与 Agent 集成。）

## C. Workspace、Tool 与权限

- [x] C01：文件读取默认最多展示 20000 字符；大型结果头尾预览各最多 4096 bytes，完整内容通过 `result:` 引用分段回读。（验证：Workspace 契约。）
- [x] C02：新文件创建缺失父目录；已有文件没有 `overwrite: true` 时拒绝；编辑旧文本匹配数不为 1 时零写入。（验证：Workspace 契约与原子故障测试。）
- [x] C03：父级跳转、Workspace 外绝对路径、敏感目录、外部符号链接和审批后 inode/父目录替换均被拒绝。（验证：契约、属性、故障测试。）
- [x] C04：相邻 observe Tool 并发执行；change、external、control 保持顺序；局部失败和单 Tool 超时不取消无关结果。（验证：批次时序测试。）
- [x] C05：Plan 目录只含内置 observe Tool；伪造 write、Shell、MCP 或 Subagent 调用在执行入口再次拒绝，审批不能解锁。（验证：Tool/MCP 契约。）
- [x] C06：权限顺序固定为硬约束、精确规则、Run/Shell 策略、人工审批。（验证：策略属性与四类审批测试。）
- [x] C07：`allow_once`、`deny_once`、`allow_always`、`deny_always` 四类决定可观察；长期规则只匹配精确 Tool 与目标。（验证：持久规则测试。）
- [x] C08：11 类危险命令家族在规则与审批前硬拒绝。（验证：参数化危险命令测试。）
- [x] C09：命令完成、超时、取消和 Application 关闭均回收整个进程组；输出超限时保留结果引用。（验证：真实子孙进程测试。）
- [x] C10：macOS Seatbelt 允许 Workspace 写入、阻止 Workspace 外写入和网络；缺失或自检失败时失败关闭。（验证：真实 Seatbelt 与故障测试。）

## D. MCP

- [x] D01：项目 Server 整体覆盖同名用户 Server，并在启动外部进程/连接前确认。（验证：MCP 契约。）
- [x] D02：stdio 与 Streamable HTTP 均使用真实 FastMCP Server 完成初始化、分页发现、调用与关闭。（验证：两个真实集成测试。）
- [x] D03：eager 暴露完整目录；lazy 初始激活数为 0，搜索激活后在后续 Run 保持可用。（验证：lazy 契约。）
- [x] D04：每次 MCP Tool 调用单独审批；Plan 中不暴露且不能伪造执行。（验证：MCP 契约。）
- [x] D05：单 Server 配置、连接、断线或调用失败不破坏其他 Server 和内置 Tool。（验证：MCP 故障测试。）
- [x] D06：文本与结构化结果进入受控内容；二进制只表示 type、MIME/name 等元数据，不展开原始数据。（验证：结果转换契约。）

## E. Session、Prompt、Summary 与记忆

- [x] E01：新格式只位于 `.artcode/ch14/sessions/`，不加载旧 `.artcode/sessions/`。（验证：Session 契约。）
- [x] E02：Transcript 使用校验和 JSONL 同步追加；写失败不进入内存权威状态。（验证：部分写入故障。）
- [x] E03：坏完整记录隔离且原档哈希不变；不完整尾部修复；坏 Tool exchange 回退最近安全前缀。（验证：恢复故障与集成测试。）
- [x] E04：同一 Session 只允许一个写锁；latest 跳过最近但被占用的 Session。（验证：双实例锁测试。）
- [x] E05：Tool exchange 单条记录包含全部请求、结果、调用前 Assistant 文本及不透明 metadata；取消补齐缺失结果。（验证：Session 契约。）
- [x] E06：Prompt 是不可变 Run 投影；后续 Transcript 修改不改变既有 Run lease。（验证：Prompt 契约。）
- [x] E07：指令、Notice、Summary、用户/项目记忆、Skill 与 Transcript 使用显式来源标签，内容采用受限编码而不能伪装来源。（验证：Prompt 边界测试。）
- [x] E08：Notice 在 preview/status 时不消费，只在真正 dispatch 时投递一次。（验证：重复 dispatch 与下一 Run 测试。）
- [x] E09：指令总预算为 64 KiB，include 最大 5 层；循环、越界、非 Markdown 和坏 UTF-8 可诊断。（验证：指令故障测试。）
- [x] E10：预算优先显示 Provider input usage；不可用时使用确定性字符估算并标记来源。（验证：跨 Run usage 测试。）
- [x] E11：Summary 只替代较早 Assistant/Tool 视图；所有 User 原文始终逐条、逐字、有序保留。（验证：属性测试。）
- [x] E12：自动、强制、紧急、手动压缩单次有界；失败保留旧状态；重复压缩把旧 Summary 作为下一次派生输入。（验证：上下文故障测试。）
- [x] E13：用户偏好与项目事实分别保存在人类可编辑 Markdown，`memory.index.md` 可重建。（验证：记忆故障测试。）
- [x] E14：只有 natural Run 安排记忆更新；更新串行，失败不阻塞下一项且不改变回复或 Transcript。（验证：并发计数和失败恢复。）
- [x] E15：恢复间隔达到 24 小时会生成一次外部环境复核 Notice。（验证：可控时钟恢复测试。）

## F. Skill

- [x] F01：来源优先级为项目、用户、内置、扩展，定义整体覆盖而不跨来源合并。（验证：四来源测试。）
- [x] F02：坏高优先级同名 Skill 阻断低优先级回退，不影响其他有效 Skill。（验证：刷新故障测试。）
- [x] F03：目录发现只读取 frontmatter；激活时才读取最新完整 SOP。（验证：发现后改写 SOP 测试。）
- [x] F04：自然语言与 `/skill` 激活共用同一状态所有者；`/clear` 清除激活但不改 Transcript。（验证：Skill/Application 测试。）
- [x] F05：多个已激活 Skill 的 Tool 集合取严格交集；未知 Tool 或不可用模型明确失败。（验证：属性与契约测试。）
- [x] F06：坏热更新保留当前 Session 最后有效版本，修复后新执行自动使用新版本。（验证：热更新故障测试。）
- [x] F07：Shared Skill 使用主 Session；Isolated Skill 使用临时 Transcript，只返回最终总结且不创建 Task/Worktree。（验证：Skill 集成。）

## G. Subagent、Task 与 Worktree

- [x] G01：统一 `agent` Tool 支持 definition/fork；definition 从干净 Transcript 开始，fork 的首次 Prompt 以前缀逐项等于父快照。（验证：Subagent 契约。）
- [x] G02：Role 来源整体覆盖；frontmatter 固定七字段；写/Shell Role 必须使用 Worktree；模型档位不可用时零 Model 调用。（验证：Role 契约。）
- [x] G03：子能力是父快照、Role allow/deny 与后台白名单交集，且移除 agent/Task/load_skill 递归控制能力。（验证：属性测试。）
- [x] G04：最多 4 个 Task 并发；其余排队；排队取消不创建 Model 或 Worktree。（验证：调度故障测试。）
- [x] G05：definition 前台阈值固定 120 秒；Ctrl+B/手动后台事件立即结束等待，同一 Task 状态、轮次、usage 与 Worktree 原地继续。（验证：终端控制与 30 秒测试阈值下即时切换测试。）
- [x] G06：Task ID 为 `task-` 加 8 位小写十六进制；列表/详情/取消只存在当前进程。（验证：Task 契约。）
- [x] G07：后台通知按完成顺序、每 Task 一次、结果最多 8000 Unicode 字符；完整结果保留详情。（验证：逆序完成与 8001 字符测试。）
- [x] G08：通知只在下一安全 Prompt 边界投递，包含状态、usage、结果和 handoff，不包含 Role SOP/子对话。（验证：Application agent Tool 黑盒测试。）
- [x] G09：入队时冻结完整 Git 提交和初始化规则；主 Workspace 未提交内容不复制。（验证：真实 Git 契约。）
- [x] G10：自动名为 `agent-<8 hex>`，分支为 `worktree-agent-<8 hex>`；名称最多 64 bytes且每段为小写安全标识。（验证：Worktree Interface。）
- [x] G11：默认复制 ignored 的 `permissions.local.yml`、`.artcode/instructions.md`，只读链接 ignored `.venv`，并设置 Worktree 专属 `.githooks`。（验证：真实初始化测试。）
- [x] G12：自定义初始化规则只接受 version/copy/symlink/hooks；路径为无 glob、无遍历的相对字面值。（验证：规则解析与冻结测试。）
- [x] G13：主 Workspace、兄弟 Worktree 和元数据作用域相互隔离；子 Seatbelt 不能读取主根，但可读取自身副本。（验证：真实 Seatbelt/双 Worktree。）
- [x] G14：无文件变化且无新增提交的 Worktree 自动清理；未提交文件、新增本地提交、检查错误或取消后的成果保留。（验证：契约与故障测试。）
- [x] G15：新进程能重新识别保留 Worktree；启动扫描一次，之后每 60 分钟扫描，创建满 24 小时才进入安全清理候选。（验证：重启识别、可控时钟与 Application 生命周期。）
- [x] G16：危险丢弃要求 task/path/branch 精确确认，仅从主 Application `/worktree-discard` 可达；模型 Tool 无强制丢弃入口。（验证：Workspace 契约、Tool Schema 与 Application 命令。）
- [x] G17：系统不自动 merge、rebase、cherry-pick、push、创建远端分支或 PR。（验证：Git 命令路径与 handoff 测试。）

## H. Application、TUI 与端到端

- [x] H01：配置在任何 Session 写入、MCP 连接或进程效果前校验；同层多个问题一次报告。（验证：Application 启动故障。）
- [x] H02：未知/非法本地命令不调用 Model、不写 Transcript。（验证：Application 命令测试。）
- [x] H03：普通文本、Plan/Act、压缩、权限、Sandbox、Skill、Task、Session、Memory、Worktree、状态和退出命令均从唯一 Application 分流。（验证：Application 黑盒。）
- [x] H04：终端启用多行输入，TextOutput 在 Model 完成前流式到达；Ctrl+C 取消当前 Run，Ctrl+B 转后台。（验证：流式时序与 prompt_toolkit Keys 测试。）
- [x] H05：存在活动 Task 时 `/exit` 提供等待、取消、返回三个分支，不静默退出。（验证：Application 分支逻辑与 Task 生命周期测试。）
- [x] H06：状态查询基于不可变脱敏快照，不消费 Notice、不改变权限或执行顺序。（验证：状态视图测试。）
- [x] H07：关闭顺序回收 Task、Memory worker、MCP、Model、进程、Session 锁和周期清理任务；成果 Worktree 继续保留。（验证：关闭与取消故障测试。）
- [x] H08：完整行为矩阵精确覆盖 F1–F98、N1–N16、AC1–AC25 共 139 项。（验证：矩阵 T14/T15 校验。）
- [x] H09：切换后全量非 live 测试、编译、构建、wheel 内容审计与全新虚拟环境安装通过。（证据：`ch14_results.md`。）
- [x] H10：真实 Provider 测试已执行；外部服务返回 HTTP 500 `Grok requires Postgres (DATABASE_URL)`，明确记录为外部服务阻塞，未以 Fake 冒充成功。（证据：`ch14_results.md`。）
- [x] E2E-01：真实 Session→Agent→Model→Tool→Workspace 两轮 Tool 协议完成并提交。（验证：`test_core_agent_run.py`。）
- [x] E2E-02：两个写 Subagent 基于同一冻结提交修改各自 Worktree 同名文件，主文件字节保持不变。（验证：`test_core_parallel_worktrees.py`。）
- [x] E2E-03：源码入口、console script 与全新 wheel 安装入口均创建新格式 Session 并正常 `/exit`。（验证：入口黑盒与临时安装记录。）
