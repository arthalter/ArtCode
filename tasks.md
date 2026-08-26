# ch13：子 Agent 与 Worktree 隔离 Tasks

## 执行原则

1. 严格按依赖关系推进；每个任务先补目标测试，再实现，再运行受影响测试。
2. 所有子 Agent 从创建时就拥有独立运行状态；任何前台转后台行为只能改变等待方式，不能重建任务。
3. 任何可能写入仓库的子 Agent 都必须先取得独立 Worktree；Worktree 初始化失败时不得降级到主工作区运行。
4. 所有文件和命令工具都通过显式工作目录运行，不使用进程级目录切换，也不以清空全局缓存代替路径隔离。
5. 自动清理必须以保护成果为先；无法证明目录归属、空闲状态和 Git 安全状态时一律保留。
6. 保持现有普通对话、Plan/Do、Skill、MCP、权限、会话恢复、记忆和上下文治理流程兼容。
7. 本章不新增独立 Hook 子系统；运行时如果提供 Hook 引擎，子 Agent 只复用同一个共享实例。

## 参考资料索引

- **需求基线：** 根目录 `spec.md`。
- **理论材料 A：** 浏览器中的《理论学习：SubAgent 子任务分发》，重点参考“统一 Agent 工具”“定义式与 Fork 式”“运行时状态隔离”“RunToCompletion”“后台任务与通知”“工具过滤”。
- **理论材料 B：** 浏览器中的《理论学习：Git Worktree 并行隔离》，重点参考“分支与工作目录的区别”“安全命名”“快速恢复”“环境初始化”“显式 cwd”“退出保护”“过期清理”。
- **现有主链路：** `artcode/bootstrap.py`、`artcode/runtime/app.py`、`artcode/agent/loop.py`、`artcode/agent/request.py`。
- **现有工具与权限链路：** `artcode/tools/`、`artcode/permissions/`、`artcode/sandbox/`。
- **现有路径与持久内容链路：** `artcode/workspace.py`、`artcode/persistence/`、`artcode/prompting/`、`artcode/context_management/`。

## T1：建立子 Agent、后台任务与 Worktree 的基础契约

**影响文件：** `artcode/subagents/models.py`、`artcode/subagents/__init__.py`、`artcode/background/models.py`、`artcode/background/__init__.py`、`artcode/worktrees/models.py`、`artcode/worktrees/__init__.py`、`artcode/config.py`、`artcode/workspace.py`、`config.example.yml`、`tests/unit/test_subagent_models.py`、`tests/unit/test_background_models.py`、`tests/unit/test_worktree_models.py`、`tests/unit/test_config.py`、`tests/unit/test_workspace.py`

**依赖任务：** 无

**参考资料定位：** Spec F1、F5、F9、F17、F30～F34、F47，N5～N6；理论材料 A“角色定义”“后台状态”；理论材料 B“目录与分支命名”。

**完成结果：** 定义不可变的创建请求、角色元信息、任务状态、用量、停止原因、Worktree 租约与交接摘要；配置和路径对象能表达模型档位、后台执行及项目 Worktree 规则，但不在模型层执行文件或 Git 操作。

**实施要点：**

1. 明确定义式与 Fork 式的判别字段及组合约束，使统一 Agent 工具后续始终复用同一请求结构。
2. 将角色、后台任务和 Worktree 状态设计成可序列化快照，避免把可变运行对象直接暴露给 TUI 或模型工具。
3. 扩展用户配置和项目路径，加入角色目录、系统托管 Worktree 目录、项目初始化规则与模型档位映射。
4. 保持现有配置缺省行为兼容；未知字段、非法状态转换和不完整交接信息在进入运行时前被拒绝。

**验证：** 运行 `pytest tests/unit/test_subagent_models.py tests/unit/test_background_models.py tests/unit/test_worktree_models.py tests/unit/test_config.py tests/unit/test_workspace.py -q`；覆盖合法构造、非法组合、状态转换、快照不可变性和旧配置兼容。

## T2：实现多来源角色发现、解析、覆盖与刷新

**影响文件：** `artcode/subagents/roles.py`、`artcode/subagents/models.py`、`artcode/subagents/builtin/.gitkeep`、`artcode/workspace.py`、`MANIFEST.in`、`pyproject.toml`、`tests/fixtures/subagents.py`、`tests/unit/test_subagent_roles.py`

**依赖任务：** T1

**参考资料定位：** Spec F2～F9、AC2～AC4；理论材料 A“定义式子 Agent”“Markdown + YAML frontmatter”“多来源加载”。可复用现有 `artcode/skills/discovery.py` 和 `artcode/skills/service.py` 的安全发现思路，但角色目录与 Skill 激活状态保持独立。

**完成结果：** 项目、用户、内置和插件来源能够产出唯一有效角色目录；同名角色整体覆盖，非法高优先级定义形成阻断诊断而不静默回退；每次创建前刷新并返回启动快照。

**实施要点：**

1. 严格解析 YAML frontmatter 和 Markdown 正文，校验角色名、用途、工具白名单、工具黑名单、模型档位、最大轮次、权限模式与隔离声明。
2. 按项目、用户、内置、插件顺序决定同名角色，禁止跨来源字段合并；插件只贡献角色目录，不在本章实现插件安装与生命周期。
3. 区分启动阻断诊断和单角色诊断，使一个坏角色不影响其他不同名有效角色。
4. 校验普通工具名、白黑名单冲突、写能力与 Worktree 声明、模型映射可用性，并保证运行中任务继续使用旧快照。

**验证：** 运行 `pytest tests/unit/test_subagent_roles.py -q`；覆盖四级来源、同名覆盖、非法高优先级阻断、热更新、删除、未知工具、模型缺失、写角色未隔离和正文生命周期。

## T3：建立每个 Agent 的显式执行作用域与路径隔离

**影响文件：** `artcode/runtime/execution_scope.py`、`artcode/tools/base.py`、`artcode/tools/execution.py`、`artcode/tools/policy.py`、`artcode/tools/file_tools.py`、`artcode/tools/command_tool.py`、`artcode/mcp/adapter.py`、`artcode/mcp/catalog.py`、`artcode/prompting/reminder.py`、`tests/unit/test_execution_scope.py`、`tests/unit/test_file_tools.py`、`tests/unit/test_command_tool.py`、`tests/integration/test_workspace_file_flow.py`、`tests/integration/test_process_flow.py`

**依赖任务：** T1

**参考资料定位：** Spec F10～F12、F16、F39～F41、AC5、AC10、AC14；理论材料 B“显式 cwd 与绝对路径缓存”。现有 `ToolEnvironment`、`ToolRunContext`、`WorkspacePathPolicy` 是改造入口。

**完成结果：** 主 Agent 和每个子 Agent 都从自身执行作用域取得绝对工作目录、路径策略、权限快照和会话标识；文件、命令及 MCP 工具不再依赖进程当前目录推断操作位置。

**实施要点：**

1. 将工作目录作为每次工具执行的显式上下文，移除路径相关代码对 `Path.cwd()` 的隐式回退。
2. 为主工作区和 Worktree 分别构造路径策略，确保相对路径只在当前作用域解析，绝对路径仍受当前根边界限制。
3. 让命令工具的用户可选 cwd 只能在当前作用域内进一步收窄，不能切到主工作区、其他 Worktree 或外部目录；主 Agent 的普通工具也不能进入系统托管 Worktree 根。
4. 保持 Provider、MCP 管理器、工具实现和底层文件系统服务可共享；路径策略与 Seatbelt 会话按执行作用域创建，每次调用只消费当前 Agent 的作用域快照。

**验证：** 运行 `pytest tests/unit/test_execution_scope.py tests/unit/test_file_tools.py tests/unit/test_command_tool.py tests/integration/test_workspace_file_flow.py tests/integration/test_process_flow.py -q`；并发作用域操作同名文件时只能改变各自目录，进程 cwd 始终不变。

## T4：实现 Worktree 安全命名、归属元数据与只读检查

**影响文件：** `artcode/worktrees/naming.py`、`artcode/worktrees/metadata.py`、`artcode/worktrees/inspection.py`、`artcode/worktrees/models.py`、`tests/unit/test_worktree_naming.py`、`tests/unit/test_worktree_metadata.py`、`tests/unit/test_worktree_inspection.py`、`tests/property/test_worktree_paths.py`

**依赖任务：** T1

**参考资料定位：** Spec F32～F36、N1～N2、N5、AC11～AC13；理论材料 B“名称校验”“快速恢复”“三层安全过滤”。

**完成结果：** 系统名称和用户提供的嵌套名称都只能解析到托管根内；已有目录可通过有限只读文件检查验证 Git 仓库、分支、基准提交和任务归属，不需要先调用 Git。

**实施要点：**

1. 对名称整体和每个路径段分别校验，拒绝空段、`.`、`..`、绝对路径、反斜杠、控制字符、超长输入和解析后越界。
2. 将目录名、分支名和任务标识分开生成与验证，避免把模型文本直接拼接为 Git 参数。
3. 以原子方式写入最小归属元数据；恢复时同时验证 `.git` 指针、公共 Git 目录、分支和任务标识。
4. 对符号链接、损坏元数据、被替换目录和归属不匹配一律拒绝接管。

**验证：** 运行 `pytest tests/unit/test_worktree_naming.py tests/unit/test_worktree_metadata.py tests/unit/test_worktree_inspection.py tests/property/test_worktree_paths.py -q`；属性测试生成的任意非法名称均不能逃离托管目录或覆盖已有目录。

## T5：实现 Worktree 创建、快速恢复与环境初始化

**影响文件：** `artcode/worktrees/git.py`、`artcode/worktrees/initializer.py`、`artcode/worktrees/manager.py`、`artcode/worktrees/models.py`、`artcode/workspace.py`、`.gitignore`、`tests/fixtures/git_repositories.py`、`tests/unit/test_worktree_git.py`、`tests/unit/test_worktree_initializer.py`、`tests/integration/test_worktree_lifecycle.py`

**依赖任务：** T3、T4

**参考资料定位：** Spec F30～F40、AC10～AC14；理论材料 B“创建与进入”“快速恢复”“复制配置、Hooks、软链依赖、补齐忽略文件”。

**完成结果：** 管理器能基于入队时捕获的提交创建独立分支和 Worktree，初始化项目运行环境并返回执行租约；合法已有目录走只读恢复，不重复执行 Git 创建。

**实施要点：**

1. 所有 Git 子进程使用参数数组和显式 cwd，不经 shell 拼接；非 Git 仓库、无提交、分支冲突或 Git 失败时不降级运行，并确保托管 Worktree 根被版本控制忽略。
2. 创建成功后按项目规则复制本地配置和忽略文件、设置 Worktree 专属 Hooks，并为声明可共享的大型依赖建立受控软链接。
3. 软链接目标必须解析到允许的主工作区依赖目录，并通过子 Agent 路径策略禁止写入共享目标。
4. 初始化中途失败时只回滚本次能够证明新建且安全的资源，任何已有或含成果目录保持原状并报告诊断。

**验证：** 运行 `pytest tests/unit/test_worktree_git.py tests/unit/test_worktree_initializer.py tests/integration/test_worktree_lifecycle.py -q`；覆盖新建、重复恢复、嵌套名称、基准冻结、托管目录忽略、初始化各规则、软链越界和分阶段故障回滚。

## T6：实现 Worktree 退出保护、成果判断与过期清理

**影响文件：** `artcode/worktrees/status.py`、`artcode/worktrees/cleanup.py`、`artcode/worktrees/manager.py`、`tests/unit/test_worktree_status.py`、`tests/unit/test_worktree_cleanup.py`、`tests/fault/test_worktree_cleanup_failures.py`、`tests/integration/test_worktree_protection.py`

**依赖任务：** T5

**参考资料定位：** Spec F42～F49、N1～N2、AC15～AC16；理论材料 B“退出与删除”“未提交/未推送保护”“过期临时目录清理”。

**完成结果：** 任务退出时能区分无成果、未提交修改、新增本地提交、已安全交接提交和未知状态；自动路径只删除无成果的系统临时 Worktree，危险状态默认保留。

**实施要点：**

1. 同时检查已跟踪修改、未跟踪文件、相对基准新增提交、上游关系和提交可达性，形成结构化交接状态。
2. 正常完成、异常、达到轮次限制和取消都走同一保护流程；取消不回滚文件操作。
3. 手动 Worktree 永不参与自动清理；显式丢弃必须由主界面用户确认，子 Agent 和模型工具没有强制删除能力。
4. 过期清理依次验证托管根边界、系统归属与非活跃状态、Git 安全状态；任一检查失败即保留并记录原因。

**验证：** 运行 `pytest tests/unit/test_worktree_status.py tests/unit/test_worktree_cleanup.py tests/fault/test_worktree_cleanup_failures.py tests/integration/test_worktree_protection.py -q`；构造脏文件、未跟踪文件、本地提交、已推送提交、活跃租约、手动目录和损坏元数据，确认只有安全目标被删除。

## T7：实现子 Agent 的工具能力交集与非交互权限端口

**影响文件：** `artcode/subagents/policy.py`、`artcode/subagents/permissions.py`、`artcode/agent/modes.py`、`artcode/tools/base.py`、`artcode/tools/policy.py`、`artcode/tools/execution.py`、`artcode/permissions/service.py`、`tests/unit/test_subagent_policy.py`、`tests/unit/test_subagent_permissions.py`、`tests/property/test_subagent_capabilities.py`、`tests/integration/test_subagent_permission_flow.py`

**依赖任务：** T2、T3

**参考资料定位：** Spec F4、F12、F25～F31、N1、AC3、AC9；理论材料 A“多层工具过滤”“权限隔离”“后台白名单”。

**完成结果：** 有效工具集由父能力上限、全局禁止、创建类型、角色白黑名单和后台限制求交得到；子 Agent 的临时审批自动拒绝并留存事件，不会阻塞等待用户。

**实施要点：**

1. 在模型可见工具集合和实际执行入口分别校验，防止伪造工具调用绕过提示层过滤。
2. 由工具描述符显式声明是否可供子 Agent 使用；将 Agent 创建、再次 Fork、用户询问、系统任务控制、默认 MCP 和危险清理列为不可恢复能力，后台白名单只会收紧，不会扩大角色或父权限。
3. 为每个子 Agent 创建新的权限追踪器；只继承全局/项目规则和父权限模式上限，不复制父 Agent 的一次性批准。
4. 所有仍需临时批准的操作返回稳定拒绝结果，并记录工具、原因、时间和任务标识。

**验证：** 运行 `pytest tests/unit/test_subagent_policy.py tests/unit/test_subagent_permissions.py tests/property/test_subagent_capabilities.py tests/integration/test_subagent_permission_flow.py -q`；属性测试证明任意角色组合都不能产生父 Agent 或全局策略之外的新能力。

## T8：实现定义式与 Fork 式子 Agent 运行时工厂

**影响文件：** `artcode/subagents/factory.py`、`artcode/subagents/runtime.py`、`artcode/conversation/context.py`、`artcode/agent/request.py`、`artcode/context_management/manager.py`、`artcode/context_management/artifacts.py`、`artcode/persistence/paths.py`、`artcode/persistence/instructions.py`、`artcode/prompting/durable.py`、`artcode/prompting/assembler.py`、`tests/unit/test_subagent_factory.py`、`tests/unit/test_subagent_prompting.py`、`tests/integration/test_subagent_state_isolation.py`

**依赖任务：** T2、T3、T5、T7

**参考资料定位：** Spec F2～F4、F8～F12、F30～F41、N3、N5、N8、AC2～AC5、AC10～AC14；理论材料 A“空白定义式”“Fork 快照与提示缓存”“共享基础设施”；理论材料 B“绝对路径缓存键”。

**完成结果：** 定义式从固定基础提示、项目指令、角色正文和任务组成的空白对话启动；Fork 式冻结父对话与工具快照，并在继承前缀之后追加角色、Worktree 和任务信息；两者得到独立状态容器。

**实施要点：**

1. 为消息、权限事件、上下文管理、Artifact Store、计划记忆、文件读取缓存、轮次和 Token 计数分别创建子实例。
2. 共享 Provider、工具实现、MCP 管理器、底层文件系统服务及可选 Hook 引擎；每个 Worktree 使用独立 Seatbelt 会话，并且不共享会话持久化写入和长期记忆更新任务。
3. 路径相关指令、提示、记忆索引和文件缓存以规范化绝对路径为键，从子 Agent 所属 Workspace 读取；不得因切换 Worktree 全局清缓存。
4. Fork 保持父请求前缀的消息顺序和工具定义顺序，仅在尾部追加子任务信息；缓存命中只采信 Provider 返回的用量字段。
5. 需要 Worktree 时在首次模型请求前完成租约绑定和路径说明注入；绑定失败则子 Agent 不启动。

**验证：** 运行 `pytest tests/unit/test_subagent_factory.py tests/unit/test_subagent_prompting.py tests/integration/test_subagent_state_isolation.py -q`；比较对象身份、消息内容、工具顺序、绝对缓存键和 Worktree 根，确认共享与隔离边界符合设计。

## T9：实现 RunToCompletion 执行器与统一停止结果

**影响文件：** `artcode/subagents/runner.py`、`artcode/subagents/models.py`、`artcode/agent/loop.py`、`artcode/agent/events.py`、`artcode/providers/events.py`、`tests/unit/test_subagent_runner.py`、`tests/fault/test_subagent_runner_failures.py`、`tests/integration/test_subagent_run_to_completion.py`

**依赖任务：** T8

**参考资料定位：** Spec F13～F16、F21～F23、F47，AC5～AC7；理论材料 A“RunToCompletion”“模型不再调用工具即完成”“用量统计”。

**完成结果：** 子 Agent 从启动持续运行到自然完成、达到轮次限制、取消或不可恢复错误，并统一产出最终文本、停止原因、累计用量、权限事件和 Worktree 交接摘要。

**实施要点：**

1. 普通工具错误继续作为工具结果进入下一轮；只有明确的终止条件结束执行。
2. 聚合每轮 Provider 用量而不是覆盖最后一轮，分别保留输入、输出、缓存命中、缓存未命中和总量。
3. 终止后始终执行 Worktree 退出判断；即使总结失败，也保留已经产生的文件与可查看状态。
4. 取消使用协作式取消并等待正在执行的工具完成取消清理，不启动第二个替代 Runner。

**验证：** 运行 `pytest tests/unit/test_subagent_runner.py tests/fault/test_subagent_runner_failures.py tests/integration/test_subagent_run_to_completion.py -q`；覆盖自然完成、多轮工具恢复、轮次上限、Provider 失败、工具取消、总结缺失和各类 Worktree 保护结果。

## T10：实现统一后台任务管理器与三种转后台路径

**影响文件：** `artcode/background/manager.py`、`artcode/background/models.py`、`artcode/background/clock.py`、`artcode/subagents/runner.py`、`tests/unit/test_background_manager.py`、`tests/fault/test_background_manager_failures.py`、`tests/integration/test_background_transition.py`

**依赖任务：** T6、T9

**参考资料定位：** Spec F15～F19、F23～F24、N4～N7、AC7～AC8；理论材料 A“显式后台”“超时自动后台”“手动切换”“Fork 强制后台”。

**完成结果：** 所有子 Agent 从创建时就由同一任务管理器持有；定义式可前台等待、显式后台或在等待期间自动/手动转后台，Fork 创建后立即返回后台任务标识。

**实施要点：**

1. 任务管理器维护排队、运行、完成、异常、达到限制和取消状态，并提供不可变列表与详情快照。
2. 前台等待使用屏蔽取消的同一异步任务；等待超时或手动切换只停止等待，运行对象、消息、Worktree 和用量保持不变。
3. 并发槽位和排队顺序可控；任务基准、父对话、角色、权限和工具快照在入队时冻结。
4. 取消只影响目标任务，不传播到父 Agent 或其他任务；完成回调失败不改变任务本身的最终状态。

**验证：** 运行 `pytest tests/unit/test_background_manager.py tests/fault/test_background_manager_failures.py tests/integration/test_background_transition.py -q`；使用可控时钟验证四条启动路径、队列、公平性、同一任务身份、并发取消和完成回调隔离。

## T11：实现 Agent 工具、任务查询工具与结果通知收件箱

**影响文件：** `artcode/subagents/tool.py`、`artcode/background/tools.py`、`artcode/background/notifications.py`、`artcode/tools/registry.py`、`artcode/tools/__init__.py`、`artcode/agent/request.py`、`artcode/conversation/context.py`、`tests/unit/test_agent_tool.py`、`tests/unit/test_background_tools.py`、`tests/unit/test_task_notifications.py`、`tests/integration/test_subagent_notification_flow.py`

**依赖任务：** T10

**参考资料定位：** Spec F1～F4、F17～F22、F25～F29、F47～F49、AC1、AC3、AC8～AC9、AC17；理论材料 A“统一 Agent 工具”“任务通知”。

**完成结果：** 主 Agent 始终看到结构稳定的 Agent 工具，并能通过系统任务工具列出、查看和取消后台任务；完成结果在安全请求边界以精简通知进入父对话，完整详情留在任务管理器。

**实施要点：**

1. Agent 工具明确校验定义式和 Fork 式的字段组合；定义式要求角色，Fork 角色可选且强制后台。
2. Agent 工具根据能力分析在启动前决定是否需要 Worktree，不允许先在主工作区写入后再迁移。
3. 任务查询工具返回有界、脱敏快照；取消工具不能提供强制删除 Worktree 或绕过权限保护的入口。
4. 通知收件箱按完成顺序投递，在父模型当前请求结束后的下一安全边界消费，避免修改正在流式生成的请求。
5. 超长结果只通知状态、摘要和详情定位；不把完整子对话、思考文本和工具轨迹复制到父上下文。

**验证：** 运行 `pytest tests/unit/test_agent_tool.py tests/unit/test_background_tools.py tests/unit/test_task_notifications.py tests/integration/test_subagent_notification_flow.py -q`；覆盖工具结构稳定性、参数矩阵、嵌套阻断、通知顺序、并发完成、长结果截断和父请求不可变性。

## T12：接入 TUI 的后台切换、任务展示、取消与退出保护

**影响文件：** `artcode/tui/keybindings.py`、`artcode/tui/app.py`、`artcode/tui/render.py`、`artcode/runtime/app.py`、`artcode/runtime/state.py`、`artcode/commands/builtin.py`、`artcode/commands/base.py`、`tests/unit/test_commands.py`、`tests/unit/test_tui_background_controls.py`、`tests/integration/test_runtime_background_flow.py`

**依赖任务：** T10、T11

**参考资料定位：** Spec F15～F24、N6、AC7～AC8；理论材料 A“前台/后台交互”“任务状态与通知”。

**完成结果：** 用户能在前台子 Agent 运行时手动切到后台，能通过本地命令查看任务列表、详情和取消任务；正常退出前会明确暴露仍在运行的任务并走受控收尾。

**实施要点：**

1. 在模型生成期间启用专用后台切换键，不与现有发送、多行输入和取消快捷键冲突；切换后立即显示任务标识和当前状态。
2. 为任务列表、任务详情和取消提供清晰的本地命令输出，区分排队、运行、停止原因、用量和 Worktree 保留状态。
3. 异步完成提示不破坏当前流式输出；同一任务的重复通知和已读状态可区分。
4. 应用退出不静默遗弃运行任务：先展示活跃任务，再按用户选择返回、等待或取消；取消后的 Worktree 仍走成果保护。

**验证：** 运行 `pytest tests/unit/test_commands.py tests/unit/test_tui_background_controls.py tests/integration/test_runtime_background_flow.py -q`；覆盖快捷键冲突、前台切换、自动转后台、通知渲染、重复取消、退出保护和终端异常。

## T13：补齐并发、故障与安全不变量测试

**影响文件：** `tests/fixtures/subagents.py`、`tests/fixtures/git_repositories.py`、`tests/property/test_subagent_capabilities.py`、`tests/property/test_worktree_paths.py`、`tests/fault/test_subagent_concurrency.py`、`tests/fault/test_subagent_failures.py`、`tests/fault/test_worktree_cleanup_failures.py`、`tests/integration/test_subagent_parallel_worktrees.py`

**依赖任务：** T1～T12

**参考资料定位：** Spec N1～N11、AC3～AC16；理论材料 A、B 全文的隔离与失败场景。

**完成结果：** 对路径、权限、缓存、并发和清理建立自动化安全网，能够证明失败只影响目标任务，任何不确定状态都不会扩大能力或删除成果。

**实施要点：**

1. 并行运行多个读任务、写任务、Fork 和定义式任务，验证消息、权限、用量、工作目录和文件内容互不串扰。
2. 在角色刷新、Git 创建、环境初始化、Provider 流、工具执行、通知、取消和清理阶段注入故障。
3. 以属性测试覆盖名称解析和能力求交，验证结果永不越出托管根、永不超过父能力上限。
4. 对 `os.chdir`/`Path.cwd()` 依赖建立回归探针，并验证主 Agent、子 Agent 与各自 Seatbelt 都不能跨越所属作用域，确保并发文件行为只由执行作用域决定。

**验证：** 运行 `pytest tests/property tests/fault tests/integration/test_subagent_parallel_worktrees.py -q`；重复并发运行无随机失败，所有保护性不变量均有可观测断言。

## T14：接入主流程

**影响文件：** `artcode/bootstrap.py`、`artcode/runtime/app.py`、`artcode/runtime/state.py`、`artcode/agent/loop.py`、`artcode/agent/request.py`、`artcode/tools/__init__.py`、`artcode/commands/builtin.py`、`artcode/workspace.py`、`README.md`、`config.example.yml`、`tests/integration/test_subagent_main_flow.py`、`tests/integration/test_agent_request_flow.py`、`tests/integration/test_main_entry_flow.py`、`tests/integration/test_skill_flow.py`、`tests/integration/test_mcp_agent_flow.py`、`tests/integration/test_persistence_flow.py`

**依赖任务：** T1～T13

**参考资料定位：** Spec 全部功能需求与 N3～N10；现有生产组合根 `artcode/bootstrap.py` 和主循环 `artcode/runtime/app.py`。

**完成结果：** Bootstrap 只组装一套 Provider、工具实现、MCP、Seatbelt 和可选 Hook 基础设施，同时为主 Agent 与子 Agent 创建不同运行状态；Agent 工具、任务管理器、角色目录、Worktree 管理器和 TUI 控制进入真实主链路。

**实施要点：**

1. 明确资源所有权和关闭顺序，后台任务先受控停止，子 Agent Artifact Store 与 Worktree 租约随后退出，共享服务最后关闭。
2. 注册 Agent 与任务工具，并在工具注册完成后校验角色工具名，保证模型看到的统一 Agent 工具结构稳定。
3. 将任务通知排入主 Agent 请求边界，验证主会话持久化只保存精简通知而不保存完整子会话。
4. 回归未调用 Agent 工具时的现有功能，确认普通文件工具仍以主 Workspace 为作用域，Skill 独立对话不会被误当成子 Agent 后台任务。

**验证：** 运行 `pytest tests/integration/test_subagent_main_flow.py tests/integration/test_agent_request_flow.py tests/integration/test_main_entry_flow.py tests/integration/test_skill_flow.py tests/integration/test_mcp_agent_flow.py tests/integration/test_persistence_flow.py -q`；随后运行全部非 live 测试。

## T15：端到端验证

**影响文件：** `tests/live/test_subagent_definition_e2e.py`、`tests/live/test_subagent_fork_cache_e2e.py`、`tests/live/test_subagent_worktree_e2e.py`、`tests/manual/ch13_acceptance.md`、`tests/manual/ch13_results.md`、`checklist.md`

**依赖任务：** T14

**参考资料定位：** Spec AC1～AC17；Checklist 全部验收项；理论材料 A、B 的完整用户路径。

**完成结果：** 在临时真实 Git 仓库中完成定义式只读任务、定义式前台转后台任务、Fork 缓存任务和两个并行写 Worktree 任务；主工作区不被直接修改，任务结果、用量和 Git 交接信息可查看。

**实施要点：**

1. 使用可控 Provider 完整覆盖定义式空白上下文、Fork 父快照、角色限制、异步通知、取消和退出保护。
2. 使用真实 Git 进程验证同一基准上的并行分支、同名文件修改、快速恢复、初始化规则、脏目录保留和安全目录清理。
3. 配置可用时执行真实 DeepSeek 调用，核对 RunToCompletion、多轮 Token 聚合和 Provider 报告的缓存命中；不能用推算值冒充缓存证据。
4. 执行全量测试、编译、构建和临时安装，逐项记录真实结果、跳过原因及遗留 Worktree 路径。

**验证：** 运行 `pytest -q`，再运行 `python -m compileall -q artcode tests` 和项目构建；真实 API 可用时运行 `pytest tests/live/test_subagent_definition_e2e.py tests/live/test_subagent_fork_cache_e2e.py tests/live/test_subagent_worktree_e2e.py -q`，最后按 `checklist.md` 完成整章验收。

## 执行顺序

```text
T1 → T2 ───────────────→ T7 ───────────→ T8 → T9 → T10 → T11 → T12 → T13 → T14 → T15
 ├→ T3 ───────→ T5 ────────────────────↗       ↑
 └→ T4 ───────→ T5 → T6 ──────────────────────┘
```
