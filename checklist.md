# ch13：子 Agent 与 Worktree 隔离 Checklist

> 本清单在实现阶段逐项勾选。每一项必须由测试、模型请求捕获、真实 Git 状态或可见 TUI 行为证明；仅阅读代码不能视为通过。

> 证据：tests/unit/test_agent_tool_contract.py、test_foreground_timeout.py、tests/fault/test_subagent_failures.py、tests/integration/test_subagent_main_flow.py、tests/unit/test_subagent_policy_permissions.py
## A. 统一 Agent 工具与创建分流

- [x] A01：主 Agent 注册且只注册一个名为 `agent` 的委派工具，不为定义式和 Fork 式分别注册不同工具。（验证：捕获普通、Plan 和 Do 请求的工具定义，`agent` 各出现一次且 JSON Schema 完全相同。）
- [x] A02：`agent` 工具只接受 `type`、`task`、`role`、`background` 四个字段，拒绝任何未知字段；`type` 和 `task` 必填。（验证：逐项缺字段、增未知字段并检查结构化参数错误，子任务创建数保持为 0。）
- [x] A03：`type` 只允许 `definition` 或 `fork`；`task` 去除首尾空白后长度必须为 1～20000 个 Unicode 字符。（验证：空白、20000 字符、20001 字符和非法类型边界测试通过。）
- [x] A04：`type: definition` 必须提供合法 `role`；`background` 省略时为前台等待，显式 `true` 时直接进入后台。（验证：四种字段组合精确比较返回结果和任务状态。）
- [x] A05：`type: fork` 的 `role` 可省略；它无条件在后台运行，`background` 省略或为 `true` 均合法，显式 `false` 被拒绝而不是悄悄改写。（验证：捕获参数矩阵及后台任务创建数。）
- [x] A06：Agent 工具不接受模型、最大轮次、权限模式、Worktree 名称或任意工具列表覆盖，这些值只能来自父快照、角色和系统配置。（验证：传入对应未知字段均失败，运行配置不变。）
- [x] A07：每个成功创建的任务 ID 采用 `task-` 加 8 位小写十六进制字符；同一会话中 ID 唯一。（验证：批量创建任务并匹配格式、集合大小和碰撞重试路径。）
- [x] A08：前台定义式任务在转后台前自然完成时，Agent 工具直接返回最终文本、停止原因、轮次、累计 Token 和 Worktree 交接摘要，不额外生成一个重复通知。（验证：短任务完成后比较工具结果、通知收件箱和任务详情。）
- [x] A09：显式后台、自动后台、手动后台和 Fork 调用立即向父 Agent 返回任务 ID 与当前状态，父 Agent 可以继续调用其他工具。（验证：脚本化 Provider 在收到任务 ID 后继续执行另一个工具并自然结束。）
- [x] A10：角色解析、模型映射、权限求交、Git 基准捕获或 Worktree 预检失败时，不发送子 Agent 的首次模型请求。（验证：对每个失败点记录 Provider 调用数为 0。）
- [x] A11：Plan 模式可以委派只读子任务，但父模式的只读上限继续生效；任何写或 Shell 能力从子 Agent 有效工具集中消失。（验证：Plan 中分别启动读角色与写角色，检查请求工具集合和伪造调用结果。）
- [x] A12：只有主 Agent 调用来源能通过 `agent` 工具的运行时来源校验；子 Agent 即使伪造同名工具调用也得到拒绝且不会创建任务。（验证：绕过模型可见列表直接向执行器注入调用，任务计数不变。）

> 证据：tests/unit/test_subagent_roles.py、test_subagent_role_validation.py、test_subagent_policy_permissions.py、tests/unit/test_subagent_round_limits.py
## B. 角色文件、来源与模型映射

- [x] B01：项目角色目录固定为 `<workspace>/.artcode/agents/`，用户角色目录固定为 `~/.artcode/agents/`，内置角色位于包内 `artcode/subagents/builtin/`，插件角色位于 `~/.artcode/plugins/<插件名>/agents/`。（验证：四处各放一个角色，目录快照记录正确来源。）
- [x] B02：每个角色是角色目录根下的单个 `*.md` 文件；不递归扫描任意子目录，符号链接文件和符号链接目录均不加载。（验证：普通文件、嵌套文件和两类符号链接发现测试通过。）
- [x] B03：frontmatter 只接受 `name`、`description`、`tools`、`model`、`max_rounds`、`permission_mode`、`isolation` 七个顶层字段，七个字段全部必填。（验证：逐项缺失和加入未知字段均产生带路径诊断。）
- [x] B04：`name` 必须匹配 `^[a-z][a-z0-9-]{0,31}$`，并与 Markdown 文件名去掉扩展名后的值完全一致。（验证：大小写、下划线、空白、33 字符和文件名不一致矩阵通过。）
- [x] B05：`description` 必须是 1～200 个 Unicode 字符的单行非空文本，不允许换行。（验证：长度和换行边界解析测试通过。）
- [x] B06：`tools` 必须是只含 `allow` 与 `deny` 的对象；两者都是无重复工具名的列表，同一工具不能同时出现于两表。（验证：类型错误、重复、交叉和未知子字段均被拒绝。）
- [x] B07：`tools.allow: []` 表示不授予任何普通工具，不表示“允许全部”；`tools.deny: []` 表示没有角色级额外禁止。（验证：捕获空白名单角色的首次请求，只包含零个普通工具。）
- [x] B08：角色只能引用已经注册且声明可供子 Agent 使用的工具；`agent`、任务管理工具、交互式工具、`load_skill` 和默认 MCP 工具出现在白名单时，该角色不可用。（验证：逐个写入受禁工具并检查角色诊断与 Provider 零调用。）
- [x] B09：`model` 只允许 `inherit`、`haiku`、`sonnet`、`opus`；后三者从用户配置 `agents.models` 的同名键映射到真实模型 ID。（验证：四种合法值、非法值和三个映射请求 payload 测试通过。）
- [x] B10：角色选择的模型档位没有非空映射时，该角色不可用；系统不猜测模型 ID，也不退回父模型。（验证：删除映射后启动失败，Provider 调用数为 0。）
- [x] B11：`max_rounds` 必须是 1～100 的整数且不能是布尔值；运行达到该值后状态为 `max_rounds`。（验证：0、1、100、101、布尔值解析及精确轮次停止测试通过。）
- [x] B12：无角色 Fork 的最大轮次固定为 50；Fork 叠加角色时使用角色的 `max_rounds`，Agent 工具不能覆盖。（验证：脚本化 Provider 运行到两个边界并检查停止轮数。）
- [x] B13：`permission_mode` 只允许 `default`、`edit`、`full`，实际权限模式取父 Agent 模式与角色模式中更严格的一方。（验证：九种父子组合得到预期模式，角色从不扩大权限。）
- [x] B14：`isolation` 只允许 `none` 或 `worktree`；白名单中只要含 `write` 或 `shell` 效果工具，角色就必须写 `isolation: worktree`，否则角色不可用。（验证：读、写、Shell 三类描述符组合解析测试通过。）
- [x] B15：只读角色可以主动声明 `isolation: worktree`，此时仍创建 Worktree；`isolation: none` 的纯只读角色不创建。（验证：两个角色运行后比较任务 Worktree 字段与 Git worktree 列表。）
- [x] B16：frontmatter 结束后的全部 Markdown 正文原样成为角色系统提示，不执行模板替换；它在子 Agent 压缩或多轮执行后继续存在。（验证：正文植入模板符号与唯一标记，捕获首次及压缩后请求。）
- [x] B17：同名角色按项目 > 用户 > 内置 > 插件整体覆盖，不跨来源合并字段或正文。（验证：四份定义使用互斥值，目录只返回项目完整版本；逐层删除后顺序降级。）
- [x] B18：最高优先级同名角色无效时，低优先级同名角色被遮蔽且不会静默启用；其他不同名有效角色仍可使用。（验证：一坏一低优先级同名加另一好角色，分别检查目录和启动结果。）
- [x] B19：同一来源出现两个同名角色时，该名字不可用且诊断同时列出冲突路径，不依赖扫描顺序选一个。（验证：交换文件创建顺序，结果保持一致。）
- [x] B20：每次处理 `agent` 调用前刷新角色目录；新任务使用最新有效快照，已经排队或运行的任务继续使用入队时版本。（验证：排队后修改正文，比较两个任务请求中的唯一标记。）
- [x] B21：用户配置 `agents` 只接受 `models` 与 `background_tools`；`models` 只接受 `haiku`、`sonnet`、`opus`，未知键在启动阶段被拒绝。（验证：逐层注入未知键并检查启动前配置错误。）

> 证据：tests/integration/test_subagent_main_flow.py、tests/unit/test_subagent_fork_freeze.py、test_subagent_state_isolation.py、test_subagent_prompt_cache.py、test_file_read_cache.py、tests/fault/test_subagent_concurrency.py、tests/live/test_subagent_fork_cache_e2e.py
## C. 对话、运行时状态与提示缓存

- [x] C01：定义式子 Agent 的 Conversation 只含固定基础系统提示、按自身绝对路径加载的用户/项目指令、角色正文、Worktree 说明和当前任务，不包含任何父 User、Assistant 或 Tool 消息。（验证：父会话植入各角色唯一标记，扫描子首次请求为零命中。）
- [x] C02：定义式任务以一条新的 User 消息承载 `task` 原文；角色正文保持 System 身份，不能与任务拼成可被任务文本覆盖的同一消息。（验证：捕获消息角色、顺序和逐字内容。）
- [x] C03：Fork 继承的是父 Agent 当前模型请求已经使用的完整消息与工具快照，不复制尚未完成的 `agent` Assistant 工具调用或待写入的工具结果。（验证：在 Agent 工具执行点比较父 PreparedModelRequest 与子快照，协议中没有悬空工具调用。）
- [x] C04：Fork 的首次请求以父消息和父工具定义作为完全相同的前缀，工具顺序不重排；可选角色、Worktree 说明和新任务只追加在该前缀之后。（验证：对消息与工具做逐字前缀比较和哈希比较。）
- [x] C05：Fork 叠加角色时只新增角色系统提示并收紧模型/工具/权限；不重写父系统提示、历史消息或父工具 Schema。（验证：前后请求差异只出现在允许的后缀、模型字段和工具删减集合。）
- [x] C06：Fork 入队后父会话继续新增消息、切换权限或加载 Skill，不改变已经冻结的子快照。（验证：排队期间修改三类父状态，再启动子任务并比较入队哈希。）
- [x] C07：每个子 Agent 分别创建 Conversation、PermissionState、权限事件列表、ContextManager、Artifact Store、PlanMemory、文件读取缓存、轮次计数和 Token 累加器。（验证：对象身份断言和并发写入后状态快照互不相等。）
- [x] C08：Provider、工具实现、MCP 管理器、底层文件系统服务和可选 Hook 引擎由子 Agent 复用同一实例；不存在第二套 Provider 客户端或工具注册表。（验证：依赖身份断言、Provider 构造计数和资源关闭次数。）
- [x] C09：主工作区与每个 Worktree 分别创建路径策略和 Seatbelt 会话；任一 Seatbelt 的允许写根只有所属工作目录，共享依赖目标只读。（验证：主、子、兄弟 Worktree 的读写矩阵和 Seatbelt profile 检查通过。）
- [x] C10：文件缓存、系统提示、项目指令和项目记忆缓存均以规范化绝对路径为键；两个 Worktree 中相同相对路径不会命中同一项目缓存条目。（验证：同名文件写入不同内容，检查缓存键和读取结果。）
- [x] C11：任何主流程、工具、MCP 适配和子 Agent 逻辑都不调用 `os.chdir()`；运行前后 `Path.cwd()` 保持不变。（验证：安装禁止 chdir 探针并并发运行主、子文件与 Shell 工具。）
- [x] C12：子 Agent 不绑定主 Session JSONL 观察者，也不向长期记忆更新队列提交其内部轮次；主会话只持久化 Agent 工具结果和精简任务通知。（验证：扫描 JSONL、Memory 队列与子工具独有标记。）
- [x] C13：每一轮 Token 用量累加到当前任务，分别保留 prompt、completion、total、cached 和 cache miss；缺失字段保持未知，不以本地估算伪造。（验证：多轮混合 usage Fixture 的任务详情精确匹配。）
- [x] C14：Fork 详情中的缓存命中只展示 Provider 返回的 `cached_tokens`/`cache_miss_tokens`；没有返回时显示“不可用”，不宣称命中缓存。（验证：有 usage 与无 usage 两种真实 payload 展示测试。）
- [x] C15：Fork 首次请求在未超过上下文强制阈值时不预先压缩；确实超过阈值时使用子 Agent 自己的压缩状态，并在任务详情标记 `cache_prefix_preserved: false`。（验证：阈值两侧请求捕获和任务字段检查。）

> 证据：tests/unit/test_subagent_policy_permissions.py、tests/property/test_subagent_capabilities.py、tests/unit/test_subagent_role_validation.py
## D. 工具过滤与非交互权限

- [x] D01：六个现有内置工具 `read_file`、`write_file`、`edit_file`、`run_command`、`find_files`、`search_text` 显式声明可供子 Agent 使用；系统工具和 MCP 工具默认不声明。（验证：注册表描述符快照精确比较。）
- [x] D02：`agents.background_tools` 省略时默认恰为上述六个名字；存在时必须是无重复的已注册“子 Agent 安全工具”列表，并只能收窄默认集合。（验证：缺省、子集、重复、未知、MCP 和系统工具配置矩阵通过。）
- [x] D03：所有子 Agent 从启动起就使用后台安全集合，即使当前以前台等待；前台转后台前后模型可见工具和实际执行能力不变化。（验证：切换前后请求工具 Schema 哈希一致。）
- [x] D04：定义式有效工具集合是父模式上限、全局允许、后台安全集合、角色 allow 减去角色 deny 的交集。（验证：构造互斥集合并精确比较最终工具名。）
- [x] D05：无角色 Fork 的有效工具集合是入队时父工具快照与全局/后台限制的交集；Fork 叠加角色后再与角色限制求交。（验证：两条 Fork 路径捕获精确集合。）
- [x] D06：模型请求过滤与 ToolExecutionService 运行时过滤各自独立生效；伪造未展示工具调用时工具实现调用数为 0。（验证：直接注入 `agent`、任务工具、MCP 和角色 deny 工具。）
- [x] D07：任何子 Agent 都看不到且不能执行 `agent`、`task_list`、`task_get`、`task_cancel`、`load_skill` 或要求用户交互的工具。（验证：请求集合扫描加运行时伪造调用矩阵。）
- [x] D08：每个子 Agent 使用新的权限追踪器，不继承父 Agent 的“仅本次允许/拒绝”；用户级、项目级和本地永久规则仍参与判断。（验证：父一次性允许与永久允许两组场景比较子决策。）
- [x] D09：角色权限模式只能收紧父模式；Plan 限制、危险命令拒绝、敏感路径和 Seatbelt 限制始终高于角色与永久允许规则。（验证：尝试以 `full` 角色和允许规则越过四类高层限制，全部失败。）
- [x] D10：子 Agent 中权限结果为 `ask` 时不打开 TUI 审批，直接返回错误码 `approval_required_in_subagent` 给子 Agent 继续推理。（验证：记录审批端口调用数为 0，下一轮模型仍收到工具错误。）
- [x] D11：MCP 工具即使通过伪造调用到达权限层，也因需要逐次人工确认而自动拒绝；不会复用父 Agent 曾经做出的 MCP 确认。（验证：父先确认一次，再由子调用，MCP Server 调用数不增加。）
- [x] D12：每次允许、规则拒绝、模式拒绝、自动拒绝和内部权限错误都记录任务 ID、工具名、目标摘要、决定来源与时间，不记录秘密原文。（验证：权限事件字段与秘密探针检查。）
- [x] D13：角色白名单或用户配置不能恢复全局禁用能力，角色黑名单与任何其他层冲突时始终采用更严格结果。（验证：属性测试随机生成策略集合，结果永不超过每个上限。）
- [x] D14：有效集合含 `write` 或 `shell` 效果时，无角色 Fork 自动要求 Worktree；只有纯 `read` 集合且角色未强制隔离时才允许在主 Workspace 的只读作用域运行。（验证：描述符效果组合与 Worktree 创建计数矩阵。）

> 证据：tests/unit/test_background_manager.py、test_background_state_machine.py、test_task_notifications.py、test_tui_background_controls.py、test_foreground_timeout.py
## E. 后台任务、通知与终端表现

- [x] E01：任务状态只允许 `queued`、`running`、`completed`、`failed`、`max_rounds`、`cancelled`，且状态只能按批准的单向转换发生。（验证：状态机合法/非法转换测试。）
- [x] E02：后台任务最大并发数固定为 4；第 5 个任务保持 `queued`，前四个任一结束后按入队顺序启动。（验证：阻塞 Runner 创建五个任务并检查时间序列。）
- [x] E03：Fork 和 `background: true` 的定义式任务完成参数校验、基准冻结和入队后即返回任务 ID，不等待 Worktree 创建或首次模型响应。（验证：阻塞 Git/Provider，父 Agent 仍先收到任务 ID。）
- [x] E04：前台定义式任务从 Agent 工具调用开始等待满 120 秒仍未完成时自动停止等待并返回任务 ID；该子任务本身不中断、不重启。（验证：可控时钟推进到 119.999 秒和 120 秒，比较任务对象身份和请求数。）
- [x] E05：前台子 Agent 运行期间按 `Ctrl+B` 可手动停止等待并进入后台；快捷键不被当作输入文本，也不触发 Ctrl+C 取消。（验证：真实 prompt_toolkit 键盘事件测试与可见输出快照。）
- [x] E06：自动或手动转后台后，已产生的消息、权限事件、轮次、Token、文件和 Worktree 路径全部延续，不从零开始。（验证：切换前后深快照及 Provider 序号连续。）
- [x] E07：本地命令固定为 `/tasks`、`/task <task-id>`、`/task-cancel <task-id>`；模型任务工具固定为 `task_list`、`task_get`、`task_cancel`。（验证：命令帮助、参数解析和工具 Schema 快照。）
- [x] E08：任务列表至少显示 ID、类型、角色、状态、前台/后台、已运行时间和 Worktree 是否保留；详情另显示完整结果、轮次、用量、权限事件、基准、分支、路径和 Git 交接状态。（验证：记录型 Renderer 对完整/缺失字段快照。）
- [x] E09：取消排队任务不会创建 Worktree 或调用 Provider；取消运行任务只取消目标 Runner，父 Agent 和其他任务继续工作。（验证：排队与运行取消的资源和调用计数。）
- [x] E10：取消不回滚已经完成的写文件或 Git 提交，取消后的 Worktree 仍执行与正常结束相同的成果保护判断。（验证：写入后阻塞并取消，文件和保留状态可见。）
- [x] E11：后台结果按完成序号投递，而不是按入队顺序；同一任务最多生成一条完成通知。（验证：逆序完成三个任务并检查通知序列和去重。）
- [x] E12：通知使用 `<task-notification>` 边界并包含任务 ID、状态、精简结论、累计用量和 Worktree 交接摘要；不含完整子对话、推理文本或工具轨迹。（验证：子过程植入唯一标记并扫描父请求与 Session。）
- [x] E13：通知中的最终文本最多 8000 个 Unicode 字符；更长结果在通知中明确标为截断，任务详情保留完整原文。（验证：生成 8000/8001 字符结果并逐字比较详情。）
- [x] E14：任务完成时如果父模型仍在流式响应或工具批次尚未写完，通知只进入收件箱，在下一次安全模型请求前消费。（验证：控制并发时序，正在发送的 Provider payload 哈希保持不变。）
- [x] E15：正常退出时存在活动任务，TUI 列出任务并提供“等待全部完成”“取消后退出”“返回 ArtCode”三个选择，不静默结束进程。（验证：三个分支的真实 Runtime 流程和资源状态。）
- [x] E16：EOF、SIGTERM 或应用异常不尝试跨会话恢复后台任务；已经创建的 Worktree 和元数据保留，下一次启动可识别并展示遗留项。（验证：强制终止测试后重启，任务未复活且目录可诊断。）
- [x] E17：任务详情仅在当前 ArtCode 进程内保存，退出后不写入跨会话任务数据库或恢复队列。（验证：退出前后扫描持久目录，只有既有 Session 精简通知和 Worktree 元数据。）

> 证据：tests/unit/test_worktree_lifecycle_contract.py、test_worktree_manager.py、test_worktree_discard.py、tests/property/test_worktree_paths.py、tests/fault/test_worktree_cleanup_failures.py、tests/integration/test_subagent_seatbelt_isolation.py、tests/live/test_subagent_worktree_e2e.py
## F. Worktree 命名、创建与环境初始化

- [x] F01：系统托管根固定为 `<workspace>/.artcode/worktrees/`，仓库 `.gitignore` 明确忽略 `.artcode/worktrees/` 和本地 `permissions.local.yml`。（验证：`git check-ignore` 对两者成功，主工作区 `git status` 不出现托管内容。）
- [x] F02：自动目录名固定为 `agent-<8 位小写十六进制>`，自动分支名固定为 `worktree-agent-<同一组 8 位十六进制>`；手动/恢复名称对应分支为 `worktree-<名称>` 并保留其中的 `/`。（验证：批量创建并精确比较目录名、分支名、嵌套映射和唯一性。）
- [x] F03：手动/恢复名称的 UTF-8 总长度不超过 64 个字符，可用 `/` 嵌套；每段必须匹配 `^[a-z0-9][a-z0-9._-]{0,31}$`。（验证：整体长度、段长度、大小写、中文和边界字符矩阵。）
- [x] F04：空名、空段、`.`、`..`、绝对路径、反斜杠、NUL/控制字符、前导 `~` 以及解析后逃离托管根的名称全部在文件或 Git 操作前拒绝。（验证：恶意语料测试的文件系统/Git 调用数均为 0。）
- [x] F05：托管根、候选父目录、目标目录或归属元数据路径任一是符号链接时拒绝创建、恢复和删除。（验证：四个位置的符号链接攻击矩阵，外部哨兵文件哈希不变。）
- [x] F06：任务入队时用 `git rev-parse HEAD` 捕获完整提交 ID；排队期间主分支新增提交不改变该任务基准。（验证：排队前后提交并比较 Worktree HEAD。）
- [x] F07：主工作区有已跟踪修改、未跟踪文件或暂存修改时仍可创建 Worktree，但这些内容不被复制，任务详情明确显示“基准不含主工作区未提交修改”。（验证：三类脏状态下比较主目录与子目录文件哈希。）
- [x] F08：当前目录不是 Git 仓库、仓库没有首个提交、基准提交消失、分支名冲突或 Git 不可执行时，任务以 `failed` 结束且不在主目录运行。（验证：五类真实 Git 失败矩阵。）
- [x] F09：新建使用参数数组调用 Git 并传入显式 cwd，不通过 Shell 拼接模型文本；创建后 Worktree HEAD、分支和任务元数据相互匹配。（验证：进程调用捕获和真实 `git worktree list --porcelain`。）
- [x] F10：归属元数据存放在托管根的系统元数据区域而不写进子分支内容，采用原子写和仅当前用户可读写权限。（验证：子 `git status` 干净、元数据权限和写入故障测试。）
- [x] F11：目标目录已存在时先只读解析 `.git` 指针和归属元数据；仓库、公共 Git 目录、分支、基准和任务全部匹配才快速恢复，整个快速恢复路径不启动 Git 子进程。（验证：Git 进程禁用后合法恢复仍成功。）
- [x] F12：已有目录任一归属字段不匹配、元数据损坏、`.git` 缺失或目录含未知普通文件时拒绝复用，不覆盖、不清空、不接管。（验证：故障矩阵前后目录树哈希不变。）
- [x] F13：项目初始化规则文件固定为 `<workspace>/.artcode/worktree.yml`，只接受 `version`、`copy`、`symlink`、`hooks`；`version` 必须为 `1`。（验证：合法样例、未知字段、缺失/错误版本解析测试。）
- [x] F14：没有规则文件时，系统复制存在且已忽略的 `permissions.local.yml` 与 `.artcode/instructions.md`，软链接存在且已忽略的 `.venv/`，并在 Worktree 中存在 `.githooks/` 时使用它作为 Hooks 目录。（验证：四项分别存在/缺失的初始化矩阵。）
- [x] F15：规则文件存在时，`copy` 和 `symlink` 是无重复的相对字面路径列表，不支持 glob；`hooks` 是相对目录或 `null`，规则值在任务入队时冻结。（验证：类型、重复、glob、绝对/遍历路径及排队后修改规则测试。）
- [x] F16：`copy` 只复制主工作区中被 Git 忽略、非符号链接且位于项目内的文件或目录；声明项缺失、未忽略、目标已存在或越界时初始化失败，不覆盖 Worktree 内容。（验证：五类来源和目标矩阵。）
- [x] F17：复制使用临时目标和原子替换，保留普通文件执行位；中途失败不留下半文件或临时目录。（验证：文件/目录复制阶段故障注入和目录快照。）
- [x] F18：`symlink` 只接受主工作区内被 Git 忽略的真实目录，目标必须在 Worktree 内原本不存在；子 Agent 可以读取链接内容，但文件工具、Shell 与 Seatbelt 均不能写入链接目标。（验证：合法依赖、文件源、越界源、写入尝试和外部哈希矩阵。）
- [x] F19：`hooks` 目录必须在初始化后的 Worktree 内存在且不是符号链接；系统使用 Worktree 专属 Git 配置设置 `core.hooksPath`，不改变主工作区和兄弟 Worktree 的值。（验证：三个工作目录分别读取配置。）
- [x] F20：环境初始化任何阶段失败，只回滚本次新建且可证明无成果的系统 Worktree；既有快速恢复目录、未知目录和主工作区内容保持不变。（验证：逐阶段故障注入与前后树哈希。）
- [x] F21：主 Agent 的普通文件工具、Shell 和 Seatbelt 不能访问 `.artcode/worktrees/`；每个子 Agent 也不能访问主根、元数据区或兄弟 Worktree，只有内部 Worktree 管理器能操作托管根。（验证：主/子/兄弟/管理器四方读写矩阵。）
- [x] F22：所有工具以各自作用域的绝对 cwd 执行；用户给 `run_command.cwd` 时只能选择当前 Worktree 内子目录，`..` 或绝对跨界路径被拒绝。（验证：嵌套合法目录和五类越界路径测试。）

> 证据：tests/unit/test_worktree_lifecycle_contract.py、test_worktree_discard.py、tests/fault/test_worktree_cleanup_failures.py、tests/unit/test_task_notifications.py
## G. Worktree 退出保护、清理与 Git 交接

- [x] G01：退出状态同时检查已跟踪修改、暂存修改、未跟踪非忽略文件、相对基准新增提交、上游和远端可达性，不能只依赖单一 `git status --porcelain`。（验证：每种状态单独及组合构造，交接摘要精确分类。）
- [x] G02：任务完成后既无文件变化又无相对基准新增提交的系统临时 Worktree 自动删除，并删除其无成果系统分支和归属元数据。（验证：完成前后 `git worktree list`、分支列表和元数据目录。）
- [x] G03：存在未提交、已暂存或未跟踪非忽略文件时默认保留 Worktree；任务结果显示路径、分支和各类文件数量。（验证：三类脏状态结果快照和目录存在性。）
- [x] G04：只要存在相对基准新增提交，任务刚结束时就保留 Worktree 供审查，无论提交是否已推送。（验证：未推送与已推送两个分支均保留。）
- [x] G05：没有上游、上游不存在或仍有任一提交只存在本地时，交接状态固定为“未推送”，任何自动清理都拒绝删除。（验证：三种 Git 拓扑和目录存在性。）
- [x] G06：取消、达到轮次上限、Provider 错误和应用退出对 Worktree 使用与自然完成相同的保护判断，不因停止原因降低安全标准。（验证：四类停止原因乘以干净/脏状态矩阵。）
- [x] G07：用户在 ArtCode 外手动创建、没有系统归属元数据的 Git Worktree 永不进入自动清理候选。（验证：真实手动 Worktree 超过过期时间后仍存在。）
- [x] G08：过期扫描在应用启动时执行一次，长时间运行时每 60 分钟执行一次；系统临时 Worktree 创建满 24 小时才算过期。（验证：可控时钟的 23:59:59、24:00:00 和周期边界。）
- [x] G09：过期清理依次通过三层过滤：路径和系统归属合法、没有活动任务/租约、Git 成果安全；任一层失败即保留并记录原因。（验证：每层单独失败的候选目录均不被删除。）
- [x] G10：过期且无变化/无新增提交的系统 Worktree 可删除 Worktree、系统分支和元数据；干净且全部新增提交已被远端引用的 Worktree 可删除目录和元数据但保留本地分支。（验证：两类安全拓扑的分支保留差异。）
- [x] G11：清理 Git 检查超时、命令失败、权限错误、元数据竞态或删除竞态时默认保留目标，不使用强制递归删除兜底。（验证：五类故障注入，目标树哈希不变或仅出现明确安全的已完成步骤。）
- [x] G12：模型和子 Agent 没有“强制丢弃成果”入口；只有主 TUI 的直接用户操作可以确认删除含未提交修改或未推送提交的 Worktree。（验证：模型工具 Schema 无该字段，伪造调用失败，TUI 路径可达。）
- [x] G13：危险删除确认明确展示不可恢复的文件数、提交数、路径和分支；用户取消后零删除，确认后只删除精确目标。（验证：记录型 Renderer 与相邻哨兵 Worktree 哈希。）
- [x] G14：任务详情和通知中的 Git 交接摘要至少包含基准提交、工作分支、Worktree 路径、是否保留、脏文件分类、新增提交数、上游和推送状态。（验证：无变化、脏文件、未推送、已推送四种快照。）
- [x] G15：系统不自动 merge、rebase、cherry-pick、push、创建远端分支或 Pull Request；这些动作只在后续主 Agent/用户明确要求且权限允许时发生。（验证：监控所有 Git argv，子任务生命周期中相关子命令计数为 0。）
- [x] G16：正常自动清理后主仓库 `git worktree prune --dry-run` 无本章制造的陈旧记录；保留 Worktree 仍能独立执行 `git status` 和查看提交。（验证：真实 Git 生命周期检查。）

> 证据：全量 980+ 非 live 测试、tests/property/*、tests/fault/*、tests/live/*、python -m compileall、python -m build
## H. 兼容性、自动测试与端到端验收

- [x] H01：不调用 `agent` 工具时，普通对话、Plan/Do、Skill、MCP、权限、Session、Memory、上下文压缩和现有文件/Shell 工具测试全部保持通过。（验证：运行现有单元与集成测试集并保存结果。）
- [x] H02：角色、Worktree、后台和通知模块都能用 Fake Provider、Fake 时钟和临时 Git 仓库独立测试，不要求真实网络才能验证安全边界。（验证：对应测试目录离线运行通过。）
- [x] H03：路径名称和工具能力交集都有属性测试；随机输入不能逃离托管根或产生超出父上限的能力。（验证：Property 测试执行非零用例且通过。）
- [x] H04：角色解析、Git 创建、复制、软链接、Hooks、Provider、工具、通知、取消、退出和清理均有故障注入测试，单任务失败不破坏父会话与其他任务。（验证：故障测试矩阵及状态快照通过。）
- [x] H05：两个定义式写任务基于同一 HEAD 并行修改各自 Worktree 中的同名文件；两个结果互不覆盖，主工作区该文件字节不变。（验证：真实 Git 端到端比较三个路径的哈希、分支和提交。）
- [x] H06：定义式只读角色执行时看不到父对话标记且不创建 Worktree；最终只把结论和用量返回主对话。（验证：Provider 请求、Git worktree 列表和主 Session 扫描。）
- [x] H07：Fork 任务能回答依赖父历史的问题，首次请求前缀与父请求一致；真实 Provider 返回的缓存命中字段被记录，未返回时如实显示不可用。（验证：确定性前缀测试加真实 DeepSeek usage 记录。）
- [x] H08：前台定义式任务分别完成 120 秒自动后台和 `Ctrl+B` 手动后台流程，切换后继续使用同一任务与 Worktree 并最终只通知一次。（验证：可控时钟测试和一次真实 TUI 操作记录。）
- [x] H09：运行中的写任务产生未提交文件后取消，Worktree 被保留；用户查看详情能定位文件，未确认危险删除前后台清理无法删除。（验证：取消—查看—清理全流程。）
- [x] H10：一个无变化任务完成后自动清理，一个含未推送提交任务完成后保留；重启 ArtCode 后前者无残留、后者可识别且文件与提交完整。（验证：两进程端到端场景。）
- [x] H11：项目级坏角色遮蔽同名用户角色但不影响另一有效角色；修复项目角色后无需重启即可用于新任务。（验证：真实目录热更新端到端流程。）
- [x] H12：四个任务并行运行且第五个排队时，父 Agent 仍能正常对话、列任务、取消其中一个并接收其余完成通知；各任务用量和状态独立。（验证：确定性并发端到端事件序列。）
- [x] H13：配置可用时真实 DeepSeek 分别完成定义式、Fork 和 Worktree 写任务；真实 API 失败必须记录为失败或环境阻塞，不能用 Fake 结果冒充。（验证：运行三个 `tests/live/test_subagent_*_e2e.py` 并保存脱敏结果。）
- [x] H14：完整 `pytest -q`、`python -m compileall -q artcode tests` 和项目构建均通过；没有用新增 xfail 或跳过掩盖本章已确认缺陷。（验证：保存退出码、测试摘要和构建产物。）
- [x] H15：测试结束后没有残留运行中的子进程、后台 asyncio 任务、活动 Seatbelt 会话或无成果临时 Worktree；被保护的成果 Worktree 在结果中逐个列出。（验证：资源审计、进程检查和 `git worktree list --porcelain`。）
- [x] H16：整章最终范围仍不包含自动合并/变基、跨 Worktree 同步、多 Agent 团队编排和后台任务跨会话恢复。（验证：用户可见命令/工具 Schema、生产导入与持久化目录扫描。）

## 最小端到端验收路径

- [x] E2E-01：在一个含未提交主工作区修改的真实临时 Git 仓库中，主 Agent 同时启动两个写角色子 Agent；两者基于入队时 HEAD 创建不同 Worktree 和分支，分别修改同名文件并产生可区分结果，主未提交修改既未进入子目录也未被覆盖。（证据：三个工作目录文件哈希、三个 Git status、两个任务详情和主 Session 通知。）
- [x] E2E-02：启动一个依赖父对话事实的 Fork 任务；Agent 工具立即返回任务 ID，父 Agent 继续工作，Fork 完成后只注入一条 `<task-notification>`，任务详情包含真实 Provider 缓存用量或“不可用”。（证据：父/子首次请求前缀哈希、通知、任务详情和 Session 扫描。）
- [x] E2E-03：启动一个会写文件且运行超过前台阈值的定义式任务，在 120 秒自动后台后取消；确认其 Worktree 因未提交成果被保留，常规清理和重启扫描均不删除，用户仍能从详情定位成果。（证据：时钟事件、取消状态、文件哈希、重启后的遗留诊断。）