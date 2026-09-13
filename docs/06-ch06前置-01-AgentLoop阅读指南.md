# `artcode/agent/loop.py` 阅读指南

## 一、这个文件是做什么的

`AgentLoop` 是 ArtCode 的总导演。

它不亲自读取文件，也不亲自发送终端文字。它负责安排整个流程：

```text
保存用户消息
→ 请求模型
→ 检查模型是否要调用工具
→ 安排工具执行
→ 保存工具结果
→ 再次请求模型
→ 直到模型给出最终答案或触发停止条件
```

这是目前最值得优先理解的文件。

## 二、先看代码地图

文件可以分成六块：

1. 导入依赖和默认常量。
2. `AgentRunRequest`：描述一次任务怎样运行。
3. `AgentRunResult`：描述运行结果，目前不是主流程重点。
4. `AgentLoop`：核心循环。
5. `_CollectedTurn`：临时保存一次模型响应。
6. 停止消息和工具阻断辅助函数。

第一遍重点只看：

- `AgentRunRequest`
- `AgentLoop.__init__`
- `AgentLoop.run`
- `_collect_model_turn`

## 三、`AgentRunRequest`：一次运行的说明书

```python
@dataclass(frozen=True)
class AgentRunRequest:
    user_content: str
    mode: AgentMode
    max_iterations: int = DEFAULT_MAX_ITERATIONS
    append_user_message: bool = True
    final_summary_on_abnormal_stop: bool = True
```

它可以理解成一张任务单：

- `user_content`：用户说了什么。
- `mode`：Normal、Plan 或 Do。
- `max_iterations`：最多循环多少轮，默认 12。
- `append_user_message`：是否把用户消息写进上下文。
- `final_summary_on_abnormal_stop`：异常停止时是否再让模型总结。

### 语法：`@dataclass`

普通类往往要手写很多初始化代码。`@dataclass` 会根据字段自动生成初始化方法。

可以把：

```python
request = AgentRunRequest("检查项目", PLAN_MODE)
```

理解成创建一张内容为“检查项目”、模式为 Plan 的任务单。

### 语法：`frozen=True`

表示对象创建后不能随意修改字段。这样任务运行到一半时，配置不容易被意外改变。

### 语法：`str`、`bool`、`int`

这些是类型标注，主要帮助人和编辑器理解代码。Python 运行时通常不会仅凭标注自动阻止错误类型。

## 四、`AgentLoop.__init__`：给总导演配齐工作人员

构造方法接收：

- `provider`：负责请求模型。
- `conversation`：保存对话历史。
- `tool_registry`：保存所有可用工具。
- `tool_context`：保存路径、超时和结果大小等工具环境。
- `plan_memory`：保存最近一次计划。
- `stream_collector`：收集流式模型响应。
- `tool_executor`：规划并执行工具。
- `request_assembler`：组装每轮发给模型的消息和工具列表。

### 语法：`x or 默认对象`

例如：

```python
self.plan_memory = plan_memory or PlanMemory()
```

意思是：调用方传了 `plan_memory` 就用它，否则创建一个新的。

这种写法适合默认对象，但要知道空字符串、空列表等也会被当成“没有值”。

### 补充：依赖注入

`AgentLoop` 没有把所有对象都写死在内部，而是允许外部传进来。这叫依赖注入。

好处是测试时可以传入假的 Provider、假的工具执行器，不必真的请求 API 或修改文件。

## 五、`run`：整个 Agent Loop 的核心

方法签名：

```python
async def run(self, request: AgentRunRequest) -> AsyncIterator[AgentEvent]:
```

可以先翻译成中文：

> 异步运行一次 Agent 任务，并且在运行过程中不断向外产生 AgentEvent。

### 第一步：保存用户消息

```python
if request.append_user_message:
    self.conversation.append_user(request.user_content)
```

只有开关为真时，才把用户输入加入对话历史。

### 第二步：通知外界任务开始

```python
yield run_started_event(...)
```

`yield` 不是最终返回并结束，而是先交出一个事件，然后函数以后还能继续执行。

这里的事件会被 Runtime 收到，再交给 TUI 展示。

### 第三步：最多循环 12 轮

```python
for iteration in range(1, request.max_iterations + 1):
```

如果最大值是 12，`range(1, 13)` 会产生 1 到 12。

每一轮都会：

1. 请求一次模型。
2. 收集文字和工具调用。
3. 判断是否结束。
4. 如果有工具调用，就执行并进入下一轮。

### 第四步：请求并收集模型响应

```python
turn = await self._collect_model_turn(request.mode)
```

`await` 表示当前任务要等待异步操作完成，但等待网络期间，事件循环可以处理其他异步工作。

### 第五步：把流式事件继续向外转交

```python
for event in turn.events:
    yield event
```

这是“中转”。`StreamCollector` 收到的文字增量、Token 用量等事件，被 `AgentLoop` 原样继续交给外部。

### 第六步：模型没有调用工具就自然结束

```python
if not model_turn.tool_calls:
```

空列表在 Python 中会被当作假，所以这句话是“如果没有工具调用”。

此时：

- 把完整回复加入对话历史。
- 如果是 Plan Mode，保存为最近计划。
- 发出自然停止事件。
- 使用 `return` 结束整个循环。

### 第七步：模型调用了工具

先把 assistant 的工具调用写进上下文，然后建立执行计划：

```python
plan = self.tool_executor.build_plan(
    model_turn.tool_calls,
    request.mode.tool_policy,
)
```

这里是 ch06 非常重要的连接点。当前只检查：

- 工具是否存在。
- 当前模式是否允许这个工具。

如果允许，就继续执行；目前还没有统一的用户审批步骤。

### 第八步：执行工具并保存结果

```python
async for event in self.tool_executor.execute_plan(plan):
```

每收到一个工具结果，就写入 Conversation Context。下一轮模型请求时，模型便能看到工具结果并决定下一步。

## 六、三种容易混淆的结束方式

### `yield`

交出一个中间事件，但函数以后还会继续。

### `return`

立即结束当前函数。这里常用于自然完成或出错停止。

### 循环自然结束

如果 12 轮都没有 `return`，`for` 循环结束，然后进入异常总结逻辑。

## 七、异常与取消

```python
except asyncio.CancelledError:
```

当用户按取消快捷键时，Runtime 会取消正在运行的异步任务。取消会以 `CancelledError` 的形式传播到这里。

代码捕获它以后：

- 发出“用户取消”事件。
- 不再继续调用工具。
- 不再继续下一轮。

### 语法：异常不是普通返回值

`raise` 抛出异常，`try/except` 捕获异常。它适合处理无法按正常路径继续的情况。

## 八、`_collect_model_turn` 做了什么

它先用 `PromptRequestAssembler` 组装：

- 对话历史
- 当前模式提醒
- 当前模式允许的工具
- 工具运行环境

然后调用 `_collect_model_turn_with_messages`，让 Provider 发出流式响应。

前导下划线 `_` 表示“这是类内部使用的方法”，只是约定，不是绝对禁止外部调用。

## 九、ch06 与这个文件的关系

权限系统不应全部堆进 `AgentLoop.run`。

比较合理的职责是：

- `AgentLoop` 仍负责总体流程。
- 权限组件负责判断“允许、询问还是拒绝”。
- TUI 负责收集用户选择。
- Tool Executor 只有得到允许后才真正执行。

`AgentLoop` 可能需要转发新的权限事件，但不应亲自解析每一种危险命令规则。

## 十、阅读练习

第一次阅读只找出以下位置：

1. 用户消息在哪里加入上下文？
2. 12 轮上限在哪里生效？
3. 没有工具调用时在哪里结束？
4. 工具结果在哪里加入上下文？
5. 用户取消在哪里被处理？

能找到这五处，就已经理解了这个文件的骨架。
