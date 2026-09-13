# ch07：MCP协议 Tasks

## 文件清单

| 操作 | 文件 | 职责 |
|---|---|---|
| 修改 | `pyproject.toml` | 增加官方 MCP SDK 稳定版本依赖 |
| 修改 | `artcode/config.py`、`workspace.py`、`cli.py` | 配置路径、加载与启动接入 |
| 新建 | `artcode/mcp/` | MCP 配置、传输、会话、适配与生命周期 |
| 修改 | `artcode/tools/`、`artcode/agent/` | 工具元数据、注册、模式与调度 |
| 修改 | `artcode/runtime/`、`artcode/tui/` | Manager 生命周期、审批与报告 |
| 修改 | `config.example.yml`、`README.md` | 示例配置与安全说明 |
| 新建 | `tests/unit/test_mcp_*.py` | MCP 各模块单元测试 |
| 新建 | `tests/integration/fixtures/mcp_test_server.py` | 可控真实 MCP 测试 Server |
| 新建 | `tests/integration/test_mcp_*.py` | 双传输与 Agent 集成测试 |

## T1：引入 SDK 并建立 MCP 公共模型

**影响文件：** `pyproject.toml`、`artcode/mcp/__init__.py`、`artcode/mcp/models.py`、`tests/unit/test_mcp_models.py`

**依赖任务：** 无

**参考资料定位：** `plan.md`“核心数据结构”；官方 Python SDK 稳定 v1 依赖说明；`artcode/permissions/models.py`

**步骤：**

1. 增加 `mcp>=1.28,<2` 依赖。
2. 创建传输、来源、状态和失败阶段枚举。
3. 创建 stdio、HTTP、解析后配置和联合类型。
4. 创建配置问题、启动审批、工具审批、Server 报告和启动报告。
5. 补充模型默认值、不可变性和报告计数测试。

**验证：**

```bash
python -m pytest tests/unit/test_mcp_models.py -q
```

预期：模型测试全部通过，项目可导入 `artcode.mcp`。

## T2：实现两层配置解析、合并与延迟展开

**影响文件：** `artcode/config.py`、`artcode/workspace.py`、`artcode/mcp/config.py`、`tests/unit/test_config.py`、`tests/unit/test_workspace.py`、`tests/unit/test_mcp_config.py`

**依赖任务：** T1

**参考资料定位：** `spec.md` F1–F11、AC1–AC12；`plan.md`“配置加载”；现有 `parse_config()` 与 `Workspace`

**步骤：**

1. 增加 Workspace 项目配置路径。
2. 从用户主配置中分离 MCP 原始配置，不改变模型配置校验。
3. 读取项目级文件并拒绝其他顶层字段。
4. 按 Server 名整项覆盖并保留来源与稳定顺序。
5. 严格校验两种传输字段及类型。
6. 实现禁用项、`${VAR}` 扫描、审批后展开和安全基础环境。
7. 覆盖合法、覆盖、未知字段、字段混用、缺失变量和 `--config` 语义。

**验证：**

```bash
python -m pytest tests/unit/test_config.py tests/unit/test_workspace.py tests/unit/test_mcp_config.py -q
```

预期：两层配置与既有主配置回归全部通过。

## T3：实现统一脱敏、名称规范化与结果转换

**影响文件：** `artcode/mcp/redaction.py`、`naming.py`、`results.py`、对应三个单元测试文件

**依赖任务：** T1

**参考资料定位：** `spec.md` F21–F25、F31、F33–F35；`plan.md`“工具 Schema 与名称”“参数预览与结果转换”；`artcode/tools/results.py`

**步骤：**

1. 实现敏感键识别、嵌套脱敏和最长 2,000 字符的稳定 JSON 预览。
2. 实现字符替换、64 字符限制和 SHA-256 前 10 位稳定后缀。
3. 转换文本、结构化内容和非文本安全元数据。
4. 将 `isError` 转成失败结果并复用 20,000 字节截断器。
5. 覆盖中文名、特殊字符、长名、秘密嵌套和混合内容块。

**验证：**

```bash
python -m pytest tests/unit/test_mcp_redaction.py tests/unit/test_mcp_naming.py tests/unit/test_mcp_results.py -q
```

预期：名称、脱敏和结果边界测试通过。

## T4：实现 stdio 日志捕获与双传输工厂

**影响文件：** `artcode/mcp/stderr.py`、`transport.py`、`tests/unit/test_mcp_stderr.py`、`test_mcp_transport.py`

**依赖任务：** T1、T2、T3

**参考资料定位：** `spec.md` F12、F17–F18；`plan.md` 双传输设计；官方 SDK 客户端示例

**步骤：**

1. 创建 SDK stdio 日志管道并后台持续读取。
2. 保存最近 100 行、最多 64 KiB、单行最多 2 KiB，存储前脱敏。
3. 实现 stdio 的参数、Workspace cwd 和安全环境传递。
4. 实现 HTTP Client 和最多 10 次重定向。
5. 包装 HTTP Transport，每次发送均重新注入全部配置 Headers。
6. 确保异常不暴露 Header 值或 URL 查询参数。
7. 用假 SDK 上下文验证资源退出和跨域 Header 转发。

**验证：**

```bash
python -m pytest tests/unit/test_mcp_stderr.py tests/unit/test_mcp_transport.py -q
```

预期：日志边界、双传输参数和 Header 转发测试通过。

## T5：实现单 Server 初始化、分页发现和调用生命周期

**影响文件：** `artcode/mcp/session.py`、`tests/unit/test_mcp_session.py`

**依赖任务：** T1、T3、T4

**参考资料定位：** `spec.md` F13–F19、F28、F32、F35–F37、F40–F42；`plan.md` 会话设计；MCP Cancellation 规范

**步骤：**

1. 用独立 `AsyncExitStack` 持有传输和 SDK 会话。
2. 实现传输、初始化、每页发现各 10 秒超时。
3. 分页读取工具并检测重复 Cursor。
4. 实现最多 100 个工具与 100 页。
5. 缓存活跃调用并允许同会话并发。
6. 实现 60 秒调用超时与结构化错误分类。
7. 实现取消传播、幂等关闭和不可用快速失败。
8. 覆盖并发、竞态、重复关闭和初始化不可取消。

**验证：**

```bash
python -m pytest tests/unit/test_mcp_session.py -q
```

预期：初始化、分页、并发、错误、取消和关闭测试通过。

## T6：实现多 Server Manager 与故障隔离

**影响文件：** `artcode/mcp/manager.py`、`tests/unit/test_mcp_manager.py`

**依赖任务：** T2、T5

**参考资料定位：** `spec.md` F15、F26–F27、F38–F43；`plan.md`“全局管理器”

**步骤：**

1. 使用容量 5 的信号量并发启动。
2. 用户级自动进入启动，项目级先审批。
3. 将拒绝、禁用和配置错误形成独立报告。
4. 获批后才展开环境变量。
5. 缓存 READY 会话，按配置顺序汇总报告和工具。
6. 单 Server 失败不取消其他启动任务。
7. 实现停止新调用、3 秒取消等待和单 Server 5 秒关闭。
8. 验证全失败时返回零工具但不抛出整体错误。

**验证：**

```bash
python -m pytest tests/unit/test_mcp_manager.py -q
```

预期：并发上限、审批、顺序、隔离和关闭测试通过。

## T7：实现工具 Schema 校验、Adapter 与确定性注册

**影响文件：** `artcode/mcp/adapter.py`、`artcode/tools/base.py`、`registry.py`、`tests/unit/test_mcp_adapter.py`、`test_tool_registry.py`

**依赖任务：** T1、T3、T5、T6

**参考资料定位：** `spec.md` F20–F27；`plan.md` Adapter 设计；现有 `Tool` 与 `ToolRegistry`

**步骤：**

1. 为 Tool 增加来源和审批策略，并为内置工具提供默认元数据。
2. 校验远端工具名、顶层对象 Schema、`properties` 与 `required`。
3. 为缺失描述生成回退描述。
4. 创建保存注册名、Server 名和远端原名的 Adapter。
5. 生成脱敏预览并通过 Manager 路由调用。
6. 为 Registry 增加稳定批量注册和逐工具问题收集。
7. 覆盖无效 Schema、冲突、Server 不可用和内置工具保留。

**验证：**

```bash
python -m pytest tests/unit/test_mcp_adapter.py tests/unit/test_tool_registry.py -q
```

预期：合法注册、无效工具隔离和调用路由测试通过。

## T8：改造工具模式筛选

**影响文件：** `artcode/agent/modes.py`、`loop.py`、`tests/unit/test_agent_modes.py`、`test_agent_loop.py`

**依赖任务：** T7

**参考资料定位：** `spec.md` F29–F30；`plan.md` 工具来源策略；现有 Plan 过滤逻辑

**步骤：**

1. 让策略按 Tool 来源与内置名称筛选。
2. Normal 和 Do 暴露全部工具。
3. Plan 暴露三个内置只读工具和全部 MCP 工具。
4. Plan 继续拒绝内置写工具和 Shell。
5. 证明名称前缀不能伪造来源。
6. 更新模型请求工具列表回归测试。

**验证：**

```bash
python -m pytest tests/unit/test_agent_modes.py tests/unit/test_agent_loop.py -q
```

预期：三种模式工具集合符合设计。

## T9：实现 MCP 专用审批与并发调度

**影响文件：** `artcode/agent/tools.py`、`artcode/permissions/models.py`、`tests/unit/test_agent_tools.py`

**依赖任务：** T7、T8

**参考资料定位：** `spec.md` F29–F32；`plan.md`“工具注册与调度”；当前 `ToolBatchExecutor`

**步骤：**

1. 增加外部 MCP 批次。
2. 相邻 MCP 调用组成同一批次。
3. 按模型顺序逐个执行一次性二选一审批。
4. MCP 审批不查询或写入权限规则。
5. 获准调用在全部审批完成后并发执行。
6. 拒绝调用不发送远端请求，不取消同批其他调用。
7. 结果按模型原始顺序回灌。
8. 保持内置只读并发和内置副作用串行。

**验证：**

```bash
python -m pytest tests/unit/test_agent_tools.py -q
```

预期：审批、并发、乱序响应和 ch06 权限回归通过。

## T10：实现 TUI 审批与启动报告

**影响文件：** `artcode/tui/app.py`、`render.py`、`artcode/runtime/app.py`、对应 TUI、Render、Runtime 单元测试

**依赖任务：** T1、T3、T6、T9

**参考资料定位：** `spec.md` F10、F31、F43；`plan.md`“TUI 与 Runtime”；现有 HITL 展示

**步骤：**

1. 增加项目级 Server 启动确认。
2. stdio 展示命令、参数、变量名和沙箱风险。
3. HTTP 展示 URL、Header 名和跨域凭证风险。
4. 增加 MCP 工具二选一确认。
5. 展示 Server、工具名、Plan 状态和脱敏参数。
6. 增加启动汇总与逐 Server 状态。
7. 将外部错误限制为 500 字符并规范化换行。
8. 覆盖拒绝、秘密隐藏、超长文本和零 Server。

**验证：**

```bash
python -m pytest tests/unit/test_tui_app.py tests/unit/test_render.py tests/unit/test_runtime.py -q
```

预期：审批、风险提示和启动报告测试通过。

## T11：创建真实 MCP 测试 Server 与双传输集成测试

**影响文件：** `tests/integration/fixtures/mcp_test_server.py`、`test_mcp_stdio_live.py`、`test_mcp_http_live.py`

**依赖任务：** T4、T5、T6、T7

**参考资料定位：** `spec.md` N27、AC13–AC23；官方 FastMCP 双传输示例；`tests/integration/README.md`

**步骤：**

1. 创建支持双传输的本地 FastMCP Server。
2. 提供成功、业务错误、慢调用、乱序、分页和断连能力。
3. 验证 stdio 与 HTTP 完整初始化、发现和调用。
4. 验证 HTTP 重定向及跨域敏感 Header 转发。
5. 验证 `stderr` 大量写入不阻塞且退出无遗留进程。
6. 验证一个 Server 断连不影响另一个 Server。

**验证：**

```bash
python -m pytest tests/integration/test_mcp_stdio_live.py tests/integration/test_mcp_http_live.py -q
```

预期：真实双传输和故障场景通过。

## T12：更新示例配置、用户文档和安全说明

**影响文件：** `config.example.yml`、`README.md`

**依赖任务：** T2、T4、T10

**参考资料定位：** `spec.md`“不做的事”、AC60–AC61；`plan.md` 配置示例与风险决策

**步骤：**

1. 增加双传输示例。
2. 说明两层路径、整项覆盖与变量展开。
3. 说明项目级 Server 每次启动确认。
4. 明确 stdio 不受文件工具 Workspace 沙箱保护。
5. 标注跨域重定向原样转发全部 Headers。
6. 说明工具始终确认、Plan 行为、不重连和仅支持工具。
7. 提供常见配置错误排查。

**验证：**

```bash
python -m pytest tests/unit/test_mcp_config.py -q
```

并人工确认示例能被解析且文档不含真实凭证。

## T13：接入主流程

**影响文件：** `artcode/cli.py`、`artcode/runtime/app.py`、`artcode/config.py`、`artcode/tools/registry.py`、相关单元与集成测试

**依赖任务：** T2、T6、T7、T8、T9、T10、T11、T12

**参考资料定位：** `spec.md` F38–F43；`plan.md` 启动、调用和 Runtime 接入；当前 `run_app()`

**步骤：**

1. CLI 加载两层 MCP 配置。
2. 创建 Manager，并在 AgentLoop 前完成审批、连接和发现。
3. 注册合法 Adapter。
4. 将 Manager 与报告注入 Runtime。
5. 进入输入循环前展示 MCP 状态。
6. MCP 全部失败或管理器级异常时以内置工具继续。
7. `finally` 中先异步关闭 MCP，再关闭 Seatbelt。
8. 覆盖 `--config`、零 Server、全失败、部分成功和正常退出。

**验证：**

```bash
python -m pytest tests/unit/test_runtime.py tests/unit/test_config.py tests/integration/test_mcp_agent_flow.py -q
```

预期：MCP 完整接入启动、工具列表和退出路径。

## T14：端到端验证

**影响文件：** `tests/integration/test_mcp_agent_flow.py`；必要的既有回归测试，不新增功能代码

**依赖任务：** T13

**参考资料定位：** `spec.md` AC62–AC64；`checklist.md`；现有 DeepSeek 与 ch06 live 测试

**步骤：**

1. 运行全部单元测试。
2. 运行真实 stdio、HTTP 和 Agent 集成测试。
3. 验证发现、模型调用、用户确认、Server 返回和结果回灌。
4. 验证 Plan 模式、部分拒绝、超时、断连与故障隔离。
5. 验证 stdio 退出无遗留进程。
6. 运行权限、Seatbelt、Agent Loop 和 Prompt Cache 回归。
7. 使用真实 DeepSeek API 完成 live integration test。
8. 对照 Checklist 记录实际证据。

**验证：**

```bash
python -m pytest tests/unit -q
python -m pytest tests/integration/test_mcp_stdio_live.py tests/integration/test_mcp_http_live.py tests/integration/test_mcp_agent_flow.py -q
python -m pytest tests/integration/test_permissions_flow.py tests/integration/test_agent_loop_flow.py tests/integration/test_prompt_cache_live.py -q
RUN_DEEPSEEK_LIVE=1 python -m pytest tests/integration/test_deepseek_live.py -q
```

预期：全部测试通过，真实 API 场景完成 MCP 结果回灌后的后续模型轮次。

## 执行顺序

```text
T1
├─→ T2 ───────────────┐
├─→ T3 → T4 → T5 → T6├─→ T7 → T8 → T9
│                     │              │
│                     └──────────────┼─→ T10
│                                    │
│                         T4–T7 ─────┴─→ T11
│
T2 + T4 + T10 ─→ T12
T2 + T6–T12 ───→ T13 接入主流程
T13 ───────────→ T14 端到端验证
```
