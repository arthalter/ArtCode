# ch06：权限系统 Tasks

## 文件清单

| 操作 | 文件 | 职责 |
|---|---|---|
| 新建 | `artcode/workspace.py` | ArtCode Home、Workspace 与敏感路径模型 |
| 修改 | `artcode/config.py`、`artcode/cli.py` | 用户级主配置、Workspace 参数和安全启动 |
| 移动 | `artcode.example.yaml` → `config.example.yml` | 新的用户级配置模板 |
| 新建 | `artcode/permissions/` | 权限类型、Glob、三层规则、写入器和决策引擎 |
| 新建 | `artcode/security/dangerous_commands.yml` | 内置危险命令规则与原因 |
| 新建 | `artcode/security/commands.py` | 危险规则加载和 Workspace 动态检查 |
| 新建 | `artcode/sandbox/seatbelt.sb` | macOS Seatbelt Profile 模板 |
| 新建 | `artcode/sandbox/seatbelt.py` | Profile 生成、自检、执行参数和生命周期 |
| 修改 | `artcode/tools/` | 单 Workspace、敏感路径、权限结果和受控 Shell |
| 修改 | `artcode/agent/` | 权限事件、逐工具审批与 Agent Loop 接入 |
| 修改 | `artcode/commands/builtin.py` | `/permission` 与 `/sandbox` |
| 修改 | `artcode/runtime/app.py` | 权限状态、Slash Command 与审批编排 |
| 修改 | `artcode/prompting/` | Workspace 和权限状态动态提醒 |
| 修改 | `artcode/tui/` | 启动状态、四选项 HITL 和风险确认 |
| 修改 | `pyproject.toml`、`README.md` | 资源打包与 ch06 使用说明 |
| 新建/修改 | `tests/unit/`、`tests/integration/` | 权限、Seatbelt、主流程与真实验收 |

## T1：建立 ArtCode Home 与 Workspace

**影响文件：** `artcode/workspace.py`、`artcode/config.py`、`artcode/cli.py`、`artcode.example.yaml`、`config.example.yml`、`tests/unit/test_workspace.py`、`tests/unit/test_config.py`

**依赖任务：** 无

**参考资料定位：** `spec.md` F1-F6、AC1-AC9；现有 `artcode/config.py` 的 `DEFAULT_ALLOWED_DIR`、`ToolConfig`、`tools.allowed_dirs`；现有 `artcode/cli.py`

**任务内容：**

1. 定义不可变应用路径对象，集中提供 `~/.artcode/`、主配置、用户权限和 Skills 路径。
2. 定义不可变 Workspace 对象，保存规范真实根路径及项目级、本地级权限文件位置。
3. 首次启动创建 ArtCode Home 和 Skills 目录，但不自动创建 Workspace。
4. 默认 Workspace 使用启动时当前目录，并支持 `--workspace` 覆盖。
5. 校验 Workspace 已存在、是目录且可解析，启动后不提供切换接口。
6. 默认配置改为 `~/.artcode/config.yml`，停止读取 Workspace 中的旧 `artcode.yaml`。
7. 删除 `ToolConfig`、`DEFAULT_ALLOWED_DIR` 和 `tools.allowed_dirs` 相关实现。
8. 将示例移动为 `config.example.yml`，说明复制目标并保留 Provider、模型、认证和 Thinking 配置。

**验证：** 运行 `python3 -m pytest tests/unit/test_workspace.py tests/unit/test_config.py`，期望 Home 自动创建、Workspace 默认值与参数覆盖正确、非法 Workspace 启动失败、旧 allowed_dirs 断言全部移除。

## T2：改造单 Workspace 路径与敏感路径边界

**影响文件：** `artcode/tools/policy.py`、`artcode/tools/base.py`、`artcode/tools/file_tools.py`、`tests/unit/test_tool_policy.py`、`tests/unit/test_file_tools.py`

**依赖任务：** T1

**参考资料定位：** `spec.md` F10-F18、AC31-AC41；现有 `AllowedPathPolicy`、`ToolExecutionContext` 和五个文件工具

**任务内容：**

1. 将多允许目录策略改为单一 Workspace 根路径，并提供真实路径和 Workspace 相对路径转换。
2. 已有路径解析真实目标，新文件解析真实父目录，再执行安全的路径包含判断。
3. 增加敏感路径策略，将主配置、三层权限文件、Skills、危险规则、Seatbelt 模板和生成 Profile 设为读写双禁。
4. 让读取、写入和编辑工具在 prepare 阶段完成 Workspace 与敏感路径检查。
5. 让查找和搜索只扫描 Workspace，不跟随指向外部或敏感路径的符号链接。
6. 为 `find_files` 提供明确扫描起始范围，使规则能够匹配实际扫描路径。
7. 工具预览使用规范 Workspace 相对目标，执行参数保留真实路径。
8. 将旧 allowed_dirs 错误迁移为 Workspace 越界或敏感路径结构化错误。

**验证：** 运行 `python3 -m pytest tests/unit/test_tool_policy.py tests/unit/test_file_tools.py tests/unit/test_workspace.py`，期望 Workspace 内路径成功，`..`、外部符号链接、新文件父目录逃逸和敏感路径均在副作用前失败。

## T3：定义权限状态、决策矩阵与审批类型

**影响文件：** `artcode/permissions/models.py`、`artcode/permissions/__init__.py`、`artcode/agent/modes.py`、`tests/unit/test_permission_engine.py`、`tests/unit/test_agent_modes.py`

**依赖任务：** T1

**参考资料定位：** `spec.md` F7-F10、F41-F56、AC10-AC30；现有 `AgentMode` 和 `ToolAccessPolicy`

**任务内容：**

1. 定义 ALLOW、ASK、DENY、NO_MATCH 决策，限制 NO_MATCH 只用于规则查询。
2. 定义 Default、Edit、Full 权限模式并编码五个文件工具的默认矩阵。
3. 定义 Sandbox Auto、Sandbox Ask、Unsandboxed Ask 及默认命令决策。
4. 定义进程内权限状态，启动值为 Default 与 Sandbox Auto。
5. 定义权限请求、规则来源、审批摘要和四种 HITL 选择。
6. 保留 Plan 工具列表硬过滤，并明确它独立于三种权限模式。
7. 用参数化测试覆盖三种模式、三种 Shell 策略和 Plan 不可提升行为。

**验证：** 运行 `python3 -m pytest tests/unit/test_permission_engine.py tests/unit/test_agent_modes.py`，期望全部矩阵与 `spec.md` 一致。

## T4：实现权限表达式与 Gitignore 风格 Glob

**影响文件：** `artcode/permissions/glob.py`、`artcode/permissions/rules.py`、`tests/unit/test_permission_glob.py`、`tests/unit/test_permission_rules.py`

**依赖任务：** T3

**参考资料定位：** `spec.md` F28-F34、AC59-AC66；规则形式 `工具名(pattern)`

**任务内容：**

1. 使用第一个左括号和最后一个右括号解析 `工具名(pattern)`。
2. 校验工具名属于六个核心工具，pattern 非空，action 只接受三种值。
3. 实现区分大小写的路径 Glob：`*` 不跨 `/`、`**` 可跨目录，并支持 `?` 与字符集合。
4. 文件目标统一匹配 Workspace 相对 POSIX 路径。
5. 命令只移除首尾空白，再对完整文本进行 Glob 匹配。
6. 覆盖内部括号、非法表达式、目录边界、大小写和完整命令测试。

**验证：** 运行 `python3 -m pytest tests/unit/test_permission_glob.py tests/unit/test_permission_rules.py`，期望精简 Gitignore 语义和非法格式处理稳定。

## T5：实现三层规则加载、合并、热重载与本地写入

**影响文件：** `artcode/permissions/rules.py`、`artcode/permissions/writer.py`、`tests/unit/test_permission_rules.py`、`tests/unit/test_permission_writer.py`

**依赖任务：** T1、T4

**参考资料定位：** `spec.md` F25-F40、F57-F61、AC53-AC71、AC76-AC82

**任务内容：**

1. 从用户级、项目级、本地级固定位置加载有序 `rules` 列表，缺失文件返回空层级。
2. 启动时校验全部已有文件，每次工具调用前重新读取三层规则。
3. 每层取最后一条匹配规则作为该层有效结果。
4. 任意层有效 DENY 时返回 DENY；否则按本地、项目、用户选择首个 ALLOW/ASK；全部未匹配返回 NO_MATCH。
5. 将读取、YAML、字段、表达式和 action 错误统一包装为带文件位置的规则错误。
6. 使用临时文件写完、校验和原子替换更新本地规则。
7. 长期决定生成精确 match；相同 match 更新 action、移动到末尾且不重复。
8. 不保留注释和排版，只保证规则语义与顺序。

**验证：** 运行 `python3 -m pytest tests/unit/test_permission_rules.py tests/unit/test_permission_writer.py`，期望热重载、同级后者优先、跨层 DENY、层级优先、精确更新和统一错误通过。

## T6：建立不可绕过的危险命令层

**影响文件：** `artcode/security/dangerous_commands.yml`、`artcode/security/commands.py`、`artcode/security/__init__.py`、`artcode/tools/command_tool.py`、`pyproject.toml`、`tests/unit/test_dangerous_commands.py`、`tests/unit/test_command_tool.py`

**依赖任务：** T1、T3

**参考资料定位：** `spec.md` F19-F24、AC42-AC52；用户提供的基础正则表；现有 `validate_shell_command`

**任务内容：**

1. 内置 YAML 每条规则保存稳定 ID、正则和拒绝原因。
2. 迁移根目录删除、磁盘格式化、设备写入、根权限修改、fork bomb 和远程脚本管道规则。
3. 补充 `diskutil`、`newfs_*`、`/dev/disk*`、`/dev/rdisk*`。
4. 根据规范 Workspace 动态检查整体删除目标。
5. 补充约定的 Git 强制清理和整体回滚规则。
6. 启动时加载并编译正则，内置文件或正则错误使启动失败。
7. 在规则查询与模式判断前执行危险检查。
8. 拒绝结果包含规则 ID 和原因，并将内置 YAML 纳入包数据。

**验证：** 运行 `python3 -m pytest tests/unit/test_dangerous_commands.py tests/unit/test_command_tool.py`，期望基准危险命令和四类补充规则被拒绝，普通命令不误报。

## T7：实现 Seatbelt Profile 生命周期

**影响文件：** `artcode/sandbox/seatbelt.sb`、`artcode/sandbox/seatbelt.py`、`artcode/sandbox/__init__.py`、`pyproject.toml`、`tests/unit/test_seatbelt.py`

**依赖任务：** T1、T2

**参考资料定位：** `spec.md` F65-F71、F75、AC86-AC98；本机 `sandbox-exec(1)` 与 `sandbox(7)` 手册

**任务内容：**

1. 编写默认拒绝模板，允许程序执行、子进程和普通文件读取。
2. 只允许写入 Workspace 与本次运行专用临时目录。
3. 对敏感路径设置读写双禁，并禁止外网、局域网和回环网络。
4. 安全转义动态路径并生成 Profile 到专用临时目录。
5. 启动时检测 `/usr/bin/sandbox-exec`，缺失即启动失败。
6. 使用生成 Profile 运行 `/usr/bin/true` 自检，失败时提供简短原因和路径。
7. 当前进程复用同一 Profile，退出时尽量清理。
8. 将模板纳入包数据，并将已弃用接口细节集中在本模块。

**验证：** 运行 `python3 -m pytest tests/unit/test_seatbelt.py`，期望打包、转义、生成、自检、失败关闭和生命周期测试通过。

## T8：重构受控 Shell 执行器

**影响文件：** `artcode/tools/base.py`、`artcode/tools/command_tool.py`、`artcode/tools/results.py`、`tests/unit/test_command_tool.py`、`tests/unit/test_tool_results.py`

**依赖任务：** T3、T6、T7

**参考资料定位：** `spec.md` F46-F51、F64、F72-F76、AC21-AC30、AC99-AC104；现有 `RunCommandTool.execute`

**任务内容：**

1. 固定使用 `/bin/zsh -f -c`，不再调用默认 `create_subprocess_shell`。
2. 构造安全环境变量白名单，将 `TMPDIR` 指向专用临时目录并排除秘密变量。
3. Sandbox Auto/Ask 使用 `sandbox-exec -f`；Unsandboxed Ask 直接启动 zsh。
4. 使用独立进程组启动，固定 10 秒超时后终止整个进程组并回收。
5. 保留 stdout、stderr、退出码、20KB 截断和结构化错误。
6. Profile 丢失、损坏或启动失败时停止命令，不降级。
7. cwd 默认 Workspace，显式 cwd 必须位于 Workspace。
8. 覆盖环境泄漏、Shell 参数、沙箱/无沙箱形状、进程组超时和不降级测试。

**验证：** 运行 `python3 -m pytest tests/unit/test_command_tool.py tests/unit/test_tool_results.py tests/unit/test_seatbelt.py`，期望固定 zsh、安全环境、两种执行形状和超时进程组通过。

## T9：实现统一权限引擎

**影响文件：** `artcode/permissions/engine.py`、`artcode/permissions/models.py`、`artcode/tools/base.py`、`tests/unit/test_permission_engine.py`

**依赖任务：** T2、T3、T5、T6

**参考资料定位：** `spec.md` F7-F10、F15、F19、F35-F50、AC10-AC16、AC30、AC40-AC43、AC67-AC71

**任务内容：**

1. 从 PreparedToolCall 构造标准权限请求，携带工具类别、规范目标、Workspace、Plan 和运行状态。
2. 固定执行 Plan 硬限制、危险命令、Workspace 与敏感路径硬检查。
3. 通过硬边界后重新加载并查询三层规则。
4. 规则 ALLOW/ASK/DENY 直接采用；NO_MATCH 时由文件模式或 Shell 策略兜底。
5. 生成可解释来源，区分硬拒绝、规则文件与顺序、模式和 Shell 策略。
6. 规则文件错误返回独立错误，不伪装成用户拒绝，也不进入 HITL。
7. 参数化覆盖六工具、三模式、三 Shell 策略、Plan、层级冲突和短路顺序。

**验证：** 运行 `python3 -m pytest tests/unit/test_permission_engine.py tests/unit/test_permission_rules.py tests/unit/test_dangerous_commands.py`，期望完整矩阵和首层短路通过。

## T10：接入逐工具审批与四选项 HITL

**影响文件：** `artcode/agent/events.py`、`artcode/agent/tools.py`、`artcode/agent/loop.py`、`artcode/tui/app.py`、`artcode/tui/render.py`、相关 Agent 与 TUI 单元测试

**依赖任务：** T5、T8、T9

**参考资料定位：** `spec.md` F54-F63、F80、AC72-AC85；现有 `ToolBatchExecutor` 与 `confirm_tool_execution`

**任务内容：**

1. 定义与具体 TUI 解耦的异步审批接口，允许测试注入假审批器。
2. ToolBatchExecutor 先 prepare，再按模型原始顺序逐项权限判断。
3. ASK 展示完整摘要并接收仅本次允许、仅本次禁止、都允许、都禁止。
4. 长期选择通过可信 RuleWriter 更新本地规则，写入失败时停止当前工具。
5. 被拒绝工具产生结构化结果，其他工具继续判断，全部结果保持原顺序。
6. 已批准的相邻只读工具仍可并发，有副作用工具保持串行。
7. HITL 等待期间不执行工具、不启动后续工具或模型请求。
8. HITL 中 `Ctrl+C` 传播取消，停止整个 Agent Loop 且不写规则。
9. 增加权限请求、决定和错误事件，Runtime/TUI 只消费结构化字段。

**验证：** 运行 `python3 -m pytest tests/unit/test_agent_events.py tests/unit/test_agent_tools.py tests/unit/test_agent_loop.py tests/unit/test_tui_app.py tests/unit/test_render.py`，期望四选项、顺序审批、拒绝后继续、规则失败、并发和取消通过。

## T11：增加权限与沙箱 Slash Commands

**影响文件：** `artcode/commands/builtin.py`、`artcode/runtime/app.py`、`artcode/tui/app.py`、`artcode/tui/render.py`、`tests/unit/test_commands.py`、`tests/unit/test_runtime.py`、`tests/unit/test_render.py`

**依赖任务：** T3、T7、T10

**参考资料定位：** `spec.md` F51-F53、F77、AC17-AC29、AC105；现有 Slash Command Registry

**任务内容：**

1. 增加 `/permission default|edit|full`，无参数时展示当前值和可选值。
2. 增加 `/sandbox auto|ask|off`，无参数时展示当前值和可选值。
3. `/sandbox off` 展示风险并确认后才切换。
4. 状态只保存在当前 Runtime，不写主配置或权限文件。
5. 更新 `/help`，保持未知 Slash 输入不误触发现有命令。
6. 启动状态展示 Workspace、权限模式、Shell 策略和 Seatbelt 自检。

**验证：** 运行 `python3 -m pytest tests/unit/test_commands.py tests/unit/test_runtime.py tests/unit/test_render.py`，期望查询、切换、关闭确认、启动默认值和不持久化通过。

## T12：更新动态提醒与安全文档

**影响文件：** `artcode/prompting/reminder.py`、`artcode/prompting/assembler.py`、`artcode/runtime/app.py`、`README.md`、`tests/unit/test_system_reminder.py`、`tests/unit/test_prompt_assembler.py`、`tests/unit/test_prompt_sections.py`

**依赖任务：** T1、T3、T9、T11

**参考资料定位：** `spec.md` F77-F80、AC105-AC108；ch05 的 `SystemReminderBuilder` 与 Prompt Cache 要求

**任务内容：**

1. 将 `cwd` 与 `allowed_dirs` 改为单一 Workspace。
2. 每轮提醒加入 Plan、权限模式、Shell 策略、通常 ALLOW/ASK 的工具类别和敏感边界。
3. 保持提醒只进入本次请求，不写 Conversation Context，不改变稳定 System Prompt。
4. 模式或 Shell 策略切换后，下一轮使用最新状态。
5. README 说明 Home、Workspace、规则、模式、HITL、Seatbelt 前提和无沙箱风险。
6. 明确 `sandbox-exec` 已弃用且本章仅用于本地 macOS 学习。

**验证：** 运行 `python3 -m pytest tests/unit/test_system_reminder.py tests/unit/test_prompt_assembler.py tests/unit/test_prompt_sections.py`，期望动态权限状态完整、历史不污染、Plan 过滤与稳定 Prompt 回归通过。

## T13：接入主流程

**影响文件：** `artcode/cli.py`、`artcode/runtime/app.py`、`artcode/agent/loop.py`、`artcode/agent/tools.py`、各公开 `__init__.py`、相关单元与集成测试

**依赖任务：** T1-T12

**参考资料定位：** `spec.md` 全部功能需求；现有 `run_app`、`ArtCodeRuntime.__post_init__`、`AgentLoop`、`ToolBatchExecutor`

**任务内容：**

1. CLI 依次初始化 Home、Workspace、配置、规则校验、危险命令库、专用临时目录和 Seatbelt 自检。
2. 将 Workspace、敏感策略、权限状态、规则服务、Seatbelt 和审批接口注入 Runtime、Agent Loop 与工具执行器。
3. Plan 继续硬过滤写工具，Normal 与 Do 使用当前权限状态。
4. 每个工具在副作用前经过硬边界、规则、模式兜底和必要 HITL。
5. Sandbox Auto/Ask 的 ALLOW 命令只能进入 Seatbelt，Off 只能来自确认切换。
6. 清理旧 allowed_dirs、默认实验场和不再使用的确认直连逻辑。
7. 更新公开导出与测试 fixtures，使所有调用方使用同一 Workspace 权限上下文。
8. 修复 ch02-ch05 回归，不改变 12 轮上限、Prompt Cache、Plan Memory 和 `/do`。

**验证：** 运行 `python3 -m pytest tests/unit`；再运行 `python3 -m pytest tests/integration/test_agent_loop_flow.py tests/integration/test_tool_flow.py tests/integration/test_permissions_flow.py`，期望全部通过。

## T14：端到端验证

**影响文件：** `tests/integration/test_permissions_flow.py`、`tests/integration/test_seatbelt_live.py`、`tests/integration/test_deepseek_live.py`、`tests/integration/README.md`、`README.md`、`checklist.md`

**依赖任务：** T13

**参考资料定位：** `spec.md` AC1-AC111；真实 macOS `sandbox-exec`；项目真实 API 测试约定

**任务内容：**

1. 临时 Workspace 验证默认启动、Workspace 参数、三层规则热重载和错误失败关闭。
2. 端到端验证三种权限模式与三种 Shell 策略的关键组合。
3. Fake Provider 验证四选项 HITL、精确本地规则、相同 match 移末尾、多工具审批、拒绝回灌和取消。
4. 真实 Seatbelt 验证 Workspace 与专用临时目录可写、外部不可写、敏感路径不可读写。
5. 真实验证外网、局域网、localhost 被拒绝，子进程继承限制。
6. 真实验证危险命令、固定 zsh、安全环境变量和超时进程组终止。
7. 真实 DeepSeek API 运行读取场景和需要权限决策的 Agent Loop。
8. 运行真实 Prompt Cache 测试，确认动态权限提醒不破坏缓存和上下文。
9. 执行完整测试并按 `checklist.md` 记录证据；任何 Seatbelt 硬验收失败都不得标记完成。

**验证：** 在 macOS 且真实 API 配置可用时运行 `python3 -m pytest`，期望单元、集成、真实 Seatbelt、真实 DeepSeek 和 Prompt Cache 全部通过；随后逐项执行 `checklist.md`。

## 执行顺序

```text
T1 ─┬─→ T2 ───────────────┐
    ├─→ T3 → T4 → T5 ────┤
    └────────→ T6 ────────┤

T2 → T7 → T8 ─────────────┤
T2 + T3 + T5 + T6 → T9 ──┤
T5 + T8 + T9 → T10 ──────┤
T3 + T7 + T10 → T11 ─────┤
T1 + T3 + T9 + T11 → T12 ┤
                           ↓
                          T13
                           ↓
                          T14
```
