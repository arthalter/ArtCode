# ch03：工具系统 Plan

## 架构概览

ch03 在 ch02 的分层基础上新增 `Tools` 层，并扩展 `Config`、`Provider`、`Conversation`、`Runtime` 和 `TUI` 的协作方式。整体设计保持“模型负责决定是否调用工具，ArtCode 负责执行工具和回灌结果”的边界。

`Tools` 层是本章新增核心。它负责定义统一工具接口、工具元信息、工具参数 Schema、工具执行上下文、结构化执行结果、允许目录检查、工具注册中心，以及六个内置工具：`read_file`、`write_file`、`edit_file`、`run_command`、`find_files`、`search_text`。所有工具都只通过这一层访问文件系统或执行命令，避免 Runtime 或 Provider 直接散落工具逻辑。

`Config` 层增加工具配置。它从 `artcode.yaml` 读取允许目录列表，只接受绝对路径；如果用户没有配置工具目录，就使用默认目录 `/Users/arthalter/Work/ArtCode/实验场`。启动时会解析真实路径、创建不存在的默认实验目录，并把允许目录摘要放进安全启动状态中展示。

`Provider` 层继续负责 OpenAI-compatible Chat Completions。ch03 会让 Provider 在首次请求中携带 `tools` 列表，并从 SSE delta 中解析 `tool_calls` 参数碎片。Provider 不执行工具，只把普通文本增量、工具调用完成、结束等事件交给 Runtime。最终总结请求不携带 `tools`，确保本章不会进入连续 Agent Loop。

`Conversation` 层继续保存本次运行内消息，但会新增工具调用相关消息写入能力。一次工具调用流程中，会保存用户消息、模型发起工具调用的 assistant 消息、工具结果消息，以及最终自然语言 assistant 消息。它仍不落盘、不做会话恢复、不做上下文压缩。

`Runtime` 层升级为单步 Agent 编排器。每轮用户输入后，它先请求模型；如果模型只返回文本，就沿用 ch02 的普通流式输出；如果模型请求一个工具，Runtime 查找工具、预检参数、必要时询问用户确认、执行工具、把结果写回 Conversation Context，再发起一次不带工具的最终总结请求。模型请求多个工具时不执行任何工具，而是为每个 tool call 都回灌结构化错误，再让模型总结。

`TUI` 层增加工具过程展示和确认能力。它展示简洁的工具名、参数摘要、影响路径或命令，等待用户输入 `yes/no`；执行后只展示成功/失败、结果大小、是否截断等摘要，不直接打印完整工具输出，避免终端被工具结果淹没。

主流程有两条路径：

```text
普通对话路径：
用户输入
  → Conversation 追加 user
  → Provider 流式请求，不触发工具
  → TUI 流式展示文本
  → Conversation 追加 assistant

工具调用路径：
用户输入
  → Conversation 追加 user
  → Provider 流式请求，解析到工具调用
  → Runtime 处理工具数量、参数预检、用户确认
  → Tools 执行并返回结构化结果
  → Conversation 追加 assistant 工具调用消息和 tool 结果消息
  → Provider 发起最终总结请求，不携带 tools
  → TUI 流式展示最终回复
  → Conversation 追加最终 assistant
```

## 核心数据结构

### ToolConfig

用于保存工具系统配置，只从 `artcode.yaml` 读取允许目录；结果大小和命令超时作为 ch03 固定策略，不开放 YAML 配置。

```python
@dataclass(frozen=True)
class ToolConfig:
    allowed_dirs: tuple[Path, ...]
```

`ArtCodeConfig` 增加：

```python
tools: ToolConfig
```

`SafeConfigStatus` 增加：

```python
allowed_dirs: tuple[str, ...]
```

`CHAPTER_NAME` 更新为 `ch03：工具系统`。

### ToolExecutionContext

工具执行时统一携带运行上下文。所有工具只依赖这个上下文，不直接读取全局配置。

```python
@dataclass(frozen=True)
class ToolExecutionContext:
    path_policy: AllowedPathPolicy
    max_result_bytes: int = 20_000
    command_timeout_seconds: float = 10.0
    default_cwd: Path | None = None
```

`default_cwd` 默认使用第一个允许目录。工具参数里的相对路径会按 `default_cwd` 解析；绝对路径按原路径解析。最终都必须通过允许目录检查。

### AllowedPathPolicy

负责路径边界判断。配置中的允许目录必须是绝对路径；工具传入路径可以是绝对路径或相对路径，但解析后的真实绝对路径必须位于任一允许目录内。

```python
@dataclass(frozen=True)
class AllowedPathPolicy:
    allowed_roots: tuple[Path, ...]

    def resolve_existing_path(self, raw_path: str, base_dir: Path | None = None) -> Path:
        ...

    def resolve_new_file_path(self, raw_path: str, base_dir: Path | None = None) -> Path:
        ...

    def ensure_allowed(self, path: Path) -> Path:
        ...

    def is_allowed(self, path: Path) -> bool:
        ...
```

读取、修改、查找和命令 cwd 使用 `resolve_existing_path`。写新文件使用 `resolve_new_file_path`，它先解析父目录并确认父目录在允许目录内，再组合出目标路径，避免新文件路径通过 `../` 绕出边界。

### ToolResult

所有工具都返回同一种结构化结果。它既给 Runtime 判断，也会序列化成 JSON 字符串写入模型上下文。

```python
@dataclass(frozen=True)
class ToolResult:
    tool_name: str
    ok: bool
    status: str
    message: str
    content: str = ""
    error_code: str | None = None
    truncated: bool = False
    bytes_returned: int = 0

    def to_model_content(self) -> str:
        ...
```

`status` 取值为 `success`、`error`、`denied`。典型错误码包括：

```text
invalid_arguments
path_outside_allowed_dirs
file_not_found
decode_error
already_exists
old_text_not_found
old_text_not_unique
dangerous_command
command_timeout
user_denied
tool_not_found
too_many_tool_calls
```

### ToolPreview

有副作用工具执行前给 TUI 展示的确认摘要。

```python
@dataclass(frozen=True)
class ToolPreview:
    tool_name: str
    summary: str
    target: str
    requires_confirmation: bool
```

TUI 展示内容来自它：工具名、参数摘要、影响路径或命令。

### PreparedToolCall

工具预检成功后的可执行对象。它把已经解析和校验过的参数保存下来，避免 `preview` 校验一遍、`execute` 再猜一遍。

```python
@dataclass(frozen=True)
class PreparedToolCall:
    tool: Tool
    arguments: dict[str, Any]
    preview: ToolPreview
```

### Tool

统一工具接口。每个工具声明名称、描述、参数 Schema、是否需要确认，并实现预检和执行。

```python
class Tool(Protocol):
    name: str
    description: str
    parameters_schema: dict[str, Any]
    requires_confirmation: bool

    def prepare(
        self,
        arguments: dict[str, Any],
        context: ToolExecutionContext,
    ) -> PreparedToolCall | ToolResult:
        ...

    async def execute(
        self,
        prepared: PreparedToolCall,
        context: ToolExecutionContext,
    ) -> ToolResult:
        ...
```

`prepare` 必须无副作用，只做参数校验、路径解析和风险检查。参数错误、路径越界、危险命令等在这一步返回 `ToolResult`。`execute` 只接收预检成功的 `PreparedToolCall`，并真正读写文件或执行命令。

### ToolRegistry

集中登记工具、按名称查找工具，并导出 OpenAI-compatible function tools 格式。

```python
class ToolRegistry:
    def register(self, tool: Tool) -> None:
        ...

    def get(self, name: str) -> Tool | None:
        ...

    def require(self, name: str) -> Tool:
        ...

    def openai_tools(self) -> list[dict[str, Any]]:
        ...
```

导出格式：

```python
{
    "type": "function",
    "function": {
        "name": tool.name,
        "description": tool.description,
        "parameters": tool.parameters_schema,
    },
}
```

### ToolCall

Provider 从流式响应中拼接出的工具调用。这里先保存原始 JSON 参数字符串，解析失败也能作为结构化工具错误回灌给模型。

```python
@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments_json: str
```

Runtime 会尝试把 `arguments_json` 解析成 `dict[str, Any]`。如果解析失败，生成 `invalid_arguments` 工具结果。

### ToolCallAccumulator

OpenAI-compatible 流式响应里的 `tool_calls` 可能分片到达。该对象按 `index` 聚合 `id`、`name` 和 `arguments` 片段。

```python
class ToolCallAccumulator:
    def add_delta(self, delta_tool_calls: list[dict[str, Any]]) -> None:
        ...

    def finish(self) -> list[ToolCall]:
        ...
```

它不执行 JSON 解析，只负责把碎片拼完整。

### Provider 事件

ch02 只有 `content_delta` 和 `done`。ch03 增加 `tool_calls`：

```python
CONTENT_DELTA = "content_delta"
TOOL_CALLS = "tool_calls"
DONE = "done"
```

事件形状：

```python
{"type": "content_delta", "text": "..."}
{"type": "tool_calls", "tool_calls": [ToolCall(...)]}
{"type": "done"}
```

Provider 接口扩展为：

```python
class StreamingProvider(Protocol):
    def stream_chat(
        self,
        messages: Sequence[dict[str, Any]],
        tools: Sequence[dict[str, Any]] | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        ...
```

首次模型请求传入工具列表；最终总结请求传入 `tools=None`。

### ConversationContext

消息类型从 `dict[str, str]` 扩展为 `dict[str, Any]`，以支持 OpenAI-compatible tool call 消息。

新增方法：

```python
def append_assistant_tool_call(self, tool_calls: Sequence[ToolCall]) -> None:
    ...

def append_tool_result(self, tool_call: ToolCall, result: ToolResult) -> None:
    ...
```

assistant 工具调用消息格式：

```python
{
    "role": "assistant",
    "content": "",
    "tool_calls": [
        {
            "id": tool_call.id,
            "type": "function",
            "function": {
                "name": tool_call.name,
                "arguments": tool_call.arguments_json,
            },
        }
    ],
}
```

tool 结果消息格式：

```python
{
    "role": "tool",
    "tool_call_id": tool_call.id,
    "name": tool_call.name,
    "content": result.to_model_content(),
}
```

## 模块设计

### `artcode.config`

**职责：** 扩展 ch02 配置解析，读取工具配置、校验允许目录、创建默认实验目录，并向 TUI 提供安全状态。

**主要接口：**

```python
DEFAULT_ALLOWED_DIR = Path("/Users/arthalter/Work/ArtCode/实验场")

@dataclass(frozen=True)
class ToolConfig:
    allowed_dirs: tuple[Path, ...]

def parse_tool_config(raw: Any | None) -> ToolConfig:
    ...
```

**配置形状：**

```yaml
tools:
  allowed_dirs:
    - /Users/arthalter/Work/ArtCode/实验场
```

如果缺少 `tools` 或 `tools.allowed_dirs`，使用默认目录。配置里只接受绝对路径。默认目录不存在时自动创建；用户显式配置的目录如果不存在，也可以创建，但必须在启动状态中展示最终允许目录。

### `artcode.tools.policy`

**职责：** 统一处理允许目录边界。所有文件路径和命令工作目录都必须经过它。

**主要接口：**

```python
class AllowedPathPolicy:
    def resolve_existing_path(self, raw_path: str, base_dir: Path | None = None) -> Path: ...
    def resolve_new_file_path(self, raw_path: str, base_dir: Path | None = None) -> Path: ...
    def ensure_allowed(self, path: Path) -> Path: ...
    def is_allowed(self, path: Path) -> bool: ...
```

**依赖：** 标准库 `pathlib`。不依赖 TUI、Provider 或 Runtime。

### `artcode.tools.results`

**职责：** 定义工具结果、错误码、截断逻辑和模型回灌格式。

**主要接口：**

```python
MAX_RESULT_BYTES = 20_000

def success_result(...) -> ToolResult: ...
def error_result(...) -> ToolResult: ...
def denied_result(...) -> ToolResult: ...
def truncate_text(text: str, max_bytes: int) -> tuple[str, bool, int]: ...
```

`truncate_text` 按 UTF-8 字节数截断，并保证返回文本仍是合法 Unicode 字符串。

### `artcode.tools.base`

**职责：** 定义 `Tool`、`ToolPreview`、`PreparedToolCall`、`ToolExecutionContext` 等基础抽象。

**依赖：** `artcode.tools.policy`、`artcode.tools.results`。

### `artcode.tools.registry`

**职责：** 集中登记六个核心工具，按名称查找，导出 OpenAI-compatible tools 列表。

**主要接口：**

```python
def create_default_tool_registry() -> ToolRegistry:
    ...
```

注册工具：

```text
read_file
write_file
edit_file
run_command
find_files
search_text
```

### `artcode.tools.file_tools`

**职责：** 实现 `read_file`、`write_file`、`edit_file`、`find_files`、`search_text`。

**设计要点：**

- `read_file` 默认读取整个 UTF-8 文本文件，可选 `start_line` / `end_line`。
- `write_file` 默认不覆盖已有文件，只有 `overwrite: true` 才允许覆盖。
- `edit_file` 使用 `old_text` 严格唯一匹配替换为 `new_text`。
- `find_files` 使用 glob，只返回允许目录内路径。
- `search_text` 使用普通文本匹配，返回路径、行号和匹配行摘要。
- 读取失败、越界、无法解码、匹配次数错误都返回 `ToolResult`，不抛到 Runtime 崩溃。

### `artcode.tools.command_tool`

**职责：** 实现 `run_command`。

**设计要点：**

- 参数接收 shell 命令字符串。
- 工作目录默认是第一个允许目录，也可传入允许目录内的 `cwd`。
- 执行前做基础危险命令拦截。
- 使用 10 秒超时。
- 捕获 stdout、stderr、exit code，并合并成结构化结果。
- 超时返回 `command_timeout`，不让进程卡住主流程。

危险命令拦截放在独立函数中，便于测试：

```python
def validate_shell_command(command: str, policy: AllowedPathPolicy) -> ToolResult | None:
    ...
```

### `artcode.providers.events`

**职责：** 扩展 Provider 事件类型，增加 `tool_calls` 事件校验。

**新增内容：**

```python
TOOL_CALLS = "tool_calls"

def tool_calls_event(tool_calls: Sequence[ToolCall]) -> dict[str, Any]:
    ...
```

### `artcode.providers.tool_calls`

**职责：** 解析和聚合 OpenAI-compatible 流式 `tool_calls` 碎片。

**主要接口：**

```python
@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments_json: str

class ToolCallAccumulator:
    def add_delta(self, delta_tool_calls: list[dict[str, Any]]) -> None: ...
    def finish(self) -> list[ToolCall]: ...
```

### `artcode.providers.openai_compatible`

**职责：** 在请求体中接入工具列表，并从 SSE 中识别文本增量和工具调用增量。

**变化：**

- `build_request_payload` 增加可选 `tools` 参数。
- 首次请求传 `tools` 时，请求体包含 `tools` 和 `tool_choice: "auto"`。
- 最终总结请求不传 `tools`。
- SSE 解析时，`delta.content` 继续产出 `content_delta`。
- SSE 解析时，`delta.tool_calls` 进入 `ToolCallAccumulator`。
- 收到 `[DONE]` 前如果累计到工具调用，产出一次 `tool_calls`，再产出 `done`。
- 如果同一次响应同时出现文本增量和工具调用，Runtime 优先按工具调用路径处理，已流式显示的文本不写入 assistant 最终文本。

### `artcode.conversation.context`

**职责：** 支持 OpenAI-compatible tool call 消息和 tool 结果消息。

**变化：**

- 消息类型从 `dict[str, str]` 改为 `dict[str, Any]`。
- 新增 `append_assistant_tool_call`。
- 新增 `append_tool_result`。
- 多个 tool call 需要追加对应数量的 tool result 消息，避免最终总结请求违反 OpenAI-compatible 消息顺序。
- 保留 ch02 的 `append_user`、`append_assistant`、`export_messages`。

### `artcode.runtime.app`

**职责：** 编排单步工具调用流程。

**变化：**

- Runtime 持有 `ToolRegistry` 和 `ToolExecutionContext`。
- `_generate_assistant_reply` 拆成首次请求和最终总结请求。
- 首次请求允许工具；最终总结请求不允许工具。
- 工具调用数量为 0：按 ch02 文本回复处理。
- 工具调用数量为 1：预检、确认、执行、回灌、总结。
- 工具调用数量大于 1：不执行任何工具，为每个 tool call 追加 `too_many_tool_calls` 结果，再发起最终总结。

### `artcode.tui`

**职责：** 展示工具过程摘要并处理确认输入。

**新增接口：**

```python
def show_tool_preview(self, preview: ToolPreview) -> None: ...
async def confirm_tool_execution(self, preview: ToolPreview) -> bool: ...
def show_tool_result_summary(self, result: ToolResult) -> None: ...
```

确认输入只接受 `yes` / `no`，也允许 `y` / `n` 作为简写。

## 模块交互

### 启动阶段

1. CLI 入口调用配置加载。
2. 配置层读取 `artcode.yaml`。
3. 如果没有 `tools.allowed_dirs`，配置层使用默认允许目录 `/Users/arthalter/Work/ArtCode/实验场`。
4. 配置层校验每个允许目录都是非空绝对路径。
5. 配置层解析允许目录真实路径，并创建不存在的允许目录。
6. Runtime 根据配置创建 `AllowedPathPolicy`、`ToolExecutionContext` 和默认 `ToolRegistry`。
7. TUI 启动状态展示 ch03 章节、模型、base_url、Thinking Mode、masked API key 和允许目录摘要。

### 普通文本对话路径

```text
用户输入普通问题
  → Runtime 追加 user 消息
  → Runtime 调用 Provider.stream_chat(messages, tools=registry.openai_tools())
  → Provider 流式产出 content_delta
  → TUI 实时输出文本
  → Provider 产出 done
  → Runtime 将完整 assistant 文本写入 Conversation Context
  → 回到输入状态
```

如果模型没有调用工具，行为应和 ch02 保持一致。

### 单工具调用路径

```text
用户输入任务
  → Runtime 追加 user 消息
  → Runtime 调用 Provider.stream_chat(messages, tools=registry.openai_tools())
  → Provider 聚合 tool_calls 参数碎片
  → Provider 产出 tool_calls 事件
  → Runtime 确认只有一个 ToolCall
  → Runtime 将 assistant tool_call 消息写入 Conversation Context
  → Runtime 解析 arguments_json
  → Runtime 从 ToolRegistry 查找工具
  → Tool.prepare 返回 PreparedToolCall 或 ToolResult 错误
  → 如果工具需要确认，TUI 询问 yes/no
  → 用户确认后 Tool.execute
  → ToolResult 写入 Conversation Context 的 tool 消息
  → TUI 展示工具结果摘要
  → Runtime 调用 Provider.stream_chat(messages, tools=None)
  → Provider 流式产出最终 content_delta
  → TUI 实时输出最终回复
  → Runtime 将最终 assistant 文本写入 Conversation Context
  → 回到输入状态
```

### 用户拒绝有副作用工具路径

```text
Tool.prepare 返回需要确认的 PreparedToolCall
  → TUI 展示工具名、参数摘要、影响路径或命令
  → 用户输入 no
  → Runtime 构造 user_denied ToolResult
  → Conversation 追加 tool 结果消息
  → Runtime 发起最终总结请求，不携带 tools
  → 模型向用户说明操作被拒绝或给出替代建议
```

拒绝时不执行工具，不写文件，不改文件，不跑命令。

### 参数错误路径

```text
Provider 产出 ToolCall
  → Runtime 写入 assistant tool_call 消息
  → Runtime 解析 arguments_json
  → JSON 解析失败、缺字段、字段类型错误或工具不存在
  → Runtime 构造结构化 ToolResult
  → Conversation 追加 tool 结果消息
  → Runtime 发起最终总结请求
```

参数错误不直接让 Runtime 崩溃，也不静默忽略。

### 多工具调用路径

```text
Provider 产出多个 ToolCall
  → Runtime 不执行任何工具
  → Conversation 追加包含所有 tool calls 的 assistant 消息
  → Runtime 为每个 tool_call_id 都追加 too_many_tool_calls ToolResult
  → Runtime 发起最终总结请求
```

这样既满足“ch03 不执行多个工具”，也保持 OpenAI-compatible tool call / tool result 消息顺序完整。

### 工具结果截断路径

```text
Tool.execute 生成原始内容
  → truncate_text 按 UTF-8 字节上限截断到 20KB 内
  → ToolResult.truncated = True
  → ToolResult.bytes_returned 记录实际返回字节数
  → TUI 摘要显示“已截断”
  → 模型上下文中的 tool 内容包含 truncated 标记
```

### 命令执行路径

```text
run_command.prepare
  → 校验 command 是非空字符串
  → 校验 cwd 落在允许目录内
  → 基础危险命令拦截
  → TUI 请求确认
  → run_command.execute
  → asyncio.create_subprocess_shell(command, cwd=allowed_cwd)
  → asyncio.wait_for(..., timeout=10)
  → 捕获 stdout/stderr/exit_code
  → 生成 ToolResult
```

### 取消生成行为

ch02 已支持生成期间 Ctrl+C 取消。本章保持这个语义：

- 首次模型请求被取消：不写入 assistant 回复，不执行工具。
- 最终总结请求被取消：工具结果已经写入 Conversation Context，但半截最终 assistant 回复不写入。
- 工具执行期间暂不承诺 Ctrl+C 精细取消；命令工具主要靠 10 秒超时兜底。

## 文件组织

```text
ArtCode/
├── artcode/
│   ├── config.py
│   │   └── 修改：增加 ToolConfig、默认允许目录、allowed_dirs 解析、ch03 启动状态
│   ├── prompts.py
│   │   └── 修改：把 system prompt 从 ch02 纯对话更新为 ch03 工具系统提示
│   ├── errors.py
│   │   └── 修改：必要时补充工具配置启动错误复用逻辑，不把工具执行失败作为异常主路径
│   ├── conversation/
│   │   ├── context.py
│   │   │   └── 修改：消息类型支持 dict[str, Any]，新增 tool_call 和 tool_result 写入
│   │   └── __init__.py
│   │       └── 修改：导出新增消息相关类型或方法
│   ├── providers/
│   │   ├── base.py
│   │   │   └── 修改：stream_chat 接口增加可选 tools 参数
│   │   ├── events.py
│   │   │   └── 修改：增加 TOOL_CALLS 事件和校验
│   │   ├── tool_calls.py
│   │   │   └── 新建：ToolCall、ToolCallAccumulator、流式参数碎片聚合
│   │   ├── openai_compatible.py
│   │   │   └── 修改：请求体支持 tools，SSE 解析支持 delta.tool_calls
│   │   └── __init__.py
│   │       └── 修改：按需导出新增类型
│   ├── tools/
│   │   ├── __init__.py
│   │   │   └── 新建：导出工具系统公共入口
│   │   ├── base.py
│   │   │   └── 新建：Tool、ToolPreview、PreparedToolCall、ToolExecutionContext
│   │   ├── policy.py
│   │   │   └── 新建：AllowedPathPolicy 和路径边界检查
│   │   ├── results.py
│   │   │   └── 新建：ToolResult、错误码、截断和 JSON 序列化
│   │   ├── registry.py
│   │   │   └── 新建：ToolRegistry、默认六工具注册、OpenAI tools 导出
│   │   ├── file_tools.py
│   │   │   └── 新建：read_file、write_file、edit_file、find_files、search_text
│   │   └── command_tool.py
│   │       └── 新建：run_command、危险命令检查、命令超时执行
│   ├── runtime/
│   │   ├── app.py
│   │   │   └── 修改：接入 ToolRegistry、ToolExecutionContext、单步工具编排和最终总结
│   │   └── __init__.py
│   │       └── 修改：按需导出 Runtime 类型
│   ├── tui/
│   │   ├── app.py
│   │   │   └── 修改：增加确认输入方法并委托 renderer 展示工具摘要
│   │   ├── render.py
│   │   │   └── 修改：启动状态显示 ch03 与 allowed_dirs，增加工具 preview/result 展示
│   │   └── __init__.py
│   │       └── 修改：按需导出新增 TUI 协议能力
│   ├── cli.py
│   │   └── 修改：创建默认 ToolRegistry 和 ToolExecutionContext 后传入 Runtime
│   └── __main__.py
│       └── 通常不需要修改，继续走 cli.main
├── tests/
│   ├── unit/
│   │   ├── test_config.py
│   │   │   └── 修改：覆盖 tools.allowed_dirs 默认值、绝对路径校验、目录创建
│   │   ├── test_context.py
│   │   │   └── 修改：覆盖 assistant tool_call 和 tool result 消息写入
│   │   ├── test_provider_events.py
│   │   │   └── 修改：覆盖 TOOL_CALLS 事件格式
│   │   ├── test_openai_provider.py
│   │   │   └── 修改：覆盖 tools 请求体、tool_choice、流式 tool_calls 解析
│   │   ├── test_runtime.py
│   │   │   └── 修改：覆盖普通对话兼容、单工具执行、拒绝确认、多工具错误、最终总结不带 tools
│   │   ├── test_render.py
│   │   │   └── 修改：覆盖启动状态 allowed_dirs 和工具摘要不打印完整结果
│   │   ├── test_tool_policy.py
│   │   │   └── 新建：覆盖允许目录、路径解析、越界拒绝、新文件父目录检查
│   │   ├── test_tool_registry.py
│   │   │   └── 新建：覆盖六工具注册、按名查找、OpenAI-compatible 导出
│   │   ├── test_file_tools.py
│   │   │   └── 新建：覆盖 read/write/edit/find/search 五个文件工具
│   │   ├── test_command_tool.py
│   │   │   └── 新建：覆盖 run_command、cwd 限制、危险命令、超时
│   │   └── test_tool_calls.py
│   │       └── 新建：覆盖 JSON 参数碎片拼接和多 tool_call 聚合
│   └── integration/
│       ├── test_deepseek_live.py
│       │   └── 修改：可补充真实工具调用 smoke 验证；若成本或模型不稳定，则保持核心 live 对话测试
│       └── README.md
│           └── 修改：说明 ch03 工具调用集成测试会真实调用 API，且只操作实验场
├── artcode.example.yaml
│   └── 修改：增加 tools.allowed_dirs 示例，使用默认实验场绝对路径
├── README.md
│   └── 修改：更新 ch03 简要说明和安全边界
├── spec.md
│   └── 已生成：ch03 需求文档
└── plan.md
    └── 新建：本文档
```

补充约定：

- ch03 的工具实现集中放在 `artcode/tools/`，不把文件读写散落到 Runtime 或 Provider。
- 单元测试优先使用 `tmp_path` 构造临时允许目录，不直接破坏真实 `实验场` 内容。
- 真实端到端验证如果涉及写文件，只写入 `实验场` 内专门测试文件名，并在测试中清理或覆盖固定测试文件。
- `spec汇总/ch02/` 保持作为历史归档，不在 ch03 设计阶段修改。

## 技术决策

| 决策点 | 选择 | 理由 |
|---|---|---|
| 工具调用格式 | 使用 OpenAI-compatible function tools | 当前 Provider 已接 OpenAI-compatible Chat Completions，先直接适配现有协议，避免 ch03 过早引入多 Provider 转换层。 |
| 工具调用轮次 | 首次请求允许工具，工具执行后最终总结请求不带 tools | 满足“工具执行后自然语言总结”，同时明确不进入连续 Agent Loop。 |
| 单轮工具数量 | 同一轮最多允许一个工具调用 | 保持 ch03 范围清楚，多工具编排留给下一章。 |
| 多工具回灌 | 不执行任何工具，但为每个 tool_call_id 都追加错误 tool result | 避免最终总结请求违反 OpenAI-compatible tool call / tool result 配对要求。 |
| 工具预检 | `prepare` 返回 `PreparedToolCall` 或 `ToolResult` | 参数错误、路径越界和危险命令在无副作用阶段处理，执行阶段只处理已校验输入。 |
| 工具执行边界 | 所有核心工具都受允许目录限制 | 读、写、改、找、搜、命令执行共享同一安全边界，新手更容易理解。 |
| 允许目录配置 | `artcode.yaml` 中配置绝对路径列表 | 启动时固定、可测试、可解释；绝对路径避免相对路径含义混乱。 |
| 默认允许目录 | `/Users/arthalter/Work/ArtCode/实验场` | 符合本项目学习场景，把真实源码和实验操作分开。 |
| 默认目录不存在 | 启动时自动创建 | 减少首次使用门槛，启动状态仍会展示当前允许目录。 |
| 有副作用工具 | 写文件、改文件、执行命令前必须确认 | 在允许目录基础上再加一层人为确认，降低误操作风险。 |
| 用户拒绝工具 | 作为结构化工具结果回灌给模型 | 模型能解释“为什么没有执行”，上下文也保留本轮事实。 |
| 工具结果格式 | 统一 `ToolResult` 并 JSON 序列化给模型 | 成功、失败、拒绝、超时、截断都用同一形状，便于模型理解和测试断言。 |
| 结果大小限制 | 单次 20KB，按 UTF-8 字节截断 | 控制上下文占用，仍足够覆盖小文件、搜索结果和命令报错。 |
| 文件编码 | 只支持 UTF-8 文本 | ch03 聚焦 coding agent 基础能力，二进制处理留到后续。 |
| 写文件覆盖 | 默认拒绝覆盖，必须 `overwrite: true` | 防止误覆盖，也训练模型明确表达意图。 |
| 改文件规则 | 严格原文唯一匹配替换 | 行为可预测；匹配不到或多次匹配都让模型根据错误重试。 |
| 找文件规则 | glob | 和开发者常见文件匹配习惯一致，比正则更适合新手。 |
| 搜文本规则 | 普通文本匹配 | 避免正则语法复杂度，满足 ch03 搜代码内容需求。 |
| 命令执行形式 | 接收 shell 命令字符串 | 最接近真实 CLI agent 使用体验；结合允许目录、危险命令拦截和确认控制风险。 |
| 命令超时 | 固定 10 秒 | 避免卡住学习型 CLI；配置化留到后续。 |
| 危险命令控制 | 基础危险命令拦截，不承诺完整沙箱 | 能挡住明显高风险命令，同时如实保留 ch03 的能力边界。 |
| TUI 工具输出 | 展示过程和摘要，不展示完整结果 | 用户知道工具发生了什么，终端又不会被大段输出淹没。 |
| 工具结果保存 | 保存到本次运行 Conversation Context，不落盘 | 与 ch02 会话边界一致，支持后续追问引用刚刚的工具结果。 |
| 测试策略 | 工具和编排用单元测试为主，真实 API 只做 smoke | 工具行为应稳定可测；真实模型工具调用受模型和网络影响，不宜承担大量确定性断言。 |

## Spec 覆盖检查

- F1-F3 由 `artcode.tools.base`、`registry`、`file_tools`、`command_tool` 覆盖。
- F4-F5 由 `artcode.config` 和 `artcode.tools.policy` 覆盖。
- F6-F7 由 `ToolPreview`、TUI 确认接口和 Runtime 拒绝回灌覆盖。
- F8-F13 由 `ToolResult`、文件工具、命令工具、截断和错误码覆盖。
- F14-F15 由 `providers.tool_calls`、Provider 事件和 Runtime 多工具错误处理覆盖。
- F16 由 Conversation 工具消息写入、Runtime 最终总结请求和 Provider `tools=None` 覆盖。
- F17 由 TUI 工具 preview/result 展示覆盖。
- F18 由 `artcode.prompts` 更新覆盖。
- 未发现未覆盖的功能需求。
