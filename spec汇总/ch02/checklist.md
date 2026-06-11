# ch02：让AI说话

## 配置验收

- [x] 项目根目录存在 `artcode.example.yaml`。
- [x] `artcode.example.yaml` 不包含真实 API key。
- [x] 真实 `artcode.yaml` 已加入 `.gitignore`。
- [x] 缺少 `artcode.yaml` 时，启动阶段给出友好提示。
- [x] `artcode.yaml` 不是合法 YAML 时，启动阶段给出友好提示。
- [x] YAML 顶层不是对象/map 时，启动失败并提示配置结构错误。
- [x] 缺少 `protocol` 时，启动失败并提示缺失字段。
- [x] 缺少 `model` 时，启动失败并提示缺失字段。
- [x] 缺少 `base_url` 时，启动失败并提示缺失字段。
- [x] 缺少 `api_key` 时，启动失败并提示缺失字段。
- [x] `protocol` 不是 `openai` 时，启动失败并提示当前不支持。
- [x] `model` 为空字符串时，启动失败。
- [x] `base_url` 为空字符串时，启动失败。
- [x] `api_key` 为空字符串时，启动失败。
- [x] `thinking.enabled` 不是布尔值时，启动失败。
- [x] `thinking.effort` 不是 `low`、`medium`、`high` 之一时，启动失败。
- [x] 不配置 `thinking` 时，程序仍能启动并按默认普通对话运行。
- [x] 状态栏不显示完整 `api_key`。

## 示例配置验收

- [x] `artcode.example.yaml` 包含 `protocol: openai`。
- [x] `artcode.example.yaml` 包含 DeepSeek API 根路径示例。
- [x] `artcode.example.yaml` 包含 DeepSeek 模型名示例。
- [x] `artcode.example.yaml` 使用占位符作为 API key。
- [x] `artcode.example.yaml` 包含 `thinking.enabled` 示例。
- [x] `artcode.example.yaml` 包含 `thinking.effort: high` 示例。

## TUI 验收

- [x] `python -m artcode` 可以进入聊天界面。
- [x] 安装后运行 `artcode` 可以进入聊天界面。
- [x] 启动时显示 `ArtCode`。
- [x] 启动时显示 `ch02：让AI说话`。
- [x] 启动时显示当前 protocol。
- [x] 启动时显示当前 model。
- [x] 启动时显示当前 base_url。
- [x] 启动时显示 `streaming: on`。
- [x] 启动时显示 Thinking Mode 开启或关闭状态。
- [x] Thinking Mode 开启时，启动状态显示 effort。
- [x] 每轮输入提示符保持简洁。
- [x] 每轮输入提示符包含当前模型信息。
- [x] `/help` 只显示 `/exit`、`/quit`、`/help`。
- [x] `/exit` 可以退出 ArtCode。
- [x] `/quit` 可以退出 ArtCode。
- [x] 空输入不会发送给模型。
- [x] 全空白输入不会发送给模型。
- [x] 空输入不会写入 Conversation Context。
- [x] 支持粘贴多行文本。
- [x] 目标体验为 Enter 发送。
- [x] 目标体验为 Ctrl+Enter 换行。
- [x] 如果终端无法可靠识别 Ctrl+Enter，界面显示实际备用换行快捷键。
- [x] 输入状态下 Ctrl+C 可以友好退出。
- [x] 空输入状态下 Ctrl+D 可以友好退出。

## Slash Commands 验收

- [x] 命令处理逻辑集中在 Commands 层。
- [x] `/exit` 只有在整条输入为该命令时才触发。
- [x] `/quit` 只有在整条输入为该命令时才触发。
- [x] `/help` 只有在整条输入为该命令时才触发。
- [x] 普通问题中包含 `/help` 字样时不会误触发命令。
- [x] 命令系统可以通过新增 handler 的方式扩展新命令。

## 流式与 Provider 验收

- [x] Provider 使用 `httpx.AsyncClient`。
- [x] Provider 不使用 OpenAI SDK。
- [x] Provider 请求地址由 `base_url` 拼接 `/chat/completions` 得到。
- [x] `base_url` 末尾带斜杠时，请求地址不会出现双斜杠。
- [x] 请求连接超时为 10 秒。
- [x] 请求读取超时为 60 秒。
- [x] 超时后 TUI 显示友好错误，程序继续运行。
- [x] SSE 解析器能识别 `data:` 行。
- [x] SSE 解析器能识别 `[DONE]`。
- [x] SSE 解析器能处理一个 event 中的多行 data。
- [x] SSE 解析器会忽略注释行。
- [x] SSE 解析器不做自动重连。
- [x] 模型回复不会等完整生成后才显示。
- [x] 收到最终回答增量时，TUI 立即输出。
- [x] Provider 正常流式事件使用 dict。
- [x] Provider 正常流式事件包含 `content_delta`。
- [x] Provider 正常流式事件包含 `done`。
- [x] Provider 错误通过 ArtCode 统一异常抛出。
- [x] TUI 不直接解析 DeepSeek 原始 SSE 字段。

## Thinking Mode 验收

- [x] `thinking.enabled: true` 时，请求体携带 Thinking Mode 相关扩展字段。
- [x] `thinking.enabled: false` 时，请求体不携带 Thinking Mode 相关扩展字段。
- [x] `thinking.effort: high` 能被映射到 DeepSeek/OpenAI-compatible 请求体。
- [x] 服务端返回 reasoning/thinking 内容时，TUI 不显示该内容。
- [x] 服务端返回 reasoning/thinking 内容时，该内容不写入 Conversation Context。
- [x] 服务端不接受 Thinking Mode 参数时，TUI 显示可理解错误。
- [x] ch02 不提供 `/thinking` 命令。

## 输出内容验收

- [x] AI 回复内容原样流式输出。
- [x] AI 回复不做 Markdown 重渲染。
- [x] AI 回复不做代码块语法高亮。
- [x] AI 回复中的反引号按模型返回内容显示。
- [x] AI 回复中的缩进按模型返回内容显示。
- [ ] rich 只用于状态栏、角色标签、错误和提示等界面元素。

## Conversation Context 验收

- [x] 启动后 Conversation Context 包含内置 system prompt。
- [x] system prompt 说明 ArtCode 当前只支持纯对话。
- [x] system prompt 说明 ArtCode 当前不执行工具。
- [x] system prompt 说明 ArtCode 当前不读取文件。
- [x] system prompt 说明 ArtCode 当前不编辑代码。
- [x] 用户发送问题后，user 消息加入上下文。
- [x] AI 完整回复结束后，assistant 消息加入上下文。
- [x] 第二轮问题可以引用第一轮内容并得到相关回答。
- [x] 程序退出后不要求恢复历史对话。
- [x] ch02 不保存会话文件。
- [x] ch02 不做自动上下文裁剪。
- [x] 对话过长导致 API 报错时，TUI 显示友好错误。

## 取消生成验收

- [x] 生成期间 Ctrl+C 会取消当前回复。
- [x] 取消当前回复后程序回到输入状态。
- [x] 取消后终端保留已打印的半截内容。
- [x] 取消后终端显示本轮回复未写入上下文的提示。
- [x] 取消后的半截 assistant 回复不会加入 Conversation Context。
- [x] 取消后的下一轮请求不包含半截 assistant 回复。

## 错误验收

- [x] API key 无效时，TUI 显示认证相关友好错误。
- [x] 网络连接失败时，TUI 显示网络相关友好错误。
- [x] 请求超时时，TUI 显示超时相关友好错误。
- [x] 模型名不可用时，TUI 显示模型相关友好错误。
- [x] Thinking Mode 不被接口接受时，TUI 显示 Thinking Mode 相关友好错误。
- [x] 流式响应中途断开时，TUI 显示流式中断错误。
- [x] 错误提示中不包含完整 API key。
- [x] 请求类错误不会导致整个 TUI 崩溃。
- [x] 配置类错误在启动阶段提示并退出。

## 安全与持久化验收

- [x] ch02 不生成日志文件。
- [x] ch02 不保存完整对话记录。
- [x] ch02 不保存 reasoning/thinking 内容。
- [x] ch02 不保存 API 请求体日志。
- [x] ch02 不保存 API 响应体日志。
- [x] ch02 不读取项目文件。
- [x] ch02 不编辑项目文件。
- [x] ch02 不执行 shell 命令。

## 测试验收

- [x] 测试目录按 `tests/unit/` 和 `tests/integration/` 分层。
- [x] 单元测试覆盖配置加载。
- [x] 单元测试覆盖配置缺字段。
- [ ] 单元测试覆盖配置字段类型错误。
- [x] 单元测试覆盖 Thinking Mode 配置解析。
- [x] 单元测试覆盖 Conversation Context 追加和导出。
- [x] 单元测试覆盖 Slash Commands 解析。
- [x] 单元测试覆盖 SSE `data:` 解析。
- [x] 单元测试覆盖 SSE `[DONE]` 识别。
- [x] 单元测试覆盖 SSE 多行 data 合并。
- [x] 单元测试覆盖 Provider 事件格式约束。
- [x] 默认运行 `pytest` 会执行真实 DeepSeek API 集成测试。
- [x] 集成测试读取项目根目录 `artcode.yaml`。
- [x] 集成测试能收到至少一个 `content_delta`。
- [x] 集成测试聚合出的最终回答非空。
- [x] 集成测试验证多轮上下文可用。
- [x] 集成测试验证 Thinking Mode 参数能被真实接口接受。
- [x] 文档明确提醒真实集成测试会消耗 DeepSeek API 额度。
- [x] 文档明确提醒真实集成测试依赖网络和 DeepSeek 服务状态。
