# LangChain 框架知识对标 — ArtCode 项目

> **重要前提：ArtCode 项目没有使用 LangChain。** 本文档从"如果使用 LangChain 会怎么做"的视角，将项目中自实现的模块与 LangChain 对应概念进行对标，帮助理解两者的设计异同。

---

## 1. 为什么不用 LangChain？

| 考量维度 | ArtCode 选择 | 理由 |
|----------|-------------|------|
| 学习目标 | 从零理解 Agent 架构 | 使用框架会屏蔽实现细节 |
| 依赖控制 | 极简依赖（4 个核心库） | LangChain 依赖树非常庞大 |
| 定制性 | 完全可控的流式/错误/Provider | 框架抽象层多，调试困难 |
| 版本稳定性 | 不受框架 Breaking Change 影响 | LangChain 版本迭代快，API 频繁变动 |
| 代码量 | ch02 仅 ~650 行源码 | 用 LangChain 可能更少但理解成本高 |

---

## 2. 核心概念对标表

| ArtCode 自实现 | LangChain 对应概念 | 说明 |
|---------------|-------------------|------|
| `ConversationContext` | `BaseChatMessageHistory` | 对话历史管理 |
| `StreamingProvider` (Protocol) | `BaseChatModel` | 模型调用抽象 |
| `OpenAICompatibleProvider` | `ChatOpenAI` | OpenAI-compatible 模型实现 |
| `SSEDecoder` | LangChain 内部 SSE 解析 | 流式响应解析 |
| `SYSTEM_PROMPT` | `SystemMessage` | 系统提示 |
| `content_delta_event()` | `AIMessageChunk` | 流式内容增量 |
| `CommandRegistry` | `@tool` 装饰器 | 命令/工具注册 |
| `ArtCodeRuntime` | `RunnableSequence` / `AgentExecutor` | 运行时编排 |
| `ArtCodeConfig` | `ChatOpenAI(model=..., base_url=..., api_key=...)` | 模型配置 |

---

## 3. 逐层对标分析

### 3.1 Provider 层 — vs LangChain ChatModel

**ArtCode 做法：**

```python
# 自实现：用 Protocol 定义接口，httpx 自己发请求
class StreamingProvider(Protocol):
    def stream_chat(self, messages: Sequence[dict[str, str]]) -> AsyncIterator[dict[str, str]]:
        ...

class OpenAICompatibleProvider:
    async def stream_chat(self, messages):
        async with httpx.AsyncClient(...) as client:
            async with client.stream("POST", url, json=payload) as response:
                # 手动解析 SSE，手动错误映射
```

**LangChain 等价做法：**

```python
from langchain_openai import ChatOpenAI

llm = ChatOpenAI(
    model="deepseek-chat",
    base_url="https://api.deepseek.com",
    api_key="sk-xxx",
    streaming=True,
)

async for chunk in llm.astream(messages):
    print(chunk.content, end="")
```

**核心差异：**
- LangChain 封装了 HTTP 细节、重试、错误处理
- ArtCode 对每个错误场景有精确控制（"连接超时 10s"、"Thinking Mode 不支持" 直接给中文提示）
- LangChain 的 `astream()` 返回 `AIMessageChunk`，ArtCode 返回简单的 `dict[str, str]`

### 3.2 Conversation 层 — vs LangChain MessageHistory

**ArtCode 做法：**

```python
class ConversationContext:
    def __init__(self, system_prompt: str = SYSTEM_PROMPT) -> None:
        self._messages: list[Message] = [{"role": "system", "content": system_prompt}]

    def append_user(self, content: str) -> None:
        self._append("user", content)

    def export_messages(self) -> list[Message]:
        return deepcopy(self._messages)
```

**LangChain 等价做法：**

```python
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from langchain_community.chat_message_histories import ChatMessageHistory

history = ChatMessageHistory()
history.add_message(SystemMessage(content=SYSTEM_PROMPT))
history.add_message(HumanMessage(content="你好"))
history.add_message(AIMessage(content="你好！有什么我可以帮你的？"))
```

**核心差异：**
- LangChain 用强类型 Message 子类（`HumanMessage`, `AIMessage`, `SystemMessage`, `ToolMessage`）
- ArtCode 用裸 `dict`（`{"role": "user", "content": "..."}`）—— 简单直接，不引入类型系统
- LangChain MessageHistory 支持多种后端（内存、Redis、SQLite），ArtCode 当前只支持内存
- ArtCode 用 `deepcopy` 防止状态泄露，LangChain 的 `.messages` 属性直接返回内部列表引用

### 3.3 Commands 层 — vs LangChain Tool

**ArtCode 做法：**

```python
class CommandRegistry:
    def register(self, name: str, handler: CommandHandler) -> None:
        self._handlers[name] = handler

    def handle(self, user_input: str) -> CommandResult | None:
        handler = self._handlers.get(user_input.strip())
        return handler(user_input) if handler else None

# 注册命令
registry.register("/exit", _exit)
registry.register("/help", _help)
```

**LangChain 等价做法：**

```python
from langchain_core.tools import tool

@tool
def exit_program() -> str:
    """退出 ArtCode 程序"""
    raise SystemExit(0)

@tool
def show_help() -> str:
    """显示帮助信息"""
    return "/exit  /quit  /help"

llm_with_tools = llm.bind_tools([exit_program, show_help])
```

**核心差异：**
- ArtCode 的命令是**终端本地命令**（`/exit`、`/help`），由 Runtime 直接拦截，不发给模型
- LangChain 的 tool 是**模型可调用的工具**，由模型决定何时调用，结果反馈给模型
- ArtCode 采用精确匹配（整条输入等于 `/exit` 才触发），避免误触发
- ArtCode 的命令系统为后续集成 tool use 预留了扩展点（`CommandResult` 可以扩展为 tool call）

### 3.4 SSE 解析 — vs LangChain 内部处理

**ArtCode 做法：**

```python
class SSEDecoder:
    def __init__(self) -> None:
        self._data_lines: list[str] = []

    def feed(self, raw_line: str | bytes) -> list[SSEEvent]:
        line = _normalize_line(raw_line)
        if line == "":
            return self._flush()           # 空行 = 事件结束
        if line.startswith(":"):
            return []                       # 注释行跳过
        if line.startswith("data:"):
            self._data_lines.append(_field_value(line))
        return []

    def _flush(self) -> list[SSEEvent]:
        data = "\n".join(self._data_lines)
        self._data_lines.clear()
        return [SSEEvent(data=data, done=data.strip() == "[DONE]")]
```

**LangChain 内部处理：**

LangChain 使用 `httpx-sse` 或内部 SSE 解析器，对开发者完全透明。

**核心差异：**
- ArtCode 的 SSE 解析器极简（~50 行），只处理 `data:` 行和 `[DONE]`
- 不支持 `event:`、`id:`、`retry:` 字段（不需要）
- 学习价值高——理解 SSE 协议的精髓
- LangChain 中开发者完全不需要了解 SSE

---

## 4. 如果后续要引入 LangChain

当项目进入 tool use、文件编辑、复杂 Agent 循环阶段，可能需要 LangChain 或类似框架。以下是可能的迁移路径：

### 4.1 渐进式引入（推荐）

保留现有分层架构，逐步替换底层实现：

| 阶段 | 替换部分 | 使用 LangChain |
|------|---------|---------------|
| ch02-03 | 无 | 保持自实现 |
| ch04 Tool Use | `CommandRegistry` | 引入 `@tool` + `ToolNode` (LangGraph) |
| ch05 文件编辑 | 工具层 | `FileSystemTool` (可选) |
| ch06 Agent 循环 | `ArtCodeRuntime` | `create_react_agent` (LangGraph) |

### 4.2 LangChain/LangGraph 核心概念速查

| 概念 | 用途 | ArtCode 对标 |
|------|------|-------------|
| `BaseChatModel` | 模型抽象基类 | `StreamingProvider` Protocol |
| `ChatOpenAI` | OpenAI-compatible 实现 | `OpenAICompatibleProvider` |
| `BaseMessage` 子类 | 强类型消息 | `dict[str, str]` |
| `@tool` 装饰器 | 工具定义 | `CommandRegistry.register()` |
| `ToolNode` | 工具执行节点 | 尚未实现 |
| `StateGraph` | Agent 状态图 | 尚未实现 |
| `Checkpointer` | 状态持久化 | 尚未实现 |
| `RunnableConfig` | 运行时配置 | `ArtCodeConfig` dataclass |

---

## 5. 关键设计原则对照

| 原则 | ArtCode 实现 | LangChain 实现 |
|------|-------------|---------------|
| 接口定义 | `Protocol` 类 | `ABC` 抽象基类 |
| 流式输出 | `AsyncIterator[dict]` | `AsyncIterator[BaseMessageChunk]` |
| 错误处理 | 自定义异常层次 | 框架异常 + 重试机制 |
| 配置管理 | 手写 YAML + dataclass | Pydantic `BaseModel` |
| 依赖注入 | 手动组装 | `Runnable` 链式组合 |
| 消息格式 | 裸 dict | 强类型 Message 子类 |

---

## 6. 总结

| ArtCode 的优势 | LangChain 的优势 |
|---------------|-----------------|
| 零框架依赖，启动快 | 生态丰富，即插即用 |
| 完全可控的流式/错误行为 | 内置重试/回退/缓存 |
| 适合学习 Agent 底层机制 | 适合快速搭建原型 |
| 代码量少，易于理解 | 功能全面，覆盖边缘场景 |
| 底层透明，调试容易 | 社区支持，文档多 |

**ArtCode 的策略是正确的：** 在学习阶段，从零实现比依赖框架更有价值。理解底层原理后，未来可以更自信地选择是否引入框架、引入框架的哪些部分。
