# ch04：动手实现 Agent Loop Tasks

## 文件清单

| 操作 | 文件 | 职责 |
|---|---|---|
| 新建 | `artcode/agent/__init__.py` | 导出 Agent 层公共入口 |
| 新建 | `artcode/agent/events.py` | Agent 事件、停止原因、Token 用量、模型轮次结果 |
| 新建 | `artcode/agent/modes.py` | Agent 运行模式、工具访问策略、只读工具集合 |
| 新建 | `artcode/agent/memory.py` | 本次运行内最近计划 |
| 新建 | `artcode/agent/stream.py` | 双路流式收集器 |
| 新建 | `artcode/agent/tools.py` | 多工具安全分类、分批、预检和执行 |
| 新建 | `artcode/agent/loop.py` | Agent Loop 主编排 |
| 修改 | `artcode/providers/events.py` | 增加真实 Token 用量事件 |
| 修改 | `artcode/providers/openai_compatible.py` | 解析流式 usage 字段 |
| 修改 | `artcode/providers/base.py` | 补充 Provider 事件语义 |
| 修改 | `artcode/commands/base.py` | 支持带参数 Slash Command |
| 修改 | `artcode/commands/builtin.py` | 增加 `/plan`、`/do`，更新帮助 |
| 修改 | `artcode/runtime/app.py` | 接入 AgentLoop，移除 ch03 单步工具编排 |
| 修改 | `artcode/tui/app.py` | 暴露 Agent 进度展示方法 |
| 修改 | `artcode/tui/render.py` | 渲染迭代、批次、Token 用量、停止原因 |
| 修改 | `artcode/prompts.py` | 更新 ch04 系统提示 |
| 修改 | `artcode/config.py` | 章节名更新为 ch04 |
| 修改 | `artcode/cli.py` | 创建并注入 AgentLoop / PlanMemory 依赖 |
| 修改 | `README.md` | 更新 ch04 Agent Loop 简介 |
| 修改 | `tests/integration/README.md` | 说明真实 DeepSeek 测试默认执行 |
| 新建 | `tests/unit/test_agent_events.py` | 覆盖 Agent 事件与停止原因 |
| 新建 | `tests/unit/test_agent_modes.py` | 覆盖工具访问策略 |
| 新建 | `tests/unit/test_agent_memory.py` | 覆盖最近计划内存行为 |
| 新建 | `tests/unit/test_agent_stream.py` | 覆盖双路流式收集和流式错误 |
| 新建 | `tests/unit/test_agent_tools.py` | 覆盖多工具分批、未知工具、执行顺序 |
| 新建 | `tests/unit/test_agent_loop.py` | 覆盖 Agent Loop 主行为 |
| 修改 | `tests/unit/test_commands.py` | 覆盖 `/plan`、`/do` 和带参数命令 |
| 修改 | `tests/unit/test_provider_events.py` | 覆盖 token_usage 事件 |
| 修改 | `tests/unit/test_openai_provider.py` | 覆盖 usage SSE 解析 |
| 修改 | `tests/unit/test_runtime.py` | 覆盖 Runtime 接入 AgentLoop |
| 修改 | `tests/unit/test_render.py` | 覆盖 Agent 进度展示 |
| 修改 | `tests/unit/test_tui_app.py` | 覆盖 TUI 新展示入口 |
| 修改 | `tests/integration/test_tool_flow.py` | 按 ch04 多工具行为更新兼容场景 |
| 新建 | `tests/integration/test_agent_loop_flow.py` | Fake Provider 多轮 Agent Loop 端到端 |
| 修改 | `tests/integration/test_deepseek_live.py` | 增加真实流式 Agent Loop 路径 |

## T1: 建立 Agent 基础类型和运行模式

**影响文件：** `artcode/agent/__init__.py`、`artcode/agent/events.py`、`artcode/agent/modes.py`、`artcode/agent/memory.py`、`tests/unit/test_agent_events.py`、`tests/unit/test_agent_modes.py`、`tests/unit/test_agent_memory.py`

**依赖任务：** 无

**参考资料定位：** `spec.md` F15、F19-F24；`plan.md` 的 `AgentEvent`、`StopReason`、`AgentMode`、`ToolAccessPolicy`、`PlanMemory`

**步骤：**

1. 创建 `artcode.agent` 包并导出公共类型。
2. 定义 `AgentEventType`、`AgentEvent`、`StopReason`、`TokenUsage`、`ModelTurn`。
3. 定义 `ToolAccessPolicy`，支持全工具和指定工具集合过滤。
4. 定义只读工具集合 `read_file`、`find_files`、`search_text`。
5. 定义 `NORMAL_AGENT_MODE`、`PLAN_MODE`、`DO_MODE`。
6. 定义 `PlanMemory`，支持保存、读取、清空最近计划。
7. 补充事件、模式过滤和内存计划单元测试。

**验证：** 运行 `.venv/bin/python -m pytest tests/unit/test_agent_events.py tests/unit/test_agent_modes.py tests/unit/test_agent_memory.py -q`，期望全部通过。

## T2: 扩展 Provider Token 用量事件

**影响文件：** `artcode/providers/events.py`、`artcode/providers/openai_compatible.py`、`artcode/providers/base.py`、`tests/unit/test_provider_events.py`、`tests/unit/test_openai_provider.py`

**依赖任务：** T1

**参考资料定位：** `spec.md` F19、AC18-AC19；`plan.md` 的 Provider Token 用量设计

**步骤：**

1. 在 Provider 事件中增加 `token_usage` 类型和构造函数。
2. 校验 `prompt_tokens`、`completion_tokens`、`total_tokens` 允许为整数或缺省。
3. 在 OpenAI-compatible SSE 解析中识别真实 `usage` 字段。
4. 有 usage 时产出 `token_usage` 事件；没有 usage 时不产出。
5. 保持现有 `content_delta`、`tool_calls`、`done` 行为不变。
6. 补充 Provider 事件和 SSE usage 解析测试。

**验证：** 运行 `.venv/bin/python -m pytest tests/unit/test_provider_events.py tests/unit/test_openai_provider.py -q`，期望 usage 和既有事件测试通过。

## T3: 实现双路流式收集器

**影响文件：** `artcode/agent/stream.py`、`tests/unit/test_agent_stream.py`

**依赖任务：** T1、T2

**参考资料定位：** `spec.md` F14-F16、AC16、AC20；`plan.md` 的 `StreamCollector`

**步骤：**

1. 实现 `StreamCollector.collect`。
2. 收到文本增量时立即产出 Agent `TEXT_DELTA` 事件。
3. 同时把文本增量追加到完整响应缓冲。
4. 收到工具调用事件时保存完整工具调用列表。
5. 收到 Token 用量事件时转成 Agent `TOKEN_USAGE` 事件。
6. 收到完成事件时产出 `ModelTurn`。
7. Provider 抛错时向上抛出，不在收集器里写上下文。
8. 补充文本双路、工具调用、Token 用量、流式错误测试。

**验证：** 运行 `.venv/bin/python -m pytest tests/unit/test_agent_stream.py -q`，期望所有收集器测试通过。

## T4: 实现工具安全分批和预检

**影响文件：** `artcode/agent/tools.py`、`tests/unit/test_agent_tools.py`

**依赖任务：** T1

**参考资料定位：** `spec.md` F5-F10、F21、AC4-AC7、AC12；`plan.md` 的 `ToolSafety`、`ToolExecutionPlan`、`ToolBatchExecutor`

**步骤：**

1. 定义 `ToolSafety`、`ToolExecutionBatch`、`ToolExecutionPlan`、`PreparedToolExecution`。
2. 实现工具名安全分类，`run_command` 始终归为有副作用。
3. 实现按原始顺序扫描并分批：相邻只读合并，有副作用单独成批。
4. 检查未知工具：同一轮出现未知工具时不生成执行计划。
5. 检查当前模式不允许的工具：Plan Mode 请求写、改、命令时不生成执行计划。
6. 解析 JSON 参数；非法 JSON 对已知工具生成结构化失败结果。
7. 调用工具 `prepare`；预检失败生成结构化失败结果。
8. 补充分批、未知工具、Plan Mode 禁止工具、参数错误、预检失败测试。

**验证：** 运行 `.venv/bin/python -m pytest tests/unit/test_agent_tools.py -q`，期望分批和预检测试通过。

## T5: 实现工具批次执行

**影响文件：** `artcode/agent/tools.py`、`tests/unit/test_agent_tools.py`

**依赖任务：** T4

**参考资料定位：** `spec.md` F6、F9、F11-F12、AC4-AC11；`plan.md` 的 `ToolBatchExecutor.execute_plan`

**步骤：**

1. 实现只读批次使用 `asyncio.gather` 并发执行。
2. 实现有副作用批次串行执行。
3. Agent Loop 场景中不调用 TUI 确认，也不返回 `user_denied`。
4. 同一只读批次即使实际完成顺序不同，也按原始工具顺序产出结果。
5. 已知工具执行失败时产出 `TOOL_RESULT`，不抛出到主循环。
6. 对每个批次产出 `TOOL_BATCH_STARTED` 事件。
7. 补充只读并发、有副作用串行、结果顺序、失败继续事件测试。

**验证：** 运行 `.venv/bin/python -m pytest tests/unit/test_agent_tools.py -q`，期望执行器测试通过。

## T6: 实现 AgentLoop 自然完成和多轮循环

**影响文件：** `artcode/agent/loop.py`、`tests/unit/test_agent_loop.py`

**依赖任务：** T1、T3、T5

**参考资料定位：** `spec.md` F1-F4、F16-F18、AC1、AC20-AC22；`plan.md` 的 `AgentLoop`

**步骤：**

1. 定义 `AgentRunRequest` 和 `AgentRunResult`。
2. 实现 `AgentLoop.run` 异步事件流骨架。
3. 根据请求写入 user 消息。
4. 每轮按当前模式过滤工具列表并调用 `StreamCollector`。
5. 模型不请求工具时写入 assistant 消息并自然停止。
6. 模型请求工具时写入 assistant tool_call 消息，不把同轮过程文本写入 assistant 消息。
7. 写入每个 tool result 后进入下一轮。
8. 补充普通自然完成、工具后继续下一轮、文本加工具不污染上下文测试。

**验证：** 运行 `.venv/bin/python -m pytest tests/unit/test_agent_loop.py -q`，期望自然完成和多轮循环测试通过。

## T7: 实现 AgentLoop 停止条件和异常总结

**影响文件：** `artcode/agent/loop.py`、`tests/unit/test_agent_loop.py`

**依赖任务：** T6

**参考资料定位：** `spec.md` F3、F10、F13-F14、F27-F28、AC2-AC3、AC12-AC16、AC31；`plan.md` 的异常最终总结、取消传播、流式错误

**步骤：**

1. 实现 12 轮迭代上限停止。
2. 达到迭代上限时发出 `STOPPED(iteration_limit)`。
3. 迭代上限后发起一次 `tools=None` 的无工具最终总结。
4. 未知工具或模式不允许工具时，本轮所有工具不执行。
5. 未知工具停止后写入结构化 tool result，并尝试无工具最终总结。
6. 用户取消时不写入半截文本、不启动新工具、不请求最终总结。
7. 流式错误时不写入半截文本、不请求最终总结。
8. 最终总结本身失败时不递归总结。
9. 补充迭代上限、未知工具、取消、流式错误、最终总结工具列表为空测试。

**验证：** 运行 `.venv/bin/python -m pytest tests/unit/test_agent_loop.py -q`，期望所有停止条件测试通过。

## T8: 扩展 Slash Command 解析

**影响文件：** `artcode/commands/base.py`、`artcode/commands/builtin.py`、`tests/unit/test_commands.py`

**依赖任务：** T1

**参考资料定位：** `spec.md` F21、F24、AC27-AC29；`plan.md` 的 Commands 层设计

**步骤：**

1. 给 `CommandResult` 增加 `argument` 字段。
2. 将命令解析改为第一段匹配命令名，剩余内容作为参数。
3. 保持多行 slash 输入不触发命令。
4. 注册 `/plan` 和 `/do`。
5. `/plan 任务描述` 返回计划 action 和任务描述。
6. `/plan` 无参数时返回帮助提示。
7. `/do` 和 `/do 附加说明` 返回执行 action 和附加说明。
8. 更新 `/help` 文本。
9. 补充 exit/help/plan/do/多行输入测试。

**验证：** 运行 `.venv/bin/python -m pytest tests/unit/test_commands.py -q`，期望命令测试通过。

## T9: 增加 TUI Agent 进度展示

**影响文件：** `artcode/tui/app.py`、`artcode/tui/render.py`、`tests/unit/test_render.py`、`tests/unit/test_tui_app.py`

**依赖任务：** T1

**参考资料定位：** `spec.md` F15、F20、AC3、AC17、AC32-AC33；`plan.md` 的 TUI 层设计

**步骤：**

1. 增加迭代进度展示方法。
2. 增加工具调用数量展示方法。
3. 增加工具批次开始展示方法。
4. 增加 Token 用量展示方法。
5. 增加 Agent 停止原因展示方法。
6. 确保展示内容是摘要，不直接打印完整工具输出。
7. 保留 ch03 工具预览和结果摘要方法以兼容测试。
8. 补充渲染和 TUI app 转发测试。

**验证：** 运行 `.venv/bin/python -m pytest tests/unit/test_render.py tests/unit/test_tui_app.py -q`，期望 TUI 展示测试通过。

## T10: 更新系统提示、章节状态和文档

**影响文件：** `artcode/prompts.py`、`artcode/config.py`、`README.md`、`tests/unit/test_config.py`、`tests/unit/test_context.py`

**依赖任务：** T1

**参考资料定位：** `spec.md` F1、F5、F12、F21、N5、AC8、AC23；`plan.md` 的 `artcode.prompts` 和文件组织

**步骤：**

1. 将章节名更新为 `ch04：动手实现 Agent Loop`。
2. 更新系统提示，说明普通输入默认进入 Agent Loop。
3. 更新系统提示，说明同一轮可以请求多个工具。
4. 更新系统提示，说明 Plan Mode 只允许读类工具。
5. 更新系统提示，说明 Agent Loop 中副作用工具会自动执行，模型必须谨慎。
6. 删除 ch03 “单轮最多一个工具调用”和“工具后必须最终回复”的限制描述。
7. 更新 README ch04 简介。
8. 更新配置和上下文测试。

**验证：** 运行 `.venv/bin/python -m pytest tests/unit/test_config.py tests/unit/test_context.py -q`，期望章节和提示测试通过。

## T11: 更新 Provider、工具流和旧 Runtime 测试预期

**影响文件：** `tests/unit/test_runtime.py`、`tests/integration/test_tool_flow.py`、相关已受影响测试文件

**依赖任务：** T2-T10

**参考资料定位：** `spec.md` F5、F12、AC8、AC30；`plan.md` 的 Runtime 角色变化和 ch03 单工具限制取消

**步骤：**

1. 将 ch03 单步 Runtime 测试迁移到 AgentLoop 或 Runtime 事件消费测试。
2. 删除“多个工具调用直接 too_many_tool_calls”的预期。
3. 更新多工具调用预期为按安全性分批执行。
4. 删除 Agent Loop 中用户拒绝确认的预期。
5. 保留允许目录、危险命令、工具结果结构化错误等 ch03 安全边界测试。
6. 更新 `test_tool_flow.py`，让 fake provider 走 ch04 Agent Loop。
7. 确保旧测试不再依赖 Runtime 私有单步方法。

**验证：** 运行 `.venv/bin/python -m pytest tests/unit/test_runtime.py tests/integration/test_tool_flow.py -q`，期望更新后的兼容测试通过。

## T12: 接入主流程

**影响文件：** `artcode/runtime/app.py`、`artcode/cli.py`、`artcode/agent/__init__.py`、`tests/unit/test_runtime.py`

**依赖任务：** T1-T11

**参考资料定位：** `spec.md` F1、F21-F28、AC27-AC32；`plan.md` 的 Runtime 接入接口和三条主流程

**步骤：**

1. 在 CLI 创建 `PlanMemory`。
2. 创建 `AgentLoop` 所需依赖并注入 Runtime。
3. Runtime 普通输入构造 `NORMAL_AGENT_MODE` 请求。
4. Runtime `/plan` 构造 `PLAN_MODE` 请求。
5. Runtime `/do` 读取最近计划，没有计划时展示提示。
6. Runtime `/do 附加说明` 将最近计划和附加说明组合为执行目标。
7. Runtime 消费 AgentEvent 并转发到 TUI。
8. 移除或停用 ch03 Runtime 单步工具编排路径。
9. 确保 `Ctrl+C` 取消当前 AgentLoop task。
10. 补充 Runtime 普通输入、`/plan`、`/do`、无计划 `/do`、事件转发测试。

**验证：** 运行 `.venv/bin/python -m pytest tests/unit/test_runtime.py tests/unit/test_commands.py tests/unit/test_render.py -q`，期望主流程接入测试通过。

## T13: 端到端验证

**影响文件：** `tests/integration/test_agent_loop_flow.py`、`tests/integration/test_deepseek_live.py`、`tests/integration/README.md`、`README.md`

**依赖任务：** T12

**参考资料定位：** `spec.md` AC35-AC37；`plan.md` 的集成测试文件组织

**步骤：**

1. 新建 fake provider 多轮 Agent Loop 集成测试。
2. 覆盖“读文件 → 写文件或改文件 → 继续验证 → 自然总结”的完整流程。
3. 覆盖“`/plan 任务描述` → 保存最近计划 → `/do` 执行最近计划”的完整流程。
4. 覆盖多个只读工具并发和结果顺序。
5. 覆盖未知工具整批不执行并异常总结。
6. 扩展真实 DeepSeek live 测试，验证至少一个真实流式 Agent Loop 路径。
7. 更新集成测试 README，说明真实 API 测试默认执行。
8. 运行全部单元测试、fake provider 集成测试、真实 DeepSeek 集成测试。

**验证：** 运行 `.venv/bin/python -m pytest tests/unit -q`、`.venv/bin/python -m pytest tests/integration -q`，期望本地 fake 集成和真实 DeepSeek 集成测试均通过；如果真实 API 返回服务端错误，记录实际错误并修复可控问题后重跑。

## 执行顺序

```text
T1
├─ T2 → T3
├─ T4 → T5
├─ T8
├─ T9
└─ T10

T3 + T5 → T6 → T7
T2-T10 → T11 → T12 → T13
```
