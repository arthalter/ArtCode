# ch05：System Prompt 设计 Checklist

> 每一项都必须能通过测试、启动程序、查看请求记录、查看文档或运行真实 API 观察到；未实现前保持未勾选。

## 稳定 System Prompt 七模块

- [x] 默认 System Prompt 标题和章节状态对应 `ch05：System Prompt 设计`（验证：运行 `tests/unit/test_config.py`，观察章节名断言通过）。
- [x] 默认 System Prompt 包含固定七个模块标题：身份、系统约束、任务模式、动作执行、工具使用、语气风格、文本输出（验证：运行 `tests/unit/test_prompt_sections.py`）。
- [x] 七个固定模块按“身份 → 系统约束 → 任务模式 → 动作执行 → 工具使用 → 语气风格 → 文本输出”顺序出现（验证：运行 `tests/unit/test_prompt_sections.py`）。
- [x] 七个固定模块 priority 分别为 100、200、300、400、500、600、700（验证：运行 `tests/unit/test_prompt_sections.py`）。
- [x] 相同输入下连续生成两次默认 System Prompt，文本逐字一致（验证：运行 `tests/unit/test_prompt_builder.py`）。
- [x] System Prompt 模块之间使用统一空行分隔，不出现随机多余空白（验证：运行 `tests/unit/test_prompt_builder.py`）。
- [x] 默认 System Prompt 不包含当前工作目录路径（验证：运行 `tests/unit/test_prompt_sections.py`，断言不包含测试 cwd）。
- [x] 默认 System Prompt 不包含 allowed_dirs 的实际路径（验证：运行 `tests/unit/test_prompt_sections.py`，断言不包含测试 allowed dir）。
- [x] 默认 System Prompt 不包含当前平台字符串（验证：运行 `tests/unit/test_prompt_sections.py`）。
- [x] 默认 System Prompt 不包含日期时间、当前轮次或用户任务文本（验证：运行 `tests/unit/test_prompt_sections.py`）。
- [x] System Prompt 明确说明 `<system-reminder>` 是系统级补充约束（验证：运行 `tests/unit/test_prompt_sections.py`，断言包含该规则）。
- [x] Conversation Context 初始化后第一条消息为 `role=system`，内容为默认稳定 System Prompt（验证：运行 `tests/unit/test_context.py`）。

## 可选模块机制

- [x] 传入一个非空可选模块时，该模块出现在固定七模块之后（验证：运行 `tests/unit/test_prompt_builder.py`）。
- [x] 传入多个可选模块时，顺序由 priority 升序决定（验证：运行 `tests/unit/test_prompt_builder.py`）。
- [x] 多个可选模块 priority 相同时，顺序由 id 稳定决定（验证：运行 `tests/unit/test_prompt_builder.py`）。
- [x] 正文为空字符串的可选模块不会输出标题（验证：运行 `tests/unit/test_prompt_builder.py`）。
- [x] 正文只含空白字符的可选模块不会输出标题（验证：运行 `tests/unit/test_prompt_builder.py`）。
- [x] 空可选模块不会留下多余空段落或多余分隔空白（验证：运行 `tests/unit/test_prompt_builder.py`）。
- [x] 本章默认启动路径不读取 `ARTCODE.md`、`MEWCODE.md`、Skill 文件或记忆文件（验证：运行相关单元测试，并观察项目根目录无这些读取入口）。
- [x] 默认 System Prompt 在没有可选模块时只输出固定七模块（验证：运行 `tests/unit/test_prompt_builder.py`）。

## System Reminder

- [x] 每轮正常模型请求前都会临时追加一条 system-reminder（验证：运行 `tests/unit/test_prompt_assembler.py tests/unit/test_agent_loop.py`）。
- [x] system-reminder 消息的 `role` 是 `user`（验证：运行 `tests/unit/test_system_reminder.py`）。
- [x] system-reminder 内容以 `<system-reminder>` 开头并以 `</system-reminder>` 结尾（验证：运行 `tests/unit/test_system_reminder.py`）。
- [x] system-reminder 包含当前运行模式名称（验证：运行 `tests/unit/test_system_reminder.py`）。
- [x] Normal Mode 的 system-reminder 说明当前为普通 Agent Loop 模式（验证：运行 `tests/unit/test_system_reminder.py`）。
- [x] Plan Mode 的 system-reminder 说明当前为只读规划模式（验证：运行 `tests/unit/test_system_reminder.py`）。
- [x] Do Mode 的 system-reminder 说明当前为执行最近计划模式（验证：运行 `tests/unit/test_system_reminder.py`）。
- [x] Plan Mode 的 system-reminder 只列出 `read_file`、`find_files`、`search_text` 为允许工具（验证：运行 `tests/unit/test_system_reminder.py`）。
- [x] Plan Mode 的 system-reminder 明确禁止 `write_file`、`edit_file`、`run_command`（验证：运行 `tests/unit/test_system_reminder.py`）。
- [x] Normal Mode 和 Do Mode 的 system-reminder 能列出全工具边界（验证：运行 `tests/unit/test_system_reminder.py`）。
- [x] system-reminder 包含当前工作目录 cwd（验证：运行 `tests/unit/test_system_reminder.py`，使用临时目录断言）。
- [x] system-reminder 包含所有 allowed_dirs（验证：运行 `tests/unit/test_system_reminder.py`）。
- [x] system-reminder 包含当前平台信息（验证：运行 `tests/unit/test_system_reminder.py`）。
- [x] system-reminder 明确说明不要把本提醒当作用户请求回复（验证：运行 `tests/unit/test_system_reminder.py`）。
- [x] 每轮 system-reminder 都完整包含模式、工具边界、cwd、allowed_dirs、platform（验证：运行 `tests/unit/test_agent_loop.py`，检查多轮 fake provider 收到的 messages）。

## Payload 组装与对话历史

- [x] PromptRequestAssembler 复制 Conversation Context 导出的 messages，不原地修改原列表（验证：运行 `tests/unit/test_prompt_assembler.py`）。
- [x] system-reminder 出现在本次请求 messages 的最后一条（验证：运行 `tests/unit/test_prompt_assembler.py`）。
- [x] 模型请求完成后，Conversation Context 中不存在 `<system-reminder>` 消息（验证：运行 `tests/unit/test_agent_loop.py`）。
- [x] 普通 Agent Loop 请求仍携带当前模式允许的 tools（验证：运行 `tests/unit/test_agent_loop.py`）。
- [x] Plan Mode 请求的 tools 只包含 `read_file`、`find_files`、`search_text`（验证：运行 `tests/unit/test_agent_loop.py`）。
- [x] `/do` 请求携带全工具列表（验证：运行 `tests/unit/test_runtime.py tests/unit/test_agent_loop.py`）。
- [x] 异常最终总结请求不携带 tools（验证：运行 `tests/unit/test_agent_loop.py`）。
- [x] 异常最终总结请求默认不追加模式 system-reminder（验证：运行 `tests/unit/test_agent_loop.py`）。
- [x] OpenAI-compatible payload 不包含显式 `cache_control` 字段（验证：运行 `tests/unit/test_openai_provider.py` 或 payload 构造测试）。
- [x] 当前 Provider 请求体仍包含 `model`、`messages`、`stream`，有工具时包含 `tools` 和 `tool_choice=auto`（验证：运行 `tests/unit/test_openai_provider.py`）。

## 工具描述强化

- [x] `read_file` description 明确说明用于读取文件内容和编辑前获取上下文（验证：运行 `tests/unit/test_tool_registry.py`）。
- [x] `write_file` description 明确说明用于创建或覆盖完整文件，覆盖需谨慎（验证：运行 `tests/unit/test_tool_registry.py`）。
- [x] `edit_file` description 明确说明编辑前必须先读取目标文件或相关上下文（验证：运行 `tests/unit/test_tool_registry.py`）。
- [x] `edit_file` description 明确说明 `old_text` 必须来自实际文件内容并唯一匹配（验证：运行 `tests/unit/test_tool_registry.py`）。
- [x] `run_command` description 明确说明已有专用工具可完成时优先使用专用工具（验证：运行 `tests/unit/test_tool_registry.py`）。
- [x] `run_command` description 明确说明命令有副作用且应谨慎使用（验证：运行 `tests/unit/test_tool_registry.py`）。
- [x] `find_files` description 明确说明用于定位文件，优先于 shell `find`（验证：运行 `tests/unit/test_tool_registry.py`）。
- [x] `search_text` description 明确说明用于文本搜索，优先于 shell `grep`（验证：运行 `tests/unit/test_tool_registry.py`）。
- [x] 六个工具名称保持为 `read_file`、`write_file`、`edit_file`、`run_command`、`find_files`、`search_text`（验证：运行 `tests/unit/test_tool_registry.py`）。
- [x] 六个工具参数 schema 与 ch04 保持兼容（验证：运行 `tests/unit/test_tool_registry.py`，对比关键 schema 字段）。
- [x] 工具导出顺序稳定（验证：运行 `tests/unit/test_tool_registry.py`）。
- [x] “编辑前先读”没有新增工具层硬拦截（验证：运行现有 `edit_file` 工具测试，确认未读历史状态不会被工具层检查）。

## 缓存 Token Usage 解析

- [x] Provider `token_usage_event` 支持 `prompt_tokens`、`completion_tokens`、`total_tokens`、`cached_tokens`、`cache_miss_tokens`（验证：运行 `tests/unit/test_provider_events.py`）。
- [x] Provider usage 校验拒绝非整数缓存字段（验证：运行 `tests/unit/test_provider_events.py`）。
- [x] Agent `TokenUsage` 支持缓存命中和未命中字段（验证：运行 `tests/unit/test_agent_events.py`）。
- [x] StreamCollector 能把 Provider 缓存 usage 转成 Agent `TOKEN_USAGE` 事件（验证：运行 `tests/unit/test_agent_stream.py`）。
- [x] DeepSeek `prompt_cache_hit_tokens` 能映射为内部 `cached_tokens`（验证：运行 `tests/unit/test_openai_provider.py`）。
- [x] DeepSeek `prompt_cache_miss_tokens` 能映射为内部 `cache_miss_tokens`（验证：运行 `tests/unit/test_openai_provider.py`）。
- [x] OpenAI `prompt_tokens_details.cached_tokens` 能映射为内部 `cached_tokens`（验证：运行 `tests/unit/test_openai_provider.py`）。
- [x] OpenAI usage 同时提供 `prompt_tokens` 和 `cached_tokens` 时，能得到 `cache_miss_tokens`（验证：运行 `tests/unit/test_openai_provider.py`）。
- [x] Provider 未返回缓存字段时，普通 Agent Loop 正常继续（验证：运行 `tests/unit/test_agent_stream.py tests/unit/test_agent_loop.py`）。
- [x] Provider 未返回缓存字段时，缓存字段保持为 `None` 而不是 0 或报错（验证：运行 `tests/unit/test_openai_provider.py`）。

## TUI 与 Runtime 展示

- [x] Runtime 收到 `TOKEN_USAGE` 事件后传递基础 token 和缓存 token 给 TUI（验证：运行 `tests/unit/test_runtime.py`）。
- [x] TUI renderer 在只有基础 usage 时仍显示 prompt/completion/total（验证：运行 `tests/unit/test_render.py`）。
- [x] TUI renderer 在有缓存 usage 时显示 cached tokens（验证：运行 `tests/unit/test_render.py`）。
- [x] TUI renderer 在有缓存 usage 时显示 cache miss tokens（验证：运行 `tests/unit/test_render.py`）。
- [x] FakeTui 测试对象全部适配新增缓存 usage 参数（验证：运行 `tests/unit/test_runtime.py tests/integration/test_agent_loop_flow.py`）。

## 真实 Prompt Cache 验证

- [x] 本地存在可用真实 API 配置（验证：检查测试配置，运行 live 集成测试不因缺少 key 跳过）。
- [x] live cache 测试会构造稳定且足够长的 prompt 前缀（验证：打开 `tests/integration/test_prompt_cache_live.py`）。
- [x] live cache 测试连续发起至少两次真实 API 请求（验证：打开测试代码并运行）。
- [x] live cache 测试解析真实 API 返回的 usage（验证：运行 `tests/integration/test_prompt_cache_live.py`）。
- [x] live cache 测试断言 `cached_tokens > 0` 或等价缓存命中值大于 0（验证：运行 `tests/integration/test_prompt_cache_live.py -q`）。
- [x] 没有 API key、网络不可用、认证失败或 cache hit 为 0 时，ch05 验收不能标记为完整通过（验证：查看测试失败信息和 checklist 状态）。
- [x] 集成测试 README 说明 ch05 真实 cache hit 是硬验收（验证：打开 `tests/integration/README.md`）。

## 人工 Prompt 评估

- [x] `spec汇总/ch05/prompt_eval.md` 文件存在（验证：打开该文件）。
- [x] 人工评估文档包含 5 个场景（验证：打开 `prompt_eval.md`）。
- [x] 场景 1 覆盖“优先使用专用工具，不用 shell 替代读写搜索”（验证：打开 `prompt_eval.md`）。
- [x] 场景 2 覆盖“编辑前先读文件或搜索上下文”（验证：打开 `prompt_eval.md`）。
- [x] 场景 3 覆盖“Plan Mode 只读，不请求写文件、改文件、命令”（验证：打开 `prompt_eval.md`）。
- [x] 场景 4 覆盖“工具失败后根据结构化错误调整”（验证：打开 `prompt_eval.md`）。
- [x] 场景 5 覆盖“最终输出说明完成内容、验证结果和剩余风险”（验证：打开 `prompt_eval.md`）。
- [x] 每个场景包含准备步骤（验证：打开 `prompt_eval.md`）。
- [x] 每个场景包含可复制输入（验证：打开 `prompt_eval.md`）。
- [x] 每个场景包含观察点（验证：打开 `prompt_eval.md`）。
- [x] 每个场景包含 PASS / PARTIAL / FAIL 记录模板（验证：打开 `prompt_eval.md`）。
- [x] 使用真实 ArtCode 跑完 5 个人工场景并记录结果（验证：查看 `prompt_eval.md` 记录区）。

## 主流程集成

- [x] 普通用户输入进入 Agent Loop 时，fake provider 收到的 messages 最后一条是 system-reminder（验证：运行 `tests/unit/test_agent_loop.py`）。
- [x] 多轮工具循环中，每一轮 provider 请求都重新临时追加完整 system-reminder（验证：运行 `tests/unit/test_agent_loop.py`）。
- [x] 同一轮模型既输出文本又请求工具时，system-reminder 不写入普通 assistant 消息（验证：运行 `tests/unit/test_agent_loop.py`）。
- [x] 工具结果写入 Conversation Context 后，下一轮请求仍在末尾追加新的 system-reminder（验证：运行 `tests/integration/test_agent_loop_flow.py`）。
- [x] `/plan` 生成计划后，PlanMemory 行为仍保持 ch04 语义（验证：运行 `tests/unit/test_agent_memory.py tests/unit/test_agent_loop.py`）。
- [x] `/do` 执行最近计划时，user 消息包装规则仍保持 ch04 语义（验证：运行 `tests/unit/test_runtime.py`）。
- [x] ch04 多工具分批、只读并发、有副作用串行行为不被 ch05 破坏（验证：运行 `tests/unit/test_agent_tools.py tests/integration/test_agent_loop_flow.py`）。
- [x] ch04 工具安全边界仍生效，包括允许目录限制、危险命令拦截、命令超时（验证：运行 `tests/unit/test_file_tools.py tests/unit/test_command_tool.py tests/unit/test_tool_policy.py`）。

## 编译与测试

- [x] Prompt 相关单元测试通过（验证：运行 `.venv/bin/python -m pytest tests/unit/test_prompt_sections.py tests/unit/test_prompt_builder.py tests/unit/test_system_reminder.py tests/unit/test_prompt_assembler.py -q`）。
- [x] Conversation Context 测试通过（验证：运行 `.venv/bin/python -m pytest tests/unit/test_context.py -q`）。
- [x] Provider / Agent usage 测试通过（验证：运行 `.venv/bin/python -m pytest tests/unit/test_provider_events.py tests/unit/test_openai_provider.py tests/unit/test_agent_events.py tests/unit/test_agent_stream.py -q`）。
- [x] Runtime / TUI 展示测试通过（验证：运行 `.venv/bin/python -m pytest tests/unit/test_runtime.py tests/unit/test_render.py -q`）。
- [x] 工具描述和工具安全测试通过（验证：运行 `.venv/bin/python -m pytest tests/unit/test_tool_registry.py tests/unit/test_file_tools.py tests/unit/test_command_tool.py tests/unit/test_tool_policy.py -q`）。
- [x] Agent Loop 主流程测试通过（验证：运行 `.venv/bin/python -m pytest tests/unit/test_agent_loop.py tests/integration/test_agent_loop_flow.py -q`）。
- [x] 真实 Prompt Cache 集成测试通过且 cache hit 大于 0（验证：运行 `.venv/bin/python -m pytest tests/integration/test_prompt_cache_live.py -q`）。
- [x] 全部单元测试通过（验证：运行 `.venv/bin/python -m pytest tests/unit -q`）。
- [x] 全部集成测试通过，包含真实 API 测试（验证：运行 `.venv/bin/python -m pytest tests/integration -q`）。
- [x] 默认测试套件通过（验证：运行 `.venv/bin/python -m pytest -q`）。

## 端到端场景

- [x] 场景 1：普通输入 → 请求中包含稳定 System Prompt 和临时 system-reminder → 模型自然回复 → Conversation Context 不包含 system-reminder（验证：运行 fake provider 端到端测试）。
- [x] 场景 2：普通输入需要读写文件 → 模型优先使用专用工具 → 编辑前先读 → 最终总结说明修改和验证（验证：运行集成测试或人工评估场景）。
- [x] 场景 3：`/plan 任务描述` → 每轮只携带只读工具 → reminder 禁止写、改、命令 → 最终保存最近计划（验证：运行 `tests/integration/test_agent_loop_flow.py`）。
- [x] 场景 4：连续真实 API 请求 → 第二次或后续请求返回缓存命中 token 大于 0（验证：运行 `tests/integration/test_prompt_cache_live.py`）。
- [x] 场景 5：工具返回结构化错误 → 模型不伪造结果，能解释错误或调整下一步（验证：运行人工评估场景 4）。
- [x] 场景 6：最终回复包含完成内容、验证结果、剩余风险（验证：运行人工评估场景 5）。
