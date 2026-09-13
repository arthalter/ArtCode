# ch10：斜杠命令系统 Plan

## 架构概览

ch10 在现有输入循环前增加一条明确的“解析—查找—分发”链路，并把当前依赖字符串 `action` 的 Runtime 条件分支改成注册项直接调用处理函数：

```text
PromptToolkit 取得原始输入
  ↓
CommandParser
  ├─ EMPTY   → 直接读取下一次输入
  ├─ MESSAGE → Runtime 以 Default 模式启动普通 Agent
  └─ COMMAND → CommandDispatcher
                   ↓
              CommandRegistry.resolve
                ├─ 未命中 → 本地错误 + /help
                └─ 命中   → CommandDefinition.handler
                                  ↓
                           CommandController（由 Runtime 实现）
                             ├─ 显示/清屏/刷新状态
                             ├─ 查询或切换运行状态
                             ├─ 手动压缩
                             └─ Plan/Do Agent 请求
```

命令包只依赖抽象控制接口，不导入 Rich 或 Prompt Toolkit。`ArtCodeRuntime` 结构化实现控制接口，将命令动作转给 TUI、AgentLoop、PermissionState、PersistenceCoordinator 和 ContextManager。这样内置命令可以使用 Fake Controller 独立测试，而 Runtime 主循环不再知道每个命令名称。

本章不引入持久 Agent 模式。显示模式只在一次请求的生命周期内变化：等待普通输入和 Do 请求使用 `[DEFAULT]`，Plan 请求从开始到结束使用 `[PLAN]`，最终在 `finally` 中恢复 `[DEFAULT]`。

## 核心数据结构

### `CommandType`

字符串枚举，固定三个值：

- `LOCAL`：由本地分发器处理，不进入普通 Agent；`/compact` 虽可能调用摘要 Provider，仍属于该类。
- `UI_STATE`：清理界面或查询、修改当前运行状态。
- `AI`：把命令参数或最近计划转换为 Agent 用户请求。

该字段用于帮助展示、测试断言和未来扩展，不参与权限决策。

### `CommandDefinition`

不可变命令定义：

```python
@dataclass(frozen=True)
class CommandDefinition:
    name: str
    aliases: tuple[str, ...]
    description: str
    usage: tuple[str, ...]
    command_type: CommandType
    handler: CommandHandler
    argument_hint: str | None = None
    hidden: bool = False
```

约束：

- `name` 和每个 alias 都必须是以 `/` 开头、不含空白的非空标识。
- 描述与用法必须非空，避免注册出无法生成帮助的命令。
- 内置定义全部使用空 aliases；`/exit` 与 `/quit` 是两个定义。
- 注册中心不修改传入定义，所有查找使用归一化索引。

### `ParsedInput`

不可变解析结果，携带 `route`、普通消息原文或命令调用。`route` 固定为 `EMPTY`、`MESSAGE`、`COMMAND`。命令调用包含用户输入的命令标识、归一化标识、参数文本和原始输入，便于错误提示与测试，但不得整体写入 Conversation。

### `CommandFlow`

处理函数只返回 `CONTINUE` 或 `EXIT`。普通消息与 Plan/Do 的 Agent 调用由控制器执行，Runtime 主循环只需判断是否退出，不再分支判断 `plan`、`compact` 等字符串动作。

### `CommandExecutionContext`

每次分发创建的轻量上下文，包含当前 `CommandRegistry` 和一个 `CommandController`。帮助处理函数使用 registry 读取元数据，其余处理函数只使用 controller。

### `CommandController`

使用 `Protocol` 描述命令可以调用的应用能力，由 `ArtCodeRuntime` 结构化实现：

```python
class CommandController(Protocol):
    def show_command_message(self, message: str) -> None: ...
    def clear_screen(self) -> None: ...
    def set_display_mode(self, mode: DisplayMode) -> None: ...
    def get_token_usage(self) -> TokenUsage | None: ...
    def refresh_status(self) -> None: ...

    async def send_user_message(self, content: str, mode: AgentMode) -> None: ...
    async def compact_context(self) -> None: ...
    def get_recent_plan(self) -> str | None: ...
    def handle_permission(self, argument: str) -> None: ...
    async def handle_sandbox(self, argument: str) -> None: ...
    def show_sessions(self) -> None: ...
    def show_memory(self) -> None: ...
```

这些方法表达应用能力而非渲染细节。命令处理函数不访问 `TuiRenderer.console`、Prompt Toolkit session 或 Runtime 私有字段。

### `DisplayMode`

界面枚举只包含 `DEFAULT` 和 `PLAN`。它与 `AgentMode` 不合并：Agent 仍保留 Normal、Plan、Do 三种请求策略，而界面按用户确认只显示 `[DEFAULT]` 与 `[PLAN]`。

### `RuntimeStatusSnapshot`

不可变脱敏快照，字段固定为：

- `model`
- `workspace`
- `display_mode`
- `permission_mode`
- `shell_policy`
- `seatbelt_status`
- `session_id`
- `session_state`
- `estimated_context_tokens`
- `context_window_tokens`
- `last_token_usage`

Token 用量沿用 Agent 事件中的真实 `TokenUsage`；Runtime 每次收到 `TOKEN_USAGE` 时覆盖保存最近一份。上下文估算由 AgentLoop 提供只读的“下一次 Default 请求估算”，复用 ch08 的 Prompt 组装、工具列表和 TokenEstimator，不发送 Provider 请求。缺少 ContextManager、Persistence 或真实 usage 时使用 `None`，渲染为“不可用”。

## 模块设计

### 命令基础类型与控制协议

**文件：** `artcode/commands/base.py`

**职责：**

- 定义 `CommandType`、`CommandDefinition`、`CommandHandler`、`CommandFlow`、`CommandExecutionContext`。
- 定义 `CommandController`、`DisplayMode` 和 `RuntimeStatusSnapshot`。
- 只声明稳定数据与协议，不实现具体命令、不导入 TUI 框架。

**错误边界：** 无效定义由注册中心拒绝；运行期处理函数不增加通用异常包装，保持实现简单。

### 输入解析器

**文件：** `artcode/commands/parser.py`

**职责：**

- `parse_input(raw: str) -> ParsedInput` 先用 `strip()` 判断空输入。
- 用 `lstrip()` 后的第一个字符判断是否为命令；普通消息返回未经修改的 `raw`。
- 对命令文本使用一次无参数空白切分，空格、Tab 和换行都可结束命令名。
- 命令名用 `lower()` 归一化；参数只去除两端空白，内部空格和换行不变。
- 所有首个非空白字符为 `/` 的输入都返回 `COMMAND`，解析器不判断命令是否存在。

**固定边界：** `/unknown\n下一行` 是未知命令调用，不是普通消息；`请解释 /help` 是普通消息。

### 注册中心

**文件：** `artcode/commands/registry.py`

**职责：**

- 按登记顺序保存 `CommandDefinition`，供帮助稳定展示。
- 使用一个 `dict[str, CommandDefinition]` 为规范名称和全部别名建立统一索引。
- 每次登记先完整校验新定义的全部标识，再一次性写入，避免失败后留下半注册状态。
- 归一化后检查名称—名称、名称—别名、别名—别名以及定义内部重复。
- 冲突时抛出 `CommandRegistrationError`，信息包含冲突标识、已有规范名称和新规范名称。
- 提供 `resolve(identifier)`、`definitions(include_hidden=False)` 等只读查询。

**启动时机：** 默认注册中心在 `ArtCodeRuntime` 构造阶段完成全部内置登记；任何冲突在 `run()` 显示首次输入提示前抛出，并由现有 CLI 启动错误路径转换为非零退出。

### 命令分发器

**文件：** `artcode/commands/dispatcher.py`

**职责：**

- 接收已经解析的命令调用，不再次判断普通消息。
- 通过 registry 查找规范名称或别名。
- 未命中时调用 controller 显示“未知命令 + `/help`”并返回 `CONTINUE`。
- 命中时建立 `CommandExecutionContext`，异步调用定义中的 handler，返回 `CommandFlow`。
- 不捕获未预期的编程异常，不把失败调用改送 Agent。

### 内置命令

**文件：** `artcode/commands/builtin.py`

`create_default_registry()` 以固定顺序登记以下定义，全部 `hidden=False`、`aliases=()`：

| 名称 | 类型 | 参数 | 处理行为 |
|---|---|---|---|
| `/exit` | LOCAL | 无 | 返回 `EXIT` |
| `/quit` | LOCAL | 无 | 返回 `EXIT`，保持独立定义 |
| `/help` | LOCAL | 可选命令名 | 从 registry 生成总览或详情 |
| `/plan` | AI | 必填任务描述，可多行 | 以 Plan AgentMode 发送参数 |
| `/do` | AI | 可选附加说明，可多行 | 读取最近计划并以 Do AgentMode 发送组合目标 |
| `/compact` | LOCAL | 无 | 调用现有手动压缩 |
| `/permission` | UI_STATE | 可选模式 | 委托 controller 查询或切换权限 |
| `/sandbox` | UI_STATE | 可选策略 | 委托 controller 查询、确认或切换 Shell 策略 |
| `/sessions` | LOCAL | 无 | 展示 ch09 会话摘要 |
| `/memory` | LOCAL | 无 | 展示 ch09 记忆摘要 |
| `/clear` | UI_STATE | 无 | 只调用界面清屏 |
| `/status` | LOCAL | 无 | 调用 controller 刷新脱敏状态 |

无参数命令收到非空参数时统一显示对应 usage 并返回 `CONTINUE`。`/help` 详情使用 `/help /status` 形式；总览按登记顺序输出名称、类型、描述和首条用法，详情补充全部用法、别名、参数提示与隐藏状态。隐藏项不进入总览，但知道精确名称的用户仍可查询详情和执行。

`/plan` 直接使用解析后的完整参数，不把 `/plan` 字面量写入 Conversation。`/do` 复用当前“最近计划 + 可选附加说明”的组合格式，避免改变 ch04/ch09 的恢复和 PlanMemory 行为。

### Runtime 命令控制与主分流

**文件：** `artcode/runtime/app.py`

**职责：**

- 在 `__post_init__` 中创建或接收完整 registry，并创建 parser 与 dispatcher。
- 实现 `CommandController`，将显示与清屏转发给 TUI，将 Plan/Do/Compact 转发给 AgentLoop，将状态操作转发给现有领域对象。
- `run()` 每次读取输入后只判断 `ParsedInput.route`：空输入继续、普通消息运行 Default Agent、命令调用 dispatcher。
- 删除基于 `CommandResult.action` 的连续条件分支。
- 保留现有权限、沙箱、会话、记忆方法及其提示文本，只把它们变为 controller 的公开结构化实现。
- 用 `_display_mode` 保存当前界面标记，用 `_last_token_usage` 保存最近真实用量。
- `_run_agent` 在请求前切换显示模式，在 `finally` 中恢复 DEFAULT；Do AgentMode 映射到 DEFAULT。
- 收到 `TOKEN_USAGE` 事件时先更新 `_last_token_usage`，再交给 TUI 即时显示。
- `refresh_status()` 构造 `RuntimeStatusSnapshot` 并一次性交给 TUI 渲染，不发 Provider 请求。

**上下文估算：** Runtime 通过 AgentLoop 的只读估算入口获取下一次 Default 请求大小；该入口只组装 Prompt 并调用现有估算器，不运行轻量压缩、自动压缩或任何持久化动作。

### Agent 请求估算

**文件：** `artcode/agent/loop.py`

增加一个只读估算入口：按指定 AgentMode 组装与下一次真实请求相同的 messages 和 tools，并交给 ContextManager 估算。ContextManager 未配置时返回不可用。该入口不得追加用户消息、触发压缩、更新 Token anchor 或调用 Provider。

### TUI 控制与渲染

**文件：** `artcode/tui/app.py`、`artcode/tui/render.py`

**职责：**

- TUI 保存当前 `DisplayMode`，默认值为 DEFAULT。
- 输入提示符渲染为 `[DEFAULT] <model> >` 的紧凑形式。
- Plan 请求期间，助手标签包含 `[PLAN]`；Do 和普通请求包含 `[DEFAULT]`。
- 提供 `clear_screen()`，由 Rich Console 发出清屏控制，不重建 PromptSession、不触碰应用状态。
- 提供 `show_runtime_status(snapshot)`，用单个紧凑 Panel 展示固定字段；缺失数值显示“不可用”。
- 现有启动、工具、上下文和持久状态渲染保持不变。

### 公开导出与章节状态

**文件：** `artcode/commands/__init__.py`、`artcode/config.py`

- 导出新的定义、类型、解析器、注册中心和分发器，移除已废弃 `CommandResult` 公开入口。
- 章节显示更新为 `ch10：斜杠命令系统`。
- 不修改配置文件格式或新增配置项。

## 模块交互

### 普通输入

```text
"请解释 /help"
  → ParsedInput(MESSAGE, 原文)
  → Runtime.send_user_message(..., NORMAL_AGENT_MODE)
  → [DEFAULT] Agent Loop
  → Conversation / JSONL 正常追加
```

### 未知多行命令

```text
" /Unknown\n下一行"
  → ParsedInput(COMMAND, name="/unknown", argument="下一行")
  → Registry 未命中
  → Controller.show_command_message("未知命令…/help")
  → 返回输入循环
  → Provider、Conversation、JSONL 均不变化
```

### Plan 与 Do

```text
/plan 第一行任务\n第二行约束
  → AI handler
  → set_display_mode(PLAN)
  → send_user_message(完整多行参数, PLAN_MODE)
  → 只读工具 + 保存 PlanMemory
  → finally set_display_mode(DEFAULT)

/do 可选附加说明
  → AI handler 读取 PlanMemory
  → 组合最近计划与附加说明
  → send_user_message(..., DO_MODE)
  → [DEFAULT] 全工具 Agent Loop
```

### Status

```text
/status
  → LOCAL handler
  → controller.get_token_usage()
  → AgentLoop.estimate_next_request(NORMAL_AGENT_MODE)
  → 汇总当前权限、沙箱、会话和显示模式
  → TUI.show_runtime_status(snapshot)
  → 无 Provider 请求、无状态变更
```

## 文件组织

```text
artcode/
├── commands/
│   ├── __init__.py       # 新命令 API 导出
│   ├── base.py           # 定义、类型、控制协议、状态快照
│   ├── parser.py         # EMPTY / MESSAGE / COMMAND 解析
│   ├── registry.py       # 统一索引、冲突检测、元数据枚举
│   ├── dispatcher.py     # 查找并调用 handler
│   └── builtin.py        # 12 个独立内置命令定义与行为
├── runtime/
│   └── app.py            # CommandController 与统一回车分流
├── agent/
│   └── loop.py           # 下一次请求的只读 Token 估算
├── tui/
│   ├── app.py            # 模式状态、清屏、状态转发
│   └── render.py         # 模式提示符和状态 Panel
└── config.py             # ch10 章节名称

tests/
├── unit/
│   ├── test_commands.py  # 定义、registry、parser、dispatcher、builtins
│   ├── test_runtime.py   # 主分流、兼容命令、状态与 Token 记录
│   ├── test_agent_loop.py# 只读估算无副作用
│   ├── test_tui_app.py   # 模式与清屏转发
│   └── test_render.py    # 提示符、状态 Panel、脱敏
└── integration/
    ├── test_command_flow.py       # 真实组件命令分流集成
    └── test_ch10_live_e2e.py      # DeepSeek Plan → Do 回归
```

## 技术决策

| 决策点 | 选择 | 理由 |
|---|---|---|
| 命令执行入口 | 所有 handler 统一为异步 | `/sandbox`、`/compact`、Plan/Do 已经需要 await；统一签名比同步/异步双分支更简单 |
| 名称归一化 | 去首尾空白后 `lower()` | 满足大小写不敏感且与用户明确要求一致；命令标识限定为无空白文本 |
| 冲突索引 | 名称与别名共享单个字典 | 通过结构直接保证任意组合不可撞名，查找也是常数时间 |
| 注册写入 | 先校验全部标识，再一次性提交 | 一个坏 alias 不会留下半个可用命令 |
| 帮助来源 | 完全从 `CommandDefinition` 生成 | 消除静态帮助文本与实现漂移 |
| 内置别名 | 全部为空 | 用户要求保留旧名字，功能相近时取消新名字，不把已有命令改造成别名 |
| 多行命令 | 首个空白结束名称，其余作为参数 | 明确保证斜杠输入不回退 Agent，并支持多行 Plan 任务 |
| 运行期错误 | 直接显示参数/未知命令提示，不新增错误框架 | 用户选择简单实现；编程异常按现有 Python/CLI 路径暴露 |
| 命令与界面解耦 | Runtime 结构化实现 Controller Protocol | 不增加一层只做转发的适配器，同时让命令测试不依赖渲染框架 |
| 模式状态 | 请求级 DisplayMode，finally 恢复 | 兼容 ch04 的一次性 `/plan` 和 `/do`，同时提供可观察标记 |
| `/compact` 分类 | LOCAL | 分类描述入口路径而非内部是否调用 Provider，保留 ch08 完整语义 |
| `/clear` | Console 清屏，不替换任何状态对象 | 将视觉行为与 Conversation/持久数据严格分开 |
| `/status` 估算 | 复用真实下一请求组装和 ch08 estimator | 比只数字符或只估算 Conversation 更接近实际 Prompt，又不会调用 Provider |
| 最近 Token | Runtime 缓存最近 `TOKEN_USAGE` 事件 | Provider 已给出真实数据，无需重复估算或改变 ContextManager anchor |
| 补全 | 不实现 | 用户明确移除 Tab 补全；避免为 PromptSession 增加额外交互状态 |
| 依赖 | 只用标准库和已有 Rich/Prompt Toolkit | 保持现有打包边界和学习项目可读性 |

## Spec 覆盖

| Spec | 设计归属 |
|---|---|
| F1–F4 | `CommandDefinition`、`CommandRegistry` |
| F5–F10 | `CommandParser`、`CommandDispatcher`、Runtime 统一入口 |
| F11–F15 | `CommandType`、`CommandController`、`DisplayMode`、分发器 |
| F16–F25 | `builtin.py`、Runtime controller、TUI status/clear |
| N1–N3 | 单索引、原子登记、互斥分流与 Provider/Conversation Spy 测试 |
| N4 | `RuntimeStatusSnapshot` 白名单字段与渲染脱敏测试 |
| N5–N6 | Protocol 边界、无新依赖、打包冒烟 |
| N7–N9 | 既有回归、命令集成和真实 DeepSeek 端到端测试 |
