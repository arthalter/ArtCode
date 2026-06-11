# ch04：动手实现 Agent Loop Checklist

> 每一项都通过运行测试、启动程序或观察上下文/文件变化来验证，聚焦可观测行为。

## Agent Loop 基础行为

- [x] 普通用户输入默认进入 Agent Loop（验证：运行 Runtime 单元测试，观察普通输入会创建 `NORMAL_AGENT_MODE` 的 Agent 运行请求）。
- [x] 模型不请求工具时 Agent Loop 自然结束（验证：运行 `tests/unit/test_agent_loop.py`，观察自然完成用例中最后一条上下文消息是 assistant 自然语言回复）。
- [x] 自然结束时不额外发起无工具总结请求（验证：运行 `tests/unit/test_agent_loop.py`，观察 fake provider 只被调用一次）。
- [x] Agent Loop 每轮按当前模式携带工具列表（验证：运行 `tests/unit/test_agent_loop.py`，观察普通模式和 `/do` 携带全工具、Plan Mode 只携带只读工具）。
- [x] Agent Loop 达到第 12 轮仍未自然结束时停止（验证：运行 `tests/unit/test_agent_loop.py`，观察停止原因是 `iteration_limit` 且迭代数为 12）。
- [x] 达到 12 轮上限后会尝试一次无工具最终总结（验证：运行 `tests/unit/test_agent_loop.py`，观察最后一次 provider 调用的 `tools` 为 `None`）。
- [x] 达到迭代上限时 TUI 展示明确停止原因（验证：运行 `tests/unit/test_render.py`，观察渲染输出包含迭代上限停止摘要）。

## 多工具调用与执行顺序

- [x] 同一轮多个工具调用不会再触发 ch03 的 `too_many_tool_calls` 错误（验证：运行 `tests/unit/test_agent_tools.py tests/unit/test_agent_loop.py`，观察多个有效工具被分批执行）。
- [x] 多个相邻只读工具会被合并为同一批（验证：运行 `tests/unit/test_agent_tools.py`，观察 `read_file`、`find_files`、`search_text` 连续调用生成一个 `read_only` 批次）。
- [x] 同一只读批次会并发执行（验证：运行 `tests/unit/test_agent_tools.py`，用带延迟 fake tool 观察总耗时小于串行耗时）。
- [x] 并发只读工具结果按模型原始调用顺序写入上下文（验证：运行 `tests/unit/test_agent_loop.py`，观察 tool result 顺序与 tool call 顺序一致）。
- [x] “只读工具 → 有副作用工具 → 只读工具”会被分成三批（验证：运行 `tests/unit/test_agent_tools.py`，观察批次顺序为 `read_only`、`side_effect`、`read_only`）。
- [x] 有副作用工具逐个串行执行（验证：运行 `tests/unit/test_agent_tools.py`，用记录时间的 fake side-effect tool 观察第二个在第一个结束后开始）。
- [x] `run_command` 即使命令看似只读也归为有副作用工具（验证：运行 `tests/unit/test_agent_tools.py`，观察 `run_command("ls")` 生成 `side_effect` 批次）。
- [x] Agent Loop 中写文件、改文件和执行命令不会弹出 ch03 yes/no 确认（验证：运行 `tests/unit/test_agent_loop.py`，观察 fake TUI 的确认方法未被调用）。
- [x] 工具批次开始时会发出进度事件（验证：运行 `tests/unit/test_agent_tools.py tests/unit/test_agent_loop.py`，观察事件中包含批次序号、安全分类和工具数量）。

## 工具安全边界

- [x] 允许目录限制在 ch04 Agent Loop 中仍然生效（验证：运行 `tests/unit/test_agent_loop.py tests/unit/test_file_tools.py`，观察越界读写返回结构化错误且目标文件未被访问）。
- [x] 危险命令拦截在 ch04 Agent Loop 中仍然生效（验证：运行 `tests/unit/test_agent_loop.py tests/unit/test_command_tool.py`，观察危险命令返回 `dangerous_command` 且未执行）。
- [x] 工具执行超时仍返回结构化错误（验证：运行 `tests/unit/test_command_tool.py`，观察超时命令返回 `command_timeout`）。
- [x] 工具结果超过 20KB 仍会截断并标记（验证：运行 `tests/unit/test_tool_results.py tests/unit/test_agent_loop.py`，观察 tool result JSON 中 `truncated=true`）。
- [x] 已知工具参数 JSON 非法时写入结构化失败结果（验证：运行 `tests/unit/test_agent_tools.py tests/unit/test_agent_loop.py`，观察 `invalid_arguments` tool result 写入上下文）。
- [x] 已知工具 prepare 失败时写入结构化失败结果并继续下一轮（验证：运行 `tests/unit/test_agent_loop.py`，观察失败后 provider 被再次调用）。
- [x] 已知工具执行失败时写入结构化失败结果并继续下一轮（验证：运行 `tests/unit/test_agent_loop.py`，观察失败 tool result 后进入下一轮模型请求）。
- [x] 同一轮工具调用中出现未知工具时，本轮所有工具都不执行（验证：运行 `tests/unit/test_agent_loop.py`，观察同轮有效 fake tool 执行次数为 0）。
- [x] 未知工具停止原因可观测（验证：运行 `tests/unit/test_agent_loop.py tests/unit/test_render.py`，观察停止原因是 `unknown_tool` 且 TUI 有对应摘要）。
- [x] 未知工具停止后会尝试无工具最终总结（验证：运行 `tests/unit/test_agent_loop.py`，观察后续 provider 调用 `tools=None`）。

## 流式收集与上下文写入

- [x] 文本增量会实时产生 `TEXT_DELTA` 事件（验证：运行 `tests/unit/test_agent_stream.py`，观察每个 provider `content_delta` 都转成 Agent 文本事件）。
- [x] 流式收集器会保存完整响应文本（验证：运行 `tests/unit/test_agent_stream.py`，观察最终 `ModelTurn.text` 等于所有增量拼接）。
- [x] Provider 返回工具调用时 `ModelTurn.tool_calls` 包含完整工具调用列表（验证：运行 `tests/unit/test_agent_stream.py`，观察多个 tool call 均被保留）。
- [x] 同一轮模型既输出文本又请求工具时，文本会显示但不写入普通 assistant 消息（验证：运行 `tests/unit/test_agent_loop.py`，观察 TUI 收到文本事件但上下文只包含 assistant tool_call 消息）。
- [x] 每一轮 assistant tool_call 消息都写入 Conversation Context（验证：运行 `tests/unit/test_agent_loop.py tests/unit/test_context.py`，观察上下文包含 OpenAI-compatible tool_call 消息）。
- [x] 每一个 tool result 都写入 Conversation Context（验证：运行 `tests/unit/test_agent_loop.py tests/unit/test_context.py`，观察上下文包含对应 `role=tool` 消息）。
- [x] 用户取消时半截文本不写入 Conversation Context（验证：运行 `tests/unit/test_agent_loop.py`，观察取消后上下文没有半截 assistant 消息）。
- [x] 流式错误时半截文本不写入 Conversation Context（验证：运行 `tests/unit/test_agent_loop.py`，观察 `stream_error` 后上下文没有半截 assistant 消息）。
- [x] 流式错误后不再请求最终总结（验证：运行 `tests/unit/test_agent_loop.py`，观察 provider 调用次数没有额外总结请求）。

## Token 用量事件

- [x] Provider 事件支持真实 Token 用量（验证：运行 `tests/unit/test_provider_events.py`，观察 `token_usage` 事件校验通过）。
- [x] OpenAI-compatible SSE 出现真实 `usage` 字段时会产出 Token 用量事件（验证：运行 `tests/unit/test_openai_provider.py`）。
- [x] Agent StreamCollector 会把 Provider Token 用量转成 Agent `TOKEN_USAGE` 事件（验证：运行 `tests/unit/test_agent_stream.py`）。
- [x] TUI 能展示真实 Token 用量摘要（验证：运行 `tests/unit/test_render.py`，观察输出包含 prompt/completion/total token 数）。
- [x] Provider 未返回 usage 时 Agent Loop 正常继续（验证：运行 `tests/unit/test_agent_stream.py tests/unit/test_agent_loop.py`，观察无 usage 用例不报错）。
- [x] 系统不估算 token 用量（验证：运行 `tests/unit/test_agent_stream.py`，观察无 usage 时没有 `TOKEN_USAGE` 事件）。

## Plan Mode 与 `/do`

- [x] `/plan 任务描述` 能被解析为带参数的计划命令（验证：运行 `tests/unit/test_commands.py`，观察 action 为 `plan` 且 argument 为任务描述）。
- [x] `/plan` 无任务描述时提示用户补充任务（验证：运行 `tests/unit/test_commands.py`，观察返回帮助提示）。
- [x] `/plan` 每轮只携带 `read_file`、`find_files`、`search_text`（验证：运行 `tests/unit/test_agent_loop.py tests/unit/test_agent_modes.py`，观察工具列表不包含写、改、命令工具）。
- [x] `/plan` 请求写文件、改文件或执行命令时不会执行工具（验证：运行 `tests/unit/test_agent_loop.py`，观察对应 fake tool 执行次数为 0）。
- [x] `/plan` 自然结束后计划文本写入 Conversation Context（验证：运行 `tests/unit/test_agent_loop.py`，观察最后 assistant 消息是计划文本）。
- [x] `/plan` 自然结束后最近计划保存到 PlanMemory（验证：运行 `tests/unit/test_agent_memory.py tests/unit/test_agent_loop.py`）。
- [x] `/plan` 异常停止时不覆盖旧计划（验证：运行 `tests/unit/test_agent_loop.py`，先保存旧计划，再触发 plan 流式错误，观察旧计划仍存在）。
- [x] 最近计划不落盘（验证：运行 `tests/unit/test_agent_memory.py`，观察 PlanMemory 只存在内存对象中；测试后项目目录无新增计划文件）。
- [x] 没有最近计划时输入 `/do` 会提示先执行 `/plan 任务描述`（验证：运行 `tests/unit/test_runtime.py`，观察 TUI 输出提示且 provider 未被调用）。
- [x] `/do` 会使用全工具 Agent Loop 执行最近计划（验证：运行 `tests/unit/test_runtime.py tests/unit/test_agent_loop.py`，观察工具列表包含写、改、命令工具）。
- [x] `/do 附加说明` 会把附加说明并入执行目标（验证：运行 `tests/unit/test_runtime.py`，观察写入上下文的 user 消息包含最近计划和附加说明）。
- [x] `/do` 执行时同样受 12 轮上限约束（验证：运行 `tests/unit/test_agent_loop.py`，用 DO_MODE 触发迭代上限，观察第 12 轮停止）。

## Runtime 与 TUI 集成

- [x] Runtime 普通输入通过 AgentLoop 运行，不再走 ch03 单步 `_handle_tool_calls` 路径（验证：运行 `tests/unit/test_runtime.py`，观察 fake AgentLoop 收到普通请求）。
- [x] Runtime 能消费 `TEXT_DELTA` 并转发给 TUI（验证：运行 `tests/unit/test_runtime.py`，观察 fake TUI 收到文本增量）。
- [x] Runtime 能消费 `TOOL_CALLS_RECEIVED` 并展示工具调用数量（验证：运行 `tests/unit/test_runtime.py tests/unit/test_render.py`）。
- [x] Runtime 能消费 `TOOL_BATCH_STARTED` 并展示批次摘要（验证：运行 `tests/unit/test_runtime.py tests/unit/test_render.py`）。
- [x] Runtime 能消费 `TOOL_RESULT` 并展示工具结果摘要（验证：运行 `tests/unit/test_runtime.py tests/unit/test_render.py`）。
- [x] Runtime 能消费 `TOKEN_USAGE` 并展示用量（验证：运行 `tests/unit/test_runtime.py tests/unit/test_render.py`）。
- [x] Runtime 能消费 `STOPPED` 并展示停止原因（验证：运行 `tests/unit/test_runtime.py tests/unit/test_render.py`）。
- [x] 用户按 `Ctrl+C` 会取消当前整轮 Agent Loop（验证：运行 `tests/unit/test_runtime.py tests/unit/test_agent_loop.py`，观察停止原因 `user_cancelled` 且无后续 provider 调用）。
- [x] TUI 不直接打印完整工具输出（验证：运行 `tests/unit/test_render.py`，断言长工具 content 不出现在渲染输出中）。

## 提示词、配置与文档

- [x] 启动状态显示 `ch04：动手实现 Agent Loop`（验证：运行 `tests/unit/test_config.py`，观察章节名断言通过）。
- [x] 系统提示说明普通输入默认进入 Agent Loop（验证：运行 `tests/unit/test_context.py`，观察 system prompt 包含 Agent Loop 行为）。
- [x] 系统提示说明同一轮可以请求多个工具（验证：运行 `tests/unit/test_context.py`）。
- [x] 系统提示不再包含 ch03 “同一轮最多一个工具调用”的限制（验证：运行 `tests/unit/test_context.py`）。
- [x] 系统提示说明 Plan Mode 只能使用读类工具（验证：运行 `tests/unit/test_context.py`）。
- [x] 系统提示说明副作用工具会自动执行且应谨慎使用（验证：运行 `tests/unit/test_context.py`）。
- [x] README 包含 ch04 Agent Loop 简介（验证：打开 `README.md`，观察包含普通输入默认循环、Plan Mode、12 轮上限）。
- [x] 集成测试 README 说明真实 DeepSeek 测试默认执行（验证：打开 `tests/integration/README.md`）。
- [x] ch04 不新增 YAML 配置项（验证：打开 `artcode.example.yaml`，观察没有新增 max_iterations 配置）。

## 编译与测试

- [x] Agent 相关单元测试通过（验证：运行 `.venv/bin/python -m pytest tests/unit/test_agent_events.py tests/unit/test_agent_modes.py tests/unit/test_agent_memory.py tests/unit/test_agent_stream.py tests/unit/test_agent_tools.py tests/unit/test_agent_loop.py -q`）。
- [x] Provider 相关单元测试通过（验证：运行 `.venv/bin/python -m pytest tests/unit/test_provider_events.py tests/unit/test_openai_provider.py -q`）。
- [x] Commands、Runtime、TUI 单元测试通过（验证：运行 `.venv/bin/python -m pytest tests/unit/test_commands.py tests/unit/test_runtime.py tests/unit/test_render.py tests/unit/test_tui_app.py -q`）。
- [x] 工具安全边界单元测试仍通过（验证：运行 `.venv/bin/python -m pytest tests/unit/test_file_tools.py tests/unit/test_command_tool.py tests/unit/test_tool_policy.py tests/unit/test_tool_results.py -q`）。
- [x] 全部单元测试通过（验证：运行 `.venv/bin/python -m pytest tests/unit -q`）。
- [x] 全部集成测试通过且包含真实 DeepSeek API 测试（验证：运行 `.venv/bin/python -m pytest tests/integration -q`）。
- [x] 默认测试套件通过（验证：运行 `.venv/bin/python -m pytest -q`）。

## 端到端场景

- [x] 场景 1：用户提出普通聊天任务 → 模型不调用工具 → Agent Loop 自然结束并写入 assistant 回复（验证：运行 fake provider 端到端测试，观察上下文最后一条是 assistant 回复）。
- [x] 场景 2：用户提出需要读写文件的任务 → Agent Loop 自主读文件 → 自动写文件或改文件 → 继续读取或运行工具验证 → 最终自然语言总结（验证：运行 `tests/integration/test_agent_loop_flow.py`，观察目标文件变化、验证工具被调用、最终回复写入上下文）。
- [x] 场景 3：`/plan 任务描述` → 只读工具生成计划 → `/do` 执行最近计划 → Agent Loop 使用全工具完成任务或说明停止原因（验证：运行 `tests/integration/test_agent_loop_flow.py`）。
- [x] 场景 4：同一轮多个只读工具 → 并发执行 → 结果按原始顺序回灌 → 下一轮模型基于结果总结（验证：运行 `tests/integration/test_agent_loop_flow.py`）。
- [x] 场景 5：同一轮出现未知工具 → 本轮所有工具不执行 → Agent Loop 异常停止 → 无工具总结说明未知工具（验证：运行 `tests/integration/test_agent_loop_flow.py`）。
- [x] 场景 6：真实 DeepSeek API 流式请求可完成至少一个 Agent Loop 路径（验证：运行 `tests/integration/test_deepseek_live.py`，观察真实 API 测试通过）。
