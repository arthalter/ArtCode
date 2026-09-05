# 简历 ArtCode 项目逐词解析与代码、测试索引

> 适用简历：`简历v8.26.pdf` 中的 ArtCode 项目段落。  
> 拆分原则：按“最小有意义技术词组”拆解，不机械拆成单个汉字。  
> 本文只解释简历用词、实现位置、调用链和测试位置，不做代码审查，也不提出优化建议。

## 0. 先记住一句话

**ArtCode 是一个运行在终端里的本地 AI 编程助手：主循环让模型持续思考、调用工具、读取结果并继续行动；Plan/Do 分开规划与执行；MCP、Skill 和子 Agent 扩展能力；权限系统、路径约束与 macOS Seatbelt 控制执行边界；上下文压缩、会话和长期记忆负责长任务连续性。**

主调用链：

```text
python -m artcode / artcode
  → cli.main
  → Bootstrap.build
  → ArtCodeRuntime
  → AgentLoop.run
  → RequestPreparer.prepare
  → Provider.stream
  → ToolExecutionService.execute_plan
  → PermissionService.authorize
  → 工具执行
  → 工具结果写回 ConversationContext
  → 下一轮模型请求
```

入口代码：

- `artcode/__main__.py`
- `artcode/cli.py:20`
- `artcode/bootstrap.py:85`
- `artcode/runtime/app.py:406`
- `artcode/agent/loop.py:71`

入口测试：

- `tests/integration/test_main_entry_flow.py`
- `tests/integration/test_config_startup_flow.py:28`
- `tests/integration/test_runtime_flow.py`
- `tests/unit/test_agent_loop.py:172`

---

## 1. 项目名称逐词解析

简历原句：

> ArtCode——终端 AI 编程助手｜AI 应用开发工程师｜2026.06–2026.08

| 词语 | 在项目里的含义 | 对应代码 | 对应测试 |
|---|---|---|---|
| `Art` | 项目品牌名的一部分，可以理解为“把编程助手做成一套有方法、有边界的工程能力”。它不是单独的运行模块。 | `pyproject.toml:6` | `tests/integration/test_main_entry_flow.py` |
| `Code` | 助手工作的主要对象是代码仓库：读取、搜索、写入、精确编辑和执行命令。 | `artcode/tools/registry.py:74`、`artcode/tools/file_tools.py:75`、`artcode/tools/command_tool.py:19` | `tests/unit/test_file_tools.py:31`、`tests/unit/test_command_tool.py` |
| `ArtCode` | Python 包名、命令名和应用名。安装后通过 `artcode` 命令启动。 | `pyproject.toml:6`、`pyproject.toml:27` | `tests/integration/test_main_entry_flow.py` |
| `终端` | 用户不需要浏览器页面，输入、流式输出、审批和快捷键都发生在 Terminal/TUI。 | `artcode/tui/app.py:29`、`artcode/tui/keybindings.py:6` | `tests/unit/test_tui_app.py:34`、`tests/unit/test_keybindings.py:8` |
| `AI` | 核心决策由兼容大模型接口的 Provider 完成，模型可返回文本、推理内容或工具调用。 | `artcode/providers/base.py:49`、`artcode/providers/events.py:48` | `tests/unit/test_provider_events.py:21`、`tests/integration/test_provider_flow.py:51` |
| `编程` | 工具集合围绕代码工程操作设计，而不是通用聊天：文件、搜索、Shell、Git Worktree。 | `artcode/tools/registry.py:74`、`artcode/worktrees/manager.py:21` | `tests/integration/test_workspace_file_flow.py`、`tests/unit/test_worktree_manager.py:26` |
| `助手` | 模型不是只回答一次，而是在 Agent Loop 内根据结果继续工作，直到自然完成、取消或异常停止。 | `artcode/agent/loop.py:71` | `tests/unit/test_agent_loop.py:197`、`tests/soak/test_unlimited_agent_loop.py:99` |
| `AI 应用开发工程师` | 职责覆盖模型接入、Agent 循环、工具协议、上下文、记忆、权限、测试和终端交互，而非只写 Prompt。 | `artcode/bootstrap.py:96` | `tests/integration/test_agent_request_flow.py`、`tests/integration/test_runtime_tool_metadata_flow.py` |

面试时可以把项目名解释成：

> ArtCode 是一个本地 Python CLI Coding Agent。它把大模型、工具执行、权限控制、上下文管理、长期记忆和多 Agent 协作组装成一条完整的代码任务执行链。

---

## 2. 项目介绍逐词解析

简历原句：

> 轻量级终端 AI 编程助手，以 ReAct 循环与 Plan Mode 双模式驱动 LLM 自主完成代码工程任务。

### 2.1 “轻量级”

含义：项目是本地单进程 CLI，生产依赖集中在 Python 包、HTTP 客户端、终端 UI、渲染和 MCP 客户端，没有额外的 Web 服务部署链。

- 依赖声明：`pyproject.toml:5-17`
- 组件集中装配：`artcode/bootstrap.py:96`
- 测试：`tests/integration/test_main_entry_flow.py`、`tests/soak/test_entrypoint_lifecycle.py:26`

### 2.2 “终端 AI 编程助手”

拆成四层理解：

1. **终端输入**：`PromptSession.prompt_async` 读取多行输入，Enter 发送，Ctrl+J 或 Esc+Enter 换行。  
   代码：`artcode/tui/app.py:34-48`、`artcode/tui/keybindings.py:6-20`  
   测试：`tests/unit/test_keybindings.py:8`、`tests/unit/test_tui_app.py:150`
2. **流式输出**：Provider 持续产生 `ContentDelta`，Runtime 将增量交给 TUI。  
   代码：`artcode/providers/events.py:48-93`、`artcode/runtime/app.py:485-507`  
   测试：`tests/unit/test_provider_events.py:21`、`tests/integration/test_provider_flow.py:51`
3. **代码工具**：读取、查找、搜索、写入、编辑、运行命令。  
   代码：`artcode/tools/registry.py:74-89`  
   测试：`tests/unit/test_file_tools.py:31`、`tests/integration/test_tool_batch_flow.py:123`
4. **Agent 控制**：模型决定下一步，系统校验并执行，再把结果送回模型。  
   代码：`artcode/agent/loop.py:94-183`  
   测试：`tests/unit/test_agent_loop.py:197`

### 2.3 “ReAct”

`ReAct = Reason + Act`，即“推理/判断下一步”与“采取行动”交替进行。

ArtCode 中没有一个只叫 `ReAct` 的类，它由下面的循环共同实现：

```text
模型流式生成
  → 收集 reasoning / text / tool_calls
  → 若没有 tool_calls：结束本轮
  → 若有 tool_calls：形成执行计划
  → 权限判断并执行工具
  → 将每个 tool result 追加回对话
  → iteration + 1，再请求模型
```

- 循环主体：`artcode/agent/loop.py:94-183`
- 推理、文本、工具调用事件：`artcode/providers/events.py:48-93`
- 流式工具参数拼接：`artcode/providers/tool_calls.py:22-75`
- 工具执行计划：`artcode/tools/execution.py:70-139`
- 工具结果回填：`artcode/agent/loop.py:168-178`
- 测试：`tests/unit/test_agent_loop.py:197`、`tests/unit/test_tool_calls.py:6`、`tests/integration/test_agent_request_flow.py:121`

### 2.4 “循环”

“循环”强调一次用户请求内部可以发生多轮模型调用。循环条件是：没有显式上限，或者当前迭代数没有超过 `max_iterations`。

- 代码：`artcode/agent/loop.py:94-97`
- 默认无限轮主链测试：`tests/soak/test_unlimited_agent_loop.py:99`
- 显式上限测试：`tests/integration/test_agent_request_flow.py:134`

### 2.5 “Plan Mode”

含义：先让模型分析仓库和形成计划，但只给它读类工具，不允许写文件或执行 Shell。

- 模式定义：`artcode/agent/modes.py:73-77`
- 工具过滤：`artcode/agent/modes.py:18-57`
- `/plan` 命令：`artcode/commands/builtin.py:154-161`
- 计划保存：`artcode/agent/loop.py:118-120`、`artcode/agent/memory.py:7-19`
- 测试：`tests/unit/test_agent_modes.py:30`、`tests/unit/test_commands.py:341`、`tests/unit/test_agent_loop.py:366`

### 2.6 “双模式”

这里指 **Plan / Do** 两个阶段：

| 模式 | 作用 | 工具能力 | 代码 | 测试 |
|---|---|---|---|---|
| Plan | 阅读项目并生成计划 | 只读效果工具 | `artcode/agent/modes.py:73` | `tests/unit/test_agent_modes.py:30` |
| Do | 取出最近计划并执行 | 全工具，但仍经过权限系统 | `artcode/agent/modes.py:79`、`artcode/commands/builtin.py:164` | `tests/unit/test_commands.py:367` |

### 2.7 “驱动 LLM”

含义：Agent Loop 负责构造请求、调用统一 Provider 接口、接收事件并决定是否进入下一轮。

- 请求对象：`artcode/providers/base.py:10-46`
- Provider 协议：`artcode/providers/base.py:49-51`
- 请求准备：`artcode/agent/request.py:125-186`
- 发起模型流：`artcode/agent/loop.py:344-370`
- 测试：`tests/unit/test_openai_provider.py:138`、`tests/integration/test_provider_flow.py:51`

### 2.8 “自主完成”

“自主”不是绕过权限，而是模型可以在允许的工具和模式边界内自行选择下一步，并通过多轮调用推进任务。

- 模型工具选择：`artcode/providers/deepseek.py:151-175`
- 模式边界：`artcode/agent/modes.py:9-57`
- 权限入口：`artcode/tools/execution.py:175-205`
- 测试：`tests/unit/test_agent_loop.py:197`、`tests/integration/test_tool_batch_flow.py:176`

### 2.9 “代码工程任务”

不是只生成代码文本，而是包含仓库阅读、文本检索、文件修改、命令执行、测试和 Git 隔离协作。

- 文件工具：`artcode/tools/file_tools.py`
- 命令工具：`artcode/tools/command_tool.py`
- 进程管理：`artcode/tools/process.py`
- Worktree：`artcode/worktrees/manager.py`
- 测试：`tests/integration/test_workspace_file_flow.py`、`tests/integration/test_process_flow.py`、`tests/integration/test_subagent_main_flow.py:169`

---

## 3. “交互、引擎、工具、权限、记忆五层架构”逐层解析

| 层 | 负责什么 | 主要代码 | 代表测试 |
|---|---|---|---|
| 交互层 | 终端输入、流式展示、审批、命令和快捷键 | `artcode/tui/`、`artcode/commands/`、`artcode/runtime/app.py` | `tests/unit/test_tui_app.py`、`tests/unit/test_commands.py` |
| 引擎层 | Agent 循环、请求准备、模式、上下文和 Provider 调用 | `artcode/agent/`、`artcode/context_management/`、`artcode/providers/` | `tests/unit/test_agent_loop.py`、`tests/unit/test_context_manager.py` |
| 工具层 | 工具注册、元数据、批次规划、文件与命令执行、MCP 适配 | `artcode/tools/`、`artcode/mcp/` | `tests/unit/test_tool_execution.py`、`tests/integration/test_mcp_agent_flow.py` |
| 权限层 | 危险命令、规则、权限模式、人工审批和规则持久化 | `artcode/security/`、`artcode/permissions/`、`artcode/sandbox/` | `tests/unit/test_permission_engine.py`、`tests/integration/test_permissions_flow.py` |
| 记忆层 | 会话 JSONL、指令、长期记忆笔记、计划记忆和上下文压缩 | `artcode/persistence/`、`artcode/agent/memory.py`、`artcode/context_management/` | `tests/integration/test_persistence_flow.py`、`tests/integration/test_memory_flow.py` |

组件组装位置：`artcode/bootstrap.py:96-304`。

---

## 4. 项目介绍后半句逐词解析

简历原句：

> 支持多模型统一接入、MCP 工具扩展、技能沉淀与多 Agent Worktree 隔离协作，全程配套 1600+ 自动化测试。

### 4.1 “多模型”

模型名是配置项，也支持请求级 `model_override`；子 Agent 角色可将逻辑档位映射到具体模型。

- 默认模型配置：`artcode/config.py:73-84`
- 请求级覆盖：`artcode/providers/base.py:10-46`
- Provider payload 选模型：`artcode/providers/deepseek.py:151-175`
- 子 Agent 模型档位：`artcode/config.py:58-69`
- 测试：`tests/unit/test_openai_provider.py:66`、`tests/unit/test_config.py:189`、`tests/unit/test_subagent_roles.py:181`

### 4.2 “统一接入”

统一点有两层：

1. 上层只依赖 `StreamingProvider.stream(request)`，不直接依赖某一家供应商 SDK。  
   代码：`artcode/providers/base.py:49-51`
2. 下层把不同 SSE 字段归一为 `ContentDelta / ReasoningDelta / ToolCallsCompleted / UsageReported / StreamCompleted`。  
   代码：`artcode/providers/events.py:48-93`、`artcode/providers/deepseek.py:201-257`

测试：`tests/unit/test_provider_events.py`、`tests/unit/test_deepseek_provider.py:146`、`tests/integration/test_provider_flow.py:51`。

### 4.3 “MCP 工具扩展”

MCP Server 暴露的远程工具会被转换成 ArtCode 的统一 `ToolDescriptor` 和 `McpToolAdapter`，因此可以进入同一套工具注册、模式过滤、审批和执行链。

- MCP 会话和工具发现：`artcode/mcp/session.py:23-86`
- 适配器：`artcode/mcp/adapter.py:36-80`
- 注册进工具仓库：`artcode/mcp/manager.py:169-221`
- 测试：`tests/unit/test_mcp_adapter.py:9`、`tests/integration/test_mcp_agent_flow.py:49`

### 4.4 “技能沉淀”

Skill 把可复用的 SOP、说明、工具白名单、执行模式和可选模型写成标准包；新任务只需发现并激活，不必把流程重新硬编码进 Agent Loop。

- 多来源发现：`artcode/skills/discovery.py:40-86`
- 激活和会话状态：`artcode/skills/service.py:124-170`
- 按名称加载：`artcode/skills/load_tool.py:19-89`
- SOP 注入请求：`artcode/skills/prompt.py:6-34`
- 测试：`tests/unit/test_skills.py:16`、`tests/integration/test_skill_flow.py:29`

### 4.5 “多 Agent”

主 Agent 通过 `agent` 工具创建独立任务。子 Agent 有 `definition` 和 `fork` 两种来源，并拥有独立对话、运行状态和工具能力快照。

- `agent` 工具：`artcode/subagents/tool.py:27-190`
- 请求类型：`artcode/subagents/models.py:13-15`
- 子运行时创建：`artcode/subagents/factory.py:77-257`
- 状态隔离测试：`tests/unit/test_subagent_state_isolation.py:20`
- 主链测试：`tests/integration/test_subagent_main_flow.py:42`

### 4.6 “Worktree 隔离协作”

具有写入或 Shell 能力的子 Agent 必须在从入队时 Git 提交创建的独立 Worktree 中运行。每个任务有自己的路径和分支，主工作区未提交内容不会复制过去。

- 是否需要 Worktree：`artcode/subagents/policy.py:22-55`
- 冻结基准提交：`artcode/worktrees/manager.py:36-43`
- 创建任务 Worktree：`artcode/worktrees/manager.py:48-147`
- 完成交接：`artcode/worktrees/manager.py:215-250`
- 测试：`tests/fault/test_subagent_concurrency.py:72`、`tests/fault/test_worktree_dirty_baseline.py:16`、`tests/integration/test_subagent_main_flow.py:169`

### 4.7 “1600+ 自动化测试”

当前仓库执行 `pytest --collect-only -q` 可收集 **1649 个测试**。测试分为：

- 单元测试：`tests/unit/`
- 集成测试：`tests/integration/`
- 故障注入：`tests/fault/`
- 性质测试：`tests/property/`
- 长时间/重复运行：`tests/soak/`
- 真实 API：`tests/live/` 与标记为 `live` 的集成测试

测试配置：`pyproject.toml:39-48`。

---

## 5. 技术栈逐词解析

| 技术词 | 一句话解释 | ArtCode 中怎么用 | 代码位置 | 测试位置 |
|---|---|---|---|---|
| Python | 项目的实现语言和运行环境 | 使用 Python 3.11+、异步生成器、`asyncio`、dataclass 和 Protocol | `pyproject.toml:5-17`、`artcode/agent/loop.py:71` | 整个 `tests/` |
| MCP | Model Context Protocol，模型工具扩展协议 | 连接 stdio/streamable HTTP Server，发现工具并适配进统一注册表 | `artcode/mcp/session.py:36`、`artcode/mcp/transport.py:14` | `tests/integration/test_mcp_stdio_live.py`、`tests/integration/test_mcp_http_live.py` |
| ReAct | 推理与行动交替 | 模型返回工具调用，执行结果回填，再进入下一轮 | `artcode/agent/loop.py:94-183` | `tests/unit/test_agent_loop.py:197` |
| Plan Mode | 只读规划模式 | 仅允许 `ToolEffect.READ`，自然结束时保存计划 | `artcode/agent/modes.py:73-77`、`artcode/agent/loop.py:118` | `tests/unit/test_agent_modes.py:30`、`tests/unit/test_agent_loop.py:366` |
| Function Calling | 模型以结构化参数请求函数/工具 | 向模型发送 `tools`，拼接流式 `tool_calls`，解析 JSON 参数后执行 | `artcode/providers/deepseek.py:169`、`artcode/providers/tool_calls.py:22`、`artcode/tools/execution.py:229` | `tests/unit/test_tool_calls.py:6`、`tests/unit/test_openai_provider.py:138` |
| Prompt Caching | 供应商对稳定提示前缀进行缓存 | 请求保持稳定前缀，并读取供应商返回的 cache hit/miss Token；没有在消息中手工插入 `cache_control` | `artcode/prompting/assembler.py:40-62`、`artcode/providers/deepseek.py:266-280` | `tests/unit/test_prompt_assembler.py:54`、`tests/integration/test_prompt_cache_live.py:32` |
| Git Worktree | 同一 Git 仓库的独立工作目录与分支 | 为写型子 Agent 创建任务专属路径，结束后生成状态与交接信息 | `artcode/worktrees/manager.py:48`、`artcode/worktrees/manager.py:215` | `tests/unit/test_worktree_lifecycle_contract.py:90`、`tests/fault/test_subagent_concurrency.py:72` |
| 流式 SSE | Server-Sent Events 增量传输 | 解码 `data:` 事件，把文本、推理、工具调用和用量逐步输出 | `artcode/providers/sse.py:9-72`、`artcode/providers/deepseek.py:98-134` | `tests/unit/test_sse.py:6`、`tests/integration/test_provider_flow.py:51` |
| prompt_toolkit | Python 终端交互库 | 多行输入、异步 Prompt、Enter 发送、Ctrl+B 后台化、Ctrl+C 取消 | `artcode/tui/app.py:29-107`、`artcode/tui/keybindings.py:6` | `tests/unit/test_keybindings.py:8`、`tests/unit/test_tui_background_controls.py:20` |

---

## 6. 亮点一：“工具加载与协议适配”逐词解析

简历原句：

> MCP 工具默认零注入、按需检索激活，未激活工具不占上下文；基于 OpenAI 兼容协议统一接入 DeepSeek 等多供应商，流式响应归一为统一事件接口，新增供应商仅需配置 base_url 与模型名。

### 6.1 “工具加载”

指 MCP 工具从“远端发现”到“本地可调用”的完整过程：

```text
读取 MCP 配置
  → 建立 MCP Session
  → list_tools 分页发现
  → create_adapter 转为统一工具
  → 注册 ToolRegistry
  → Agent 请求中发送工具定义
```

- 配置解析：`artcode/mcp/config.py`
- 连接与发现：`artcode/mcp/session.py:36-86`
- 适配：`artcode/mcp/adapter.py:60-80`
- 注册：`artcode/mcp/manager.py:169-221`
- 测试：`tests/unit/test_mcp_manager.py:44`、`tests/integration/test_mcp_agent_flow.py:49`

### 6.2 “协议适配”

有两种适配：

- **MCP → ArtCode Tool**：把 MCP 的名称、描述、`inputSchema` 和调用结果转换成统一工具结构。  
  代码：`artcode/mcp/adapter.py:24-80`  
  测试：`tests/unit/test_mcp_adapter.py:9`
- **OpenAI-compatible SSE → ProviderEvent**：把供应商流转换成统一事件。  
  代码：`artcode/providers/deepseek.py:98-134`、`artcode/providers/deepseek.py:201-257`  
  测试：`tests/unit/test_deepseek_provider.py:146`

### 6.3 “零注入”

“注入”是把工具定义放入模型请求的 `tools` 字段。“零注入”指在 MCP **lazy 加载策略**下，初始请求不包含任何具体 MCP 工具，只包含目录检索工具 `mcp_search_tools`。

- 策略枚举与配置：`artcode/mcp/models.py`、`artcode/config.py:192-202`
- lazy 初始只注册搜索工具：`artcode/mcp/manager.py:179-186`
- 请求工具定义生成：`artcode/prompting/assembler.py:64-79`
- 测试：`tests/unit/test_mcp_lazy_catalog.py:47`

配置条件：使用 `mcp.loading: lazy` 进入上述按需路径；`eager` 路径会在启动时统一注册具体工具。位置：`config.example.yml:33-35`、`artcode/mcp/manager.py:188-221`。

### 6.4 “按需检索激活”

模型先调用 `mcp_search_tools(query, limit)`；目录按照注册名、远端名、描述和参数 Schema 打分；命中的具体工具被注册，从下一轮模型请求开始可调用。

- 检索打分：`artcode/mcp/catalog.py:51-97`
- 搜索工具：`artcode/mcp/catalog.py:100-175`
- 激活：`artcode/mcp/manager.py:234-265`
- 测试：`tests/unit/test_mcp_lazy_catalog.py:68`、`tests/integration/test_mcp_agent_flow.py:49`

### 6.5 “未激活工具不占上下文”

模型请求只从当前 `ToolRegistry` 导出工具定义。lazy 模式下未激活的适配器只存在 MCP Catalog 中，没有注册进 Registry，因此不会进入请求的 `tools` 数组。

- 注册边界：`artcode/mcp/manager.py:169-186`
- 工具请求统计：`artcode/agent/events.py:95-117`
- 测试：`tests/unit/test_mcp_lazy_catalog.py:47`、`tests/unit/test_agent_events.py`

### 6.6 “OpenAI 兼容协议”

含义：请求发送到 `{base_url}/chat/completions`，使用 `messages`、`tools`、`tool_choice`、`stream` 和 `stream_options` 等兼容字段。

- URL：`artcode/providers/deepseek.py:137-138`
- payload：`artcode/providers/deepseek.py:151-175`
- 配置协议：`artcode/config.py:14-16`、`artcode/config.py:106-132`
- 测试：`tests/unit/test_openai_provider.py:30`、`tests/unit/test_openai_provider.py:50`

### 6.7 “DeepSeek 等多供应商”

只要服务提供 OpenAI-compatible Chat Completions 流式接口，上层仍使用相同 `ProviderRequest` 和 `ProviderEvent`。模型差异集中在 Provider payload 适配，例如 DeepSeek thinking 与 Grok reasoning 参数。

- 统一接口：`artcode/providers/base.py:49-51`
- 模型差异处理：`artcode/providers/deepseek.py:151-179`
- 测试：`tests/unit/test_deepseek_provider.py:59`、`tests/unit/test_openai_provider.py:43`

### 6.8 “统一事件接口”

事件类型：

| 事件 | 含义 | 代码 |
|---|---|---|
| `ContentDelta` | 可见文本增量 | `artcode/providers/events.py:48` |
| `ReasoningDelta` | 推理内容增量 | `artcode/providers/events.py:57` |
| `ToolCallsCompleted` | 完整工具调用集合 | `artcode/providers/events.py:66` |
| `UsageReported` | Token 与缓存用量 | `artcode/providers/events.py:75` |
| `StreamCompleted` | 流结束及 finish reason | `artcode/providers/events.py:84` |

测试：`tests/unit/test_provider_events.py`、`tests/integration/test_provider_flow.py:51`。

### 6.9 “配置 base_url 与模型名”

`base_url` 决定兼容服务端点，`model` 决定请求模型；`api_key` 提供认证。切换兼容供应商时，Agent Loop、工具和上下文层不随供应商改变。

- 配置结构：`artcode/config.py:72-84`
- 严格解析：`artcode/config.py:106-132`
- 测试：`tests/integration/test_config_startup_flow.py:28`、`tests/unit/test_openai_provider.py:66`

---

## 7. 亮点二：“上下文压缩与长会话稳定”逐词解析

简历原句：

> 两层渐进式压缩（轻量存盘 + 语义总结）配合工具调用配对修复与熔断保护，数小时连续会话上下文不丢失；Plan/Do 双模式分离规划与执行，防止执行偏离目标。

### 7.1 “上下文”

上下文是发送给模型的消息历史、系统提示、Skill 信息、运行提醒和工具定义。

- 对话容器：`artcode/conversation/context.py`
- 请求组装：`artcode/prompting/assembler.py:27-62`
- 请求准备：`artcode/agent/request.py:125-186`
- 测试：`tests/unit/test_context.py:15`、`tests/unit/test_prompt_assembler.py:27`

### 7.2 “两层渐进式压缩”

先处理最占空间的工具结果，再在接近窗口上限时总结较早历史：

```text
第一层：LightweightCompactor
  大工具结果写入 .artcode/context/
  对话中只保留 <persisted-output> marker

第二层：ContextSummarizer
  保留系统消息、原始用户消息、最近完整协议单元
  把较早内部历史压缩成结构化语义摘要
```

- 调度：`artcode/agent/request.py:125-186`
- 测试：`tests/integration/test_context_management_flow.py:97`

### 7.3 “轻量存盘”

超过单条阈值或工具结果组总阈值时，将完整工具输出原子写入上下文 artifact，消息中换成带路径与预览的 marker。

- 候选和阈值处理：`artcode/context_management/lightweight.py:24-71`
- 存盘与 marker 交换：`artcode/context_management/lightweight.py:73-107`
- Artifact：`artcode/context_management/artifacts.py:72-124`
- 测试：`tests/unit/test_context_lightweight.py:25`、`tests/unit/test_context_artifacts.py:31`、`tests/unit/test_context_agent_integration.py:116`

### 7.4 “语义总结”

模型把较早的内部历史总结成九个固定部分，同时原始用户消息仍以独立 `role=user` 消息保留，最近历史保持原协议结构。

- 摘要结构：`artcode/context_management/summarizer.py:25-50`
- 摘要请求：`artcode/context_management/summarizer.py:70-103`
- 事务提交：`artcode/context_management/summarizer.py:227-252`
- 测试：`tests/unit/test_context_summarizer.py:81`、`tests/soak/test_repeated_context_compaction.py:67`

### 7.5 “工具调用配对修复”

OpenAI 工具协议要求 assistant 的每个 `tool_call` 后面都有对应 `tool` 结果。若取消或异常中断导致结果缺失，系统插入结构化错误结果，使下一次请求仍满足协议。

- 修复函数：`artcode/conversation/context.py:289-333`
- 每轮前修复：`artcode/agent/loop.py:71-76`
- 取消时修复：`artcode/agent/loop.py:191-199`
- 测试：`tests/unit/test_context.py:120`、`tests/property/test_conversation_protocol_properties.py:89`

### 7.6 “熔断保护”

自动摘要连续失败达到上限后，打开压缩熔断，避免每轮都重复发起失败摘要；手动压缩成功可以重置状态。强制阈值每个周期只尝试一次。

- 触发选择：`artcode/context_management/manager.py:51-58`
- 失败计数和开路：`artcode/context_management/manager.py:78-112`
- 测试：`tests/unit/test_context_manager.py:53`、`tests/unit/test_context_manager.py:80`

### 7.7 “长会话稳定 / 上下文不丢失”

这句话对应的是几组连续性机制：原始用户消息保留、工具协议单元不拆分、摘要事务提交、存盘失败时保留原结果、会话 JSONL 恢复安全前缀。

- 保留策略：`artcode/context_management/retention.py`
- 摘要事务：`artcode/context_management/summarizer.py:227-252`
- 存盘失败保护：`artcode/context_management/lightweight.py:79-107`
- 会话恢复：`artcode/persistence/sessions.py`
- 测试：`tests/unit/test_context_retention.py:38`、`tests/fault/test_context_commit_faults.py:36`、`tests/soak/test_repeated_context_compaction.py:67`、`tests/soak/test_unlimited_agent_loop.py:99`

### 7.8 “Plan/Do 分离规划与执行”

Plan 模式只读，并把最终计划保存到 `PlanMemory`；Do 命令取出最近计划，构造新的执行请求并切换到全工具模式。

- Plan 保存：`artcode/agent/loop.py:108-131`
- PlanMemory：`artcode/agent/memory.py:7-19`
- Do 取计划：`artcode/commands/builtin.py:164-175`
- 测试：`tests/unit/test_agent_loop.py:366`、`tests/unit/test_commands.py:367`

### 7.9 “防止执行偏离目标”

实现含义是：计划阶段没有写权限；执行阶段把“最近计划”原文放入新的 Do 请求，并可附加用户说明，使执行目标有明确输入来源。

- 只读政策：`artcode/agent/modes.py:73-77`
- Do 请求：`artcode/commands/builtin.py:167-175`
- 测试：`tests/unit/test_agent_modes.py:30`、`tests/unit/test_commands.py:367`

---

## 8. 亮点三：“记忆沉淀与规则自学习”逐词解析

简历原句：

> 对话完成后异步提炼偏好、反馈、知识、参考四类记忆并持久化，新会话自动继承；用户“以后拒绝”的操作自动落盘为持久规则，同类操作后续直接拦截。

### 8.1 “对话完成后”

只有 Agent 自然完成并写入最终 assistant 消息后，才构造 `CompletedTurn` 提交给长期记忆观察者。

- 提交时机：`artcode/agent/loop.py:108-131`
- 完成轮数据：`artcode/agent/events.py:49-57`
- 测试：`tests/unit/test_agent_loop.py:395`、`tests/unit/test_agent_loop.py:435`

### 8.2 “异步提炼”

主 Agent 只调用 `MemoryService.submit`，后台单消费者 Worker 串行处理；当前回复不等待记忆模型完成。

- 服务入口：`artcode/persistence/memory_service.py:15-59`
- Worker：`artcode/persistence/updater.py:274-356`
- 测试：`tests/unit/test_memory_service.py:74`、`tests/unit/test_memory_updater.py:154`

### 8.3 “偏好、反馈、知识、参考四类记忆”

代码中的正式枚举是：

| 简历词 | 代码枚举 | 含义 | 代码 |
|---|---|---|---|
| 偏好 | `preference` | 用户跨任务或项目可复用的习惯 | `artcode/persistence/models.py:121-125` |
| 反馈 | `correction` | 用户对错误结果、做法或事实的纠正 | `artcode/persistence/models.py:121-125` |
| 知识 | `project_knowledge` | 当前项目可长期复用的事实 | `artcode/persistence/models.py:121-125` |
| 参考 | `reference` | 后续任务可能需要再次使用的资料或依据 | `artcode/persistence/models.py:121-125` |

提炼提示：`artcode/persistence/updater.py:34-90`。  
测试：`tests/unit/test_memory_updater.py:67`、`tests/integration/test_memory_flow.py:96`。

### 8.4 “持久化”

记忆不是只保存在进程变量中，而是写成用户级或项目级 Markdown 笔记，并维护可重建索引。

- 双存储：`artcode/persistence/memory_service.py:26-37`
- 笔记写入：`artcode/persistence/notes.py:64-256`
- 原子写：`artcode/persistence/notes.py:338-352`
- 测试：`tests/unit/test_memory_notes.py:50`、`tests/fault/test_memory_service_faults.py`

### 8.5 “新会话自动继承”

启动时 `DurablePromptSource` 读取用户级和项目级记忆索引，把它们作为只读持久信息加入系统提示；新会话因此可以使用之前的长期记忆。

- 持久提示源：`artcode/prompting/durable.py`
- 请求时读取最新索引：`artcode/persistence/memory_service.py`、`artcode/prompting/assembler.py:35-44`
- 测试：`tests/unit/test_persistence_prompt_integration.py:38`、`tests/integration/test_persistence_flow.py:62`

### 8.6 “以后拒绝”

终端审批提供四种选择：仅本次允许、仅本次禁止、以后允许、以后禁止。“以后禁止”映射为 `ApprovalChoice.DENY_ALWAYS`。

- 枚举：`artcode/permissions/models.py:94-99`
- TUI 选项：`artcode/tui/app.py:180-192`
- 测试：`tests/unit/test_tui_app.py:130`、`tests/unit/test_permission_service.py:138`

### 8.7 “自动落盘为持久规则”

当选择 `ALLOW_ALWAYS` 或 `DENY_ALWAYS` 时，PermissionService 生成工具名与目标的精确匹配表达式，调用 `RuleWriter.write_exact` 写入 `permissions.local.yml`。

- 永久选择处理：`artcode/permissions/service.py:208-242`
- 规则写入：`artcode/permissions/writer.py`
- 测试：`tests/unit/test_permission_service.py:162`、`tests/integration/test_permissions_flow.py:32`

### 8.8 “同类操作后续直接拦截”

后续相同工具和目标再次进入 `PermissionEngine.decide` 时，规则加载器命中持久化 deny，PermissionService 直接返回 `permission_denied`，不会再次进入人工确认。

- 规则决策：`artcode/permissions/engine.py:34-91`
- deny 短路：`artcode/permissions/service.py:102-108`
- 测试：`tests/unit/test_permission_service.py:117`、`tests/integration/test_tool_batch_flow.py:227`

---

## 9. 亮点四：“技能沉淀与多 Agent 协作”逐词解析

简历原句：

> 技能以标准包多来源发现与激活；主 Agent 拆分任务、多子 Agent 并行执行，Git Worktree 文件级隔离保证并行写互不覆盖，完成后仅回传结论与交接信息。

### 9.1 “技能”

Skill 是可复用任务方法包，核心入口包含元数据和 SOP，还可以带附属资源。

- 定义模型：`artcode/skills/models.py`
- 解析：`artcode/skills/discovery.py:135-262`
- 测试：`tests/unit/test_skill_checklist_boundaries.py:14`、`tests/unit/test_skill_checklist_boundaries.py:107`

### 9.2 “标准包”

目录型 Skill 以一个入口文件作为 SOP，目录中的其他文件只作为资源列表；加载前资源正文不会整体进入模型上下文。

- 包发现：`artcode/skills/discovery.py:88-128`
- 加载返回资源清单：`artcode/skills/load_tool.py:68-88`
- 测试：`tests/unit/test_skills.py:42`、`tests/integration/test_skill_checklist_scenarios.py:138`

### 9.3 “多来源发现”

来源按项目、用户、内置三个根目录扫描；同名 Skill 按来源优先级选择。

- 来源顺序：`artcode/skills/discovery.py:22-24`
- 发现和选择：`artcode/skills/discovery.py:46-86`
- 测试：`tests/unit/test_skills.py:16`

### 9.4 “激活”

未激活时只把 Skill 名称和描述列给模型；调用 `load_skill` 后，SOP 和工具白名单从下一轮请求开始生效。

- 目录提示：`artcode/skills/prompt.py:9-20`
- 激活：`artcode/skills/service.py:124-143`
- SOP 注入：`artcode/skills/prompt.py:21-34`
- 工具白名单交集：`artcode/skills/service.py:164-170`
- 测试：`tests/unit/test_skills.py:74`、`tests/integration/test_skill_flow.py:29`

### 9.5 “主 Agent 拆分任务”

主 Agent 通过统一 `agent` Function Calling 工具提交任务描述、类型、角色和前后台选项。

- 工具 Schema：`artcode/subagents/tool.py:27-67`
- 参数准备：`artcode/subagents/tool.py:69-91`
- 创建任务：`artcode/subagents/tool.py:93-190`
- 测试：`tests/unit/test_agent_tool_contract.py:37`、`tests/integration/test_subagent_main_flow.py:42`

### 9.6 “多子 Agent 并行执行”

每个任务是独立 `asyncio.Task`，由固定容量 4 的 Semaphore 控制并发；第 5 个任务排队等待。

- 并发管理：`artcode/background/manager.py:47-88`
- 实际执行：`artcode/background/manager.py:196-227`
- 测试：`tests/unit/test_background_manager.py:9`、`tests/fault/test_subagent_concurrency.py:22`

### 9.7 “Git Worktree 文件级隔离”

每个写型任务拥有独立工作目录和分支，子 Agent 的文件工具和 Shell 默认工作目录都指向该 Worktree；不同任务不会写同一个物理工作目录。

- 能力计算：`artcode/subagents/policy.py:22-55`
- 子 Agent Workspace 创建：`artcode/subagents/factory.py:119-257`
- Worktree 创建：`artcode/worktrees/manager.py:48-147`
- 测试：`tests/fault/test_subagent_concurrency.py:72`、`tests/integration/test_subagent_seatbelt_isolation.py:42`

### 9.8 “并行写互不覆盖”

隔离来自两个维度：不同 Worktree 路径，以及每个子 Agent 独立的运行状态、权限快照和文件缓存。

- 状态创建：`artcode/subagents/factory.py:119-257`
- 文件缓存说明：`artcode/tools/file_cache.py:14-20`
- 测试：`tests/unit/test_subagent_state_isolation.py:20`、`tests/fault/test_subagent_concurrency.py:72`

### 9.9 “仅回传结论与交接信息”

后台任务通知携带精简最终文本、累计用量和 Worktree handoff；完整信息保留在任务详情中，不把子 Agent 的完整内部对话合并进主对话。

- 通知：`artcode/background/notifications.py:12-57`
- 交接结构：`artcode/background/presentation.py:4-31`
- 任务详情：`artcode/background/manager.py:255-282`
- 测试：`tests/unit/test_task_notifications.py:62`、`tests/fault/test_task_notification_timing.py:34`

---

## 10. 亮点五：“安全沙箱与全链路可观测”逐词解析

简历原句：

> 危险命令校验、路径沙箱、规则引擎、权限模式、人工确认五层拦截，任一层拒绝即终止，OS 沙箱兜底；工具调用、权限决策、Token 用量、任务状态全量审计可回溯。

### 10.1 五层拦截总览

```text
工具调用
  → 1. 危险命令校验
  → 2. 路径边界与敏感路径校验
  → 3. 用户/项目/本地规则引擎
  → 4. 权限模式与 Shell 策略
  → 5. 人工确认
  → 工具自身 execute
  → Shell 再由 Seatbelt 包裹
```

### 10.2 “危险命令校验”

Shell 请求先解析危险命令规则；命中后返回硬拒绝，规则中的 allow 也不能覆盖。

- 校验器：`artcode/security/commands.py`
- 决策顺序：`artcode/permissions/engine.py:39-54`
- 测试：`tests/unit/test_dangerous_commands.py:22`、`tests/unit/test_permission_engine.py:85`

### 10.3 “路径沙箱”

文件访问只允许 Workspace 和显式只读根；路径解析后检查越界、敏感目录、符号链接和审批后目标变化，并通过目录文件描述符执行原子写。

- 路径政策：`artcode/tools/policy.py:14-98`
- 访问与 TOCTOU 校验：`artcode/tools/filesystem.py:59-186`
- 深层路径安全：`artcode/tools/filesystem.py:278-360`
- 测试：`tests/unit/test_workspace_file_access.py:62`、`tests/unit/test_workspace_file_access.py:168`、`tests/property/test_workspace_paths.py:67`

### 10.4 “规则引擎”

规则来自用户、项目和本地三层；匹配工具名与目标后生成 allow、ask 或 deny 决策。

- 决策器：`artcode/permissions/engine.py:25-91`
- 规则加载与匹配：`artcode/permissions/rules.py`
- 测试：`tests/unit/test_permission_rules.py:16`、`tests/unit/test_permission_rules.py:30`

### 10.5 “权限模式”

`default / edit / full` 控制读写默认动作；Shell 另有 `auto / ask / off` 策略。权限状态在请求执行前会形成不可变快照。

- 模式：`artcode/permissions/models.py:15-41`
- Runtime 权威状态：`artcode/runtime/state.py:65-85`
- 测试：`tests/unit/test_permission_engine.py:34`、`tests/unit/test_runtime_state.py:35`

### 10.6 “人工确认”

当最终决定是 ask 时，TUI 展示工具、目标、模式和来源，用户选择允许/禁止一次或永久允许/禁止。

- 请求审批：`artcode/permissions/service.py:162-247`
- TUI：`artcode/tui/app.py:180-192`
- 测试：`tests/unit/test_permission_service.py:138`、`tests/unit/test_tui_app.py:130`

### 10.7 “任一层拒绝即终止”

工具执行服务在 prepare/authorize 阶段拿到 `ToolResult` 后不再调用工具的 `execute`；模式不允许或未知工具时，执行计划也会直接返回 blocked。

- 模式/未知工具短路：`artcode/tools/execution.py:70-106`
- 权限短路：`artcode/tools/execution.py:175-227`
- 测试：`tests/unit/test_tool_execution.py:183`、`tests/unit/test_tool_execution.py:345`

### 10.8 “OS 沙箱兜底”

Shell 默认通过 macOS `/usr/bin/sandbox-exec` 启动。Seatbelt Profile 默认 deny，只开放必要进程、Workspace/临时目录文件访问，并统一拒绝网络。

- Session 与自检：`artcode/sandbox/seatbelt.py:20-102`
- Profile：`artcode/sandbox/seatbelt.sb:1-16`
- 命令前缀：`artcode/tools/command_tool.py:66-72`
- 测试：`tests/unit/test_seatbelt.py:31`、`tests/integration/test_seatbelt_live.py:14`

### 10.9 “全链路可观测”

“可观测”在项目中表现为结构化事件、运行快照、会话记录和任务详情：

| 对象 | 记录内容 | 代码 | 测试 |
|---|---|---|---|
| 工具调用 | 调用数量、批次、工具名、结构化结果 | `artcode/agent/events.py:127-142`、`artcode/conversation/context.py` | `tests/unit/test_agent_loop.py:197`、`tests/integration/test_tool_batch_flow.py:202` |
| 权限决策 | decision、source、rule index、目标哈希、审批选择和规则写入事件 | `artcode/permissions/service.py:88-100`、`artcode/permissions/service.py:249-265` | `tests/unit/test_subagent_policy_permissions.py:140`、`tests/unit/test_permission_service.py:117` |
| Token 用量 | prompt、completion、total、cache hit、cache miss | `artcode/providers/events.py:9-45`、`artcode/runtime/app.py:499-507` | `tests/unit/test_agent_events.py:14`、`tests/unit/test_runtime_state.py:65` |
| 任务状态 | queued、running、completed、failed、cancelled、max rounds | `artcode/background/models.py`、`artcode/background/manager.py:196-244` | `tests/unit/test_background_state_machine.py`、`tests/unit/test_background_manager.py:9` |
| 会话回溯 | 用户消息、assistant、tool calls、tool results 和计划追加为 JSONL | `artcode/persistence/sessions.py` | `tests/unit/test_session_journal.py:23`、`tests/unit/test_session_recovery.py:80` |
| Worktree 交接 | baseline、branch、path、变化数量、提交和推送状态 | `artcode/background/presentation.py:4-31`、`artcode/worktrees/manager.py:215-248` | `tests/unit/test_task_notifications.py:62`、`tests/unit/test_worktree_lifecycle_contract.py:193` |

---

## 11. 五条亮点的完整调用链

### 11.1 MCP 懒加载链

```text
McpManager.start
  → McpSession.connect / list_tools
  → McpCatalog 保存适配器
  → lazy 模式只注册 mcp_search_tools
  → 模型调用 mcp_search_tools
  → McpCatalog.search
  → McpManager.activate
  → ToolRegistry.register
  → 下一轮 RequestPreparer 导出新工具定义
```

### 11.2 上下文压缩链

```text
RequestPreparer.prepare
  → LightweightCompactor.apply
  → 估算完整请求 Token
  → ContextManager.choose_trigger
  → RetentionPlanner.plan
  → ContextSummarizer.summarize
  → ConversationContext.replace_entries_if_version
  → 重新组装请求
```

### 11.3 记忆链

```text
AgentLoop 自然完成
  → CompletedTurn
  → MemoryService.submit
  → MemoryUpdateWorker 后台 FIFO
  → MemoryUpdater 调用模型提炼
  → MemoryUpdateParser 严格校验
  → MemoryNoteStore.apply
  → Markdown 笔记和索引
  → 新请求由 DurablePromptSource 读取
```

### 11.4 多 Agent 链

```text
主 Agent 调用 agent 工具
  → AgentTool.prepare
  → SubagentFactory.prepare_launch
  → BackgroundTaskManager.submit
  → 写型任务 WorktreeManager.acquire
  → SubagentFactory.create 独立运行时
  → SubagentRunner.run
  → WorktreeManager.handoff
  → TaskNotificationInbox
  → 下一次安全请求边界通知主 Agent
```

### 11.5 安全链

```text
ToolExecutionService._prepare_and_authorize
  → 工具参数与路径 prepare
  → PermissionService.authorize
  → PermissionEngine.decide
       ├─ Plan 限制
       ├─ DangerousCommandValidator
       ├─ Path/Sensitive 决策
       ├─ 持久规则
       └─ PermissionMode / ShellPolicy
  → 必要时 TUI 人工确认
  → 工具 execute
  → run_command 再套 Seatbelt
```

---

## 12. 面试快速索引

| 面试官关键词 | 首选代码入口 | 首选测试 |
|---|---|---|
| ReAct 怎么实现 | `artcode/agent/loop.py:94` | `tests/unit/test_agent_loop.py:197` |
| Plan/Do 怎么隔离 | `artcode/agent/modes.py:73`、`artcode/commands/builtin.py:164` | `tests/unit/test_commands.py:367` |
| MCP 零注入 | `artcode/mcp/manager.py:179` | `tests/unit/test_mcp_lazy_catalog.py:47` |
| MCP 怎么检索 | `artcode/mcp/catalog.py:51` | `tests/unit/test_mcp_lazy_catalog.py:68` |
| 多供应商怎么统一 | `artcode/providers/base.py:49`、`artcode/providers/deepseek.py:201` | `tests/integration/test_provider_flow.py:51` |
| Function Calling | `artcode/providers/tool_calls.py:22`、`artcode/tools/execution.py:229` | `tests/unit/test_tool_calls.py:6` |
| Prompt Cache | `artcode/prompting/assembler.py:27`、`artcode/providers/deepseek.py:266` | `tests/integration/test_prompt_cache_live.py:32` |
| 两层压缩 | `artcode/context_management/lightweight.py:24`、`artcode/context_management/summarizer.py:175` | `tests/integration/test_context_management_flow.py:97` |
| 工具配对修复 | `artcode/conversation/context.py:289` | `tests/unit/test_context.py:120` |
| 压缩熔断 | `artcode/context_management/manager.py:51` | `tests/unit/test_context_manager.py:53` |
| 长期记忆 | `artcode/persistence/memory_service.py:15`、`artcode/persistence/updater.py:185` | `tests/integration/test_memory_flow.py:96` |
| 以后禁止 | `artcode/permissions/service.py:208` | `tests/integration/test_permissions_flow.py:32` |
| Skill 激活 | `artcode/skills/service.py:124` | `tests/integration/test_skill_flow.py:29` |
| 子 Agent | `artcode/subagents/tool.py:27` | `tests/integration/test_subagent_main_flow.py:42` |
| 并发任务 | `artcode/background/manager.py:47` | `tests/unit/test_background_manager.py:9` |
| Worktree 隔离 | `artcode/worktrees/manager.py:48` | `tests/fault/test_subagent_concurrency.py:72` |
| 危险命令 | `artcode/security/commands.py` | `tests/unit/test_dangerous_commands.py:22` |
| 路径安全 | `artcode/tools/filesystem.py:59` | `tests/unit/test_workspace_file_access.py:62` |
| 权限链 | `artcode/permissions/engine.py:34`、`artcode/permissions/service.py:48` | `tests/integration/test_tool_batch_flow.py:227` |
| Seatbelt | `artcode/sandbox/seatbelt.py:20`、`artcode/sandbox/seatbelt.sb:1` | `tests/integration/test_seatbelt_live.py:14` |
| Token 可观测 | `artcode/providers/events.py:9`、`artcode/runtime/state.py:84` | `tests/unit/test_runtime_state.py:65` |
| 会话恢复 | `artcode/persistence/sessions.py` | `tests/unit/test_session_recovery.py:23` |

---

## 13. 一分钟口述版

> ArtCode 是我用 Python 实现的本地终端 AI 编程助手。核心是 ReAct Agent Loop：模型流式返回文本、推理或 Function Calling，系统把工具调用经过模式、权限和安全检查后执行，再把结果写回上下文继续下一轮。规划和执行使用 Plan/Do 两种模式，Plan 只读并保存计划，Do 再拿计划进入执行链。为了控制长上下文，我做了轻量工具结果存盘和语义总结两层压缩，同时处理工具调用配对修复和摘要熔断。扩展侧支持 MCP 懒加载、标准 Skill 包和多子 Agent；写型子 Agent 必须进入独立 Git Worktree，并通过后台任务管理器并发运行。长期记忆会在自然完成后异步提炼四类信息写入 Markdown，新会话自动读取；权限审批中的“以后禁止”会写成持久规则。安全侧由危险命令、路径、规则、权限模式、人工确认和 macOS Seatbelt 共同控制。当前仓库可以收集 1649 个自动化测试，覆盖单元、集成、故障、性质、Soak 和 Live 场景。

