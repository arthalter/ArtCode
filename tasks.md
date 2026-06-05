# ch02：让AI说话

## 任务 1：建立项目依赖与命令入口

影响文件：`pyproject.toml`、`artcode/__init__.py`、`artcode/__main__.py`、`artcode/cli.py`

依赖任务：无

参考资料定位：Python `pyproject.toml`、`project.scripts`、pytest 配置

任务内容：

- 使用 `pyproject.toml` 管理项目依赖。
- 声明运行依赖：`PyYAML`、`httpx`、`prompt_toolkit`、`rich`。
- 声明测试依赖：`pytest`、`pytest-asyncio`。
- 声明安装后的命令入口 `artcode`。
- 保留开发调试入口 `python -m artcode`。

验收方式：

- 执行 `python -m artcode` 能进入 ArtCode 启动流程。
- 安装项目后执行 `artcode` 能进入 ArtCode 启动流程。

## 任务 2：建立分层目录骨架

影响文件：`artcode/runtime/`、`artcode/conversation/`、`artcode/commands/`、`artcode/providers/`、`artcode/tui/`

依赖任务：任务 1

参考资料定位：本章目录分层约定

任务内容：

- 建立入口层、配置层、Runtime 层、Conversation 层、Commands 层、Providers 层、TUI 层。
- 每层只放 ch02 需要的最小实现。
- 不提前实现 tool use、MCP、Hook、权限、会话持久化等后续能力。

验收方式：

- 源码目录能清楚看出各层职责。
- TUI 层不直接包含模型 API 请求细节。
- Provider 层不直接打印终端内容。

## 任务 3：实现配置文件加载与校验

影响文件：`artcode/config.py`、`artcode.example.yaml`、`.gitignore`、`tests/unit/test_config.py`

依赖任务：任务 2

参考资料定位：`PyYAML`、Python `dataclasses`、DeepSeek API 配置说明

任务内容：

- 从项目根目录读取 `artcode.yaml`。
- 使用 `PyYAML` 解析 YAML。
- 不使用 Pydantic 等专门校验库。
- 手写校验配置结构和字段类型。
- 校验通过后转换为标准库 dataclass。
- 支持 `thinking.enabled` 和 `thinking.effort`。
- 提供脱敏后的配置状态给 TUI 使用。
- 提供 `artcode.example.yaml`。
- 将真实 `artcode.yaml` 加入 `.gitignore`。

验收方式：

- 缺少配置文件时能给出启动错误。
- 配置字段缺失或类型错误时能给出启动错误。
- TUI 状态展示不会显示完整 API key。

## 任务 4：定义统一错误类型

影响文件：`artcode/errors.py`、`tests/unit/test_config.py`、后续 Provider/TUI 测试

依赖任务：任务 3

参考资料定位：`httpx` 异常、常见 HTTP 状态码、DeepSeek API 错误响应

任务内容：

- 定义 ArtCode 内部统一错误类型。
- 覆盖配置错误、认证错误、网络错误、模型错误、超时错误、Thinking Mode 不支持、流式中断。
- 配置类错误用于启动失败。
- 请求类错误用于 TUI 中显示后继续运行。
- 所有错误展示都必须避免泄露完整 API key。

验收方式：

- 单元测试能断言不同错误被归类为 ArtCode 可理解的错误。
- TUI 能捕获请求类错误并回到输入状态。

## 任务 5：实现 Conversation Context

影响文件：`artcode/conversation/context.py`、`artcode/conversation/__init__.py`、`artcode/prompts.py`、`tests/unit/test_context.py`

依赖任务：任务 4

参考资料定位：OpenAI-compatible `messages` 格式、system prompt 设计

任务内容：

- 使用 OpenAI-compatible dict 消息保存本次运行内对话。
- 启动时加入内置 system prompt。
- 支持追加 user 消息。
- 支持追加完整 assistant 消息。
- 支持导出当前 messages 给 Provider。
- 不保存取消生成时的半截 assistant 回复。
- 不做会话持久化。
- 不做自动上下文裁剪。

验收方式：

- 初始化后包含 system 消息。
- 用户输入后追加 user 消息。
- 完整回复后追加 assistant 消息。
- 取消回复不会追加 assistant 消息。

## 任务 6：实现 Slash Commands 系统

影响文件：`artcode/commands/base.py`、`artcode/commands/builtin.py`、`artcode/commands/__init__.py`、`tests/unit/test_commands.py`

依赖任务：任务 5

参考资料定位：CLI slash command 设计

任务内容：

- 集中管理 Slash Commands。
- 实现 `/exit`、`/quit`、`/help`。
- `/help` 只显示极简命令列表。
- 只有整条输入是单独命令时才触发命令。
- 预留后续新增 `/clear`、`/thinking`、`/session` 的扩展方式。

验收方式：

- `/exit` 和 `/quit` 返回退出结果。
- `/help` 返回帮助结果。
- 普通文本中包含斜杠时不会误触发命令。

## 任务 7：实现轻量 SSE 解析器

影响文件：`artcode/providers/sse.py`、`tests/unit/test_sse.py`

依赖任务：任务 4

参考资料定位：Server-Sent Events 格式、OpenAI-compatible streaming 响应

任务内容：

- 将 HTTP 流式响应行解析为 SSE data 内容。
- 支持 `data:` 行。
- 支持一个事件内多行 `data:` 合并。
- 忽略注释行。
- 空行结束一个 SSE event。
- 识别 `[DONE]`。
- 不做自动重连。
- 不实现完整浏览器 EventSource 客户端。

验收方式：

- 单行 data 能被解析。
- 多行 data 能被合并。
- 注释行被忽略。
- `[DONE]` 能被识别为结束。

## 任务 8：定义 Provider 基础接口与事件约束

影响文件：`artcode/providers/base.py`、`artcode/providers/events.py`、`artcode/providers/__init__.py`、`tests/unit/test_provider_events.py`

依赖任务：任务 7

参考资料定位：Provider 抽象、流式事件模型

任务内容：

- 定义 Provider 层的统一职责。
- Provider 正常流式输出使用 dict 事件。
- ch02 只支持 `content_delta` 和 `done` 两类正常事件。
- 事件类型和字段集中定义，避免魔法字符串散落。
- 错误通过 ArtCode 统一异常抛出，不作为普通事件返回。
- Provider 不直接依赖 TUI。

验收方式：

- `content_delta` 事件包含文本增量。
- `done` 事件能表示本轮回复结束。
- 非法事件类型能在测试中被发现。

## 任务 9：实现 OpenAI-compatible Provider

影响文件：`artcode/providers/openai_compatible.py`、`tests/integration/test_deepseek_live.py`

依赖任务：任务 3、任务 7、任务 8

参考资料定位：DeepSeek Chat Completions API、DeepSeek Thinking Mode、`httpx.AsyncClient`

任务内容：

- 使用 `httpx.AsyncClient` 发送异步 HTTP 请求。
- 不使用 OpenAI SDK。
- 将 `base_url` 作为 OpenAI-compatible API 根路径。
- 请求地址统一拼接 `/chat/completions`。
- 处理 `base_url` 末尾斜杠。
- 设置固定连接超时和读取超时。
- 构造 stream 请求。
- 将 ArtCode 内部 Thinking Mode 配置轻量映射到请求体扩展字段。
- 如果 Thinking Mode 关闭，不携带 thinking 扩展字段。
- 解析 SSE 数据。
- 提取最终回答内容并产出 `content_delta`。
- 忽略 `reasoning_content`。
- 流结束时产出 `done`。
- 将 HTTP、认证、网络、超时、模型和流式错误转换为 ArtCode 统一错误。

验收方式：

- 对真实 DeepSeek API 能收到流式最终回答内容。
- Thinking Mode 开启时请求能被真实接口接受。
- reasoning 内容不会被上抛到 TUI。

## 任务 10：实现 TUI 渲染能力

影响文件：`artcode/tui/render.py`、`tests/unit/` 中相关渲染辅助测试

依赖任务：任务 3、任务 6、任务 8

参考资料定位：`rich` Console、终端颜色输出

任务内容：

- 启动时显示完整非敏感状态栏。
- 状态栏包含 ArtCode、章节名、protocol、model、base_url、streaming、thinking 状态。
- 每轮输入提示符保持简洁，并带当前模型信息。
- 使用角色标签区分用户和 ArtCode。
- 使用友好样式显示错误。
- 使用极简样式显示 `/help`。
- AI 回复内容原样流式输出。
- 不做 Markdown 重渲染。
- 不做代码块语法高亮。

验收方式：

- 状态栏不包含完整 API key。
- AI 文本中的 Markdown 和代码块按原样输出。
- `/help` 只显示三个基础命令。

## 任务 11：实现异步 TUI 输入循环

影响文件：`artcode/tui/app.py`、`artcode/tui/keybindings.py`、相关测试

依赖任务：任务 6、任务 10

参考资料定位：`prompt_toolkit` 异步输入、key bindings、`asyncio`

任务内容：

- 使用异步模型组织 TUI 输入。
- 支持多行输入。
- 目标体验为 Enter 发送、Ctrl+Enter 换行。
- 如果终端无法可靠识别 Ctrl+Enter，提供备用换行快捷键。
- 界面提示实际可用快捷键。
- 支持粘贴多行文本。
- 空输入或全空白输入直接忽略。
- 输入状态下 Ctrl+C/Ctrl+D 友好退出。

验收方式：

- 普通输入可以发送。
- 多行输入可以发送。
- 空输入不会进入 Provider。
- 退出快捷键不会抛出未处理异常。

## 任务 12：实现 Runtime 编排

影响文件：`artcode/runtime/app.py`、`artcode/cli.py`、`artcode/__main__.py`

依赖任务：任务 3、任务 5、任务 6、任务 9、任务 11

参考资料定位：`asyncio` 应用编排、CLI 主流程设计

任务内容：

- 串联配置、Provider、Conversation Context、Commands 和 TUI。
- 启动时加载配置并初始化 Provider。
- 普通用户输入追加为 user 消息。
- 调用 Provider 获取流式事件。
- 收到 `content_delta` 时立即交给 TUI 渲染。
- 收到 `done` 后将完整 assistant 回复写入 Conversation Context。
- 生成期间 Ctrl+C 取消当前回复。
- 取消后保留终端已打印内容，并显示本轮未写入上下文提示。
- 取消回复不写入 Conversation Context。
- 请求类错误显示后回到输入状态。

验收方式：

- 一轮完整对话后上下文包含 user 和 assistant 消息。
- 取消生成后上下文不包含半截 assistant 消息。
- 请求错误后程序继续等待下一次输入。

## 任务 13：接入主流程

影响文件：`artcode/cli.py`、`artcode/__main__.py`、`pyproject.toml`

依赖任务：任务 12

参考资料定位：Python CLI entry point、`asyncio.run`

任务内容：

- 将 Runtime 编排接入 `python -m artcode`。
- 将 Runtime 编排接入安装后的 `artcode` 命令。
- 配置启动错误以友好方式打印并退出。
- 用户正常退出时不显示异常堆栈。

验收方式：

- `python -m artcode` 可以进入完整聊天界面。
- `artcode` 可以进入完整聊天界面。
- 缺配置时启动失败但提示清楚。

## 任务 14：端到端验证

影响文件：`tests/integration/test_deepseek_live.py`、`checklist.md`

依赖任务：任务 13

参考资料定位：DeepSeek live API、`pytest-asyncio`

任务内容：

- 默认 `pytest` 执行真实 DeepSeek API 集成测试。
- 集成测试直接读取项目根目录 `artcode.yaml`。
- 测试会真实消耗 DeepSeek API 额度。
- 验证能收到至少一个 `content_delta`。
- 验证聚合后的最终回答非空。
- 验证多轮上下文基本可用。
- 验证 Thinking Mode 参数能被真实接口接受。

验收方式：

- 在存在有效 `artcode.yaml` 和网络可用时，集成测试通过。
- 测试文档明确提醒真实 API 成本和网络依赖。
