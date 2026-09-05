# ch05：System Prompt 设计 Spec

## 背景

ArtCode 在 ch04 已经具备 Agent Loop、Plan Mode、`/do`、多工具调用、流式事件和真实 Token 用量展示能力。当前系统提示仍主要是一段固定大字符串，工具描述也偏基础，动态运行约束和稳定全局规则没有清晰分层。

这会带来三个问题：第一，身份、行为、工具、安全、输出等规则混在一起，后续插入项目指令、Skill 或长期记忆时容易失控；第二，Plan Mode、环境信息等动态内容如果继续硬拼进系统提示，会破坏服务端 Prompt Cache 的稳定前缀；第三，模型对“优先使用专用工具”“编辑前先读”“Plan Mode 只读”等关键约定的遵守主要依赖零散提示，缺少系统化强化。

ch05 的目标是把 ArtCode 的 System Prompt 从“一段提示文本”升级为“稳定可拼装的 Prompt 工程体系”：固定规则按模块组装，动态规则通过每轮临时 system-reminder 注入，工具描述和系统规则双重强化，Provider 能解析并展示缓存命中数据，最终用真实 API 证明 Prompt Cache 命中过。

## 目标用户

- 正在学习 CLI Coding Agent Prompt 工程的新手开发者。
- 希望理解稳定 System Prompt、动态运行提醒、工具描述和 Prompt Cache 如何协同工作的项目作者。
- 希望 ArtCode 在本地学习场景中更稳定遵守任务模式、工具优先级和输出规范的用户。

## 本章目标

- 将稳定 System Prompt 拆成固定七模块，并按固定优先级稳定拼装。
- 预留可选模块机制，让未来项目指令、Skill、长期记忆能作为会话启动时确定的稳定扩展规则接入。
- 区分稳定内容和动态内容：稳定规则进入 System Prompt，动态模式和环境信息进入每轮临时 system-reminder。
- 在每轮模型请求前注入完整 system-reminder，并且不写入 Conversation Context。
- 在 system-reminder 中提供当前运行模式、工具边界、当前工作目录、允许访问目录和平台信息。
- 强化现有六个工具的描述，让模型更容易遵守专用工具优先、编辑前先读、只读模式不写入等规则。
- 解析 DeepSeek 和 OpenAI-compatible 常见缓存命中字段，并统一展示为内部缓存用量。
- 使用真实 API 执行 live cache 验证，必须观察到缓存命中 token 大于 0。
- 准备 5 个典型人工评估场景，辅助后续人工对比 Prompt 质量。

## 功能需求

- F1: ArtCode 提供稳定 System Prompt 组装能力，将全局指令拆为七个固定模块：身份、系统约束、任务模式、动作执行、工具使用、语气风格、文本输出。
- F2: 七个固定模块必须按固定优先级从前到后拼装，模块之间使用统一空行分隔，相同输入下输出逐字一致。
- F3: 固定 System Prompt 不包含当前任务、当前轮次、当前工作目录、允许访问目录、平台、日期时间或其他每轮变化的信息。
- F4: ArtCode 预留可选模块机制，允许会话启动时传入额外稳定模块，并将其排在七个固定模块之后。
- F5: 本章不接入真实项目指令文件、真实 Skill、长期记忆来源；可选模块只通过测试或调用方显式传入验证拼装能力。
- F6: 空的可选模块不会输出标题、空段落或多余分隔空白。
- F7: 可选模块变化时允许 System Prompt 缓存重新建立；未变化时必须保持逐字稳定。
- F8: ArtCode 支持每轮模型请求前临时注入 system-reminder。
- F9: system-reminder 使用 `role=user` 消息承载，并用 `<system-reminder>...</system-reminder>` 标签包裹。
- F10: system-reminder 只参与本次 API 请求，不写入 Conversation Context，不进入长期对话历史。
- F11: 每轮 system-reminder 都完整注入，不做首轮完整、后续精简或间隔重复策略。
- F12: system-reminder 至少包含当前运行模式、当前模式允许的工具、当前模式禁止的工具或边界说明。
- F13: system-reminder 至少包含当前工作目录、允许访问目录和当前平台。
- F14: 稳定 System Prompt 明确要求模型将 `<system-reminder>` 视为系统级补充约束，不得当作用户真实请求回复，也不得向用户解释标签本身。
- F15: Normal Mode、Plan Mode 和 Do Mode 每轮都能生成对应的 system-reminder。
- F16: Plan Mode 的 system-reminder 明确说明只能使用只读工具，不得请求写文件、改文件或执行命令。
- F17: API payload 组装时将稳定 System Prompt、真实对话消息、临时 system-reminder 和工具列表清晰分配到当前 OpenAI-compatible 请求结构中。
- F18: 当前 Provider 仍以 DeepSeek / OpenAI-compatible 可落地为主，不强行发送当前 Provider 未必接受的显式 `cache_control` 字段。
- F19: Prompt 组装和 payload 组装的内部概念不写死 DeepSeek，后续可由其他 Provider 映射到自己的系统提示、消息、工具或缓存控制格式。
- F20: 现有六个工具的 description 得到强化，包括读取文件、写文件、精确修改文件、执行命令、查找文件和搜索文本。
- F21: 工具 description 不改工具名称、不改参数结构、不改工具调用协议。
- F22: System Prompt 和工具 description 双重强调优先使用专用工具，不应在已有专用工具可完成时用 shell 命令替代。
- F23: System Prompt 和 `edit_file` description 双重强调编辑文件前必须先读取目标文件或相关上下文。
- F24: “编辑前先读”在本章只作为强提示规则，不做工具层硬拦截、软校验或历史读取状态追踪。
- F25: Provider usage 解析支持基础 token 用量：输入 token、输出 token 和总 token。
- F26: Provider usage 解析支持 DeepSeek 常见缓存字段，并统一为内部缓存命中 token 和缓存未命中 token。
- F27: Provider usage 解析支持 OpenAI 常见缓存字段，并统一为内部缓存命中 token；必要时可由输入 token 和命中 token 推出未命中 token。
- F28: 当 Provider 未返回缓存字段时，普通请求不报错；但 live cache 验证场景必须要求真实缓存命中。
- F29: TUI 或事件流能够展示缓存命中 token 和缓存未命中 token。
- F30: 本章提供真实 API live cache 验证场景，必须执行真实请求并观察到缓存命中 token 大于 0。
- F31: ch05 验收要求本地存在可用真实 API 配置；没有 API key、网络不可用或真实缓存未命中时，ch05 验收不能完整通过。
- F32: 本章提供人工评估 Markdown 清单，包含 5 个可复制输入场景和对应观察点。
- F33: 5 个人工评估场景覆盖：优先使用专用工具、编辑前先读、Plan Mode 只读、工具失败后调整、最终输出风格。

## 非功能需求

- N1: System Prompt 组装逻辑应独立于 Provider、Runtime 和 TUI，避免把 Prompt 文本继续散落在多个模块中。
- N2: Prompt 模块排序必须可预测，不能依赖字典遍历、文件系统顺序或其他不稳定来源。
- N3: 相同固定模块和相同可选模块输入下，组装结果必须逐字稳定，以保护 Prompt Cache 前缀。
- N4: 动态运行信息不得进入稳定 System Prompt；当前工作目录、允许访问目录和平台信息都通过临时 system-reminder 注入。
- N5: system-reminder 注入不得污染 Conversation Context，避免对话历史、后续记忆和未来上下文压缩被临时指令堆满。
- N6: OpenAI-compatible payload 必须保持当前真实 Provider 可接受，不为缓存目标发送不兼容字段。
- N7: 缓存 usage 解析应兼容字段缺失；常规 Agent Loop 不因为 Provider 未返回缓存命中字段而失败。
- N8: live cache 验证属于 ch05 的硬验收，必须在真实 API 配置可用时证明命中过。
- N9: 工具 description 强化不改变工具行为、安全边界、参数 schema 或既有调用兼容性。
- N10: 本章不新增硬权限策略；允许目录限制、危险命令拦截、命令超时等仍由现有工具安全层负责。
- N11: 单元测试应覆盖 Prompt 组装稳定性、可选模块顺序、system-reminder 注入、不污染 Conversation Context、工具描述强化、缓存 usage 解析和 payload 形状。
- N12: 集成测试应覆盖真实 Agent Loop 携带 system-reminder、Plan Mode 工具边界、真实 API 缓存命中和人工评估文档存在性。

## 不做的事

- 不做项目指令文件加载；本章不读取 `ARTCODE.md`、`MEWCODE.md` 或类似项目说明文件。
- 不做自动记忆系统；本章不保存、不检索、不注入长期记忆。
- 不做真实 Skill 系统接入；本章只预留可选模块机制。
- 不做真实 MCP Server 接入。
- 不做 LLM-as-judge 自动评估管线。
- 不做自动化 Prompt 质量评分。
- 不做显式 `cache_control` Provider 适配。
- 不做 Anthropic、Gemini 或其他非 OpenAI-compatible Provider 协议接入。
- 不做运行中动态刷新可选模块；可选模块视为会话启动时确定的稳定扩展规则。
- 不把 current_date、timezone、当前轮次、当前任务摘要或工具执行摘要放进 System Prompt。
- 不做“编辑前先读”的工具层硬拦截。
- 不改工具名称。
- 不改工具参数结构。
- 不改 Agent Loop 的 12 轮上限。
- 不做上下文压缩。
- 不做跨会话对话持久化。

## 验收标准

- AC1: ArtCode 能生成标题为“ch05：System Prompt 设计”的稳定 System Prompt。
- AC2: 生成的 System Prompt 包含且只包含七个固定模块标题：身份、系统约束、任务模式、动作执行、工具使用、语气风格、文本输出。
- AC3: 七个固定模块按指定顺序出现。
- AC4: 相同输入下连续生成两次 System Prompt，文本逐字一致。
- AC5: System Prompt 模块之间只有统一的空行分隔，不出现随机多余空白。
- AC6: System Prompt 不包含当前工作目录、允许访问目录、平台、日期时间、当前轮次或用户任务文本。
- AC7: 传入一个非空可选模块时，该模块出现在七个固定模块之后。
- AC8: 传入多个可选模块时，顺序由优先级和稳定 tie-breaker 决定。
- AC9: 空可选模块不会在 System Prompt 中留下标题或空段落。
- AC10: Conversation Context 初始化后，第一条消息是稳定 System Prompt。
- AC11: 每轮 API 请求前都会临时追加一条 `role=user` 的 system-reminder。
- AC12: system-reminder 内容被 `<system-reminder>` 和 `</system-reminder>` 包裹。
- AC13: system-reminder 包含当前运行模式。
- AC14: system-reminder 包含当前模式允许的工具和禁止边界。
- AC15: system-reminder 包含当前工作目录。
- AC16: system-reminder 包含允许访问目录。
- AC17: system-reminder 包含当前平台。
- AC18: system-reminder 明确说明不要把本提醒当作用户请求回复。
- AC19: system-reminder 出现在本次请求 messages 的末尾。
- AC20: 模型请求结束后，Conversation Context 中不存在 system-reminder 消息。
- AC21: Plan Mode 请求的工具列表仍只包含只读工具。
- AC22: Plan Mode 的 system-reminder 明确禁止写文件、改文件和执行命令。
- AC23: Do Mode 和 Normal Mode 也会注入对应模式的 system-reminder。
- AC24: API payload 仍符合当前 OpenAI-compatible Provider 可接受的结构。
- AC25: 默认 payload 不包含未适配 Provider 的显式 `cache_control` 字段。
- AC26: `read_file`、`write_file`、`edit_file`、`run_command`、`find_files`、`search_text` 六个工具的 description 均包含更明确的用途说明。
- AC27: 工具 description 强化后，六个工具的名称保持不变。
- AC28: 工具 description 强化后，六个工具的参数 schema 保持兼容。
- AC29: `edit_file` description 明确要求编辑前先读取目标文件或相关上下文。
- AC30: `run_command` description 明确说明已有专用工具能完成时优先使用专用工具。
- AC31: Provider 能解析 DeepSeek usage 中的缓存命中字段，并映射为内部缓存命中 token。
- AC32: Provider 能解析 DeepSeek usage 中的缓存未命中字段，并映射为内部缓存未命中 token。
- AC33: Provider 能解析 OpenAI usage 中的 cached tokens 字段，并映射为内部缓存命中 token。
- AC34: 当 OpenAI usage 提供输入 token 和 cached tokens 时，系统能得到缓存未命中 token。
- AC35: Provider 未返回缓存字段时，普通 Agent Loop 正常继续。
- AC36: TUI 或事件流能展示缓存命中 token 和缓存未命中 token。
- AC37: live cache 验证使用真实 API 配置发起请求。
- AC38: live cache 验证断言真实返回的缓存命中 token 大于 0。
- AC39: 没有真实 API 配置时，ch05 验收不能标记为完整通过。
- AC40: 人工评估 Markdown 清单存在，并包含 5 个典型场景。
- AC41: 人工评估场景 1 能观察模型是否优先使用专用工具。
- AC42: 人工评估场景 2 能观察模型是否编辑前先读。
- AC43: 人工评估场景 3 能观察模型是否在 Plan Mode 中保持只读。
- AC44: 人工评估场景 4 能观察模型是否根据结构化工具错误调整。
- AC45: 人工评估场景 5 能观察最终回复是否说明完成内容、验证结果和剩余风险。
- AC46: 单元测试覆盖 Prompt 组装、可选模块、system-reminder、payload 组装、工具 description 和 usage 解析。
- AC47: 集成测试覆盖至少一个真实 Agent Loop 请求中 system-reminder 的注入行为。
- AC48: 集成测试覆盖真实 API cache hit 大于 0。
