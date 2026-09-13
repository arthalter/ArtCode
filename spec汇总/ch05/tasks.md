# ch05：System Prompt 设计 Tasks

## 文件清单

| 操作 | 文件 | 职责 |
|---|---|---|
| 新建 | `artcode/prompting/__init__.py` | 导出 Prompt 组装公共入口 |
| 新建 | `artcode/prompting/sections.py` | `PromptSection`、七个固定模块、默认模块集合 |
| 新建 | `artcode/prompting/builder.py` | `PromptBuilder` 和稳定 System Prompt 拼装 |
| 新建 | `artcode/prompting/reminder.py` | `ReminderContext`、运行环境收集、system-reminder 渲染 |
| 新建 | `artcode/prompting/assembler.py` | 每轮 Provider 请求的 messages/tools 组装 |
| 修改 | `artcode/prompts.py` | 保持 `SYSTEM_PROMPT` 兼容入口，改为由 PromptBuilder 生成 |
| 修改 | `artcode/conversation/context.py` | 继续用稳定 System Prompt 初始化第一条 system 消息 |
| 修改 | `artcode/agent/loop.py` | 接入请求组装器，临时注入 system-reminder |
| 修改 | `artcode/agent/events.py` | Agent `TokenUsage` 增加缓存字段 |
| 修改 | `artcode/agent/stream.py` | 透传 Provider 缓存 usage |
| 修改 | `artcode/providers/events.py` | Provider `token_usage_event` 增加缓存字段 |
| 修改 | `artcode/providers/openai_compatible.py` | 解析 DeepSeek / OpenAI 缓存 usage 字段 |
| 修改 | `artcode/runtime/app.py` | 将缓存 usage 传给 TUI |
| 修改 | `artcode/tui/app.py` | TUI 协议增加缓存 usage 参数 |
| 修改 | `artcode/tui/render.py` | 展示缓存命中和未命中 token |
| 修改 | `artcode/tools/file_tools.py` | 强化文件类工具 description |
| 修改 | `artcode/tools/command_tool.py` | 强化 `run_command` description |
| 修改 | `artcode/config.py` | 章节名更新为 ch05 |
| 修改 | `README.md` | 更新 ch05 System Prompt 设计简介 |
| 修改 | `tests/integration/README.md` | 说明 ch05 真实 cache hit 测试要求 |
| 新建 | `tests/unit/test_prompt_sections.py` | 覆盖固定七模块和默认 prompt |
| 新建 | `tests/unit/test_prompt_builder.py` | 覆盖排序、空模块、稳定输出 |
| 新建 | `tests/unit/test_system_reminder.py` | 覆盖 reminder 内容和消息形态 |
| 新建 | `tests/unit/test_prompt_assembler.py` | 覆盖临时注入、不污染历史、工具过滤 |
| 修改 | `tests/unit/test_context.py` | 覆盖默认 system prompt 更新 |
| 修改 | `tests/unit/test_provider_events.py` | 覆盖缓存 usage 事件校验 |
| 修改 | `tests/unit/test_openai_provider.py` | 覆盖 DeepSeek / OpenAI 缓存 usage 解析 |
| 修改 | `tests/unit/test_agent_events.py` | 覆盖 Agent TokenUsage 缓存字段 |
| 修改 | `tests/unit/test_agent_stream.py` | 覆盖缓存 usage 透传 |
| 修改 | `tests/unit/test_runtime.py` | 覆盖 Runtime 传递缓存 usage |
| 修改 | `tests/unit/test_render.py` | 覆盖 TUI 缓存 usage 展示 |
| 修改 | `tests/unit/test_tool_registry.py` | 覆盖工具 description 和导出顺序稳定 |
| 修改 | `tests/unit/test_config.py` | 覆盖 ch05 章节名 |
| 修改 | `tests/integration/test_agent_loop_flow.py` | 覆盖真实 Agent Loop 请求中 system-reminder 注入 |
| 新建 | `tests/integration/test_prompt_cache_live.py` | 真实 API cache hit 大于 0 验证 |
| 新建 | `spec汇总/ch05/prompt_eval.md` | 5 个人工 Prompt 质量评估场景 |

## T1: 建立 Prompting 包和固定七模块

**影响文件：** `artcode/prompting/__init__.py`、`artcode/prompting/sections.py`、`tests/unit/test_prompt_sections.py`

**依赖任务：** 无

**参考资料定位：** `spec.md` F1-F3、AC1-AC3、AC6；`plan.md` 的 `PromptSection`、`artcode.prompting.sections`

**步骤：**

1. 新建 `artcode.prompting` 包。
2. 定义 `PromptSection`，包含 `id`、`title`、`priority`、`content`。
3. 定义七个固定模块：身份、系统约束、任务模式、动作执行、工具使用、语气风格、文本输出。
4. 给七个固定模块设置固定 priority：100、200、300、400、500、600、700。
5. 在固定模块正文中写入 ch05 稳定规则，并明确 `<system-reminder>` 是系统级补充约束。
6. 确保固定模块正文不包含 cwd、allowed_dirs、platform、日期时间、当前轮次或用户任务。
7. 补充固定模块数量、标题、顺序和动态信息排除测试。

**验证：** 运行 `.venv/bin/python -m pytest tests/unit/test_prompt_sections.py -q`，期望固定七模块测试全部通过。

## T2: 实现 PromptBuilder 和可选模块机制

**影响文件：** `artcode/prompting/builder.py`、`artcode/prompting/__init__.py`、`tests/unit/test_prompt_builder.py`

**依赖任务：** T1

**参考资料定位：** `spec.md` F2、F4-F7、AC4-AC9；`plan.md` 的 `PromptBuilder`

**步骤：**

1. 实现 `PromptBuilder.build`。
2. 过滤正文为空或只含空白的模块。
3. 按 `(priority, id)` 稳定排序。
4. 将每个模块渲染为固定格式：标题、空行、正文。
5. 统一模块间空行和首尾空白策略。
6. 提供 `build_system_prompt(optional_sections=())` 便捷入口。
7. 补充相同输入逐字一致、可选模块排在固定模块后、空模块跳过、priority 相同时按 id 稳定排序测试。

**验证：** 运行 `.venv/bin/python -m pytest tests/unit/test_prompt_builder.py -q`，期望拼装稳定性测试全部通过。

## T3: 迁移默认 SYSTEM_PROMPT 入口

**影响文件：** `artcode/prompts.py`、`artcode/conversation/context.py`、`tests/unit/test_context.py`、`tests/unit/test_prompt_sections.py`

**依赖任务：** T1、T2

**参考资料定位：** `spec.md` F1-F3、AC1-AC6、AC10；`plan.md` 的 `artcode.prompts`

**步骤：**

1. 将 `artcode.prompts.SYSTEM_PROMPT` 改为由 `build_system_prompt()` 生成。
2. 保持 `ConversationContext(system_prompt=SYSTEM_PROMPT)` 的旧用法不变。
3. 更新上下文测试，断言第一条消息是 ch05 稳定 System Prompt。
4. 测试 System Prompt 包含七个固定模块标题。
5. 测试 System Prompt 不包含动态环境信息。

**验证：** 运行 `.venv/bin/python -m pytest tests/unit/test_context.py tests/unit/test_prompt_sections.py -q`，期望上下文和 prompt 测试通过。

## T4: 实现 system-reminder 生成

**影响文件：** `artcode/prompting/reminder.py`、`tests/unit/test_system_reminder.py`

**依赖任务：** T1

**参考资料定位：** `spec.md` F8-F16、AC11-AC18、AC22-AC23；`plan.md` 的 `ReminderContext`、`SystemReminderBuilder`

**步骤：**

1. 定义 `ReminderContext`。
2. 实现运行环境收集：当前模式、模式说明、允许工具、禁止工具、cwd、allowed_dirs、platform。
3. cwd 优先取 `ToolExecutionContext.default_cwd`，缺省时取 `Path.cwd()`。
4. allowed_dirs 取 `ToolExecutionContext.path_policy.allowed_roots`。
5. platform 使用 Python 标准库获取系统和架构信息。
6. 实现 `SystemReminderBuilder.build_message`，输出 `role=user` 消息。
7. 用 `<system-reminder>` 标签包裹 reminder 正文。
8. 在正文中包含“不要把本提醒当作用户请求回复”的说明。
9. 补充 Normal / Plan / Do Mode 的 reminder 内容测试，特别断言 Plan Mode 明确禁止写、改、命令。

**验证：** 运行 `.venv/bin/python -m pytest tests/unit/test_system_reminder.py -q`，期望 reminder 测试全部通过。

## T5: 实现 PromptRequestAssembler

**影响文件：** `artcode/prompting/assembler.py`、`tests/unit/test_prompt_assembler.py`

**依赖任务：** T4

**参考资料定位：** `spec.md` F10、F15-F19、AC19-AC25；`plan.md` 的 `PromptRequestAssembler`

**步骤：**

1. 定义 `PromptRequest`。
2. 实现 `PromptRequestAssembler.assemble`。
3. 复制 Conversation Context 导出的 messages，不原地修改。
4. 正常模式下按 `AgentMode.tool_policy` 过滤工具。
5. 正常模式下在 messages 末尾追加临时 system-reminder。
6. 支持 `tools=None` 的无工具请求。
7. 默认不添加显式 `cache_control` 字段。
8. 补充 messages 末尾注入、原始历史不变、Plan Mode 工具过滤、无工具请求测试。

**验证：** 运行 `.venv/bin/python -m pytest tests/unit/test_prompt_assembler.py -q`，期望请求组装测试全部通过。

## T6: 强化现有六个工具描述

**影响文件：** `artcode/tools/file_tools.py`、`artcode/tools/command_tool.py`、`tests/unit/test_tool_registry.py`

**依赖任务：** 无

**参考资料定位：** `spec.md` F20-F24、AC26-AC30；`plan.md` 的工具描述强化设计

**步骤：**

1. 强化 `read_file` description，说明用于读取文件内容和编辑前获取上下文。
2. 强化 `write_file` description，说明用于创建或覆盖完整文件，覆盖需谨慎。
3. 强化 `edit_file` description，说明精确替换、编辑前必须先读、`old_text` 必须来自实际文件内容。
4. 强化 `run_command` description，说明已有专用工具能完成时优先专用工具，命令有副作用且需谨慎。
5. 强化 `find_files` description，说明用于定位文件，优先于 shell `find`。
6. 强化 `search_text` description，说明用于文本搜索，优先于 shell `grep`。
7. 保持工具名称、参数 schema、执行逻辑不变。
8. 补充工具 description 包含关键规则、工具名称不变、参数 schema 兼容、导出顺序稳定测试。

**验证：** 运行 `.venv/bin/python -m pytest tests/unit/test_tool_registry.py -q`，期望工具导出测试通过。

## T7: 扩展 Provider 和 Agent 缓存 Token Usage

**影响文件：** `artcode/providers/events.py`、`artcode/providers/openai_compatible.py`、`artcode/agent/events.py`、`artcode/agent/stream.py`、`tests/unit/test_provider_events.py`、`tests/unit/test_openai_provider.py`、`tests/unit/test_agent_events.py`、`tests/unit/test_agent_stream.py`

**依赖任务：** 无

**参考资料定位：** `spec.md` F25-F29、AC31-AC35；`plan.md` 的 `TokenUsage` 和 Token Usage 流转

**步骤：**

1. 给 Provider `token_usage_event` 增加 `cached_tokens` 和 `cache_miss_tokens`。
2. 给 Provider 事件校验补充缓存字段类型检查。
3. 给 Agent `TokenUsage` 增加缓存字段。
4. 更新 `TokenUsage.from_event_payload` 和 `to_payload`。
5. 更新 `StreamCollector`，透传缓存字段。
6. 在 OpenAI-compatible SSE usage 解析中识别 DeepSeek `prompt_cache_hit_tokens` 和 `prompt_cache_miss_tokens`。
7. 在 OpenAI-compatible SSE usage 解析中识别 OpenAI `prompt_tokens_details.cached_tokens`。
8. 对 OpenAI cached tokens 场景，在可用时计算 `cache_miss_tokens`。
9. 缓存字段缺失时保持 `None`，普通 Agent Loop 不失败。
10. 补充 DeepSeek usage、OpenAI usage、缺失缓存字段、字段类型校验测试。

**验证：** 运行 `.venv/bin/python -m pytest tests/unit/test_provider_events.py tests/unit/test_openai_provider.py tests/unit/test_agent_events.py tests/unit/test_agent_stream.py -q`，期望 usage 相关测试通过。

## T8: 扩展 TUI 和 Runtime 缓存用量展示

**影响文件：** `artcode/tui/app.py`、`artcode/tui/render.py`、`artcode/runtime/app.py`、`tests/unit/test_render.py`、`tests/unit/test_runtime.py`

**依赖任务：** T7

**参考资料定位：** `spec.md` F29、AC36；`plan.md` 的 TUI / Runtime 设计

**步骤：**

1. 扩展 TUI 协议 `show_token_usage` 参数，增加 `cached_tokens` 和 `cache_miss_tokens`。
2. 更新 `TerminalTuiApp.show_token_usage`。
3. 更新 renderer 展示逻辑；缓存字段存在时显示 cached 和 miss。
4. 更新 Runtime 消费 `TOKEN_USAGE` 事件的逻辑，传递缓存字段。
5. 更新相关 fake TUI 测试对象。
6. 补充只有基础 usage、包含缓存 usage 两类展示测试。

**验证：** 运行 `.venv/bin/python -m pytest tests/unit/test_render.py tests/unit/test_runtime.py -q`，期望 Runtime 和 TUI 测试通过。

## T9: 建立真实 Prompt Cache 验证测试

**影响文件：** `tests/integration/test_prompt_cache_live.py`、`tests/integration/README.md`

**依赖任务：** T1、T2、T7

**参考资料定位：** `spec.md` F30-F31、AC37-AC39、AC48；`plan.md` 的 live cache 风险与缓解

**步骤：**

1. 新建真实 API cache hit 集成测试。
2. 使用真实配置构造稳定且足够长的 System Prompt 前缀。
3. 连续发起至少两次真实 OpenAI-compatible 流式请求。
4. 收集并解析每次返回的 Token Usage。
5. 断言至少一次请求的 `cached_tokens > 0`。
6. 如果没有 API 配置、认证失败、网络不可用或缓存命中为 0，测试失败并输出可读诊断。
7. 更新集成测试 README，说明 ch05 要求真实 API 配置和 cache hit 硬验收。

**验证：** 运行 `.venv/bin/python -m pytest tests/integration/test_prompt_cache_live.py -q`，期望真实 API cache hit 测试通过。

## T10: 编写人工 Prompt 评估清单和文档更新

**影响文件：** `spec汇总/ch05/prompt_eval.md`、`README.md`、`artcode/config.py`、`tests/unit/test_config.py`

**依赖任务：** T1、T6

**参考资料定位：** `spec.md` F32-F33、AC40-AC45；`plan.md` 的 `prompt_eval.md`

**步骤：**

1. 新建 `spec汇总/ch05/prompt_eval.md`。
2. 写入 5 个人工评估场景：专用工具优先、编辑前先读、Plan Mode 只读、工具失败后调整、最终输出风格。
3. 每个场景包含准备步骤、可复制输入、观察点、PASS / PARTIAL / FAIL 记录模板。
4. 更新 README，补充 ch05 System Prompt 设计简介。
5. 更新章节名为 `ch05：System Prompt 设计`。
6. 补充配置章节名测试。

**验证：** 运行 `.venv/bin/python -m pytest tests/unit/test_config.py -q`，并人工打开 `spec汇总/ch05/prompt_eval.md` 确认 5 个场景齐全。

## T11: 接入主流程

**影响文件：** `artcode/agent/loop.py`、`artcode/prompting/assembler.py`、`tests/unit/test_agent_loop.py`、`tests/unit/test_prompt_assembler.py`、`tests/integration/test_agent_loop_flow.py`

**依赖任务：** T3、T4、T5、T6、T7、T8

**参考资料定位：** `spec.md` F8-F19、AC19-AC25、AC47；`plan.md` 的每轮正常 Agent 请求、Plan Mode 请求、异常最终总结

**步骤：**

1. 在 Agent Loop 正常模型请求路径接入 `PromptRequestAssembler`。
2. 每轮正常请求前复制真实 Conversation Context，并临时追加 system-reminder。
3. 保证 system-reminder 出现在本次请求 messages 末尾。
4. 保证 system-reminder 不写入 Conversation Context。
5. 保持 Plan Mode 工具过滤行为。
6. 保持异常最终总结请求 `tools=None`，默认不注入模式 reminder。
7. 更新 fake provider 测试，记录收到的 messages 和 tools。
8. 补充 Normal / Plan / Do Mode 的 reminder 注入测试。
9. 补充 Plan Mode 只读工具列表和 reminder 禁止边界测试。
10. 补充异常最终总结无工具、无模式 reminder 测试。

**验证：** 运行 `.venv/bin/python -m pytest tests/unit/test_agent_loop.py tests/unit/test_prompt_assembler.py tests/integration/test_agent_loop_flow.py -q`，期望主流程接入测试通过。

## T12: 端到端验证

**影响文件：** `tests/unit/*`、`tests/integration/*`、`spec汇总/ch05/prompt_eval.md`

**依赖任务：** T1-T11

**参考资料定位：** `spec.md` AC1-AC48；`plan.md` 的模块交互、风险与缓解

**步骤：**

1. 运行 Prompt 相关单元测试。
2. 运行 Provider / Agent usage 相关单元测试。
3. 运行 Runtime / TUI / 工具描述相关单元测试。
4. 运行全部单元测试。
5. 运行全部集成测试，其中真实 cache hit 测试必须执行且通过。
6. 手动启动 ArtCode，观察普通输入请求中含有 system-reminder 且不写入 Conversation Context。
7. 手动执行 `/plan` 场景，观察工具列表只包含只读工具，reminder 明确禁止写、改、命令。
8. 按 `prompt_eval.md` 至少跑完 5 个人工场景并记录结果。
9. 若真实 API 未配置或 cache hit 为 0，标记 ch05 验收未完整通过。

**验证：**

- `.venv/bin/python -m pytest tests/unit -q`
- `.venv/bin/python -m pytest tests/integration -q`
- `.venv/bin/python -m pytest -q`
- 人工完成 `spec汇总/ch05/prompt_eval.md` 中 5 个场景记录。
