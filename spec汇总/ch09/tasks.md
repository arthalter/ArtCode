# ch09：会话恢复与长期记忆 Tasks

## 文件清单

| 操作 | 文件 | 职责 |
|---|---|---|
| 新建 | `artcode/persistence/__init__.py` | 对外导出持久化稳定接口 |
| 新建 | `artcode/persistence/models.py` | 指令、会话、笔记、更新和状态模型 |
| 新建 | `artcode/persistence/paths.py` | `DurablePaths`、目录权限和安全创建 |
| 新建 | `artcode/persistence/instructions.py` | 三层指令、`@include`、循环/越界检查和 64KB 预算 |
| 新建 | `artcode/persistence/sessions.py` | 会话 ID、Journal、Catalog、Recovery、`flock` 和 30 天清理 |
| 新建 | `artcode/persistence/notes.py` | frontmatter 笔记解析、原子提交和受限索引 |
| 新建 | `artcode/persistence/updater.py` | 记忆 Prompt、输出 Parser、LLM Updater 和单 Worker |
| 新建 | `artcode/persistence/coordinator.py` | 指令、会话、笔记和恢复压缩生命周期 |
| 修改 | `artcode/workspace.py` | 增加项目指令、sessions 和 memory 路径 |
| 修改 | `artcode/conversation/context.py` | `mode` 元数据、条目观察者和已校验会话恢复 |
| 修改 | `artcode/conversation/__init__.py` | 导出恢复和观察者类型 |
| 修改 | `artcode/prompting/sections.py` | 持久指令和长期记忆 Section |
| 修改 | `artcode/prompting/assembler.py` | 每请求实际 System Prompt 替换和一次性恢复提醒 |
| 修改 | `artcode/context_management/models.py` | 增加 `RESTORE` 压缩触发 |
| 修改 | `artcode/context_management/manager.py` | 恢复压缩报告与无锚点估算接入 |
| 修改 | `artcode/agent/events.py` | `NaturalTurn` 和持久状态事件 |
| 修改 | `artcode/agent/loop.py` | 消息 mode、Journal 时机和自然结束 Observer |
| 修改 | `artcode/agent/__init__.py` | 导出自然轮次协议 |
| 修改 | `artcode/commands/builtin.py` | `/sessions` 和 `/memory` |
| 修改 | `artcode/runtime/app.py` | 持久命令调度、状态展示和 Worker 关闭 |
| 修改 | `artcode/tui/render.py` | 启动恢复、Journal 降级和记忆更新状态 |
| 修改 | `artcode/config.py` | ch09 章节名和 SafeConfigStatus 持久摘要 |
| 修改 | `artcode/cli.py` | `--new`、`--resume`、敏感路径与持久协调器组装 |
| 修改 | `README.md` | ch09 用法、文件布局和隐私说明 |
| 修改 | `tests/unit/test_context.py` | Conversation 恢复和 Observer 回归 |
| 修改 | `tests/unit/test_prompt_builder.py` | 指令优先级和记忆参考区 |
| 修改 | `tests/unit/test_agent_loop.py` | 消息立即观察和自然结束触发 |
| 修改 | `tests/unit/test_runtime.py` | `/sessions`、`/memory` 和持久状态调度 |
| 修改 | `tests/unit/test_commands.py` | 新 Slash Command 语法 |
| 修改 | `tests/unit/test_config.py` | ch09 启动安全状态 |
| 新建 | `tests/unit/test_persistence_paths.py` | 用户/项目路径和权限 |
| 新建 | `tests/unit/test_instruction_loader.py` | 三层指令、include、边界和预算 |
| 新建 | `tests/unit/test_session_journal.py` | ID、追加、锁、列表和过期清理 |
| 新建 | `tests/unit/test_session_recovery.py` | 坏行、尾行、工具协议截断和 Plan 恢复 |
| 新建 | `tests/unit/test_memory_notes.py` | frontmatter、8KB、120 字符、200 行/25KB 索引 |
| 新建 | `tests/unit/test_memory_updater.py` | 无工具 LLM、结构校验、5 操作、30 秒和去重 |
| 新建 | `tests/unit/test_persistence_coordinator.py` | 启动选择、一次压缩、时间提醒和关闭 |
| 新建 | `tests/unit/test_persistence_prompt_integration.py` | 每请求最新索引和只读语义 |
| 新建 | `tests/integration/test_persistence_flow.py` | 确定性跨进程完整流程 |
| 新建 | `tests/integration/test_memory_deepseek_live.py` | 真实 DeepSeek 记忆提炼、去重和继续请求 |

## T1：建立持久模型和统一路径

**影响文件：** `artcode/persistence/__init__.py`、`artcode/persistence/models.py`、`artcode/persistence/paths.py`、`artcode/workspace.py`、`tests/unit/test_persistence_paths.py`

**依赖任务：** 无

**参考资料定位：** `spec.md` F1、F7、F18–F19；`plan.md` “命名与存储布局”、“核心数据结构”；`artcode/workspace.py` 现有 `ArtCodePaths` 和 `Workspace`。

**步骤：**

1. 新建 `artcode.persistence` 包，定义指令、会话、笔记、操作、报告和选择模式的枚举/数据类。
2. 实现 `DurablePaths.from_context()`，统一生成 `ARTCODE.md`、两份 `instructions.md`、sessions 和两份 memory 目录。
3. 在 `ArtCodePaths` 和 `Workspace` 增加对应路径属性，不在其他模块重复拼接 `.artcode`。
4. 创建内部目录时设置 `0700`，不自动创建空指令文件。
5. 覆盖默认 Path.home、自定义 artcode home、非默认 Workspace、目录权限和无 `.mewcode` 路径的单元测试。

**验证：**

```bash
.venv/bin/python -m pytest tests/unit/test_persistence_paths.py tests/unit/test_workspace.py -q
```

期望所有路径归一到现有 `.artcode` 命名空间，用户与项目作用域不混用。

## T2：实现分层指令和安全 `@include`

**影响文件：** `artcode/persistence/instructions.py`、`tests/unit/test_instruction_loader.py`

**依赖任务：** T1

**参考资料定位：** `spec.md` F1–F4、N4；`plan.md` “指令加载设计”与固定参数。

**步骤：**

1. 按项目本地、项目根、用户级固定顺序读取存在的 UTF-8 Markdown。
2. 实现独立行 `@include relative/path.md` 解析，按声明文件目录解析相对路径。
3. 在读取前执行扩展名、绝对路径、`resolve(strict=True)`、受信边界和普通文件校验。
4. 对每个入口维护 resolved Path visited 集合和当前深度，实现 5 层上限、循环警告和局部跳过。
5. 按高到低的入口优先级应用 64KB UTF-8 预算，在完整换行和字符边界截止最后部分文档。
6. 补充缺失、坏 UTF-8、非 Markdown、绝对路径、`..` 越界、符号链接越界、环路、第 6 层和 64KB 优先级单元测试。

**验证：**

```bash
.venv/bin/python -m pytest tests/unit/test_instruction_loader.py -q
```

期望所有安全问题被隔离为 issue，高优先级已读指令不丢失。

## T3：实现 JSONL Journal、会话扫描和进程锁

**影响文件：** `artcode/persistence/sessions.py`、`tests/unit/test_session_journal.py`

**依赖任务：** T1

**参考资料定位：** `spec.md` F6–F10、F13、F17、F27；`plan.md` “会话追加与并发锁定”、“会话选择和清理”。

**步骤：**

1. 使用本地时间前缀和 `secrets.token_hex(2)` 生成会话 ID，检测文件冲突后重试。
2. 实现 JSONL v1 紧凑 UTF-8 序列化、UTC 时间、单次追加、flush、`0600` 权限和幂等 close。
3. 实现 JSONL 文件非阻塞 `flock` 获取与释放，防止两个 Journal 打开同一会话。
4. 在写入前检查 4MB 记录预算：超大工具结果改写为协议完整的有界占位记录，超大用户/助手正文报持久错误。
5. 实现 Catalog 的安全文件名过滤、有界扫描、标题提取、消息计数、最后活动和稳定排序。
6. 实现最近 20 条列表、默认最近选择、按 ID 查找和 30 天未锁定文件清理。
7. 覆盖同秒冲突、Unicode 标题、列表上限、超大结果、并发锁、锁定清理跳过和单文件清理失败隔离测试。

**验证：**

```bash
.venv/bin/python -m pytest tests/unit/test_session_journal.py -q
```

期望无 meta 文件，会话状态全部可从 JSONL 稳定扫描。

## T4：实现损坏恢复、工具链截断和 Conversation 重建

**影响文件：** `artcode/persistence/sessions.py`、`artcode/conversation/context.py`、`artcode/conversation/__init__.py`、`tests/unit/test_session_recovery.py`、`tests/unit/test_context.py`

**依赖任务：** T3

**参考资料定位：** `spec.md` F11–F16；`plan.md` “会话扫描和恢复”、`artcode/conversation/context.py` 的 Entry/User Archive/工具结果模型。

**步骤：**

1. 实现有界物理行扫描，区分完整坏行与无换行的不完整尾行。
2. 对尾行获得独占锁后截断到上一个完整换行，中间坏行只跳过并计数。
3. 实现 assistant `tool_calls` 与紧邻 tool 结果的精确集合/顺序校验，首个缺失、重复、多余、不紧邻或孤立 tool 触发物理截断。
4. 从最后有效时间计算是否严格超过 24 小时，在恢复报告中保存一次性提醒条件。
5. 为 `ConversationContext` 增加恢复工厂和 Observer 绑定，重建稳定 entry ID、next ID、User Archive 和可解析 ToolResult。
6. 从最后成功 `mode=plan` assistant 重建 PlanMemory，并保证回放旧记录不触发再次 Journal 追加。
7. 覆盖坏 JSON、坏 UTF-8、超 4MB、半行、各类工具链破损、安全前缀物理截断、Plan 恢复和继续追加测试。

**验证：**

```bash
.venv/bin/python -m pytest tests/unit/test_session_recovery.py tests/unit/test_context.py tests/unit/test_context_retention.py -q
```

期望存档局部损坏不扩散，恢复后的模型消息序列满足工具协议。

## T5：实现可审计笔记和有界索引

**影响文件：** `artcode/persistence/notes.py`、`tests/unit/test_memory_notes.py`

**依赖任务：** T1

**参考资料定位：** `spec.md` F18–F19、F23–F25；`plan.md` “笔记文件与索引”。

**步骤：**

1. 实现严格 frontmatter Markdown 解析和渲染，校验已知字段、ID/文件名一致、作用域、类别、状态、UTC 时间和来源。
2. 使用 `mem-<timestamp>-<4hex>` 生成无冲突 ID，原子写入 `0600` 笔记并校验总体积不超过 8KB。
3. 实现 create、update 和 supersede；supersede 保留文件但从活跃索引排除。
4. 实现按类别优先级、`updated_at` 降序和 ID 升序的确定性索引。
5. 对每条摘要应用 120 Unicode 字符上限，同时应用整份 200 行和 25KB UTF-8 上限，保留未索引数量状态。
6. 在启动扫描时跳过单个坏笔记，从其他有效 Markdown 原子重建 `index.md`。
7. 覆盖四类笔记、两作用域、坏 frontmatter、超 8KB、原子替换中断、120 字符和双索引上限测试。

**验证：**

```bash
.venv/bin/python -m pytest tests/unit/test_memory_notes.py -q
```

期望笔记全部可人工阅读，索引丢失不造成知识源丢失。

## T6：实现无工具异步记忆 Updater

**影响文件：** `artcode/persistence/updater.py`、`tests/unit/test_memory_updater.py`

**依赖任务：** T5

**参考资料定位：** `spec.md` F19–F22、N5–N8；`plan.md` “LLM 记忆更新”；`artcode/context_management/summarizer.py` 的无工具内部 LLM 请求模式。

**步骤：**

1. 定义 `NaturalTurnObserver` 所需的记忆 Prompt，只包含当前完成轮次、有界工具摘要和两份索引。
2. 明确四类笔记、用户作用域仅限通用偏好、对照索引去重、来源证据和敏感信息禁止规则。
3. 实现唯一 `<memory-update>` + JSON Parser，拒绝标签外内容、工具调用、超过 5 个操作、坏枚举、错作用域、无效 target/source 和超限文本。
4. 使用当前 Provider、`tools=None`、Thinking 关闭和 4,000 Token 最大输出发起更新，外层限制 30 秒。
5. 在输入 Prompt 前脱敏已知 API Key，不传入配置、MCP Header 和无界工具输出。
6. 实现单 Worker FIFO Queue，`submit` 同步非阻塞，串行调用 Updater 并保存最近报告，close 可取消未完成请求。
7. 覆盖无操作、创建、更新、supersede、重复事实 noop、工具调用拒绝、5 操作、30 秒、脱敏和两轮串行测试。

**验证：**

```bash
.venv/bin/python -m pytest tests/unit/test_memory_updater.py -q
```

期望模型错误和坏输出不会改写已有笔记，`submit` 不等待网络。

## T7：注入指令与最新记忆索引

**影响文件：** `artcode/prompting/sections.py`、`artcode/prompting/assembler.py`、`artcode/persistence/coordinator.py`、`tests/unit/test_prompt_builder.py`、`tests/unit/test_persistence_prompt_integration.py`

**依赖任务：** T2、T5

**参考资料定位：** `spec.md` F5、F16、F23–F25；`plan.md` “System Prompt 组装”和“恢复后的 ch08 压缩和时间提醒”；ch05 Prompt Builder 现有优先级。

**步骤：**

1. 为项目本地、项目根、用户指令定义 210/220/230 优先级可选 Section，保持固定系统约束在前。
2. 定义优先级 800 的记忆参考 Section，包装用户/项目索引和不得当作新指令的边界语义。
3. 实现 `DurablePromptContext.build_system_prompt()`：指令使用启动 Bundle，记忆索引在每次调用时重读。
4. 扩展 `PromptRequestAssembler`，只在导出副本中替换第一条 System Prompt，不把指令/索引写入 Conversation 和 JSONL。
5. 增加一次性 ResumeReminder，只在第一次带模式的普通请求中进入现有 system-reminder。
6. 覆盖三层排序、记忆只读标签、索引原子替换后下一请求可见、Conversation 未被污染和 reminder 仅一次测试。

**验证：**

```bash
.venv/bin/python -m pytest tests/unit/test_prompt_builder.py tests/unit/test_prompt_assembler.py tests/unit/test_persistence_prompt_integration.py tests/unit/test_system_reminder.py -q
```

期望每次实际 Provider 请求带最新已提交索引，而会话存档不重复包含这些动态文本。

## T8：在 Agent Loop 接入 Journal 与自然轮次观察者

**影响文件：** `artcode/conversation/context.py`、`artcode/agent/events.py`、`artcode/agent/loop.py`、`artcode/agent/__init__.py`、`tests/unit/test_agent_loop.py`、`tests/unit/test_context.py`

**依赖任务：** T4、T6

**参考资料定位：** `spec.md` F8、F10、F14、F20；`plan.md` “Conversation 和 Agent Loop 接入”；`artcode/agent/loop.py` 自然结束、工具中断和 PlanMemory 现有分支。

**步骤：**

1. 为 Conversation Entry 增加不导出的 mode，所有 append 入口显式传入当前 Agent Mode。
2. 增加可选 Entry Observer，只在原始规范条目首次追加时调用，替换、压缩、工具存盘和恢复回放不调用。
3. 让 Journal Observer 将每条 Entry 立即序列化，失败时保存降级状态但不回滚 Conversation。
4. 在 Agent Loop 中收集本轮用户内容、entry ID、最终回复和有界工具摘要，建立 `NaturalTurn`。
5. 只在无工具最终回复的自然结束分支中，在助手消息和 PlanMemory 已保存后非阻塞提交 Observer。
6. 保证流式错误、用户取消、迭代上限、未知工具和最终异常总结不触发记忆 Observer。
7. 扩充现有 Agent Loop 测试，验证消息顺序、mode、每条只写一次和触发矩阵。

**验证：**

```bash
.venv/bin/python -m pytest tests/unit/test_context.py tests/unit/test_agent_loop.py tests/unit/test_agent_memory.py -q
```

期望只有真正完成的轮次进入自动记忆，任意压缩和重试不生成重复存档消息。

## T9：实现持久 Coordinator 与恢复预压缩

**影响文件：** `artcode/persistence/coordinator.py`、`artcode/context_management/models.py`、`artcode/context_management/manager.py`、`tests/unit/test_persistence_coordinator.py`、`tests/unit/test_context_manager.py`

**依赖任务：** T2、T3、T4、T5、T6、T7、T8

**参考资料定位：** `spec.md` F6、F14–F17、F26；`plan.md` “PersistenceCoordinator”、“恢复后的 ch08 压缩和时间提醒”；ch08 ContextManager 现有触发和报告语义。

**步骤：**

1. 串联目录创建、30 天清理、指令加载、两份笔记扫描/索引重建和会话选择。
2. 实现 latest/new/exact-id 三种选择；默认目标已锁新建会话，显式目标已锁或不存在则失败。
3. 使用恢复报告创建 Conversation、PlanMemory、Journal Observer、Prompt Context 和 Memory Worker。
4. 将 `RESTORE` 加入 ch08 触发枚举和状态报告，复用无锚点估算、Retention Planner 和 Summarizer。
5. 在完整工具 Schema 就绪后对恢复请求估算，越过自动线只先尝试一次 RESTORE 压缩，不更新普通 usage 锚点。
6. 实现 close 次序：取消/收束 Memory Worker，flush/close Journal，不删除会话和笔记。
7. 覆盖无会话、默认恢复、默认锁定新建、精确恢复失败、24 小时 reminder、RESTORE 成功/失败和 close 幂等测试。

**验证：**

```bash
.venv/bin/python -m pytest tests/unit/test_persistence_coordinator.py tests/unit/test_context_manager.py tests/unit/test_context_summarizer.py -q
```

期望 Coordinator 只协调生命周期，没有重新实现指令、JSONL 或笔记算法。

## T10：增加 CLI、Slash Command 和可观察状态

**影响文件：** `artcode/commands/builtin.py`、`artcode/runtime/app.py`、`artcode/tui/render.py`、`artcode/config.py`、`artcode/cli.py`、`tests/unit/test_commands.py`、`tests/unit/test_runtime.py`、`tests/unit/test_config.py`、`tests/unit/test_tui_app.py`、`tests/unit/test_render.py`

**依赖任务：** T9

**参考资料定位：** `spec.md` F6、F26–F27；`plan.md` “会话选择和清理”、“终端状态设计”；现有 CommandRegistry 和 TUI Renderer。

**步骤：**

1. 在 argparse 中增加互斥 `--new` 与 `--resume SESSION_ID`，把结果转换为 SessionSelection，无参数为 latest。
2. 增加 `/sessions` 和 `/memory` 及帮助文本，并由 Runtime 调用 Coordinator/Catalog 生成实时摘要。
3. 扩展 SafeConfigStatus 和启动 Panel，显示会话 ID、新建/恢复、消息数、坏行、截断、指令 issue 和两级有效笔记数。
4. 增加 Journal 持久性降级和 MemoryUpdateReport 运行期展示，只打印计数与脱敏摘要。
5. 将章节名更新为 ch09，保持 API Key mask 和现有权限/沙箱状态。
6. 覆盖 CLI 互斥、坏 ID、新命令不写入 Conversation、列表 20 条、状态不泄密和异步通知测试。

**验证：**

```bash
.venv/bin/python -m pytest tests/unit/test_commands.py tests/unit/test_runtime.py tests/unit/test_config.py tests/unit/test_tui_app.py tests/unit/test_render.py -q
```

期望用户能理解当前恢复和记忆状态，输出中无指令全文、笔记全文和认证值。

## T11：接入主流程

**影响文件：** `artcode/cli.py`、`artcode/runtime/app.py`、`artcode/agent/loop.py`、`artcode/prompting/assembler.py`、`README.md`、`tests/unit/test_persistence_coordinator.py`、`tests/unit/test_runtime.py`、`tests/unit/test_context_agent_integration.py`

**依赖任务：** T1–T10

**参考资料定位：** `spec.md` 全部功能需求；`plan.md` “架构概览”、“PersistenceCoordinator”、“错误隔离和敏感路径”；`artcode/cli.py` 现有启动/close 顺序。

**步骤：**

1. 在 `run_app` 中于 Workspace/Config 就绪后启动 PersistenceCoordinator，使用它提供的 Conversation、PlanMemory、Prompt Context 和 NaturalTurnObserver。
2. 将三份指令入口、sessions 目录和两份 memory 目录加入敏感路径，不扩大模型工具访问权限。
3. 保持现有 ArtifactStore、Seatbelt、MCP、Tool Registry、ContextManager 顺序，在工具 Schema 就绪后执行恢复预压缩。
4. 将 Prompt Context 注入 Assembler，将 NaturalTurnObserver 注入 AgentLoop，将持久查询注入 Runtime。
5. 补齐启动中途失败和正常/异常退出的反向 close 顺序，保证 Journal 解锁、Memory Worker 取消与现有 MCP/Artifact/Seatbelt 全部收尾。
6. 更新 README，说明三类记忆的区别、实际 `.artcode` 路径、`@include`、CLI 会话选择、自动更新通知、手工编辑方式和本地隐私边界。
7. 运行新增单元测试、所有现有单元测试和非 live 集成测试，修复所有回归而不放宽原断言。

**验证：**

```bash
.venv/bin/python -m pytest tests/unit -q
.venv/bin/python -m pytest tests/integration -q -k "not live"
```

期望全部主流程只创建一个活动 Journal 和一个 Memory Worker，未配置指令/笔记时旧行为保持。

## T12：端到端验证

**影响文件：** `tests/integration/test_persistence_flow.py`、`tests/integration/test_memory_deepseek_live.py`、`tests/integration/README.md`、`README.md`、`spec汇总/ch09/checklist.md`

**依赖任务：** T11

**参考资料定位：** `spec.md` AC1–AC27；`plan.md` 架构流程；`tests/integration/test_context_management_flow.py` 和 `tests/integration/test_context_management_deepseek_live.py` 的 fake/live 分层。

**步骤：**

1. 建立临时 app home 和 Workspace，写入三层指令、include 与预置用户/项目笔记。
2. 用确定性 Fake Provider 运行“新会话 → 工具调用 → 自然结束 → 异步更新 → 关闭 → 新进程默认恢复 → 继续回答”。
3. 在第一进程中模拟最后 JSONL 半行和缺失工具结果，验证第二进程只保留安全前缀并能继续追加。
4. 构造越过 ch08 自动线的恢复历史，验证先执行一次 RESTORE 摘要，完整用户原文和工具协议组仍满足 ch08 保证。
5. 模拟超过 24 小时与 30 天的会话，分别验证一次性 reminder 和未锁定过期清理。
6. 用真实 DeepSeek API 执行至少两轮：第一轮产生可验证项目知识笔记，第二轮重复相同事实并验证 LLM 更新/noop 而非重复创建。
7. 关闭并创建新 Runtime，验证第一次模型请求已包含指令、恢复历史和最新索引，模型能正确回答预埋知识。
8. 执行全量单元、集成、真实 DeepSeek、格式/编译检查，将 `checklist.md` 的每项预期改为实际证据后再标记完成。

**验证：**

```bash
.venv/bin/python -m pytest tests/integration/test_persistence_flow.py -q
.venv/bin/python -m pytest tests/integration/test_memory_deepseek_live.py -q -s
.venv/bin/python -m pytest -q
```

期望真实端到端链路完成指令加载、会话恢复、局部损坏处理、恢复压缩、异步笔记、LLM 去重和新请求继续。

## 执行顺序

```text
T1 → T2 ───────┐
 ├→ T3 → T4 ─────├→ T8 ──┐
 └→ T5 → T6 ─┐     │       ├→ T9 → T10 → T11 → T12
          └→ T7 ─┘       │
T2 ─────────────────┘
```

T2、T3 和 T5 在 T1 完成后可并行；T6 依赖笔记 Store，T7 依赖指令与索引，T8 依赖会话恢复与 Updater。Coordinator 必须在所有纯组件接口稳定后组装，主流程和端到端验证始终为最后两个任务。
