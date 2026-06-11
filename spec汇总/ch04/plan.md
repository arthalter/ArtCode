# ch04：动手实现 Agent Loop Plan

## 架构概览

ch04 新增独立的 `Agent` 层，位于 `Runtime` 和现有 `Provider / Tools / Conversation` 之间。`Runtime` 不再直接处理“模型请求 → 工具执行 → 总结”的细节，而是把普通输入、`/plan`、`/do` 转换成一次 Agent 运行请求，然后消费 Agent 层产生的结构化事件并交给 TUI 展示。

`Agent` 层是本章核心，负责 ReAct 循环。它每轮导出当前 Conversation Context，按当前模式选择工具列表，请求 Provider 流式响应，收集完整模型输出，判断模型是自然结束还是请求工具；如果请求工具，就执行工具、写回工具调用消息和工具结果消息，再进入下一轮。循环最多 12 轮。

`Agent` 层内部拆成四个子组件：

- `AgentLoop`：主循环控制器，负责 12 轮上限、停止条件、异常最终总结、取消传播和上下文写入顺序。
- `StreamCollector`：消费 Provider 流式事件，一边发出文本增量事件给界面，一边收集完整文本、工具调用和 Token 用量。
- `ToolBatchExecutor`：负责多工具调用的预检、未知工具整体停止、按安全性分批、只读工具并发、有副作用工具串行、按原始顺序回灌结果。
- `PlanMemory`：保存本次运行内最近计划，支持 `/plan` 写入和 `/do` 读取，不落盘。

`Runtime` 层保留用户输入主循环、退出命令和 TUI 绑定，但它的职责会收窄：读取输入、识别 `/plan` 和 `/do`，构造 Agent 运行模式，遍历 Agent 事件，并调用 TUI 展示文本、工具、进度、错误和停止原因。ch03 中直接放在 Runtime 里的 `_generate_model_response`、`_handle_tool_calls`、`_execute_one_tool_call` 会迁移到 Agent 层或被 Agent 层替代。

`Commands` 层会从“只支持完整命令匹配”扩展为“支持带参数 Slash Command”。`/plan 任务描述` 会被解析为计划请求，`/do` 和 `/do 附加说明` 会被解析为执行最近计划请求；`/exit`、`/quit`、`/help` 保持原行为。

`Provider` 层继续保持 OpenAI-compatible Chat Completions 边界。ch04 不改变工具调用解析的大方向，但会扩展事件类型，支持 Provider 在返回真实 usage 信息时产出 Token 用量事件。Provider 不关心 Agent Loop，也不执行工具。

`Tools` 层继续使用 ch03 的工具抽象、注册中心、允许目录策略和结构化结果。ch04 不改工具的安全边界，只在 Agent 层改变调用策略：允许一次模型响应携带多个工具调用，取消 ch03 的单工具限制，并且 Agent Loop 中不再调用 TUI yes/no 确认。

`Conversation` 层继续作为本次运行内上下文存储。普通自然语言回复写入 assistant 消息；带工具调用的轮次写入 assistant tool_call 消息和对应 tool result 消息；同一轮里模型先输出的过程文本只实时展示，不单独写入普通 assistant 消息。

`TUI` 层增加 Agent Loop 进度展示能力。它消费 Runtime 转发来的 Agent 事件，展示第几轮、工具调用数量、工具批次、工具结果摘要、Token 用量和停止原因。完整工具输出仍不直接刷屏。

主流程分为三条：

```text
普通输入：
用户输入任务
  → Runtime 追加 user 消息
  → AgentLoop 使用全工具循环
  → 模型自然结束或停止条件触发
  → Runtime/TUI 展示最终结果和停止原因

/plan：
用户输入 /plan 任务描述
  → Runtime 追加 user 计划请求
  → AgentLoop 使用只读工具循环
  → 自然语言计划写入上下文
  → PlanMemory 保存最近计划

/do：
用户输入 /do 或 /do 附加说明
  → Runtime 从 PlanMemory 读取最近计划
  → Runtime 追加 user 执行请求
  → AgentLoop 使用全工具循环执行计划
  → 模型自然结束或停止条件触发
```

## 核心数据结构

### AgentMode

表示一次 Agent 运行的模式，决定可用工具范围和提示语义。

```python
@dataclass(frozen=True)
class AgentMode:
    name: str
    tool_policy: ToolAccessPolicy
    purpose: str
```

预置三种模式：

```python
NORMAL_AGENT_MODE   # 普通输入，全工具
PLAN_MODE           # /plan，只读工具
DO_MODE             # /do，全工具，携带最近计划
```

### ToolAccessPolicy

描述当前模式可暴露给模型的工具范围。

```python
@dataclass(frozen=True)
class ToolAccessPolicy:
    allowed_tool_names: frozenset[str] | None

    def allows(self, tool_name: str) -> bool:
        ...

    def filter_openai_tools(self, tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        ...
```

约定：

```python
READ_ONLY_TOOL_NAMES = frozenset({"read_file", "find_files", "search_text"})
```

`allowed_tool_names=None` 表示全工具。

### AgentRunRequest

Runtime 发给 AgentLoop 的一次运行请求。

```python
@dataclass(frozen=True)
class AgentRunRequest:
    user_content: str
    mode: AgentMode
    max_iterations: int = 12
    append_user_message: bool = True
    final_summary_on_abnormal_stop: bool = True
```

含义：

- 普通输入：`user_content` 是用户原始任务。
- `/plan`：`user_content` 是计划请求文本。
- `/do`：`user_content` 是最近计划和附加说明组合出的执行目标。
- `append_user_message` 用于控制是否由 AgentLoop 写入 user 消息；默认由 AgentLoop 写入，Runtime 不再重复写。
- 用户取消和流式错误会跳过异常最终总结，即使 `final_summary_on_abnormal_stop=True`。

### AgentRunResult

AgentLoop 完成后的结果摘要，主要用于测试和 Runtime 判断是否保存最近计划。

```python
@dataclass(frozen=True)
class AgentRunResult:
    stop_reason: StopReason
    final_text: str
    iterations_used: int
    tool_results_count: int
    saved_plan: str | None = None
```

### StopReason

Agent Loop 停止原因。

```python
class StopReason(StrEnum):
    NATURAL = "natural"
    ITERATION_LIMIT = "iteration_limit"
    UNKNOWN_TOOL = "unknown_tool"
    USER_CANCELLED = "user_cancelled"
    STREAM_ERROR = "stream_error"
```

### ModelTurn

一次模型流式响应被完整收集后的结果。

```python
@dataclass(frozen=True)
class ModelTurn:
    text: str
    tool_calls: list[ToolCall]
    usage: TokenUsage | None = None
```

规则：

- 没有工具调用时，`text` 可以作为自然语言 assistant 消息写入上下文。
- 有工具调用时，`text` 只用于实时展示，不作为普通 assistant 消息写入上下文。
- `tool_calls` 可以包含多个工具调用。

### TokenUsage

Provider 返回真实用量时使用；不估算。

```python
@dataclass(frozen=True)
class TokenUsage:
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
```

### AgentEvent

Agent 层向 Runtime/TUI 发出的结构化事件。

```python
@dataclass(frozen=True)
class AgentEvent:
    type: AgentEventType
    payload: dict[str, Any]
```

事件类型：

```python
class AgentEventType(StrEnum):
    RUN_STARTED = "run_started"
    ITERATION_STARTED = "iteration_started"
    TEXT_DELTA = "text_delta"
    MODEL_TURN_COMPLETED = "model_turn_completed"
    TOOL_CALLS_RECEIVED = "tool_calls_received"
    TOOL_BATCH_STARTED = "tool_batch_started"
    TOOL_RESULT = "tool_result"
    TOKEN_USAGE = "token_usage"
    FINAL_SUMMARY_STARTED = "final_summary_started"
    STOPPED = "stopped"
```

### ToolSafety

工具安全分类，用于分批。

```python
class ToolSafety(StrEnum):
    READ_ONLY = "read_only"
    SIDE_EFFECT = "side_effect"
```

分类规则：

```python
read_file   -> READ_ONLY
find_files  -> READ_ONLY
search_text -> READ_ONLY
write_file  -> SIDE_EFFECT
edit_file   -> SIDE_EFFECT
run_command -> SIDE_EFFECT
```

未知工具不分类，直接触发未知工具停止。

### ToolExecutionPlan

一次模型响应中的工具调用分批结果。

```python
@dataclass(frozen=True)
class ToolExecutionBatch:
    index: int
    safety: ToolSafety
    tool_calls: tuple[ToolCall, ...]

@dataclass(frozen=True)
class ToolExecutionPlan:
    batches: tuple[ToolExecutionBatch, ...]
```

分批规则：

- 按模型原始工具调用顺序扫描。
- 连续只读工具合并为一个并发批次。
- 每个有副作用工具单独成为一个串行批次。
- 有副作用工具前后的只读工具不会跨过去合并。

### PreparedToolExecution

ToolBatchExecutor 预检后的执行对象。

```python
@dataclass(frozen=True)
class PreparedToolExecution:
    tool_call: ToolCall
    tool: Tool
    prepared: PreparedToolCall
```

参数 JSON 解析失败、工具预检失败、路径越界、危险命令等不产生 `PreparedToolExecution`，而是直接产生 `ToolResult` 并按已知工具失败继续循环。

### PlanMemory

本次运行内最近计划。

```python
@dataclass
class PlanMemory:
    latest_plan: str | None = None

    def save(self, plan: str) -> None:
        ...

    def get(self) -> str | None:
        ...

    def clear(self) -> None:
        ...
```

## 核心接口

### AgentLoop

```python
class AgentLoop:
    def __init__(
        self,
        provider: StreamingProvider,
        conversation: ConversationContext,
        tool_registry: ToolRegistry,
        tool_context: ToolExecutionContext,
        plan_memory: PlanMemory,
    ) -> None:
        ...

    async def run(self, request: AgentRunRequest) -> AsyncIterator[AgentEvent]:
        ...
```

`run` 是异步事件流。Runtime 使用：

```python
async for event in agent_loop.run(request):
    ...
```

### StreamCollector

```python
class StreamCollector:
    async def collect(
        self,
        provider: StreamingProvider,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
    ) -> AsyncIterator[AgentEvent | ModelTurn]:
        ...
```

设计意图：

- 收到 `content_delta` 时立即 yield `TEXT_DELTA`。
- 收到真实 usage 时 yield `TOKEN_USAGE`。
- 流结束时 yield `ModelTurn`。
- 如果 Provider 抛出 `RequestError`，由 AgentLoop 转换成 `STREAM_ERROR` 停止。

### ToolBatchExecutor

```python
class ToolBatchExecutor:
    def __init__(
        self,
        tool_registry: ToolRegistry,
        tool_context: ToolExecutionContext,
    ) -> None:
        ...

    def build_plan(self, tool_calls: list[ToolCall], policy: ToolAccessPolicy) -> ToolExecutionPlan | ToolResult:
        ...

    async def execute_plan(
        self,
        plan: ToolExecutionPlan,
    ) -> AsyncIterator[AgentEvent]:
        ...
```

约定：

- `build_plan` 如果发现未知工具或当前模式不允许的工具，返回对应结构化错误结果并触发异常停止。
- `execute_plan` 内部会按批次执行工具。
- 只读批次使用 `asyncio.gather` 并发执行。
- 有副作用批次一次只执行一个工具。
- 输出的 `TOOL_RESULT` 事件按模型原始顺序产生。

### Runtime 接入接口

Runtime 不再手写工具循环，只构造请求：

```python
request = AgentRunRequest(user_content=user_input, mode=NORMAL_AGENT_MODE)
```

`/plan`：

```python
request = AgentRunRequest(user_content=task, mode=PLAN_MODE)
```

`/do`：

```python
request = AgentRunRequest(user_content=execution_prompt, mode=DO_MODE)
```

Runtime 负责把事件转成 TUI 调用，不负责判断工具批次和停止条件。

## 模块设计

### `artcode.agent.events`

**职责：** 定义 Agent 层事件、停止原因、Token 用量、模型轮次结果等通用结构。

**对外接口：**

```python
AgentEvent
AgentEventType
StopReason
TokenUsage
ModelTurn
```

**依赖：** 只依赖标准库和 `artcode.providers.tool_calls.ToolCall`。

**覆盖需求：** F15、F19、F20、N2、N3、N14。

### `artcode.agent.modes`

**职责：** 定义 Agent 运行模式和工具访问策略。

**对外接口：**

```python
AgentMode
ToolAccessPolicy
READ_ONLY_TOOL_NAMES
NORMAL_AGENT_MODE
PLAN_MODE
DO_MODE
```

**依赖：** 不依赖 Runtime/TUI，只处理工具名过滤。

**覆盖需求：** F21、F25、F26、AC23、AC30。

### `artcode.agent.memory`

**职责：** 保存本次进程内最近计划。

**对外接口：**

```python
PlanMemory
```

**依赖：** 无外部业务依赖。

**覆盖需求：** F22、F23、F24、AC25、AC26、AC27。

### `artcode.agent.stream`

**职责：** 消费 Provider 流式事件，实时产出文本事件，同时收集完整模型轮次结果。

**对外接口：**

```python
StreamCollector.collect(...)
```

**行为：**

- `content_delta` → 产出 `TEXT_DELTA` 事件，并追加到完整文本缓冲。
- `tool_calls` → 保存完整工具调用列表。
- `token_usage` → 产出 `TOKEN_USAGE` 事件。
- `done` → 产出 `ModelTurn`。
- Provider 异常向上抛给 `AgentLoop` 处理。

**依赖：** `StreamingProvider`、Provider 事件常量、`ModelTurn`、`AgentEvent`。

**覆盖需求：** F14、F16、F19、AC16、AC18、AC19、AC20。

### `artcode.agent.tools`

**职责：** 实现工具安全分类、多工具分批、工具参数解析、工具预检和执行。

**对外接口：**

```python
ToolSafety
ToolExecutionBatch
ToolExecutionPlan
PreparedToolExecution
ToolBatchExecutor
```

**行为：**

- 检查每个 tool call 是否存在于 `ToolRegistry`。
- 检查每个工具是否被当前 `ToolAccessPolicy` 允许。
- 同一轮中只要出现未知工具或模式不允许工具，整轮工具都不执行。
- JSON 参数解析失败、工具 prepare 失败等已知工具失败，会作为 tool result 写回上下文，并允许 AgentLoop 进入下一轮。
- 相邻只读工具组成并发批次。
- 有副作用工具单独组成串行批次。
- Agent Loop 中不调用 `confirm_tool_execution`。

**依赖：** `ToolRegistry`、`ToolExecutionContext`、`Tool`、`PreparedToolCall`、`ToolResult`、`ToolCall`。

**覆盖需求：** F5-F12、AC4-AC13。

### `artcode.agent.loop`

**职责：** 实现 ch04 的 Agent Loop 主编排。

**对外接口：**

```python
AgentLoop
AgentRunRequest
AgentRunResult
```

**行为：**

1. 根据请求追加 user 消息。
2. 发出 `RUN_STARTED`。
3. 从第 1 轮到第 12 轮循环：
   - 发出 `ITERATION_STARTED`。
   - 按当前模式过滤工具列表。
   - 使用 `StreamCollector` 请求模型并转发文本/用量事件。
   - 如果模型不请求工具：写入普通 assistant 消息，发出 `STOPPED(natural)`，结束。
   - 如果模型请求工具：写入 assistant tool_call 消息。
   - 使用 `ToolBatchExecutor` 构造并执行工具批次。
   - 按顺序写入 tool result 消息。
   - 继续下一轮。
4. 达到 12 轮上限：发出 `STOPPED(iteration_limit)`，尽量做一次无工具最终总结。
5. 发现未知工具：不执行本轮工具，写入结构化错误，发出 `STOPPED(unknown_tool)`，尽量做一次无工具最终总结。
6. 用户取消：停止整轮循环，不写入半截文本，不再总结。
7. 流式错误：停止整轮循环，不写入半截文本，不再总结。

**依赖：** `StreamCollector`、`ToolBatchExecutor`、`ConversationContext`、`ToolRegistry`、`ToolExecutionContext`、`PlanMemory`。

**覆盖需求：** F1-F4、F13-F18、F27-F28、AC1-AC3、AC14-AC17、AC21-AC22、AC31。

### `artcode.commands.base`

**职责：** 扩展 Slash Command 解析能力，让命令可以携带参数。

**对外接口变化：**

```python
@dataclass(frozen=True)
class CommandResult:
    action: str
    message: str = ""
    argument: str = ""
```

`CommandRegistry.handle` 从“完全匹配整行”改为：

- 第一段作为命令名。
- 后续文本作为 `argument`。
- 仍然只处理单行 slash command；多行输入不当作命令。

**覆盖需求：** F21、F24、AC27-AC29。

### `artcode.commands.builtin`

**职责：** 注册 `/plan` 和 `/do`，更新 `/help`。

**行为：**

- `/plan 任务描述` 返回 `action="plan"` 和任务描述。
- `/plan` 无任务描述时返回帮助提示。
- `/do` 返回 `action="do"`，argument 为空。
- `/do 附加说明` 返回 `action="do"` 和附加说明。
- `/exit`、`/quit`、`/help` 保持原有语义。

### `artcode.runtime.app`

**职责：** 接入 AgentLoop，消费 AgentEvent，并把事件转发给 TUI。

**变化：**

- 删除或停用 ch03 的单步 `_handle_tool_calls` 编排。
- 初始化并持有 `AgentLoop` 和 `PlanMemory`。
- 普通输入构造 `NORMAL_AGENT_MODE` 请求。
- `/plan` 构造 `PLAN_MODE` 请求；运行结束后由 AgentLoop 保存最近计划。
- `/do` 从 `PlanMemory` 读取最近计划；没有计划时展示提示；有计划时构造 `DO_MODE` 请求。
- 将事件转成 TUI 调用：文本增量、工具批次、工具结果、Token 用量、停止原因等。

**覆盖需求：** F1、F21-F28、AC27-AC32。

### `artcode.tui.render` / `artcode.tui.app`

**职责：** 增加 Agent Loop 进度展示，不再在 Agent Loop 中弹出工具确认。

**新增展示：**

```python
show_agent_iteration(current: int, maximum: int)
show_tool_calls_received(count: int)
show_tool_batch_started(batch_index: int, safety: str, count: int)
show_token_usage(...)
show_agent_stopped(reason: str, message: str)
```

**保留展示：**

- `stream_delta`
- `finish_assistant_message`
- `show_tool_preview`
- `show_tool_result_summary`

`confirm_tool_execution` 可以暂时保留给未来章节或兼容测试，但 ch04 AgentLoop 不调用它。

### `artcode.providers.events`

**职责：** 扩展 Provider 事件类型，支持真实 Token 用量。

**新增：**

```python
TOKEN_USAGE = "token_usage"

def token_usage_event(usage: TokenUsage | dict[str, int | None]) -> dict[str, Any]:
    ...
```

Provider 层只在上游确实返回 usage 时发出该事件。

### `artcode.providers.openai_compatible`

**职责：** 解析 OpenAI-compatible 流式响应里的真实 usage。

**变化：**

- 在 SSE payload 中检查 `usage` 字段。
- 如果存在真实 usage，产出 `token_usage` Provider 事件。
- 不估算 token。
- 仍然在 `[DONE]` 前产出完整 tool_calls 事件。

### `artcode.prompts`

**职责：** 更新 ch04 系统提示。

**变化：**

- 说明普通输入默认进入 Agent Loop。
- 说明同一轮可以请求多个工具。
- 说明 `/plan` 只能使用只读工具。
- 说明 Agent Loop 中有副作用工具会自动执行，模型必须谨慎使用。
- 说明未知工具会终止本轮任务。
- 移除 ch03 “单轮最多一个工具调用”和“工具执行后最终回复”的限制描述。

## 模块交互

### 普通 Agent Loop

```text
Runtime
  读取用户输入
  └─ CommandRegistry 判断不是 slash command
     └─ AgentLoop.run(NORMAL_AGENT_MODE, user_content)
        ├─ ConversationContext.append_user(user_content)
        ├─ emit RUN_STARTED
        ├─ for iteration in 1..12
        │  ├─ emit ITERATION_STARTED
        │  ├─ ToolAccessPolicy 过滤全工具列表
        │  ├─ StreamCollector.collect(provider, messages, tools)
        │  │  ├─ Provider.stream_chat(...)
        │  │  ├─ content_delta → emit TEXT_DELTA
        │  │  ├─ token_usage → emit TOKEN_USAGE
        │  │  └─ done → ModelTurn(text, tool_calls, usage)
        │  ├─ 如果没有 tool_calls
        │  │  ├─ ConversationContext.append_assistant(text)
        │  │  ├─ emit STOPPED(natural)
        │  │  └─ return
        │  ├─ 如果有 tool_calls
        │  │  ├─ ConversationContext.append_assistant_tool_call(tool_calls)
        │  │  ├─ emit TOOL_CALLS_RECEIVED
        │  │  ├─ ToolBatchExecutor.build_plan(tool_calls, full_tool_policy)
        │  │  ├─ 如果未知工具或模式不允许工具
        │  │  │  ├─ 写入对应 tool result
        │  │  │  ├─ emit TOOL_RESULT
        │  │  │  ├─ emit STOPPED(unknown_tool)
        │  │  │  └─ 无工具最终总结
        │  │  ├─ ToolBatchExecutor.execute_plan(...)
        │  │  │  ├─ emit TOOL_BATCH_STARTED
        │  │  │  ├─ 只读批次 asyncio.gather 并发执行
        │  │  │  ├─ 有副作用批次串行执行
        │  │  │  └─ emit TOOL_RESULT（按原始顺序）
        │  │  └─ ConversationContext.append_tool_result(...)
        │  └─ 进入下一轮
        └─ 12 轮用尽
           ├─ emit STOPPED(iteration_limit)
           └─ 无工具最终总结
```

### `/plan 任务描述`

```text
Runtime
  CommandRegistry.handle("/plan 任务描述")
  └─ CommandResult(action="plan", argument="任务描述")
     └─ AgentLoop.run(PLAN_MODE, user_content)
        ├─ ConversationContext.append_user("请先制定计划：任务描述")
        ├─ 每轮只暴露 read_file / find_files / search_text
        ├─ 如果模型请求写文件、改文件或执行命令
        │  ├─ 作为模式不允许工具处理
        │  ├─ 本轮工具不执行
        │  └─ 停止并总结原因
        ├─ 自然结束时写入 assistant 计划文本
        └─ PlanMemory.save(final_text)
```

`/plan` 的最近计划来自自然结束时的最终文本。若 `/plan` 因未知工具、流式错误、用户取消或迭代上限没有得到可用最终文本，则不覆盖旧计划。

### `/do` 与 `/do 附加说明`

```text
Runtime
  CommandRegistry.handle("/do ...")
  ├─ PlanMemory.get()
  ├─ 如果没有最近计划
  │  └─ TUI 提示“请先执行 /plan 任务描述”
  └─ 如果有最近计划
     ├─ 组合执行目标：
     │  最近计划
     │  附加说明（如有）
     └─ AgentLoop.run(DO_MODE, execution_prompt)
        ├─ ConversationContext.append_user(execution_prompt)
        ├─ 每轮暴露全工具
        └─ 按普通 Agent Loop 执行
```

### 异常最终总结

异常最终总结只在以下停止原因触发：

```text
iteration_limit
unknown_tool
```

不触发最终总结的原因：

```text
user_cancelled
stream_error
natural
```

最终总结请求：

```text
ConversationContext 已包含已有 user、assistant tool_call、tool result
  → Provider.stream_chat(messages, tools=None)
  → StreamCollector 转发 TEXT_DELTA
  → 完成后 append_assistant(summary_text)
```

如果最终总结本身流式错误或被取消，不再递归总结，也不写入半截文本。

### 多工具分批示例

模型同一轮返回：

```text
read_file(A)
search_text(B)
write_file(C)
find_files(D)
run_command(E)
read_file(F)
```

分批结果：

```text
Batch 1: READ_ONLY 并发执行 read_file(A), search_text(B)
Batch 2: SIDE_EFFECT 串行执行 write_file(C)
Batch 3: READ_ONLY 并发执行 find_files(D)
Batch 4: SIDE_EFFECT 串行执行 run_command(E)
Batch 5: READ_ONLY 并发执行 read_file(F)
```

回灌顺序始终是：

```text
A → B → C → D → E → F
```

即使 B 比 A 先完成，也等同批次全部完成后按原始顺序写入 tool result。

### 取消传播

```text
用户 Ctrl+C
  → Runtime 当前 AgentLoop task 被 cancel
  → AgentLoop 捕获 CancelledError
  → 取消当前 Provider 流或工具执行 task
  → 不写入半截文本
  → 不启动新工具
  → 不请求最终总结
  → emit STOPPED(user_cancelled)
  → Runtime/TUI 显示已取消
```

### 流式错误

```text
Provider 抛出 RequestError / StreamInterruptedError
  → StreamCollector 向上抛出
  → AgentLoop emit STOPPED(stream_error)
  → Runtime/TUI 展示错误
  → 半截文本不写入 Conversation Context
  → 不请求最终总结
```

### Token 用量

```text
OpenAI-compatible SSE payload 出现真实 usage
  → Provider 产出 token_usage 事件
  → StreamCollector 转成 Agent TOKEN_USAGE 事件
  → Runtime/TUI 展示
```

如果没有 usage 字段，什么都不发，循环照常进行。

## 文件组织

```text
artcode/
├── agent/
│   ├── __init__.py          — 导出 ch04 Agent 层公共入口
│   ├── events.py            — AgentEvent、AgentEventType、StopReason、TokenUsage、ModelTurn
│   ├── modes.py             — AgentMode、ToolAccessPolicy、只读工具集合、三种运行模式
│   ├── memory.py            — PlanMemory，本次运行内最近计划
│   ├── stream.py            — StreamCollector，双路流式收集
│   ├── tools.py             — ToolSafety、工具分批、ToolBatchExecutor
│   └── loop.py              — AgentLoop、AgentRunRequest、AgentRunResult
├── commands/
│   ├── base.py              — CommandResult 增加 argument，CommandRegistry 支持带参数命令
│   └── builtin.py           — 注册 /plan、/do，更新 /help
├── providers/
│   ├── events.py            — 增加 token_usage Provider 事件
│   ├── openai_compatible.py — 解析真实 usage 字段并产出 token_usage
│   └── base.py              — 保持 stream_chat 接口，必要时补充事件说明
├── runtime/
│   └── app.py               — 接入 AgentLoop，消费 AgentEvent，移除 ch03 单步工具编排
├── tui/
│   ├── app.py               — 暴露 Agent 进度展示方法
│   └── render.py            — 渲染迭代、批次、Token 用量、停止原因
├── tools/
│   ├── base.py              — 保持 ch03 工具接口；Agent Loop 不再调用确认
│   └── registry.py          — 可增加按工具名导出 OpenAI tools 的便捷方法
├── conversation/
│   └── context.py           — 继续保存多轮 assistant tool_call 和 tool result
├── prompts.py               — 更新 ch04 系统提示
├── config.py                — CHAPTER_NAME 更新为 ch04：动手实现 Agent Loop
└── cli.py                   — 创建 PlanMemory / AgentLoop 依赖并注入 Runtime
```

测试文件：

```text
tests/unit/
├── test_agent_events.py     — Agent 事件、停止原因、TokenUsage
├── test_agent_modes.py      — 工具访问策略和只读过滤
├── test_agent_memory.py     — 最近计划内存保存/读取/清空
├── test_agent_stream.py     — 双路流式收集、Token 用量、流式错误
├── test_agent_tools.py      — 多工具分批、未知工具、只读并发、有副作用串行
├── test_agent_loop.py       — 自然完成、12 轮上限、未知工具、取消、失败后继续
├── test_commands.py         — /plan、/do、带参数 slash command
├── test_runtime.py          — Runtime 接入 AgentLoop 和 TUI 事件转发
├── test_render.py           — Agent 进度、批次、停止原因、Token 用量展示
├── test_provider_events.py  — token_usage Provider 事件校验
└── test_openai_provider.py  — usage SSE 解析
```

集成测试文件：

```text
tests/integration/
├── test_agent_loop_flow.py  — fake provider 的多轮 Agent Loop 端到端
├── test_tool_flow.py        — 保留 ch03 工具流兼容场景，按 ch04 行为更新多工具预期
├── test_deepseek_live.py    — 真实 DeepSeek 流式 smoke，扩展至少一个真实 Agent Loop 路径
└── README.md                — 更新真实测试默认执行说明
```

文档文件：

```text
spec汇总/ch04/
├── spec.md                  — 已批准规格
├── plan.md                  — 本技术设计
├── tasks.md                 — 后续任务拆解
└── checklist.md             — 后续验收清单

README.md                   — 更新 ch04 简介和 Agent Loop 行为
artcode.example.yaml         — 如无新增配置则不改；迭代上限本章固定为 12
```

注意：

- ch04 不新增 YAML 配置项；最大迭代轮数固定为 12。
- ch04 不删除 ch03 工具安全逻辑。
- `confirm_tool_execution` 可以保留在 TUI 里，但 Agent Loop 不调用。
- `实验场/helloworld` 这类本地编译产物不纳入任务文件清单。

## 技术决策

| 决策点 | 选择 | 理由 |
|---|---|---|
| Agent Loop 放在哪里 | 新增 `artcode.agent` 层 | 保持 Runtime 轻量，让循环、事件、工具调度、停止条件有独立边界，方便后续权限系统、上下文压缩、Hook、MCP 扩展。 |
| 最大迭代数 | 固定 12 轮，不做配置项 | 足够覆盖小型 coding 任务，又避免本章引入额外配置复杂度。后续可在需要时再开放配置。 |
| 普通输入行为 | 默认进入 Agent Loop | 符合“从被动应答变成自主干活 Agent”的本章目标。 |
| ch03 单工具限制 | ch04 明确取消 | Agent Loop 需要支持模型一次规划多个读取或操作；用安全分批替代“多个工具直接报错”。 |
| 多工具执行顺序 | 按原始顺序分批，相邻只读并发，有副作用串行 | 在不打乱模型意图的前提下利用并发；避免写后读、读后写顺序被破坏。 |
| 并发结果回灌 | 按模型原始工具调用顺序写回 | 保持上下文稳定，降低测试不确定性，也便于模型理解自己的观察结果。 |
| `run_command` 分类 | 始终有副作用 | 不做命令白名单，也不猜测 shell 命令是否只读，规则简单可解释。 |
| 有副作用工具确认 | Agent Loop 中不再确认 | 满足“自主循环干活”的目标；安全边界沿用 ch03 的允许目录、危险命令拦截和超时。 |
| 未知工具处理 | 同一轮出现未知工具则整批不执行并停止 | 未知工具说明模型和工具协议脱节，继续执行同轮其他工具风险较高。 |
| 已知工具失败处理 | 回灌失败结果后继续循环 | 失败是 ReAct 的观察结果，模型可以修正参数、换路径或自然结束。 |
| 半截文本处理 | 实时显示，但未完成不写入上下文 | 保持用户体验，同时避免污染 Conversation Context。 |
| 同轮文本加工具 | 文本显示但不单独写入 assistant 消息 | 避免过程话被后续模型误认为最终回复；工具调用消息才是本轮上下文事实。 |
| 异常最终总结 | 仅迭代上限和未知工具触发 | 这两类停止仍有稳定上下文可总结；用户取消和流式错误不再继续请求模型。 |
| Plan Mode 工具范围 | 只允许 `read_file`、`find_files`、`search_text` | 计划阶段严格只读，避免提前写文件、改文件或跑命令。 |
| 最近计划存储 | 只存在 `PlanMemory` 内存中 | 符合本章不做长期持久化和计划落盘的边界。 |
| `/do` 附加说明 | 与最近计划组合执行 | 用户可以在执行前追加限制，不需要重新生成计划。 |
| Token 用量 | 只展示真实 usage，不估算 | 避免把估算值误当真实账单数据，也不绑定具体 tokenizer。 |
| 真实测试 | 本地配置可用时默认跑 DeepSeek live 测试 | 遵守全局协作规则，真实 API 成本不作为跳过理由。 |
| Runtime 角色 | 事件消费者和命令入口 | Runtime 不再负责工具批处理和循环停止判断，减少后续维护压力。 |
| TUI 角色 | 只展示事件，不判断业务状态 | TUI 不根据文本猜状态，便于未来替换界面或增加日志消费者。 |
