# ch10：斜杠命令系统 Tasks

## 文件清单

| 操作 | 文件 | 职责 |
|---|---|---|
| 修改 | `artcode/commands/base.py` | 命令定义、类型、执行上下文、控制协议和状态快照 |
| 新建 | `artcode/commands/parser.py` | 空输入、普通消息、斜杠命令解析 |
| 新建 | `artcode/commands/registry.py` | 统一名称/别名索引与启动冲突检测 |
| 新建 | `artcode/commands/dispatcher.py` | 未知命令处理与 handler 调用 |
| 修改 | `artcode/commands/builtin.py` | 12 个独立内置命令定义和元数据驱动帮助 |
| 修改 | `artcode/commands/__init__.py` | 新命令 API 公开导出 |
| 修改 | `artcode/runtime/app.py` | CommandController、最近 Token、状态快照和统一输入分流 |
| 修改 | `artcode/agent/loop.py` | 下一次请求的无副作用 Token 估算入口 |
| 修改 | `artcode/tui/app.py` | DisplayMode、清屏和状态渲染转发 |
| 修改 | `artcode/tui/render.py` | `[DEFAULT]/[PLAN]` 标记、清屏和状态 Panel |
| 修改 | `artcode/config.py` | ch10 章节标题 |
| 修改 | `tests/unit/test_commands.py` | 定义、解析、注册、帮助、分发和内置命令测试 |
| 修改 | `tests/unit/test_runtime.py` | 分流互斥、兼容行为、Token 与状态快照测试 |
| 修改 | `tests/unit/test_agent_loop.py` | 下一请求估算无副作用测试 |
| 修改 | `tests/unit/test_tui_app.py` | 模式、清屏和状态转发测试 |
| 修改 | `tests/unit/test_render.py` | 提示符、Plan 标签、状态字段和脱敏测试 |
| 新建 | `tests/integration/test_command_flow.py` | 命令与真实 Runtime/TUI 组件集成 |
| 新建 | `tests/integration/test_ch10_live_e2e.py` | 真实 DeepSeek Plan → Do 回归 |

## T1：定义命令模型与控制边界

**影响文件：** `artcode/commands/base.py`、`artcode/commands/__init__.py`

**依赖任务：** 无

**参考资料定位：** `spec.md` F1、F11–F15、F24；`plan.md`“核心数据结构”“命令基础类型与控制协议”。

**步骤：**

1. 用 `CommandType`、`CommandFlow` 和 `DisplayMode` 替代字符串 action。
2. 定义不可变的 `CommandDefinition`、`ParsedInput`、命令调用结构和执行上下文。
3. 定义统一异步 `CommandHandler` 签名。
4. 定义 `RuntimeStatusSnapshot` 白名单字段和 `CommandController` Protocol。
5. 暂时同时保留迁移所需导出，避免尚未完成的后续任务无法导入；在 T11 清理旧 `CommandResult`。

**验证：** 运行 `.venv/bin/python -m py_compile artcode/commands/base.py artcode/commands/__init__.py`，期望无语法和导入错误。

## T2：实现输入解析器

**影响文件：** `artcode/commands/parser.py`、`tests/unit/test_commands.py`

**依赖任务：** T1

**参考资料定位：** `spec.md` F5–F8、AC3–AC4、AC13；`plan.md`“输入解析器”。

**步骤：**

1. 实现 `parse_input`，先区分全空白、普通消息和首个非空白字符为 `/` 的命令。
2. 普通消息保留原始文本，不因首尾空白被改写。
3. 命令使用第一个空格、Tab 或换行分隔名称与参数。
4. 名称用 `lower()` 归一化；参数只去除两端空白，保留内部换行。
5. 添加空输入、句中斜杠、大小写、多种分隔符、多行参数和多行未知命令解析测试。

**验证：** 运行 `.venv/bin/python -m pytest tests/unit/test_commands.py -q -k parser`，期望解析器测试全部通过且不需要 Provider/TUI fixture。

## T3：实现注册中心和启动冲突检测

**影响文件：** `artcode/commands/registry.py`、`tests/unit/test_commands.py`

**依赖任务：** T1

**参考资料定位：** `spec.md` F1–F4、AC1–AC2；`plan.md`“注册中心”。

**步骤：**

1. 校验规范名称、aliases、描述、usage 和 handler 的基本合法性。
2. 用同一个归一化字典索引规范名称和别名，保持定义登记顺序。
3. 每次注册先预检全部标识，再一次性提交。
4. 对名称—名称、名称—别名、别名—别名、大小写差异和定义内部重复产生带双方信息的 `CommandRegistrationError`。
5. 实现按名称/别名解析和按隐藏标记枚举定义。
6. 用无冲突注册表和所有冲突组合补齐单元测试，并验证失败注册不污染既有表。

**验证：** 运行 `.venv/bin/python -m pytest tests/unit/test_commands.py -q -k registry`，期望全部通过。

## T4：实现命令分发器

**影响文件：** `artcode/commands/dispatcher.py`、`tests/unit/test_commands.py`

**依赖任务：** T1、T3

**参考资料定位：** `spec.md` F9–F11、F15、AC5、AC7；`plan.md`“命令分发器”。

**步骤：**

1. 让 dispatcher 只接收 COMMAND 解析结果和 controller，不重复解析普通输入。
2. 未命中时显示原请求名称与 `/help`，返回 `CONTINUE`。
3. 命中时构造执行上下文并 await 注册项 handler。
4. 不添加 catch-all 异常恢复，也不把未知或失败命令转发 Agent。
5. 使用 Fake Controller 验证规范名、测试 alias、未知命令、CONTINUE 和 EXIT 路径。

**验证：** 运行 `.venv/bin/python -m pytest tests/unit/test_commands.py -q -k dispatcher`，期望 Provider 和具体 TUI 均不参与测试。

## T5：登记元数据驱动的内置命令

**影响文件：** `artcode/commands/builtin.py`、`artcode/commands/__init__.py`、`tests/unit/test_commands.py`

**依赖任务：** T1、T3、T4

**参考资料定位：** `spec.md` F16–F25、Out of Scope；`plan.md`“内置命令”；`spec汇总/ch04/spec.md` 的 `/plan`、`/do`；`spec汇总/ch06/checklist.md` 的 `/permission`、`/sandbox`；`spec汇总/ch08/checklist.md` 的 `/compact`；`spec汇总/ch09/checklist.md` 的 `/sessions`、`/memory`。

**步骤：**

1. 以固定顺序创建 `/exit`、`/quit`、`/help`、`/plan`、`/do`、`/compact`、`/permission`、`/sandbox`、`/sessions`、`/memory`、`/clear`、`/status` 定义。
2. 为每条命令填满名称、空 aliases、描述、usage、类型、参数提示、hidden 和 handler。
3. 从 registry 生成 `/help` 总览和 `/help /命令` 详情，移除手写 `HELP_TEXT`。
4. 给无参数命令统一加参数拒绝；保留 `/plan` 必填和 `/do` 可选多行参数。
5. Plan/Do handler 只调用 Controller 的 PlanMemory 与 Agent 能力，不重新实现 AgentLoop。
6. 确认没有 `/session`、`/review`、隐藏内置命令或 Tab 补全定义。

**验证：** 运行 `.venv/bin/python -m pytest tests/unit/test_commands.py -q -k "builtin or help"`，期望 12 个定义的名称、类型、usage 和处理路径全部通过。

## T6：实现模式、清屏和状态渲染

**影响文件：** `artcode/tui/app.py`、`artcode/tui/render.py`、`tests/unit/test_tui_app.py`、`tests/unit/test_render.py`

**依赖任务：** T1

**参考资料定位：** `spec.md` F12–F13、F23–F24、AC8、AC10–AC11；`plan.md`“TUI 控制与渲染”。

**步骤：**

1. 在 TUI 中保存默认 `DisplayMode.DEFAULT`，提供设置模式方法。
2. 让输入提示符始终包含当前标记，并让助手标签在 Plan 请求期间显示 `[PLAN]`。
3. 添加 `clear_screen()`，只调用 Rich Console 清屏，不替换 PromptSession。
4. 添加固定字段的 Runtime 状态 Panel，缺失 Token 或估算值显示“不可用”。
5. 更新 Fake Renderer/Session 测试，验证模式切换、清屏转发、中文/英文状态字段和脱敏。

**验证：** 运行 `.venv/bin/python -m pytest tests/unit/test_tui_app.py tests/unit/test_render.py -q`，期望全部通过。

## T7：提供无副作用的上下文估算

**影响文件：** `artcode/agent/loop.py`、`tests/unit/test_agent_loop.py`

**依赖任务：** 无

**参考资料定位：** `spec.md` F24、N2–N3；`plan.md`“Agent 请求估算”“RuntimeStatusSnapshot”。

**步骤：**

1. 增加按 AgentMode 组装下一次请求并调用现有 ContextManager estimator 的只读入口。
2. ContextManager 缺失时返回不可用。
3. 确保估算使用真实 Prompt Assembler 和当前工具列表。
4. 添加 Spy 测试，证明估算不追加消息、不运行压缩、不更新 anchor、不调用 Provider。
5. 对 Default 与 Plan 工具列表差异分别断言估算走对应请求形状。

**验证：** 运行 `.venv/bin/python -m pytest tests/unit/test_agent_loop.py -q -k estimate`，期望无副作用断言全部通过。

## T8：让 Runtime 实现 CommandController

**影响文件：** `artcode/runtime/app.py`、`tests/unit/test_runtime.py`

**依赖任务：** T1、T6、T7

**参考资料定位：** `spec.md` F12–F15、F18–F24；`plan.md`“Runtime 命令控制与主分流”。

**步骤：**

1. 增加当前 DisplayMode 与最近 `TokenUsage` 两份进程内状态。
2. 实现显示、清屏、模式切换、Token 查询和状态刷新控制方法。
3. 将现有 compact、permission、sandbox、sessions、memory 和最近计划行为暴露为 Controller 方法，保持原实现逻辑与提示。
4. 在 TOKEN_USAGE 事件路径中先保存最近真实 usage，再继续现有即时显示。
5. 构造 `RuntimeStatusSnapshot`，只从白名单领域状态读取数据，并调用 TUI 状态方法。
6. 为缺少 ContextManager/Persistence/usage 和完整真实状态两种情况添加测试。

**验证：** 运行 `.venv/bin/python -m pytest tests/unit/test_runtime.py -q -k "status or token or permission or sandbox or persistence"`，期望全部通过。

## T9：完成命令核心单元测试矩阵

**影响文件：** `tests/unit/test_commands.py`

**依赖任务：** T2、T3、T4、T5

**参考资料定位：** `spec.md` AC1–AC7、AC12–AC13；`plan.md`“技术决策”。

**步骤：**

1. 参数化 12 个内置命令的名称、空 aliases、类型、隐藏状态和用法。
2. 覆盖 `/help` 总览、详情、隐藏测试定义和未知详情。
3. 覆盖所有无参数命令的多余参数拒绝，Plan 必填和 Do 可选多行参数。
4. 使用 Fake Controller 统计每种调用，证明命令只调用预期控制能力。
5. 验证测试 alias 可分发，但内置 registry 没有 alias。
6. 验证未知、多行未知和参数错误都不会调用发送用户消息能力。

**验证：** 运行 `.venv/bin/python -m pytest tests/unit/test_commands.py -q`，期望全文件通过。

## T10：完成 Runtime 与 TUI 回归测试

**影响文件：** `tests/unit/test_runtime.py`、`tests/unit/test_tui_app.py`、`tests/unit/test_render.py`、`tests/unit/test_agent_loop.py`

**依赖任务：** T6、T7、T8、T9

**参考资料定位：** `spec.md` AC8–AC12；ch04/ch06/ch08/ch09 既有对应测试。

**步骤：**

1. 更新 FakeTui 以实现新的模式、清屏和状态方法。
2. 保留并修复 `/plan → /do`、`/compact`、权限、沙箱、sessions 和 memory 既有断言。
3. 添加 `/clear` 前后 Conversation、PlanMemory、Persistence 和 Token 状态对象不变的断言。
4. 添加 `/status` 缺失/存在 usage、上下文估算、模式和秘密探针断言。
5. 验证 Plan 请求期间 `[PLAN]`，异常或取消后也恢复 `[DEFAULT]`。
6. 验证所有非 AI/compact 命令的 Provider 调用数为零。

**验证：** 运行 `.venv/bin/python -m pytest tests/unit/test_runtime.py tests/unit/test_tui_app.py tests/unit/test_render.py tests/unit/test_agent_loop.py -q`，期望全部通过。

## T11：接入主流程

**影响文件：** `artcode/runtime/app.py`、`artcode/commands/__init__.py`、`artcode/config.py`、现有受影响测试 fixtures

**依赖任务：** T2–T10

**参考资料定位：** `spec.md` F2、F5–F10、F13–F15；`plan.md`“架构概览”“Runtime 命令控制与主分流”“公开导出与章节状态”。

**步骤：**

1. 在 Runtime 构造期完成默认 registry、parser 和 dispatcher 创建，保证冲突发生在首次输入前。
2. 将 `run()` 改成只处理 EMPTY、MESSAGE、COMMAND 三种 route。
3. COMMAND 只进入 dispatcher；MESSAGE 只进入 Default Agent；EXIT 统一结束循环。
4. 删除旧 `CommandResult`、字符串 action 和 Runtime 命令条件分支。
5. 用 `try/finally` 管理请求级 DisplayMode，确保 Plan、Do、普通请求、取消和异常都恢复 DEFAULT。
6. 更新章节标题和公开导出，不增加配置或依赖。
7. 修复所有 FakeTui、测试构造器和类型引用，确保项目只有一套命令入口。

**验证：** 运行 `.venv/bin/python -m pytest tests/unit -q`，期望全部单元测试通过；再运行 `rg -n "CommandResult|command_result.action|HELP_TEXT" artcode tests`，期望没有旧分发实现残留。

## T12：端到端验证

**影响文件：** `tests/integration/test_command_flow.py`、`tests/integration/test_ch10_live_e2e.py`、`spec汇总/ch10/checklist.md`

**依赖任务：** T11

**参考资料定位：** `spec.md` AC3、AC5、AC8–AC14；`plan.md`“模块交互”；`tests/integration/test_agent_loop_flow.py`、`tests/integration/test_ch06_live_e2e.py` 的既有测试风格。

**步骤：**

1. 新增确定性集成场景：“普通消息 → 未知多行命令 → status → clear → exit”，断言只有普通消息调用 Provider，命令不进入 Conversation/JSONL。
2. 新增确定性兼容场景：“多行 `/plan` → `/do` → `/compact` → `/sessions` → `/memory`”，验证模式、PlanMemory、压缩和持久状态仍工作。
3. 使用真实 TUI Renderer 的记录 Console 验证 `[DEFAULT]`、`[PLAN]`、清屏控制和脱敏状态字段。
4. 新增真实 DeepSeek `/plan → /do` 场景，要求先只读规划、再完成一个受控 Workspace 文件任务并验证结果。
5. 运行全部非 live 集成测试，再按项目规则运行真实 Seatbelt、MCP（环境可用部分）和 DeepSeek live 测试。
6. 运行全量测试、构建 wheel 并在临时环境安装启动，确认无新增依赖、资源或导入遗漏。
7. 按实际命令输出逐项更新 checklist，任何失败修复后重新执行对应验证。

**验证：** 依次运行：

```text
.venv/bin/python -m pytest tests/integration -q -k "not live"
.venv/bin/python -m pytest tests/integration/test_ch10_live_e2e.py -q -rs
.venv/bin/python -m pytest -q
.venv/bin/python -m build
```

期望确定性测试、真实 DeepSeek 场景、全量测试和 wheel 构建全部通过；若某项因真实外部服务失败，记录实际错误，不能以 API 成本为由跳过。

## 执行顺序

```text
T1 ─┬→ T2 ───────────────┐
    ├→ T3 → T4 → T5 → T9├→ T10 → T11（接入主流程）→ T12（端到端验证）
    └→ T6 ─┬─────────────┘
           └→ T8 ─────────┘
T7 ─────────→ T8
```

T2、T3、T6 在 T1 完成后可并行，T7 可以独立开始；T9 聚合命令核心测试，T10 聚合 Runtime/TUI 回归，最终只由 T11 替换主流程，T12 执行完整验收。
