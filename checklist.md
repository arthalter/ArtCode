# ch02：让AI说话

## 配置验收

- [ ] 项目根目录存在 `artcode.example.yaml`。
- [ ] `artcode.example.yaml` 不包含真实 API key。
- [ ] 真实 `artcode.yaml` 已加入 `.gitignore`。
- [ ] 缺少 `artcode.yaml` 时，启动阶段给出友好提示。
- [ ] `artcode.yaml` 不是合法 YAML 时，启动阶段给出友好提示。
- [ ] YAML 顶层不是对象/map 时，启动失败并提示配置结构错误。
- [ ] 缺少 `protocol` 时，启动失败并提示缺失字段。
- [ ] 缺少 `model` 时，启动失败并提示缺失字段。
- [ ] 缺少 `base_url` 时，启动失败并提示缺失字段。
- [ ] 缺少 `api_key` 时，启动失败并提示缺失字段。
- [ ] `protocol` 不是 `openai` 时，启动失败并提示当前不支持。
- [ ] `model` 为空字符串时，启动失败。
- [ ] `base_url` 为空字符串时，启动失败。
- [ ] `api_key` 为空字符串时，启动失败。
- [ ] `thinking.enabled` 不是布尔值时，启动失败。
- [ ] `thinking.effort` 不是 `low`、`medium`、`high` 之一时，启动失败。
- [ ] 不配置 `thinking` 时，程序仍能启动并按默认普通对话运行。
- [ ] 状态栏不显示完整 `api_key`。

## 示例配置验收

- [ ] `artcode.example.yaml` 包含 `protocol: openai`。
- [ ] `artcode.example.yaml` 包含 DeepSeek API 根路径示例。
- [ ] `artcode.example.yaml` 包含 DeepSeek 模型名示例。
- [ ] `artcode.example.yaml` 使用占位符作为 API key。
- [ ] `artcode.example.yaml` 包含 `thinking.enabled` 示例。
- [ ] `artcode.example.yaml` 包含 `thinking.effort: high` 示例。

## TUI 验收

- [ ] `python -m artcode` 可以进入聊天界面。
- [ ] 安装后运行 `artcode` 可以进入聊天界面。
- [ ] 启动时显示 `ArtCode`。
- [ ] 启动时显示 `ch02：让AI说话`。
- [ ] 启动时显示当前 protocol。
- [ ] 启动时显示当前 model。
- [ ] 启动时显示当前 base_url。
- [ ] 启动时显示 `streaming: on`。
- [ ] 启动时显示 Thinking Mode 开启或关闭状态。
- [ ] Thinking Mode 开启时，启动状态显示 effort。
- [ ] 每轮输入提示符保持简洁。
- [ ] 每轮输入提示符包含当前模型信息。
- [ ] `/help` 只显示 `/exit`、`/quit`、`/help`。
- [ ] `/exit` 可以退出 ArtCode。
- [ ] `/quit` 可以退出 ArtCode。
- [ ] 空输入不会发送给模型。
- [ ] 全空白输入不会发送给模型。
- [ ] 空输入不会写入 Conversation Context。
- [ ] 支持粘贴多行文本。
- [ ] 目标体验为 Enter 发送。
- [ ] 目标体验为 Ctrl+Enter 换行。
- [ ] 如果终端无法可靠识别 Ctrl+Enter，界面显示实际备用换行快捷键。
- [ ] 输入状态下 Ctrl+C 可以友好退出。
- [ ] 空输入状态下 Ctrl+D 可以友好退出。

## Slash Commands 验收

- [ ] 命令处理逻辑集中在 Commands 层。
- [ ] `/exit` 只有在整条输入为该命令时才触发。
- [ ] `/quit` 只有在整条输入为该命令时才触发。
- [ ] `/help` 只有在整条输入为该命令时才触发。
- [ ] 普通问题中包含 `/help` 字样时不会误触发命令。
- [ ] 命令系统可以通过新增 handler 的方式扩展新命令。

## 流式与 Provider 验收

- [ ] Provider 使用 `httpx.AsyncClient`。
- [ ] Provider 不使用 OpenAI SDK。
- [ ] Provider 请求地址由 `base_url` 拼接 `/chat/completions` 得到。
- [ ] `base_url` 末尾带斜杠时，请求地址不会出现双斜杠。
- [ ] 请求连接超时为 10 秒。
- [ ] 请求读取超时为 60 秒。
- [ ] 超时后 TUI 显示友好错误，程序继续运行。
- [ ] SSE 解析器能识别 `data:` 行。
- [ ] SSE 解析器能识别 `[DONE]`。
- [ ] SSE 解析器能处理一个 event 中的多行 data。
- [ ] SSE 解析器会忽略注释行。
- [ ] SSE 解析器不做自动重连。
- [ ] 模型回复不会等完整生成后才显示。
- [ ] 收到最终回答增量时，TUI 立即输出。
- [ ] Provider 正常流式事件使用 dict。
- [ ] Provider 正常流式事件包含 `content_delta`。
- [ ] Provider 正常流式事件包含 `done`。
- [ ] Provider 错误通过 ArtCode 统一异常抛出。
- [ ] TUI 不直接解析 DeepSeek 原始 SSE 字段。

## Thinking Mode 验收

- [ ] `thinking.enabled: true` 时，请求体携带 Thinking Mode 相关扩展字段。
- [ ] `thinking.enabled: false` 时，请求体不携带 Thinking Mode 相关扩展字段。
- [ ] `thinking.effort: high` 能被映射到 DeepSeek/OpenAI-compatible 请求体。
- [ ] 服务端返回 reasoning/thinking 内容时，TUI 不显示该内容。
- [ ] 服务端返回 reasoning/thinking 内容时，该内容不写入 Conversation Context。
- [ ] 服务端不接受 Thinking Mode 参数时，TUI 显示可理解错误。
- [ ] ch02 不提供 `/thinking` 命令。

## 输出内容验收

- [ ] AI 回复内容原样流式输出。
- [ ] AI 回复不做 Markdown 重渲染。
- [ ] AI 回复不做代码块语法高亮。
- [ ] AI 回复中的反引号按模型返回内容显示。
- [ ] AI 回复中的缩进按模型返回内容显示。
- [ ] rich 只用于状态栏、角色标签、错误和提示等界面元素。

## Conversation Context 验收

- [ ] 启动后 Conversation Context 包含内置 system prompt。
- [ ] system prompt 说明 ArtCode 当前只支持纯对话。
- [ ] system prompt 说明 ArtCode 当前不执行工具。
- [ ] system prompt 说明 ArtCode 当前不读取文件。
- [ ] system prompt 说明 ArtCode 当前不编辑代码。
- [ ] 用户发送问题后，user 消息加入上下文。
- [ ] AI 完整回复结束后，assistant 消息加入上下文。
- [ ] 第二轮问题可以引用第一轮内容并得到相关回答。
- [ ] 程序退出后不要求恢复历史对话。
- [ ] ch02 不保存会话文件。
- [ ] ch02 不做自动上下文裁剪。
- [ ] 对话过长导致 API 报错时，TUI 显示友好错误。

## 取消生成验收

- [ ] 生成期间 Ctrl+C 会取消当前回复。
- [ ] 取消当前回复后程序回到输入状态。
- [ ] 取消后终端保留已打印的半截内容。
- [ ] 取消后终端显示本轮回复未写入上下文的提示。
- [ ] 取消后的半截 assistant 回复不会加入 Conversation Context。
- [ ] 取消后的下一轮请求不包含半截 assistant 回复。

## 错误验收

- [ ] API key 无效时，TUI 显示认证相关友好错误。
- [ ] 网络连接失败时，TUI 显示网络相关友好错误。
- [ ] 请求超时时，TUI 显示超时相关友好错误。
- [ ] 模型名不可用时，TUI 显示模型相关友好错误。
- [ ] Thinking Mode 不被接口接受时，TUI 显示 Thinking Mode 相关友好错误。
- [ ] 流式响应中途断开时，TUI 显示流式中断错误。
- [ ] 错误提示中不包含完整 API key。
- [ ] 请求类错误不会导致整个 TUI 崩溃。
- [ ] 配置类错误在启动阶段提示并退出。

## 安全与持久化验收

- [ ] ch02 不生成日志文件。
- [ ] ch02 不保存完整对话记录。
- [ ] ch02 不保存 reasoning/thinking 内容。
- [ ] ch02 不保存 API 请求体日志。
- [ ] ch02 不保存 API 响应体日志。
- [ ] ch02 不读取项目文件。
- [ ] ch02 不编辑项目文件。
- [ ] ch02 不执行 shell 命令。

## 测试验收

- [ ] 测试目录按 `tests/unit/` 和 `tests/integration/` 分层。
- [ ] 单元测试覆盖配置加载。
- [ ] 单元测试覆盖配置缺字段。
- [ ] 单元测试覆盖配置字段类型错误。
- [ ] 单元测试覆盖 Thinking Mode 配置解析。
- [ ] 单元测试覆盖 Conversation Context 追加和导出。
- [ ] 单元测试覆盖 Slash Commands 解析。
- [ ] 单元测试覆盖 SSE `data:` 解析。
- [ ] 单元测试覆盖 SSE `[DONE]` 识别。
- [ ] 单元测试覆盖 SSE 多行 data 合并。
- [ ] 单元测试覆盖 Provider 事件格式约束。
- [ ] 默认运行 `pytest` 会执行真实 DeepSeek API 集成测试。
- [ ] 集成测试读取项目根目录 `artcode.yaml`。
- [ ] 集成测试能收到至少一个 `content_delta`。
- [ ] 集成测试聚合出的最终回答非空。
- [ ] 集成测试验证多轮上下文可用。
- [ ] 集成测试验证 Thinking Mode 参数能被真实接口接受。
- [ ] 文档明确提醒真实集成测试会消耗 DeepSeek API 额度。
- [ ] 文档明确提醒真实集成测试依赖网络和 DeepSeek 服务状态。
