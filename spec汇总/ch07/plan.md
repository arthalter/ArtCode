# ch07：MCP协议 Plan

## 架构概览

ch07 在现有启动流程与工具中心之间增加独立 MCP 子系统，分为六层：

1. **配置层**：读取用户级与项目级配置，按 Server 名整项覆盖，逐 Server 严格校验，并延迟展开秘密。
2. **启动信任层**：用户级 Server 默认信任；项目级 Server 在创建进程或发送网络请求前逐项确认。
3. **会话与生命周期层**：每个 Server 独立持有传输、SDK 会话、状态、工具快照、活跃调用和诊断信息。
4. **工具适配层**：将远端工具包装成 ArtCode `Tool`，集中处理命名、Schema、预览、调用和结果转换。
5. **权限与调度层**：内置工具继续使用现有权限引擎；MCP 工具每次只允许一次性确认，并在确认后支持并发调用。
6. **Runtime 与展示层**：启动时发现并注册工具，退出时统一关闭会话，TUI 展示脱敏启动报告。

官方 Python MCP SDK 负责 JSON-RPC 2.0 请求 ID 配对、协议版本协商、stdio 与 Streamable HTTP 消息通信。ArtCode 不重复实现完整协议栈，只管理应用级配置、信任、会话缓存、工具注册和生命周期。

## 核心数据结构

### 配置模型

```python
class McpTransport(StrEnum):
    STDIO = "stdio"
    STREAMABLE_HTTP = "streamable_http"


@dataclass(frozen=True)
class StdioMcpServerConfig:
    name: str
    source: ConfigSource
    enabled: bool
    command: str
    args: tuple[str, ...]
    env: Mapping[str, str]


@dataclass(frozen=True)
class HttpMcpServerConfig:
    name: str
    source: ConfigSource
    enabled: bool
    url: str
    headers: Mapping[str, str]
```

`ConfigSource` 区分用户级与项目级。合并后保留最终条目的来源，用于决定是否需要启动确认。

```python
@dataclass(frozen=True)
class McpConfigLoadResult:
    servers: tuple[McpServerConfig, ...]
    issues: tuple[McpConfigIssue, ...]
```

MCP 单项解析错误进入 `issues`；现有主模型配置错误仍使用 `ConfigError` 并阻止启动。

### 延迟环境变量展开

```python
@dataclass(frozen=True)
class ExpansionPlan:
    template: str
    referenced_variables: tuple[str, ...]


def inspect_expansions(config: McpServerConfig) -> McpServerDisclosure: ...


def expand_server_config(
    config: McpServerConfig,
    environ: Mapping[str, str],
) -> ResolvedMcpServerConfig: ...
```

配置解析阶段只识别 `${VAR}` 并保留变量名。项目级 Server 获批后才展开真实值。缺失变量错误只能包含变量名，不能包含其他已展开秘密。

stdio 基础环境只取 `PATH`、`HOME`、`LANG`、`LC_ALL`、`LC_CTYPE`、`TMPDIR` 中实际存在的变量；显式 `env` 最后覆盖基础环境。

### Server 启动审批

```python
@dataclass(frozen=True)
class McpServerApprovalRequest:
    server_name: str
    transport: McpTransport
    source_file: Path
    command: str | None
    args: tuple[str, ...]
    url: str | None
    environment_names: tuple[str, ...]
    header_names: tuple[str, ...]
    warning: str


class McpServerApprover(Protocol):
    async def confirm_mcp_server(
        self,
        request: McpServerApprovalRequest,
    ) -> bool: ...
```

审批请求不包含解析后的秘密值。stdio 警告外部进程不受 Workspace 文件工具沙箱保护；HTTP 警告跨域重定向会原样转发 Headers。

### Server 状态与报告

```python
class McpServerState(StrEnum):
    CONFIG_INVALID = "config_invalid"
    DISABLED = "disabled"
    REJECTED = "rejected"
    CONNECTING = "connecting"
    READY = "ready"
    UNAVAILABLE = "unavailable"
    CLOSING = "closing"
    CLOSED = "closed"


class McpFailureStage(StrEnum):
    CONFIG = "config"
    APPROVAL = "approval"
    ENVIRONMENT = "environment"
    TRANSPORT = "transport"
    INITIALIZE = "initialize"
    DISCOVERY = "discovery"
    TOOL_VALIDATION = "tool_validation"
    INVOCATION = "invocation"
    SHUTDOWN = "shutdown"
```

```python
@dataclass(frozen=True)
class McpServerReport:
    name: str
    source: ConfigSource
    state: McpServerState
    tool_count: int
    skipped_tool_count: int
    failure_stage: McpFailureStage | None
    message: str


@dataclass(frozen=True)
class McpStartupReport:
    configured_count: int
    connected_count: int
    failed_count: int
    registered_tool_count: int
    servers: tuple[McpServerReport, ...]
```

报告按最终合并配置顺序排列，不按异步完成顺序排列。

### 传输抽象

```python
class McpTransportFactory(Protocol):
    def open(
        self,
        config: ResolvedMcpServerConfig,
        workspace: Path,
        stderr_sink: TextIO | None,
    ) -> AsyncContextManager[McpStreams]: ...
```

生产实现内部调用：

- stdio：`StdioServerParameters`、`stdio_client` 和 `ClientSession`。
- HTTP：带自定义 `httpx.AsyncClient` 的 `streamable_http_client` 和 `ClientSession`。

### 单 Server 会话

```python
class McpServerSession:
    name: str
    state: McpServerState
    discovered_tools: tuple[RemoteMcpTool, ...]

    async def start(self) -> McpServerReport: ...

    async def call_tool(
        self,
        remote_name: str,
        arguments: dict[str, Any],
    ) -> CallToolResult: ...

    async def cancel_active_calls(self, reason: str) -> None: ...

    async def close(self) -> None: ...
```

内部持有独立 `AsyncExitStack`、SDK `ClientSession`、活跃调用 Task 集合、状态锁、关闭锁、近期 `stderr` 环形缓冲和已见分页 Cursor 集合。

### 全局管理器

```python
class McpServerManager:
    async def start_all(
        self,
        configs: tuple[McpServerConfig, ...],
        approver: McpServerApprover,
    ) -> McpStartupReport: ...

    def get_session(self, server_name: str) -> McpServerSession | None: ...

    def adapters(self) -> tuple[McpToolAdapter, ...]: ...

    async def close(self) -> None: ...
```

管理器使用容量为 5 的启动信号量。所有 Server 完成或失败后，按配置顺序生成 Adapter。

### 工具来源与审批策略

```python
class ToolOrigin(StrEnum):
    BUILTIN = "builtin"
    MCP = "mcp"


class ToolApprovalPolicy(StrEnum):
    PERMISSION_ENGINE = "permission_engine"
    ALWAYS_ASK_ONCE = "always_ask_once"
```

内置工具使用 `BUILTIN + PERMISSION_ENGINE`；MCP Adapter 使用 `MCP + ALWAYS_ASK_ONCE`。调度器根据元数据明确分流，不通过名称前缀或 `isinstance` 猜测安全语义。

Plan 工具策略调整为：

```python
@dataclass(frozen=True)
class ToolAccessPolicy:
    allowed_builtin_names: frozenset[str] | None
    allow_mcp: bool
```

Normal 与 Do 暴露全部工具；Plan 暴露三个内置只读工具和全部 MCP 工具。

### MCP 工具适配器

```python
@dataclass(frozen=True)
class McpToolAdapter:
    name: str
    remote_name: str
    server_name: str
    description: str
    parameters_schema: dict[str, Any]
    origin: ToolOrigin = ToolOrigin.MCP
    approval_policy: ToolApprovalPolicy = ToolApprovalPolicy.ALWAYS_ASK_ONCE

    def prepare(...) -> PreparedToolCall | ToolResult: ...

    async def execute(...) -> ToolResult: ...
```

适配器同时保存模型注册名和远端原始工具名。`prepare()` 生成参数和脱敏预览；`execute()` 调用缓存会话并转换结果。

## 模块设计

### 配置加载

**文件：** `artcode/config.py`、`artcode/workspace.py`、`artcode/mcp/config.py`

项目级文件只允许 `mcp_servers`。配置示例：

```yaml
mcp_servers:
  local_files:
    transport: stdio
    enabled: true
    command: python
    args:
      - ./servers/files_server.py
    env:
      LOG_LEVEL: info
      SERVICE_TOKEN: ${SERVICE_TOKEN}

  remote_search:
    transport: streamable_http
    enabled: true
    url: https://example.com/mcp
    headers:
      Authorization: Bearer ${MCP_TOKEN}
      X-Client: ArtCode
```

固定校验：

- `mcp_servers` 必须是 map，Server 名必须是非空字符串。
- `enabled` 默认 `true`，只能是布尔值。
- stdio 只允许 `transport`、`enabled`、`command`、`args`、`env`。
- HTTP 只允许 `transport`、`enabled`、`url`、`headers`。
- `command` 与 `url` 必须是非空字符串。
- `args` 必须是字符串列表，默认空列表。
- `env` 与 `headers` 必须是字符串到字符串的 map，默认空 map。
- URL 只接受 `http` 与 `https`。
- 只支持 `${VAR}`，不支持默认值、`$VAR` 或 Shell 展开语法。

### stdio 传输

**文件：** `artcode/mcp/transport.py`、`artcode/mcp/stderr.py`

工作目录固定为 Workspace。`StderrCapture` 创建 OS 管道，持续读取子进程标准错误，逐行脱敏后写入最近 100 行且总量不超过 64 KiB 的环形缓冲；单行最多保留 2 KiB。

SDK stdio 上下文负责关闭协议流并终止其创建的子进程。ArtCode 在外层为关闭增加总时限，并以真实进程测试验证不会遗留子进程。

### Streamable HTTP 传输

**文件：** `artcode/mcp/transport.py`

HTTP Client 固定允许 HTTP/HTTPS，最多跟随 10 次同源或跨域重定向。为落实用户选择，包装底层 `AsyncHTTPTransport`，在每次实际发送前重新注入全部配置 Headers，包括认证信息。

这一高风险行为必须同时出现在启动审批、README 和代码安全说明中。URL 查询参数及 Header 值不能进入错误和日志。

### 会话初始化与工具发现

**文件：** `artcode/mcp/session.py`

状态机：

```text
已解析
  → 等待项目审批
  → 展开环境变量
  → 建立传输
  → initialize
  → 分页 tools/list
  → 校验工具
  → READY
```

固定边界：

- 传输建立、初始化和每页工具发现分别为 10 秒。
- 单个 Server 最多发现 100 个工具。
- 单个 Server 最多读取 100 页。
- 重复出现同一非空 Cursor 时关闭 Server并报告发现失败。
- 达到工具数量上限时保留前 100 个，Server 保持 READY 并报告截断。
- 达到页数上限仍未结束时关闭 Server。

本章不注册非工具能力处理器。不支持的 Server 主动请求由 SDK 返回标准不支持结果。

### 工具 Schema 与名称

**文件：** `artcode/mcp/naming.py`、`artcode/mcp/adapter.py`

Schema 校验：

- 工具名必须是非空字符串。
- `inputSchema` 必须是 JSON 对象。
- 顶层缺少 `type` 时补为 `object`，存在时必须为 `object`。
- `properties` 存在时必须是对象。
- `required` 存在时必须是无重复字符串列表，且每项存在于 `properties`。
- Schema 必须能够 JSON 序列化。
- 不主动删除合法 JSON Schema 2020-12 关键字。

名称规范化：

1. Server 名与工具名中的非 ASCII 字母、数字、下划线和连字符替换为 `_`。
2. 连续下划线合并，空片段回退为 `server` 或 `tool`。
3. 拼接为 `mcp__<server>__<tool>`。
4. 最终名称最长 64 字符。
5. 超长时保留可读前缀，并追加原始完整名称 SHA-256 前 10 位。
6. 规范化后重名时保留配置顺序靠前者，跳过后者。

### 参数预览与结果转换

**文件：** `artcode/mcp/redaction.py`、`artcode/mcp/results.py`

参数使用稳定 JSON 序列化。键名不区分大小写，只要包含 `authorization`、`cookie`、`token`、`secret`、`password`、`credential`、`api_key` 或 `apikey` 即隐藏整个值。预览最长 2,000 字符。

结果转换：

1. 文本块保留文本。
2. `structuredContent` 使用稳定 JSON 序列化。
3. 图片与音频只保留类型、MIME 和数据规模。
4. Resource Link 保留类型、名称、URI 和 MIME。
5. Embedded Resource 只保留 URI、MIME 与内容规模。
6. `isError=true` 转换为失败结果。
7. 最终使用现有 20,000 字节 UTF-8 截断器。

### 工具注册与调度

**文件：** `artcode/tools/base.py`、`artcode/tools/registry.py`、`artcode/agent/modes.py`、`artcode/agent/tools.py`

内置工具先注册，MCP 工具按最终配置顺序和 Server 返回顺序注册。

执行批次扩展为：

```python
class ToolSafety(StrEnum):
    READ_ONLY = "read_only"
    SIDE_EFFECT = "side_effect"
    EXTERNAL_MCP = "external_mcp"
```

- 相邻内置只读工具并发。
- 每个内置副作用工具独占串行批次。
- 相邻 MCP 工具组成外部批次。
- MCP 审批按模型顺序逐个进行。
- 获准调用在审批全部完成后并发执行。
- 结果按模型原始顺序回灌。
- MCP 只提供“仅本次允许/拒绝”，不查询或写入三层权限规则。

### 调用、错误与关闭

**文件：** `artcode/mcp/session.py`、`artcode/mcp/manager.py`

单次 `tools/call` 超时固定为 60 秒。

| 错误 | ToolResult | 会话处理 |
|---|---|---|
| `isError=true` | `mcp_tool_error` | 保留 |
| JSON-RPC 业务错误 | `mcp_rpc_error` | 保留 |
| 参数或序列化错误 | `mcp_invalid_arguments` | 保留 |
| 用户拒绝 | `user_denied` | 保留 |
| 调用取消且传输正常 | `cancelled` | 保留 |
| 调用超时 | `mcp_timeout` | 关闭并标记不可用 |
| EOF、连接关闭 | `mcp_transport_closed` | 关闭并标记不可用 |
| 协议损坏 | `mcp_protocol_error` | 关闭并标记不可用 |
| 已不可用 | `mcp_server_unavailable` | 快速失败 |

单次取消通过取消 SDK `call_tool` Task 尽力传播 `notifications/cancelled`。初始化请求不发送取消通知；超时直接关闭传输。

整体关闭：

1. 停止接受新调用。
2. 取消全部活跃调用并最多等待 3 秒。
3. 并发关闭所有 Server。
4. 单个 Server 最多等待 5 秒。
5. 关闭失败只进入报告。
6. 重复 `close()` 等待同一个关闭结果。

### TUI 与 Runtime

**文件：** `artcode/tui/app.py`、`artcode/tui/render.py`、`artcode/runtime/app.py`、`artcode/cli.py`

TUI 新增项目 Server 启动确认、MCP 工具一次性确认和启动报告展示。失败原因最长 500 字符并规范化换行。

CLI 接入顺序：

```text
加载两层配置
→ 创建 Manager
→ 项目级审批
→ 并发连接与发现
→ 按顺序注册 Adapter
→ 创建 Runtime 与 AgentLoop
→ 展示启动摘要
```

退出顺序：

```text
结束 Agent Loop
→ await McpServerManager.close()
→ SeatbeltSession.close()
```

MCP 管理器级异常转换为汇总失败，ArtCode 继续以内置工具启动。现有主配置、Workspace、权限与 Seatbelt 硬边界错误仍阻止启动。

## 模块交互

### 启动

```text
CLI
  → ArtCodePaths / Workspace
  → 用户主配置 + 项目 MCP 配置
  → MCP 整项合并与单项校验
  → 项目级 Server 审批
  → 环境变量展开
  → McpServerManager（最多 5 个并发）
      ├─ stdio → ClientSession → initialize → tools/list
      └─ HTTP → ClientSession → initialize → tools/list
  → 工具规范化与校验
  → 按配置顺序注册 Adapter
  → Runtime / AgentLoop
  → MCP 启动摘要
```

### 单次调用

```text
模型 ToolCall
  → Registry 找到 McpToolAdapter
  → 解析 JSON 参数
  → 生成脱敏预览
  → MCP 一次性审批
      ├─ 拒绝 → 不发送请求 → user_denied
      └─ 允许
          → 缓存 Session.call_tool
          → SDK 配对 JSON-RPC 请求与响应
          → 内容安全转换
          → 20,000 字节限制
          → ToolResult 回灌
```

### 故障隔离

```text
Server A 断开
  → A 标记 UNAVAILABLE
  → A 后续调用快速失败
  → 不自动重连
  → Server B 与内置工具保持可用
  → Agent Loop 继续
```

## 文件组织

```text
artcode/
├── config.py
├── workspace.py
├── cli.py
├── mcp/
│   ├── __init__.py
│   ├── config.py
│   ├── models.py
│   ├── transport.py
│   ├── session.py
│   ├── manager.py
│   ├── adapter.py
│   ├── naming.py
│   ├── results.py
│   ├── redaction.py
│   └── stderr.py
├── tools/
│   ├── base.py
│   └── registry.py
├── agent/
│   ├── modes.py
│   └── tools.py
├── runtime/
│   └── app.py
└── tui/
    ├── app.py
    └── render.py
```

测试文件：

```text
tests/unit/
├── test_mcp_config.py
├── test_mcp_naming.py
├── test_mcp_redaction.py
├── test_mcp_results.py
├── test_mcp_adapter.py
├── test_mcp_session.py
├── test_mcp_manager.py
└── test_mcp_transport.py

tests/integration/
├── fixtures/
│   └── mcp_test_server.py
├── test_mcp_stdio_live.py
├── test_mcp_http_live.py
└── test_mcp_agent_flow.py
```

## 技术决策

| 决策点 | 选择 | 理由 |
|---|---|---|
| SDK 版本 | `mcp>=1.28,<2` | 使用稳定 v1 API，避免自动升级到破坏性 v2 |
| 协议实现 | 官方 SDK | 由 SDK 负责 JSON-RPC、版本协商和传输 |
| 配置错误 | 单 Server 结果化 | 保持外部能力故障隔离 |
| 项目配置 | 延迟展开并启动审批 | 防止确认前执行命令或发送秘密 |
| 同名配置 | 整项覆盖 | 避免跨层混入旧字段和凭证 |
| 会话持有 | 每 Server 独立 `AsyncExitStack` | 生命周期清晰且关闭可隔离 |
| 启动并发 | 5 | 降低等待且限制资源尖峰 |
| 工具与页数上限 | 各 100 | 防止异常 Server 无限发现 |
| 名称长度 | 64 字符加稳定哈希 | 兼容模型限制并避免长名碰撞 |
| 权限模型 | MCP 每次仅本次确认 | 不信任 Server 副作用注解 |
| Plan 行为 | 暴露 MCP，调用前确认 | 按用户选择允许 Plan 使用外部能力 |
| MCP 调度 | 确认串行、执行并发 | 保持确认清晰并验证异步配对 |
| HTTP 重定向 | 最多 10 次，跨域转发全部 Headers | 按用户选择实现并明确风险 |
| 日志 | 100 行、64 KiB 环形缓冲 | 防止背压和无限增长 |
| 结果 | 文本化、20,000 字节 | 兼容现有 Provider 与工具结果 |
| 调用超时 | 60 秒后关闭会话 | 避免复用状态未知的连接 |
| 动态工具与重连 | 均不实现 | 保持范围和状态确定性 |
| 测试 | 假传输单测加真实双传输集成 | 同时验证分支逻辑和协议互通 |

## Spec 覆盖

- F1–F11：配置模型、两层合并、延迟展开和启动审批。
- F12–F19：传输工厂、会话状态机、分页、超时、重定向和日志捕获。
- F20–F27：Adapter、Schema 校验、名称规范化和确定性注册。
- F28–F37：外部工具审批、并发批次、调用路由、结果转换和错误分类。
- F38–F43：Manager 状态隔离、取消关闭和启动报告。
- N1–N30：由稳定 SDK 约束、有界资源、统一脱敏、独立会话、真实集成测试及回归测试覆盖。
