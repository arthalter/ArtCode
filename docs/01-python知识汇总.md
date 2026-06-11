# Python 知识汇总 — ArtCode 项目

> 本文档汇总 ArtCode 项目中涉及的所有 Python 语言特性、第三方库使用技巧和工程实践。

---

## 1. 现代 Python 项目构建

### 1.1 pyproject.toml + setuptools

```toml
[build-system]
requires = ["setuptools>=68", "wheel"]
build-backend = "setuptools.backends._legacy:_Backend"

[project.scripts]
artcode = "artcode.cli:main"
```

**要点：**
- 使用 `pyproject.toml` 作为项目元数据的单一来源（PEP 621）
- `project.scripts` 声明安装后的命令行入口
- 测试依赖放在 `[project.optional-dependencies]`，用 `pip install -e ".[dev]"` 安装

### 1.2 `__main__.py` 支持双重启动

```python
# artcode/__main__.py
from artcode.cli import main
if __name__ == "__main__":
    raise SystemExit(main())
```

`python -m artcode` 和安装后的 `artcode` 命令走同一入口函数。

### 1.3 `from __future__ import annotations`

每个文件开头都有此行，作用是：
- **延迟注解求值**：注解变成字符串而非立即求值
- 允许前向引用（类可以在自己的方法注解中引用自身）
- 减少运行时导入开销

---

## 2. 类型系统

### 2.1 dataclass（数据类）

项目中大量使用 `@dataclass`，核心用法：

```python
# 不可变数据类
@dataclass(frozen=True)
class ArtCodeConfig:
    protocol: str
    model: str
    base_url: str
    api_key: str
    thinking: ThinkingConfig

# 可变数据类（有默认工厂）
@dataclass
class ArtCodeRuntime:
    config: ArtCodeConfig
    provider: StreamingProvider
    commands: CommandRegistry = field(default_factory=create_default_registry)
```

**设计选择：**
- 配置对象用 `frozen=True` → 不可变，防止意外修改
- 运行时对象可变 → 可以在运行时动态更新状态
- `field(default_factory=...)` → 每个实例独立的可变默认值

### 2.2 Protocol（结构化子类型）

替代传统 ABC 的现代化方案：

```python
# StreamingProvider 协议 — 不强制继承，只要对象有 stream_chat 方法即可
class StreamingProvider(Protocol):
    def stream_chat(self, messages: Sequence[dict[str, str]]) -> AsyncIterator[dict[str, str]]:
        ...

# TuiApp 协议 — 定义 TUI 层需要实现的接口
class TuiApp(Protocol):
    def show_startup(self, status) -> None: ...
    async def read_input(self, model: str) -> str: ...
    def stream_delta(self, text: str) -> None: ...
    # ...
```

**优势：**
- 不需要显式继承或注册，只要"长得像"就行（鸭子类型 + 静态检查）
- 零运行时开销，不影响 MRO
- 适合定义"注入点"——调用方只关心方法存在，不关心继承关系

### 2.3 类型别名与泛型

```python
Message = dict[str, str]                                          # 消息类型别名

from collections.abc import AsyncIterator, Sequence               # 使用 collections.abc 泛型
from typing import Callable

CommandHandler = Callable[[str], "CommandResult"]                 # 回调函数类型
```

**要点：**
- 使用 `collections.abc` 而非 `typing` 中的泛型（Python 3.9+ 推荐）
- `AsyncIterator` 标注异步生成器返回值
- `Sequence` 比 `list` 更宽松，接受 tuple 等

---

## 3. 异步编程

### 3.1 asyncio 事件循环管理

```python
def main() -> int:
    try:
        return asyncio.run(run_app())       # 创建事件循环，运行协程，直到完成
    except KeyboardInterrupt:
        return 130                           # SIGINT 退出码
```

**`asyncio.run()` 做了什么：**
1. 创建新的事件循环
2. 运行传入的协程
3. 协程完成后关闭事件循环
4. 如果协程抛出未处理异常，向上传播

### 3.2 异步任务与取消

```python
async def _generate_assistant_reply(self) -> str | None:
    task = asyncio.create_task(self._consume_provider_stream(messages))
    self._install_generation_cancel_handler(task)
    try:
        return await task
    except asyncio.CancelledError:
        return None                              # 取消 = 不写入上下文
    except RequestError as exc:
        self.tui.show_error(exc)
        return ""                                # 错误 = 写入空消息
    finally:
        self._remove_generation_cancel_handler()
```

**关键模式：**
- `asyncio.create_task()` 将协程包装成可取消的 Task
- 通过 `signal.SIGINT` 触发 `task.cancel()`
- `CancelledError` 在 `await task` 处抛出
- 取消后返回 `None` 表示"本轮无效，不写入上下文"

### 3.3 信号处理与 asyncio 集成

```python
def _install_generation_cancel_handler(self, task: asyncio.Task[str]) -> None:
    loop = asyncio.get_running_loop()
    loop.add_signal_handler(signal.SIGINT, task.cancel)

def _remove_generation_cancel_handler(self) -> None:
    loop = asyncio.get_running_loop()
    loop.remove_signal_handler(signal.SIGINT)
```

**要点：**
- `loop.add_signal_handler()` 比 `signal.signal()` 更适合 asyncio —— 信号处理器在事件循环中安全执行
- 必须在生成结束后移除处理器，避免影响后续输入
- 如果平台不支持（如某些 Windows 版本），捕捉 `NotImplementedError` 优雅降级

### 3.4 async for 异步迭代

```python
async for event in self.provider.stream_chat(messages):
    event_type = event.get("type")
    if event_type == CONTENT_DELTA:
        self.tui.stream_delta(text)
    elif event_type == DONE:
        return "".join(parts)
```

`async for` 等价于不断 `await anext(iterator)`，适合消费流式数据。

### 3.5 httpx 异步 HTTP 客户端

```python
async with httpx.AsyncClient(timeout=..., transport=...) as client:
    async with client.stream("POST", url, headers=..., json=...) as response:
        async for line in response.aiter_lines():
            # 处理 SSE 行
```

**关键 API：**
- `client.stream()` → 流式请求（不在内存中缓存完整响应体）
- `response.aiter_lines()` → 异步按行迭代响应体
- `response.aread()` → 异步读取完整响应体（仅用于错误响应）

---

## 4. 错误处理

### 4.1 自定义异常体系

```python
@dataclass
class ArtCodeError(Exception):
    message: str
    hint: str | None = None

    @property
    def user_message(self) -> str:
        if self.hint:
            return f"{self.message}\n提示：{self.hint}"
        return self.message

class ConfigError(ArtCodeError):          # 启动阶段，退出程序
    pass

class RequestError(ArtCodeError):         # 运行阶段，显示错误后继续
    pass

class AuthenticationError(RequestError):  # HTTP 401/403
    pass
class NetworkError(RequestError):         # 连接失败
    pass
class ModelError(RequestError):           # HTTP 400/404/422
    pass
class TimeoutError(RequestError):         # 超时
    pass
class ThinkingModeUnsupportedError(RequestError):  # Thinking 模式不支持
    pass
class StreamInterruptedError(RequestError):        # 流式中断
    pass
```

**设计原则：**
- 两层继承树：`ConfigError`（致命，退出） vs `RequestError`（可恢复，继续运行）
- 每个异常携带 `message`（给用户看）和 `hint`（给用户的排查建议）
- `@property` 计算属性自动拼接用户消息

### 4.2 异常链接

```python
try:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
except yaml.YAMLError as exc:
    raise ConfigError("不是合法 YAML。", f"解析器提示：{exc}") from exc
```

`from exc` 保留原始异常链，便于调试时追溯根因。

### 4.3 密钥脱敏

```python
def mask_secret(secret: str) -> str:
    if not value:
        return "<empty>"
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}...{value[-4:]}"    # sk-e4...8567d

def scrub_secrets(text: str, secrets: Iterable[str] = ()) -> str:
    scrubbed = str(text)
    for secret in secrets:
        if secret:
            scrubbed = scrubbed.replace(secret, mask_secret(secret))
    return scrubbed
```

---

## 5. 第三方库使用

### 5.1 PyYAML

```python
raw = yaml.safe_load(path.read_text(encoding="utf-8"))
```

| 方法 | 安全性 | 说明 |
|------|--------|------|
| `yaml.load()` | ❌ 不安全 | 可执行任意 Python 对象 |
| `yaml.safe_load()` | ✅ 安全 | 只解析基本 YAML 类型 |
| `yaml.full_load()` | ⚠️ 避免 | 可能执行危险构造 |

**始终使用 `safe_load`**。

### 5.2 httpx

```python
httpx.Timeout(timeout=None, connect=10.0, read=60.0, write=10.0, pool=10.0)
```

| 参数 | 含义 |
|------|------|
| `timeout` | 总超时（`None` = 无限，因为流式响应时间不可预测） |
| `connect` | TCP 连接建立超时 |
| `read` | 两次数据到达之间的最大间隔 |
| `write` | 发送请求体的超时 |
| `pool` | 从连接池获取连接的超时 |

**错误类型映射：**
- `httpx.TimeoutException` → `TimeoutError`
- `httpx.ConnectError` / `httpx.NetworkError` → `NetworkError`
- `httpx.RemoteProtocolError` / `httpx.ReadError` / `httpx.DecodingError` → `StreamInterruptedError`

### 5.3 prompt_toolkit

```python
session = PromptSession(
    multiline=True,
    key_bindings=create_input_keybindings(),
    prompt_continuation="... ",
)

text = await session.prompt_async(prompt_text)
```

**核心概念：**
- `PromptSession` 封装输入会话（可复用，保持历史）
- `multiline=True` 启用多行输入
- `prompt_async` 异步等待用户输入
- `KeyboardInterrupt` / `EOFError` → 用户请求退出
- Key bindings 通过装饰器注册

### 5.4 rich

```python
console = Console()
console.print(text, end="", markup=False, highlight=False, soft_wrap=True)
console.print(Panel(body, title="ArtCode", border_style="cyan"))
```

**流式输出的关键参数：**
- `end=""` → 不换行（累积流式输出）
- `markup=False` → 不解析 rich 标记语法（避免把 AI 回复中的 `[text]` 误解析）
- `highlight=False` → 不高亮代码
- `soft_wrap=True` → 终端宽度自适应换行

---

## 6. Python 工程实践

### 6.1 deepcopy 防止内部状态泄露

```python
def export_messages(self) -> list[Message]:
    return deepcopy(self._messages)
```

不返回内部列表引用，调用方修改副本不影响原对象。

### 6.2 不可变配置

```python
@dataclass(frozen=True)
class ArtCodeConfig: ...

@dataclass(frozen=True)
class ThinkingConfig: ...
```

配置加载后不可修改，防止中途被意外改变。

### 6.3 依赖注入（不依赖框架）

```python
# cli.py 手动组装所有依赖
runtime = ArtCodeRuntime(
    config=config,
    provider=OpenAICompatibleProvider(config),
    conversation=ConversationContext(),
    tui=PromptToolkitTui(renderer=renderer),
)
```

不使用依赖注入框架，直接在入口函数中手动组装，依赖关系一目了然。

### 6.4 测试中的依赖替换

```python
# 测试中用 FakeProvider 替换真实的 OpenAICompatibleProvider
class FakeTui:
    # 模拟 TUI 行为，不需要真实终端
    ...
```

通过 Protocol 定义接口，测试时注入假对象，无需 mock 框架。
