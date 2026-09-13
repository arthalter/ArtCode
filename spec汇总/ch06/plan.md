# ch06：权限系统 Plan

## 架构概览

ch06 将现有“工具自行检查路径、Agent Loop 直接确认副作用”的分散结构重组为五层串联防线：

1. **运行边界层**：`ArtCodePaths` 管理可信应用数据位置，`Workspace` 固定本次被辅助项目根目录。
2. **硬安全层**：Plan 限制、Workspace 真实路径检查、敏感路径拒绝和危险命令检查不可被规则或用户审批解除。
3. **权限决策层**：三层 YAML 规则优先匹配；未匹配时由文件权限模式或 Shell 策略兜底。
4. **HITL 层**：仅对最终 ASK 的单个工具调用暂停，支持一次性决定或向本地规则写入精确长期决定。
5. **执行隔离层**：文件工具仅操作 Workspace；获得 ALLOW 的命令按策略进入 Seatbelt 或经明确确认的无沙箱 zsh。

`AgentLoop` 继续负责模型轮次和事件流；`ToolBatchExecutor` 负责工具顺序、权限审批和执行编排；路径、规则、危险命令及 Seatbelt 分别由独立模块负责。任何硬边界、规则加载或沙箱状态无法确定时均失败关闭。

## 核心数据结构

### `ArtCodePaths`

不可变对象，集中提供 ArtCode Home、主配置、用户权限、Skills、内置安全资源等可信路径。它只供主进程中的配置、规则和安全组件使用，不作为模型工具的允许根目录。

### `Workspace`

不可变对象，保存启动时确定的规范真实根路径，以及项目级和本地级权限文件位置。相对文件路径、扫描起点和命令工作目录都以它为基准。

### `WorkspacePathPolicy`

替代多根 `AllowedPathPolicy`。提供已有路径解析、新文件父目录解析、Workspace 包含判断、相对 POSIX 路径生成和敏感路径检查。路径比较使用解析符号链接后的 `Path` 层级关系。

### `PermissionState`

保存当前进程内的 `PermissionMode` 与 `ShellPolicy`：

- `PermissionMode.DEFAULT`：只读 ALLOW，写入和编辑 ASK。
- `PermissionMode.EDIT`：五个文件工具 ALLOW。
- `PermissionMode.FULL`：五个文件工具 ALLOW，为后续扩展保留与 Edit 不同的语义名称。
- `ShellPolicy.SANDBOX_AUTO`：规则未匹配时 ALLOW，并使用 Seatbelt。
- `ShellPolicy.SANDBOX_ASK`：规则未匹配时 ASK，允许后使用 Seatbelt。
- `ShellPolicy.UNSANDBOXED_ASK`：规则未匹配时 ASK，允许后直接使用受控 zsh。

Plan 仍由 `AgentMode` 表示，不进入 `PermissionMode`。

### `PermissionRequest`

由 `PreparedToolCall` 转换而来，包含工具名、工具类别、规范匹配目标、展示目标、Workspace、Plan 状态和当前权限状态。文件工具目标是 Workspace 相对路径，命令目标是仅去除首尾空白的完整命令。

### `PermissionDecision`

最终值只允许 `ALLOW`、`ASK`、`DENY`，并携带结构化来源、原因、命中规则层级和规则位置。`NO_MATCH` 仅作为规则查询的内部结果，不可传给执行器。

### `PermissionRule`

保存原始 `match`、解析后的工具名与 pattern、`action` 和来源位置。表达式用第一个 `(` 与最后一个 `)` 划分，匹配区分大小写。

### `ApprovalRequest` 与 `ApprovalChoice`

审批请求包含工具、目标、Workspace、权限模式、Shell 策略和 ASK 来源。选择固定为仅本次允许、仅本次禁止、以后允许、以后禁止；长期选择生成精确规则。

### `SeatbeltSession`

管理专用临时目录、生成后的 Profile、自检状态和清理生命周期；提供沙箱命令启动前缀及安全环境所需的 `TMPDIR`。一个 ArtCode 进程只生成并复用一个 Profile。

## 模块设计

### Workspace 与配置

**文件：** `artcode/workspace.py`、`artcode/config.py`、`artcode/cli.py`

**职责：**

- 创建稳定的 `~/.artcode/` 和 Skills 目录。
- 从 `~/.artcode/config.yml` 加载主配置。
- 将当前目录或 `--workspace` 指定目录解析为固定 Workspace。
- 启动时依次完成配置、规则、安全资源和 Seatbelt 校验。

**约束：** Workspace 不存在或不是目录时直接启动失败；不再创建默认实验场，也不再解析 `tools.allowed_dirs`。

### 路径与敏感资源

**文件：** `artcode/tools/policy.py`、`artcode/tools/base.py`、`artcode/tools/file_tools.py`

**职责：**

- 文件工具在 `prepare` 阶段完成真实路径规范化和硬边界检查。
- 新文件依据真实父目录判断；已有文件依据真实目标判断。
- 查找和搜索不跟随通往 Workspace 外或敏感位置的目录符号链接。
- `PreparedToolCall` 同时保留展示/规则匹配目标与可信执行参数。

**约束：** 普通工具不接收绕过敏感检查的开关；可信内部读写器使用独立接口。

### 权限规则

**文件：** `artcode/permissions/models.py`、`glob.py`、`rules.py`、`writer.py`

**职责：**

- 解析并校验 `工具名(pattern)` 和 action。
- 实现区分大小写的精简 Gitignore Glob。
- 每次调用重新加载用户级、项目级、本地级规则。
- 每层使用最后一条匹配规则；任一层有效 DENY 优先，否则本地、项目、用户依次选择 ALLOW/ASK。
- 原子更新本地权限文件，并在同 match 更新时移至末尾。

**错误策略：** 缺失文件视为空；存在但读取、解析或校验失败时抛出带文件位置的 `PermissionRuleError`，不使用旧结果。

### 危险命令

**文件：** `artcode/security/dangerous_commands.yml`、`artcode/security/commands.py`

**职责：**

- 启动时加载并编译内置高危命令规则。
- 在规则和模式判断前检查静态正则。
- 根据当前 Workspace 动态识别整体删除。
- 返回稳定规则 ID 和可解释原因。

**约束：** 三层权限规则不能修改、关闭或覆盖危险命令检查。

### 权限引擎

**文件：** `artcode/permissions/engine.py`

**对外接口：**

- 接收 `PreparedToolCall`、Agent 模式与 `PermissionState`。
- 返回最终 `PermissionDecision` 或结构化规则错误。

**固定决策顺序：**

1. Plan 工具硬过滤。
2. 命令危险检查。
3. Workspace 与敏感路径硬检查。
4. 热加载并合并三层规则。
5. 采用显式 ALLOW、ASK 或 DENY。
6. NO_MATCH 时由文件权限模式或 Shell 策略兜底。

任何一步拒绝或出错后，不再调用后续阶段。

### Seatbelt 与 Shell

**文件：** `artcode/sandbox/seatbelt.sb`、`artcode/sandbox/seatbelt.py`、`artcode/tools/command_tool.py`

**职责：**

- 根据 Workspace、专用临时目录和敏感路径生成 Profile。
- 启动时用 `/usr/bin/sandbox-exec` 和 `/usr/bin/true` 完成真实自检。
- 命令固定以 `/bin/zsh -f -c` 运行。
- 沙箱策略使用 `sandbox-exec -f <profile>` 包装；无沙箱策略仍使用固定 zsh、安全环境、Workspace cwd、超时与结果限制。
- 仅传递运行必需的环境变量白名单，排除 Key、Token、Secret、Password、Credential 等秘密。
- 以独立进程组启动，10 秒超时后终止整个进程组。

**错误策略：** sandbox-exec 缺失、Profile 无效、自检或启动失败均不得降级为普通 Shell。

### HITL 与工具调度

**文件：** `artcode/agent/tools.py`、`artcode/agent/events.py`、`artcode/agent/loop.py`、`artcode/tui/app.py`

**职责：**

- 每个调用先解析、prepare、权限判断，再决定拒绝、审批或执行。
- ASK 通过异步审批接口暂停，不将 TUI 细节嵌入权限引擎。
- 长期决定先原子写入本地规则，再决定是否执行当前工具。
- 相邻且已获 ALLOW 的只读工具可以并发；写入、编辑、命令和多个审批保持串行。
- 所有工具结果按模型原始顺序回灌。
- `Ctrl+C` 在审批期间取消整个 Agent Loop。

### Runtime、命令与提醒

**文件：** `artcode/runtime/app.py`、`artcode/commands/builtin.py`、`artcode/prompting/`、`artcode/tui/`

**职责：**

- Runtime 持有进程内 `PermissionState`、权限服务和 `SeatbeltSession`。
- `/permission` 和 `/sandbox` 查询或修改当前状态。
- `/sandbox off` 必须经过独立风险确认。
- 启动面板和每轮动态提醒展示 Workspace、Plan、权限模式、Shell 策略和 Seatbelt 状态。
- 动态提醒只进入当前请求，不写入 Conversation Context。

## 模块交互

### 启动

```text
CLI
  → 创建 ArtCodePaths
  → 解析固定 Workspace
  → 加载主配置
  → 校验三层权限文件
  → 加载危险命令库
  → 创建 SeatbeltSession、生成 Profile、真实自检
  → 注入 Runtime、ToolExecutionContext、PermissionEngine
  → 展示脱敏启动状态
```

### 单个工具调用

```text
模型 ToolCall
  → Tool.prepare（解析参数、规范路径、硬路径检查）
  → PermissionEngine（Plan → 危险命令 → 敏感路径 → 规则 → 模式兜底）
      ├─ DENY/错误 → 结构化 ToolResult
      ├─ ASK → HITL
      │          ├─ 一次性决定 → 不写规则
      │          └─ 长期决定 → RuleWriter 原子更新本地规则
      └─ ALLOW
  → Tool.execute
      ├─ 文件工具 → Workspace 内真实目标
      └─ 命令工具 → Seatbelt zsh 或已确认的无沙箱 zsh
  → ToolResult 按原调用顺序回灌模型
```

## 文件组织

```text
artcode/
├── workspace.py
├── permissions/
│   ├── __init__.py
│   ├── models.py
│   ├── glob.py
│   ├── rules.py
│   ├── writer.py
│   └── engine.py
├── security/
│   ├── __init__.py
│   ├── commands.py
│   └── dangerous_commands.yml
├── sandbox/
│   ├── __init__.py
│   ├── seatbelt.py
│   └── seatbelt.sb
├── tools/
├── agent/
├── runtime/
├── commands/
├── prompting/
└── tui/
```

对应测试按职责拆入 `tests/unit/test_workspace.py`、`test_permission_*`、`test_dangerous_commands.py`、`test_seatbelt.py`，并以 `tests/integration/test_permissions_flow.py` 与 `test_seatbelt_live.py` 覆盖主流程和真实 macOS 边界。

## 技术决策

| 决策点 | 选择 | 理由 |
|---|---|---|
| 应用目录与项目目录 | `ArtCodePaths` 和 `Workspace` 分离 | 防止模型工具把配置、安全资源与被辅助项目混为同一信任域 |
| 路径判断 | `resolve()` 后用路径层级关系判断 | 阻止 `..`、字符串相似前缀和符号链接逃逸 |
| 权限规则格式 | 有序 YAML `rules` 列表 | 保留“同层最后匹配覆盖”所需的确定顺序，并适合人工编辑 |
| Glob 实现 | 自有、受限、区分大小写的编译器 | Python `fnmatch` 的目录语义不足以直接表达规范中的 `*` 与 `**` 差异 |
| 热重载 | 每次工具调用重新读取三层文件 | 本地文件规模小，换取无需重启和明确的失败关闭语义 |
| 长期权限落点 | 仅写 Workspace 本地级文件 | 避免一次项目审批意外扩大为用户全局授权 |
| Shell 创建 | `create_subprocess_exec` + 固定参数 | 避免默认 shell 和用户 rc，便于精确检查沙箱包装与进程组 |
| 沙箱生命周期 | 启动生成、自检、进程内复用 | 尽早暴露不可用状态，避免每次调用重复生成造成不一致 |
| HITL 接口 | 异步 Protocol + 结构化请求 | 便于 TUI 实现、单元测试注入与取消传播 |
| 工具调度 | 权限获批后再形成并发批次 | 保留只读并发，同时确保 ASK 不并发、写操作不提前启动 |
| 错误策略 | 失败关闭且结构化回灌 | 不让规则、路径或沙箱故障静默退回更宽松行为 |

## Spec 与任务覆盖

- F1-F18：T1-T2，Workspace、配置、路径及敏感资源。
- F19-F24：T6，危险命令硬拒绝。
- F25-F40：T4-T5，规则解析、匹配、合并、热重载和写回。
- F41-F53：T3、T8、T11，权限模式、Shell 策略与命令切换。
- F54-F63：T10，四选项 HITL、取消和多工具顺序。
- F64-F76：T7-T8，Seatbelt 生命周期与受控 Shell。
- F77-F80：T10-T13，TUI、动态提醒、结构化结果和主流程。
- N1-N16：由硬边界短路、模块拆分、原子写入、安全环境、进程组超时及真实 macOS 测试共同覆盖。
- T13 负责接入主流程；T14 负责完整单元、集成、真实 Seatbelt、真实 API 与 Checklist 验收。
