# Agent 知识汇总 — ArtCode 项目

> 本文档从 ArtCode 项目出发，系统梳理 Coding Agent 的核心概念、设计模式和实现要点。

---

## 1. 什么是 Coding Agent

**Coding Agent** 是一类特殊的 AI Agent，它具备以下核心能力：

```
┌─────────────────────────────────────────────────────┐
│                   Coding Agent                       │
│                                                      │
│  ┌──────────┐   ┌──────────┐   ┌──────────┐        │
│  │   对话    │   │  工具调用  │   │  文件操作  │        │
│  │  (ch02)  │   │ (后续)    │   │ (后续)    │        │
│  └──────────┘   └──────────┘   └──────────┘        │
│                                                      │
│  ┌──────────┐   ┌──────────┐   ┌──────────┐        │
│  │  项目理解  │   │  权限控制  │   │   记忆    │        │
│  │ (后续)    │   │ (后续)    │   │ (后续)    │        │
│  └──────────┘   └──────────┘   └──────────┘        │
└─────────────────────────────────────────────────────┘
```

ArtCode ch02 只实现了最基础的**对话能力**，后续章节将逐步叠加其他能力。

---

## 2. 对话 Agent 核心架构

### 2.1 对话循环（Conversation Loop）

```
用户输入 → 命令判断 → (非命令) 追加user消息 → 调用Provider → 流式渲染 → 追加assistant消息 → 等待下一次输入
                ↓
            (是命令) 执行命令 → 返回结果
```

**核心代码（ArtCodeRuntime）：**

```python
while True:
    user_input = await self.tui.read_input(self.config.model)

    # 1. 命令拦截
    command_result = self.commands.handle(user_input)
    if command_result is not None:
        if command_result.should_exit:
            return 0
        continue

    # 2. 追加用户消息
    self.conversation.append_user(user_input)

    # 3. 生成并流式渲染回复
    result = await self._generate_assistant_reply()

    # 4. 完整回复写入上下文（取消的不写入）
    if result:
        self.conversation.append_assistant(result)
```

### 2.2 取消机制

**核心设计：Ctrl+C 取消当前生成，但不退出程序**

```
├─ 输入等待状态 → Ctrl+C → 退出程序（UserRequestedExit）
└─ 生成进行中 → Ctrl+C → 取消当前生成 → 半截回复不入上下文 → 回到输入状态
```

**实现方式：**

```python
# 生成开始时，将 SIGINT 绑定到 task.cancel()
loop.add_signal_handler(signal.SIGINT, task.cancel)

# 生成结束时，恢复默认 SIGINT 行为
loop.remove_signal_handler(signal.SIGINT)
```

**关键约束：** 取消的回复**不能写入 ConversationContext**，否则会导致后续对话基于不完整的模型输出。

---

## 3. 对话上下文（Conversation Context）

### 3.1 OpenAI-compatible 消息格式

```python
messages = [
    {"role": "system", "content": "你是 ArtCode ch02 的本地 CLI 对话助手。"},
    {"role": "user", "content": "你好"},
    {"role": "assistant", "content": "你好！有什么我可以帮你的？"},
    {"role": "user", "content": "解释一下什么是闭包"},
]
```

**四种角色：**
| role | 含义 | ch02 用法 |
|------|------|----------|
| `system` | 系统级指令 | 启动时设置一次，定义助手行为边界 |
| `user` | 用户输入 | 每轮对话追加 |
| `assistant` | AI 回复 | 完整回复后追加 |
| `tool` | 工具调用结果 | ch02 不使用 |

### 3.2 Context Window（上下文窗口）

**当前状态：** ch02 不做自动上下文裁剪。

**问题：** 对话过长 → 超过模型 token 限制 → API 返回错误 → 作为普通错误提示用户。

**后续优化方向：**
- 滑动窗口裁剪（保留最近 N 轮）
- Token 计数裁剪（按 token 而非轮数）
- 摘要压缩（旧对话压缩为摘要）
- 智能裁剪（保留关键信息，丢弃冗余）

### 3.3 状态安全

```python
def export_messages(self) -> list[Message]:
    return deepcopy(self._messages)    # 返回副本，防止外部修改
```

**原则：** 永远不暴露内部可变状态的引用。

---

## 4. Slash Command 系统

### 4.1 命令 vs 工具

| 类型 | 处理方 | 触发方式 | 适用场景 |
|------|--------|---------|---------|
| Slash Command | Runtime 直接拦截 | 精确匹配 `/command` | 程序控制（退出、帮助、切换模型） |
| Tool Call | 模型决定调用 | 模型输出 tool_call | AI 主动读取文件、执行命令 |

### 4.2 命令设计原则

```python
class CommandRegistry:
    def handle(self, user_input: str) -> CommandResult | None:
        command = user_input.strip()
        if "\n" in command:
            return None                 # 多行输入不可能是命令
        handler = self._handlers.get(command)
        return handler(command) if handler else None
```

**安全设计：**
1. 只有整条输入是单独命令才触发（`/exit` 有效）
2. 多行输入不触发命令（`/exit\n解释一下` 是正常对话）
3. 普通文本包含 `/` 不误触发（`"路径是 /usr/bin"` 不是命令）

### 4.3 内置命令

| 命令 | 动作 | 设计考量 |
|------|------|---------|
| `/exit` | 退出程序 | 与 `/quit` 等效 |
| `/quit` | 退出程序 | 用户习惯兼容 |
| `/help` | 极简帮助 | 只列出命令名，不展示复杂说明 |

---

## 5. Provider 抽象

### 5.1 为什么需要 Provider 层？

```
TUI / Runtime                  ← 不依赖具体模型实现
      ↓
StreamingProvider (Protocol)   ← 接口层
      ↓
OpenAICompatibleProvider       ← 具体实现（DeepSeek）
      ↓
httpx + SSE                    ← 传输层
```

**好处：**
- Runtime 层不感知 DeepSeek 的具体细节
- 后续可添加 Anthropic Provider、本地模型 Provider
- 测试时注入 FakeProvider

### 5.2 流式事件模型

```python
# 两类事件，极简设计
CONTENT_DELTA = "content_delta"   # {"type": "content_delta", "text": "增量文本"}
DONE = "done"                     # {"type": "done"}
```

**事件约束：**
- `content_delta` 必须携带 `text` 字段（字符串）
- `done` 不携带额外字段
- 错误通过异常抛出，不作为事件返回
- 非法事件类型在开发阶段通过 `validate_event()` 捕获

### 5.3 Thinking Mode 处理

```python
def build_request_payload(config, messages):
    payload = {"model": config.model, "messages": messages, "stream": True}
    if config.thinking.enabled:
        payload["thinking"] = {"type": "enabled"}      # DeepSeek 扩展字段
        payload["reasoning_effort"] = "high"
    # 关闭时不携带 thinking 字段 ← 避免不支持 thinking 的模型报错
    return payload
```

**关键设计：**
- thinking 关闭时不携带扩展字段 → 兼容不支持 thinking 的模型
- reasoning/reasoning_content 内容在 Provider 层丢弃 → 不泄露到上层
- 模型返回 thinking 不支持错误 → 转换为 `ThinkingModeUnsupportedError` 并给出中文排查建议

---

## 6. 错误处理哲学

### 6.1 两类错误的处理策略

| 类型 | 根类 | 处理方式 | 示例 |
|------|------|---------|------|
| 配置错误 | `ConfigError` | 启动阶段：显示错误 + 退出 | YAML 格式错误、缺少 api_key |
| 请求错误 | `RequestError` | 运行阶段：显示错误 + 回到输入 | 认证失败、网络中断、流式中断 |

### 6.2 面向新手的错误提示

```python
# ✓ 好的错误提示
"找不到配置文件 artcode.yaml。请复制 artcode.example.yaml 为 artcode.yaml，并填写 DeepSeek API key。"

# ✗ 糟糕的错误提示
"FileNotFoundError: [Errno 2] No such file or directory: 'artcode.yaml'"
```

**原则：**
- 错误消息使用中文
- 提供排查建议（hint）
- 不泄露 API key
- 不展示 Python 异常堆栈

---

## 7. Agent 演进路线

ArtCode 的渐进式学习路线（从 ch02 到完整的 Coding Agent）：

| 章节 | 新增能力 | 核心概念 |
|------|---------|---------|
| ch02 | 纯对话 | 对话循环、流式输出、上下文管理 |
| ch03 | Tool Use（计划） | 工具定义、tool_call 解析、工具执行 |
| ch04 | 文件操作（计划） | 文件读写、项目知识库 |
| ch05 | 代码编辑（计划） | diff 生成、精确替换 |
| ch06 | 权限与安全（计划） | 确认流程、沙箱 |
| ch07+ | 记忆与持久化（计划） | 会话保存、长期记忆 |

**核心洞察：** 对话是 Agent 的基石。没有稳定的对话循环、流式输出和上下文管理，后续的 tool use、文件编辑都是空中楼阁。

---

## 8. Agent 设计的关键约束

| 约束 | 原因 |
|------|------|
| 取消回复不写入上下文 | 半截回复会让后续对话混乱 |
| 系统提示不参与多轮累积 | 每次请求固定携带，不计入"上下文长度" |
| 流式内容原样输出 | ch02 不做 Markdown 渲染，避免"渲染失真"导致 Agent 误判 |
| thinking 内容不展示 | reasoning 是模型内部过程，用户不需要看到 |
| API key 不完整展示 | 安全底线 |
