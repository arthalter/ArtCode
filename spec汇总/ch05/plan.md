# ch05：System Prompt 设计 Plan

## 架构概览

ch05 将 ArtCode 的提示词链路拆成五层：稳定 System Prompt 组装、运行时 system-reminder、请求消息组装、缓存用量解析、人工评估材料。

稳定 System Prompt 组装层负责 `7+x` 模块体系。七个固定模块由代码内置，按固定优先级输出；可选模块由调用方在会话启动时传入，本章只保留机制，不接真实项目文件、Skill 或记忆来源。组装结果必须逐字稳定，并继续作为 Conversation Context 的第一条 system 消息。

运行时 system-reminder 层负责动态约束。每轮模型请求前，Agent Loop 根据当前 Agent Mode、工具策略和运行环境生成一条临时 `role=user` 消息，内容用 `<system-reminder>` 标签包裹，并追加到本次请求 messages 末尾。该消息不写入 Conversation Context。

请求消息组装层负责把真实历史和临时 reminder 分开。Conversation Context 继续只保存真实 system/user/assistant/tool 历史；Agent Loop 在调用 Provider 前复制历史、追加 reminder、过滤工具列表，再传给当前 OpenAI-compatible Provider。Provider 的请求体仍保持当前可用格式，不发送显式 `cache_control`。

缓存用量解析层扩展现有 Token 用量事件。Provider 从真实 API usage 中解析基础 token、DeepSeek cache hit/miss 字段和 OpenAI cached tokens 字段，统一转成内部缓存用量，再由 Agent 事件和 TUI 展示。

评估材料层提供 `prompt_eval.md`。它包含 5 个人工场景，用来观察模型是否遵守专用工具优先、编辑前先读、Plan Mode 只读、错误后调整和最终输出风格。本章不做 LLM-as-judge 和自动评分。

## 核心数据结构

### PromptSection

表示一个可拼装的 System Prompt 模块。

```python
@dataclass(frozen=True)
class PromptSection:
    id: str
    title: str
    priority: int
    content: str
```

字段说明：

- `id`: 稳定标识，用于排序 tie-breaker 和测试定位。
- `title`: 输出到 System Prompt 的模块标题。
- `priority`: 越小越靠前。
- `content`: 模块正文；空白内容会被过滤。

七个固定模块使用固定 priority：

| priority | id | title |
|---:|---|---|
| 100 | `identity` | 身份 |
| 200 | `system_constraints` | 系统约束 |
| 300 | `task_modes` | 任务模式 |
| 400 | `action_execution` | 动作执行 |
| 500 | `tool_usage` | 工具使用 |
| 600 | `tone` | 语气风格 |
| 700 | `text_output` | 文本输出 |

可选模块默认排在 800 之后，例如：

| priority | id | title |
|---:|---|---|
| 800 | `custom_instructions` | 自定义指令 |
| 900 | `active_skills` | 已激活的 Skill |
| 1000 | `long_term_memory` | 长期记忆 |

本章不接这些可选模块的真实来源，只支持调用方传入 `PromptSection`。

### PromptBuilder

负责把固定模块和可选模块拼成稳定 System Prompt。

```python
class PromptBuilder:
    def build(
        self,
        fixed_sections: Sequence[PromptSection],
        optional_sections: Sequence[PromptSection] = (),
    ) -> str:
        ...
```

排序规则：

- 先过滤空白 `content`。
- 按 `(priority, id)` 稳定排序。
- 每个模块渲染为 `# 标题\n\n正文`。
- 模块之间用一个空行分隔。
- 输出结果使用固定首尾空白策略。

### ReminderContext

表示生成 system-reminder 需要的运行时动态信息。

```python
@dataclass(frozen=True)
class ReminderContext:
    mode_name: str
    mode_purpose: str
    allowed_tool_names: tuple[str, ...]
    blocked_tool_names: tuple[str, ...]
    cwd: Path
    allowed_dirs: tuple[Path, ...]
    platform: str
```

字段来源：

- `mode_name` / `mode_purpose`: 来自 `AgentMode`。
- `allowed_tool_names`: 当前模式过滤后的工具名。
- `blocked_tool_names`: 默认工具中当前模式不可用的工具名；Normal / Do Mode 可为空。
- `cwd`: 优先使用 `ToolExecutionContext.default_cwd`，缺省时使用 `Path.cwd()`。
- `allowed_dirs`: 来自 `ToolExecutionContext.path_policy.allowed_roots`。
- `platform`: 通过 Python 标准库获取，例如 `macOS arm64` 或 `Darwin arm64`。

### SystemReminderBuilder

负责把 `ReminderContext` 渲染成临时消息。

```python
class SystemReminderBuilder:
    def build_message(self, context: ReminderContext) -> dict[str, str]:
        ...
```

输出格式固定为：

```json
{
  "role": "user",
  "content": "<system-reminder>\n...\n</system-reminder>"
}
```

内容必须包含：

- 当前运行模式。
- 当前允许工具。
- 当前禁止工具或边界说明。
- 当前工作目录。
- 允许访问目录。
- 当前平台。
- 不要把本提醒当作用户请求回复的说明。

### PromptRequestAssembler

负责为每轮 Provider 调用准备 messages 和 tools。

```python
@dataclass(frozen=True)
class PromptRequest:
    messages: list[dict[str, Any]]
    tools: list[dict[str, Any]] | None

class PromptRequestAssembler:
    def assemble(
        self,
        conversation_messages: Sequence[dict[str, Any]],
        mode: AgentMode | None,
        all_tools: Sequence[dict[str, Any]] | None,
        tool_context: ToolExecutionContext,
    ) -> PromptRequest:
        ...
```

规则：

- 从 Conversation Context 导出的历史只读复制，不原地修改。
- 如果 `mode` 不为空，则追加一条临时 system-reminder。
- 如果 `all_tools` 不为空，则按当前模式过滤工具。
- 异常最终总结请求 `mode=None` 或 `tools=None` 时不携带工具；是否注入 reminder 由 Agent Loop 调用点明确决定。

### TokenUsage

扩展现有 Provider 和 Agent Token 用量结构。

```python
@dataclass(frozen=True)
class TokenUsage:
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    cached_tokens: int | None = None
    cache_miss_tokens: int | None = None
```

字段映射：

- DeepSeek `prompt_cache_hit_tokens` -> `cached_tokens`
- DeepSeek `prompt_cache_miss_tokens` -> `cache_miss_tokens`
- OpenAI `prompt_tokens_details.cached_tokens` -> `cached_tokens`
- OpenAI 若有 `prompt_tokens` 和 `cached_tokens`，则 `cache_miss_tokens = prompt_tokens - cached_tokens`

缺失缓存字段时保持 `None`，普通 Agent Loop 不失败。

## 模块设计

### `artcode.prompting.sections`

**职责：** 定义 `PromptSection` 和七个固定模块内容。

**对外接口：**

- `PromptSection`
- `default_fixed_sections() -> tuple[PromptSection, ...]`
- `default_system_prompt() -> str`

**依赖：** 无 Provider 依赖；只包含稳定文本。

**满足需求：** F1-F7、F14。

### `artcode.prompting.builder`

**职责：** 实现稳定拼装规则。

**对外接口：**

- `PromptBuilder`
- `build_system_prompt(optional_sections=()) -> str`

**依赖：** `PromptSection`。

**满足需求：** F1-F7、N1-N3。

### `artcode.prompting.reminder`

**职责：** 生成每轮临时 system-reminder。

**对外接口：**

- `ReminderContext`
- `SystemReminderBuilder`
- `collect_runtime_reminder_context(mode, all_tool_names, allowed_tool_names, tool_context) -> ReminderContext`

**依赖：** `AgentMode`、`ToolExecutionContext`、Python `platform` 标准库。

**满足需求：** F8-F16、N4-N5。

### `artcode.prompting.assembler`

**职责：** 组装每轮 Provider 调用所需的 messages/tools。

**对外接口：**

- `PromptRequest`
- `PromptRequestAssembler`

**依赖：** `ConversationContext` 导出的 message 列表、`AgentMode`、`ToolExecutionContext`、`SystemReminderBuilder`。

**满足需求：** F17-F19。

### `artcode.prompts`

**职责：** 保持旧导入路径兼容，暴露默认 `SYSTEM_PROMPT`。

**设计：** 当前 `artcode.prompts.SYSTEM_PROMPT` 改为由 `build_system_prompt()` 生成。`ConversationContext` 无需知道 prompt 内部模块体系。

**满足需求：** AC10。

### `artcode.agent.loop`

**职责：** 在每轮模型请求前使用 `PromptRequestAssembler`，不再直接把 `conversation.export_messages()` 原样传给 Provider。

**改动点：**

- 正常 Agent Loop 请求：导出真实历史，追加临时 reminder，携带当前模式工具。
- 异常最终总结请求：继续不携带工具；默认不追加模式 reminder，避免在异常总结中重新引导工具使用。
- 保证 reminder 不写入 Conversation Context。

**满足需求：** F8-F19、AC19-AC23、AC47。

### `artcode.providers.events`

**职责：** 扩展 Provider token usage 事件。

**改动点：**

- `token_usage_event` 增加 `cached_tokens`、`cache_miss_tokens`。
- 校验新增字段只能是整数或 `None`。

**满足需求：** F25-F29。

### `artcode.providers.openai_compatible`

**职责：** 解析真实 API SSE usage 字段。

**改动点：**

- 保留现有基础 usage 解析。
- 解析 DeepSeek `prompt_cache_hit_tokens` / `prompt_cache_miss_tokens`。
- 解析 OpenAI `prompt_tokens_details.cached_tokens`。
- 不向 payload 添加显式 `cache_control`。

**满足需求：** F18、F25-F28、AC31-AC35。

### `artcode.agent.events`

**职责：** 扩展 Agent 层 `TokenUsage` 和 `TOKEN_USAGE` 事件 payload。

**改动点：**

- `TokenUsage` 增加缓存字段。
- `TokenUsage.from_event_payload` 支持缓存字段。
- `token_usage_event` 透传缓存字段。

**满足需求：** F29、AC36。

### `artcode.agent.stream`

**职责：** 把 Provider token usage 转为 Agent token usage。

**改动点：**

- 无缓存字段时保持兼容。
- 有缓存字段时透传。

**满足需求：** F29。

### `artcode.tui.render` 和 `artcode.tui.app`

**职责：** 展示缓存命中和未命中 token。

**改动点：**

- `show_token_usage` 增加可选 `cached_tokens`、`cache_miss_tokens`。
- 渲染文本在字段存在时追加 `cached=... miss=...`。

**满足需求：** F29、AC36。

### `artcode.runtime.app`

**职责：** 消费扩展后的 token usage 事件。

**改动点：**

- 将 `cached_tokens` 和 `cache_miss_tokens` 传给 TUI。

**满足需求：** AC36。

### `artcode.tools.file_tools` 和 `artcode.tools.command_tool`

**职责：** 强化六个现有工具 description。

**改动点：**

- `read_file`: 强调读取文件内容和编辑前获取上下文。
- `write_file`: 强调创建或覆盖完整文件，覆盖需谨慎。
- `edit_file`: 强调精确替换、必须先读、`old_text` 必须来自实际文件内容。
- `run_command`: 强调已有专用工具可完成时优先专用工具，命令有副作用且应谨慎。
- `find_files`: 强调用于定位文件，优先于 shell `find`。
- `search_text`: 强调用于搜索文本，优先于 shell `grep`。

**不改动：** 工具名、参数 schema、执行逻辑、权限策略。

**满足需求：** F20-F24。

### `spec汇总/ch05/prompt_eval.md`

**职责：** 提供人工评估清单。

**内容：**

- 场景目标。
- 准备步骤。
- 可复制输入。
- 观察点。
- PASS / PARTIAL / FAIL 记录模板。

**满足需求：** F32-F33。

## 模块交互

### 启动时 System Prompt 生成

```text
default_fixed_sections()
    -> PromptBuilder.build()
        -> artcode.prompts.SYSTEM_PROMPT
            -> ConversationContext.__init__()
                -> [{"role": "system", "content": SYSTEM_PROMPT}]
```

本章可选模块不接真实来源；默认启动路径只生成固定七模块。

### 每轮正常 Agent 请求

```text
AgentLoop._collect_model_turn(mode)
    -> tool_registry.openai_tools()
    -> PromptRequestAssembler.assemble(
           conversation.export_messages(),
           mode,
           all_tools,
           tool_context
       )
       -> mode.tool_policy.filter_openai_tools(all_tools)
       -> SystemReminderBuilder.build_message(ReminderContext)
       -> messages + [system_reminder]
    -> StreamCollector.collect(provider, request.messages, request.tools)
    -> provider.stream_chat(messages, tools)
```

Conversation Context 没有收到 system-reminder，因此请求结束后历史仍然干净。

### Plan Mode 请求

```text
Runtime "/plan xxx"
    -> AgentRunRequest(mode=PLAN_MODE)
    -> PromptRequestAssembler
       -> tools = read_file/find_files/search_text
       -> reminder 明确 Plan Mode 只读
    -> Provider
```

如果模型请求写、改、命令，现有 `ToolBatchExecutor` 仍按模式策略阻止。

### 异常最终总结

```text
AgentLoop._summarize_if_needed()
    -> _collect_model_turn_without_tools()
    -> PromptRequestAssembler 或直接 provider 调用
       -> tools=None
       -> 默认不注入模式 reminder
```

最终总结不重新开放工具，也不让 Plan Mode reminder 干扰停止原因说明。

### Token Usage 流转

```text
OpenAICompatibleProvider._events_from_sse_data()
    -> providers.token_usage_event(prompt, completion, total, cached, miss)
    -> StreamCollector
    -> agent.TokenUsage
    -> AgentEvent(TOKEN_USAGE)
    -> Runtime
    -> TUI renderer
```

## 文件组织

```text
artcode/
├── prompting/
│   ├── __init__.py          — 导出 Prompt 组装公共入口
│   ├── sections.py          — PromptSection 和七个固定模块
│   ├── builder.py           — PromptBuilder / build_system_prompt
│   ├── reminder.py          — ReminderContext / SystemReminderBuilder
│   └── assembler.py         — PromptRequest / PromptRequestAssembler
├── prompts.py               — 兼容旧入口，暴露 SYSTEM_PROMPT
├── conversation/
│   └── context.py           — 继续以 SYSTEM_PROMPT 初始化 system 消息
├── agent/
│   ├── loop.py              — 每轮请求接入 PromptRequestAssembler
│   ├── events.py            — TokenUsage 增加缓存字段
│   └── stream.py            — 透传缓存 usage
├── providers/
│   ├── events.py            — Provider token_usage_event 增加缓存字段
│   └── openai_compatible.py — 解析 DeepSeek / OpenAI 缓存字段
├── runtime/
│   └── app.py               — 传递缓存 usage 给 TUI
├── tui/
│   ├── app.py               — TUI 协议增加缓存 usage 参数
│   └── render.py            — 渲染 cached/miss token
└── tools/
    ├── file_tools.py        — 强化文件类工具 description
    └── command_tool.py      — 强化 run_command description

tests/
├── unit/
│   ├── test_prompt_sections.py      — 固定七模块和默认 prompt
│   ├── test_prompt_builder.py       — 排序、空模块、稳定输出
│   ├── test_system_reminder.py      — reminder 内容和 message 形状
│   ├── test_prompt_assembler.py     — 临时注入、不污染历史、工具过滤
│   ├── test_context.py              — 默认 system prompt 更新
│   ├── test_provider_events.py      — 缓存 usage 事件校验
│   ├── test_openai_provider.py      — DeepSeek/OpenAI usage 解析
│   ├── test_agent_stream.py         — Agent usage 透传
│   ├── test_runtime.py              — Runtime 传递缓存 usage
│   ├── test_render.py               — TUI 展示缓存 usage
│   └── test_tool_registry.py        — 工具 description 和顺序稳定
├── integration/
│   ├── test_agent_loop_flow.py      — system-reminder 真实 Agent Loop 注入
│   └── test_prompt_cache_live.py    — 真实 API cache hit > 0
└── ...

spec汇总/ch05/
├── spec.md
├── plan.md
├── tasks.md
├── checklist.md
└── prompt_eval.md
```

## 技术决策

| 决策点 | 选择 | 理由 |
|---|---|---|
| Prompt 模块形态 | `PromptSection` + `PromptBuilder` | 结构小、稳定、容易测试，也方便未来接项目指令、Skill、记忆 |
| 固定模块顺序 | 身份、系统约束、任务模式、动作执行、工具使用、语气风格、文本输出 | 使用用户确认的 ch05 正式结构 |
| 可选模块策略 | 只预留机制，不接真实来源 | 避免提前实现项目指令、Skill、记忆章节 |
| 动态信息位置 | 每轮临时 system-reminder | 不污染稳定 System Prompt，保护缓存前缀 |
| system-reminder role | `role=user` + XML 风格标签 | 兼容当前 OpenAI-compatible / DeepSeek 请求格式 |
| reminder 频率 | 每轮完整注入 | 用户暂不在意 token，且约束最强、实现最简单 |
| reminder 保存 | 不写入 Conversation Context | 避免历史、记忆和未来压缩被临时约束污染 |
| 环境信息范围 | `cwd`、`allowed_dirs`、`platform` | 用户确认先做三项，暂不做日期和时区 |
| Provider 兼容 | 不发送显式 `cache_control` | 当前以 DeepSeek / OpenAI-compatible 可落地为主 |
| 缓存字段 | DeepSeek + OpenAI 映射到统一字段 | 不写死一家，同时保持实现范围可控 |
| live cache 验收 | 真实 API 必须 cache hit > 0 | 用户确认硬验收，证明缓存策略真实生效 |
| 工具描述强化 | 只改 description | 聚焦 Prompt 工程，不破坏工具协议 |
| 编辑前先读 | 强提示，不硬拦截 | 本章不做工具状态追踪或权限策略扩展 |
| 人工评估 | Markdown 清单 | 符合定性评估目标，不引入自动 judge |

## 风险与缓解

- 真实 API cache hit 可能受服务端策略影响。缓解：live cache test 构造长且完全稳定的前缀，连续请求，并在失败信息中输出 parsed usage 便于判断。
- system-reminder 使用 `role=user` 可能被模型误解。缓解：稳定 System Prompt 和 reminder 内容都明确说明它是系统级补充，不是用户请求。
- 可选模块未来若动态变化会影响缓存。缓解：本章文档和测试规定可选模块是会话启动时确定的稳定扩展规则。
- 工具描述变长会增加输入 token。缓解：本章硬目标是 Prompt 质量和缓存命中，description 只强化必要规则，不改参数 schema。
- 异常最终总结是否注入 reminder 可能影响行为。缓解：最终总结不携带工具，默认不注入模式 reminder，保持停止说明简洁。
