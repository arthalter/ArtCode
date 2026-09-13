# ch08：上下文管理 Tasks

## 文件清单

| 操作 | 文件 | 职责 |
|---|---|---|
| 新建 | `artcode/context_management/` | Token 估算、存盘、轻量压缩、保留区、摘要和状态机 |
| 修改 | `artcode/config.py`、`config.example.yml` | 上下文窗口配置、范围校验与启动状态 |
| 修改 | `artcode/providers/`、`artcode/errors.py` | 摘要专用请求选项和上下文超限错误分类 |
| 修改 | `artcode/conversation/` | 稳定消息 ID、用户原文档案、快照和事务替换 |
| 修改 | `artcode/tools/`、`artcode/mcp/results.py`、`artcode/mcp/adapter.py` | 移除硬截断和限制存盘结果回读 |
| 修改 | `artcode/agent/` | 请求前上下文管线、状态事件、usage 锚定和紧急重试 |
| 修改 | `artcode/commands/`、`artcode/runtime/`、`artcode/tui/` | `/compact`、依赖装配和用户状态展示 |
| 修改 | `artcode/workspace.py`、`artcode/cli.py`、`.gitignore` | 会话目录定位、启动清理和退出清理 |
| 修改 | `README.md` | 配置、压缩行为、文件生命周期和手动命令说明 |
| 新建 | `tests/unit/test_context_*.py` | 上下文管理各组件单元测试 |
| 修改 | 既有 `tests/unit/test_*.py` | Provider、工具、Agent、Runtime、TUI 回归测试 |
| 新建 | `tests/integration/test_context_management_flow.py` | 本地完整流程集成测试 |
| 新建 | `tests/integration/test_context_management_deepseek_live.py` | 真实 DeepSeek 摘要与后续对话验证 |

## T1：增加上下文配置与固定策略模型

**影响文件：** `artcode/config.py`、`artcode/context_management/__init__.py`、`artcode/context_management/models.py`、`config.example.yml`、`tests/unit/test_config.py`、`tests/unit/test_context_models.py`

**依赖任务：** 无

**参考资料定位：** `spec.md` F1、AC1；`plan.md`“固定参数”“配置设计”“压缩状态机”

**步骤：**

1. 建立上下文管理包及触发器、报告、熔断状态等公共模型。
2. 增加可选上下文配置并实现默认值、整数类型和上下界校验。
3. 按 `167/200` 与 `177/200` 向下取整计算自动线和强制线。
4. 将上下文窗口加入脱敏启动状态和示例配置。
5. 覆盖默认值、边界值、比例计算、布尔值和越界拒绝测试。

**验证：**

```bash
python -m pytest tests/unit/test_config.py tests/unit/test_context_models.py -q
```

预期：200K–1000K 合法范围与两条比例线测试全部通过，既有配置行为无回归。

## T2：扩展 Provider 请求选项与上下文超限分类

**影响文件：** `artcode/providers/base.py`、`artcode/providers/openai_compatible.py`、`artcode/providers/__init__.py`、`artcode/errors.py`、`tests/unit/test_openai_provider.py`

**依赖任务：** T1

**参考资料定位：** `spec.md` F10、F19、N5、N8；`plan.md`“Provider 请求选项与错误分类”

**步骤：**

1. 定义可选最大输出和 Thinking 覆盖请求选项，并扩展 Provider 协议。
2. 普通请求保持现有 payload；摘要请求可以发送输出上限并关闭 Thinking。
3. 保证 `tools=None` 时不出现工具定义和自动工具选择字段。
4. 在脱敏后识别上下文长度错误并映射为专用异常，其他错误保持原分类。
5. 更新 Fake Provider 兼容新签名并覆盖 payload、错误优先级和秘密脱敏测试。

**验证：**

```bash
python -m pytest tests/unit/test_openai_provider.py tests/unit/test_provider_events.py -q
```

预期：摘要选项只影响专用请求，上下文超限可被可靠区分，Provider 回归通过。

## T3：实现会话条目、用户档案与 Token 估算器

**影响文件：** `artcode/conversation/context.py`、`artcode/conversation/__init__.py`、`artcode/context_management/estimator.py`、`artcode/context_management/models.py`、`tests/unit/test_context.py`、`tests/unit/test_context_estimator.py`

**依赖任务：** T1

**参考资料定位：** `spec.md` F2–F3、F11–F14、AC2、AC10–AC11；`plan.md`“会话消息模型”“Token 估算”

**步骤：**

1. 用稳定 ID 的内部条目保存消息，同时保持 `export_messages()` 的外部字典格式不变。
2. 建立只在当前进程内存在的用户原文档案和摘要覆盖 ID 集合。
3. 增加版本化快照以及版本匹配的一次性历史替换入口。
4. 实现规范化请求序列化及“汉字 1:1、其他字符 3:1”的字符估算。
5. 实现无锚点完整估算、usage 锚点差量估算和负增量下限保护。
6. 覆盖导出兼容、用户原文一致、快照隔离、事务冲突和锚点重校准测试。

**验证：**

```bash
python -m pytest tests/unit/test_context.py tests/unit/test_context_estimator.py -q
```

预期：会话协议保持兼容，字符估算和 usage 差量结果可复现。

## T4：移除工具结果硬截断并保留完整内容

**影响文件：** `artcode/tools/results.py`、`artcode/tools/base.py`、`artcode/tools/file_tools.py`、`artcode/tools/command_tool.py`、`artcode/mcp/results.py`、`artcode/mcp/adapter.py`、`artcode/tui/render.py`、`tests/unit/test_tool_results.py`、`tests/unit/test_file_tools.py`、`tests/unit/test_command_tool.py`、`tests/unit/test_mcp_results.py`、`tests/unit/test_render.py`

**依赖任务：** T1

**参考资料定位：** `spec.md` F7、AC5、N6；`plan.md`“工具结果完整保留”

**步骤：**

1. 让成功和失败 ToolResult 保存完整文本及完整 UTF-8 字节数。
2. 移除公共执行路径中的最大结果字节参数与截断标记。
3. 更新内置文件、搜索、命令和 MCP 结果转换调用。
4. 调整 TUI 工具摘要，不再显示旧的“已截断”状态。
5. 将旧截断测试改为完整尾部可见测试，并保留 Unicode 序列化回归。

**验证：**

```bash
python -m pytest tests/unit/test_tool_results.py tests/unit/test_file_tools.py tests/unit/test_command_tool.py tests/unit/test_mcp_results.py tests/unit/test_render.py -q
```

预期：超过旧限制的内置和 MCP 工具结果均不丢失，UI 不打印完整大结果。

## T5：实现 Artifact Store 与安全生命周期

**影响文件：** `artcode/context_management/artifacts.py`、`artcode/workspace.py`、`.gitignore`、`tests/unit/test_context_artifacts.py`、`tests/unit/test_workspace.py`

**依赖任务：** T1、T3、T4

**参考资料定位：** `spec.md` F5、F9、F21、N4、N7；`plan.md`“ContextArtifactStore”“生命周期与目录安全”

**步骤：**

1. 定义 Workspace 内会话目录、进程标记和安全文件名规则。
2. 使用临时文件加原子替换保存 ToolResult 原始内容，并设置仅当前用户可读写权限。
3. 生成相对路径、原始规模、Token 估算和首尾预览固定标记。
4. 实现当前 Artifact 路径身份判断，拒绝字符串前缀和符号链接伪造。
5. 实现仅清理当前会话和确认失活遗留会话的关闭、启动清理。
6. 将运行目录加入 Git 忽略规则，覆盖原子失败、路径逃逸、活动会话和幂等关闭测试。

**验证：**

```bash
python -m pytest tests/unit/test_context_artifacts.py tests/unit/test_workspace.py -q
```

预期：完整内容与标记一致，目录清理不会越出 Workspace 或删除活跃会话。

## T6：实现单结果与同轮聚合轻量压缩

**影响文件：** `artcode/context_management/lightweight.py`、`artcode/conversation/context.py`、`tests/unit/test_context_lightweight.py`、`tests/unit/test_context.py`

**依赖任务：** T3、T4、T5

**参考资料定位：** `spec.md` F4–F7、F21、AC3–AC4、AC8、AC18；`plan.md`“LightweightCompactor”

**步骤：**

1. 识别一次 assistant tool_calls 及其连续 tool results 组成的完整统计组。
2. 对单结果超过 8K Token 的消息先执行存盘替换。
3. 对处理后的组重新求和，超过 16K 时按规模降序、消息顺序平局依次存盘。
4. 跳过固定存盘标记，保证重复请求前检查幂等。
5. 写盘失败时保留完整消息并标记受保护，不允许重量摘要删除。
6. 覆盖单结果、聚合、并列顺序、失败结果、多工具协议组、重复检查和存盘失败测试。

**验证：**

```bash
python -m pytest tests/unit/test_context_lightweight.py tests/unit/test_context.py -q
```

预期：轻量层不调用 Provider，处理顺序稳定且工具调用链完整。

## T7：限制存盘结果的分段回读

**影响文件：** `artcode/tools/base.py`、`artcode/tools/file_tools.py`、`artcode/context_management/artifacts.py`、`tests/unit/test_file_tools.py`、`tests/unit/test_context_artifacts.py`

**依赖任务：** T5、T6

**参考资料定位：** `spec.md` F8、AC6；`plan.md`“存盘结果分段回读”

**步骤：**

1. 通过 ToolExecutionContext 向读取工具提供当前 Artifact Store 的只读引用。
2. 对当前会话存盘路径要求同时提供起止行，普通 Workspace 文件保持旧行为。
3. 估算选定片段，超过 8K Token 时拒绝返回并提示缩小范围。
4. 使用解析后的真实路径判断 Artifact 身份，覆盖相似前缀、旧会话和符号链接场景。
5. 验证合法分段可读取原文且下一轮轻量检查不会再次存盘。

**验证：**

```bash
python -m pytest tests/unit/test_file_tools.py tests/unit/test_context_artifacts.py -q
```

预期：全文回读被阻止，有界片段正常返回且不形成循环。

## T8：实现协议安全的近期保留区

**影响文件：** `artcode/context_management/retention.py`、`artcode/context_management/models.py`、`tests/unit/test_context_retention.py`

**依赖任务：** T3、T6

**参考资料定位：** `spec.md` F11–F14、AC10–AC11；`plan.md`“近期原文选择”

**步骤：**

1. 从尾部累计到同时满足 10K Token 与至少 5 条消息。
2. 将 assistant tool_calls 和全部对应 tool results 视为不可拆组并向前扩展切点。
3. 始终排除 System Prompt 和旧摘要，不把它们计入近期最低数量。
4. 把存盘失败的受保护消息强制留在近期区，并识别无可压缩前缀情况。
5. 收集新进入摘要的用户 ID，并与旧摘要覆盖 ID 稳定合并。
6. 覆盖短历史、大单条消息、切中工具组、已有摘要和受保护消息测试。

**验证：**

```bash
python -m pytest tests/unit/test_context_retention.py -q
```

预期：切点满足预算与最低数量，任何输出计划都不产生残缺工具协议。

## T9：实现无工具九段摘要与事务提交

**影响文件：** `artcode/context_management/summarizer.py`、`artcode/context_management/models.py`、`artcode/conversation/context.py`、`tests/unit/test_context_summarizer.py`、`tests/unit/test_context.py`

**依赖任务：** T2、T3、T8

**参考资料定位：** `spec.md` F10、F12–F16、N2、N5；`plan.md`“摘要生成”

**步骤：**

1. 构建将历史视为数据、禁止工具、要求先草稿后正文的固定 Prompt。
2. 用当前 Provider 发起无工具、关闭 Thinking 覆盖、最大输出 20K 的内部流式请求。
3. 严格解析唯一且非空的 analysis、summary、九个标题和用户原文占位符。
4. 丢弃草稿，由程序按 ID 顺序把用户档案原文注入第六段。
5. 生成摘要 System 消息和边界 System 消息，并在版本一致时事务替换前缀。
6. 覆盖标签缺失、多标签、顺序错误、工具调用、用户原文特殊字符、取消和版本冲突测试。

**验证：**

```bash
python -m pytest tests/unit/test_context_summarizer.py tests/unit/test_context.py -q
```

预期：只有有效正式摘要提交，草稿不进入历史，用户消息逐字一致，所有失败均保持旧历史。

## T10：实现阈值、熔断、强制与紧急状态机

**影响文件：** `artcode/context_management/manager.py`、`artcode/context_management/models.py`、`tests/unit/test_context_manager.py`

**依赖任务：** T1、T3、T6、T8、T9

**参考资料定位：** `spec.md` F17–F21、N8、AC14–AC18；`plan.md`“压缩状态机”

**步骤：**

1. 按配置窗口计算请求估算并选择 automatic、forced、manual 或 emergency。
2. 实现连续三次自动失败熔断、低水位跳过和成功全量复位。
3. 实现每个熔断周期最多一次强制压缩，失败后按已确认选择放行普通请求。
4. 实现手动压缩绕过阈值与熔断，并处理无可压缩前缀 no-op。
5. 实现真实超限时一次紧急压缩与一次重试许可，不允许递归。
6. 将存盘失败受保护消息纳入安全请求判断，无法安全发送时返回阻塞结果。
7. 用表驱动测试覆盖阈值前后、窗口比例、三次失败、强制失败、手动成功和紧急失败。

**验证：**

```bash
python -m pytest tests/unit/test_context_manager.py -q
```

预期：每条状态迁移与尝试次数均确定，任何失败组合都不会产生无限请求。

## T11：增加 `/compact` 与上下文状态展示

**影响文件：** `artcode/commands/builtin.py`、`artcode/agent/events.py`、`artcode/agent/__init__.py`、`artcode/runtime/app.py`、`artcode/tui/app.py`、`artcode/tui/render.py`、`tests/unit/test_commands.py`、`tests/unit/test_agent_events.py`、`tests/unit/test_runtime.py`、`tests/unit/test_tui_app.py`、`tests/unit/test_render.py`

**依赖任务：** T10

**参考资料定位：** `spec.md` F20、F22、AC17、AC19；`plan.md`“手动命令与运行时”

**步骤：**

1. 注册无参数 `/compact` 并加入帮助文本。
2. 定义包含触发原因、前后估算、存盘数量和熔断状态的上下文事件。
3. Runtime 执行命令时不追加用户消息，直接消费手动压缩事件。
4. TUI 展示简洁成功、失败、跳过和阻塞状态，启动面板显示窗口上限。
5. 保证摘要草稿、摘要正文和完整工具结果不会作为普通流式回复打印。
6. 覆盖命令路由、低水位手动压缩、熔断绕过和格式化输出测试。

**验证：**

```bash
python -m pytest tests/unit/test_commands.py tests/unit/test_agent_events.py tests/unit/test_runtime.py tests/unit/test_tui_app.py tests/unit/test_render.py -q
```

预期：`/compact` 不污染对话，用户能看到完整但简洁的上下文状态。

## T12：接入主流程

**影响文件：** `artcode/agent/loop.py`、`artcode/agent/stream.py`、`artcode/runtime/app.py`、`artcode/cli.py`、`artcode/workspace.py`、`tests/unit/test_agent_loop.py`、`tests/unit/test_agent_stream.py`、`tests/unit/test_runtime.py`、`tests/integration/test_context_management_flow.py`

**依赖任务：** T2、T3、T5、T6、T9、T10、T11

**参考资料定位：** `spec.md` F4、F10、F18–F19、N6；`plan.md`“Agent Loop 接入”“生命周期与目录安全”“模块交互”

**步骤：**

1. 在每次普通、工具后续和异常总结 API 请求前接入“轻量检查—组装—估算—重量决策”。
2. 压缩成功后重新组装请求，保证 System Reminder 和 Mode 工具集合与当前状态一致。
3. 每次成功普通响应后，用实际发送请求和 `prompt_tokens` 更新估算锚点。
4. 保留 RequestError 类型，并只对 ContextWindowExceededError 执行一次紧急压缩与原请求重试。
5. 确保重试不重复追加用户消息、不重复执行已完成工具、不污染 PlanMemory。
6. 在 CLI 启动 Artifact Store 并完成 ContextManager、ToolExecutionContext、Runtime 的依赖装配。
7. 在退出路径清理当前会话目录，并保持 MCP 和 Seatbelt 的既有关闭行为。
8. 用本地集成测试验证真实请求顺序、usage 锚定、工具协议和生命周期。

**验证：**

```bash
python -m pytest tests/unit/test_agent_loop.py tests/unit/test_agent_stream.py tests/unit/test_runtime.py tests/integration/test_context_management_flow.py -q
```

预期：所有模型请求执行统一前置管线，紧急重试有界，现有 Agent Loop 行为保持兼容。

## T13：端到端验证与使用文档

**影响文件：** `tests/integration/test_context_management_deepseek_live.py`、`tests/integration/README.md`、`README.md`、`config.example.yml`、全部受影响测试文件

**依赖任务：** T1–T12

**参考资料定位：** `spec.md` AC1–AC21；`plan.md`“固定参数”“模块交互”“技术决策”；现有 `tests/integration/test_deepseek_live.py`

**步骤：**

1. 记录上下文配置、两层压缩、存盘目录、分段回读、`/compact` 和清理行为。
2. 建立本地端到端场景：大工具结果先存盘，旧历史再摘要，后续模型请求看到摘要、边界和近期原文。
3. 验证连续三次摘要失败、强制线失败继续、真实超限紧急恢复和二次失败停止。
4. 使用真实 DeepSeek API 手动触发九段摘要，验证请求无工具、草稿丢弃、用户原文保留和后续对话连续性。
5. 运行全部单元、集成和真实 API 测试，并按 `checklist.md` 逐项记录证据。

**验证：**

```bash
python -m pytest tests/unit -q
python -m pytest tests/integration -q
python -m pytest tests/integration/test_context_management_deepseek_live.py -q -s
```

预期：全部自动化测试和真实 DeepSeek 场景通过，完整任务链在压缩前后持续工作。

## 执行顺序

```text
T1 ──> T2 ───────────────────────────────┐
 │                                      │
 ├──> T3 ──> T8 ──> T9 ──┐              │
 │      │                 │              │
 └──> T4 ──> T5 ──> T6 ──┼──> T10 ──> T11
                 └──> T7  │              │
                          └───────────────┴──> T12 ──> T13
```
