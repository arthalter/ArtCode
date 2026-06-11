# ch03：工具系统 Tasks

## 文件清单

| 操作 | 文件 | 职责 |
|---|---|---|
| 修改 | `artcode/config.py` | 增加工具配置、允许目录解析、默认实验目录创建、ch03 启动状态 |
| 修改 | `artcode.example.yaml` | 增加 `tools.allowed_dirs` 示例 |
| 修改 | `artcode/prompts.py` | 更新 ch03 工具系统提示 |
| 新建 | `artcode/tools/__init__.py` | 导出工具系统公共入口 |
| 新建 | `artcode/tools/base.py` | 定义 Tool、ToolPreview、PreparedToolCall、ToolExecutionContext |
| 新建 | `artcode/tools/results.py` | 定义 ToolResult、错误结果、拒绝结果、截断逻辑 |
| 新建 | `artcode/tools/policy.py` | 实现允许目录路径解析和边界检查 |
| 新建 | `artcode/tools/registry.py` | 实现 ToolRegistry、默认六工具注册、OpenAI tools 导出 |
| 新建 | `artcode/tools/file_tools.py` | 实现 read_file、write_file、edit_file、find_files、search_text |
| 新建 | `artcode/tools/command_tool.py` | 实现 run_command、危险命令拦截和超时执行 |
| 新建 | `artcode/providers/tool_calls.py` | 实现 ToolCall 和流式参数碎片聚合 |
| 修改 | `artcode/providers/events.py` | 增加 tool_calls 事件 |
| 修改 | `artcode/providers/base.py` | 扩展 Provider 接口，支持可选 tools |
| 修改 | `artcode/providers/openai_compatible.py` | 请求体接入 tools，解析流式 tool_calls |
| 修改 | `artcode/conversation/context.py` | 支持 assistant tool_call 消息和 tool result 消息 |
| 修改 | `artcode/runtime/app.py` | 编排单步工具调用、确认、回灌和最终总结 |
| 修改 | `artcode/tui/app.py` | 增加工具确认输入 |
| 修改 | `artcode/tui/render.py` | 展示允许目录、工具预览和结果摘要 |
| 修改 | `artcode/cli.py` | 创建工具注册中心和工具执行上下文并接入 Runtime |
| 修改 | `README.md` | 更新 ch03 简介和安全边界 |
| 修改 | `tests/unit/test_config.py` | 覆盖工具配置解析 |
| 新建 | `tests/unit/test_tool_policy.py` | 覆盖允许目录边界 |
| 新建 | `tests/unit/test_tool_results.py` | 覆盖结构化结果和截断 |
| 新建 | `tests/unit/test_tool_registry.py` | 覆盖工具注册和 OpenAI tools 导出 |
| 新建 | `tests/unit/test_file_tools.py` | 覆盖文件类工具 |
| 新建 | `tests/unit/test_command_tool.py` | 覆盖命令工具 |
| 新建 | `tests/unit/test_tool_calls.py` | 覆盖工具调用碎片拼接 |
| 修改 | `tests/unit/test_provider_events.py` | 覆盖 tool_calls 事件校验 |
| 修改 | `tests/unit/test_openai_provider.py` | 覆盖 tools 请求体和 tool_calls SSE 解析 |
| 修改 | `tests/unit/test_context.py` | 覆盖工具消息写入 |
| 修改 | `tests/unit/test_runtime.py` | 覆盖单步工具编排 |
| 修改 | `tests/unit/test_render.py` | 覆盖工具摘要展示 |
| 修改 | `tests/integration/test_deepseek_live.py` | 补充或保留真实 API smoke 验证 |
| 修改 | `tests/integration/README.md` | 说明 ch03 工具调用验证边界 |

## T1: 配置工具允许目录

**影响文件：** `artcode/config.py`、`artcode.example.yaml`、`tests/unit/test_config.py`

**依赖任务：** 无

**参考资料定位：** `spec.md` F4-F5、N1-N3、AC1-AC3；`plan.md` 的 `ToolConfig` 与 `artcode.config`

**步骤：**

1. 定义工具配置结构，保存允许目录列表。
2. 将章节名更新为 `ch03：工具系统`。
3. 在配置解析中支持 `tools.allowed_dirs`。
4. 缺少工具配置时使用默认实验目录。
5. 校验允许目录必须是非空绝对路径。
6. 启动阶段创建不存在的允许目录，并在失败时抛出配置错误。
7. 安全启动状态中增加允许目录摘要。
8. 更新示例配置文件。
9. 补充配置单元测试。

**验证：** 运行 `pytest tests/unit/test_config.py`，期望默认目录、非法相对路径、空路径、非字符串路径和安全状态测试通过。

## T2: 更新系统提示

**影响文件：** `artcode/prompts.py`、`tests/unit/test_context.py`

**依赖任务：** T1

**参考资料定位：** `spec.md` F18；`plan.md` 的启动阶段和普通/工具路径说明

**步骤：**

1. 将 ch02 纯对话提示更新为 ch03 工具系统提示。
2. 在提示中说明模型可以使用六个工具。
3. 在提示中说明所有工具受允许目录限制。
4. 在提示中说明单轮最多请求一个工具。
5. 在提示中说明工具失败后应根据结构化错误回复用户。
6. 更新上下文初始化测试，确认 system prompt 不再声称 ArtCode 不能执行工具。

**验证：** 运行 `pytest tests/unit/test_context.py`，期望 system prompt 与上下文初始化测试通过。

## T3: 建立工具基础抽象、结果和路径策略

**影响文件：** `artcode/tools/__init__.py`、`artcode/tools/base.py`、`artcode/tools/results.py`、`artcode/tools/policy.py`、`tests/unit/test_tool_results.py`、`tests/unit/test_tool_policy.py`

**依赖任务：** T1

**参考资料定位：** `spec.md` F1、F5、F8-F10；`plan.md` 的 `ToolExecutionContext`、`AllowedPathPolicy`、`ToolResult`、`ToolPreview`、`PreparedToolCall`

**步骤：**

1. 创建 `artcode/tools/` 包。
2. 定义工具执行上下文、工具预览、预检成功对象和 Tool 协议。
3. 定义结构化工具结果、成功结果、错误结果和拒绝结果。
4. 实现 UTF-8 字节上限截断，保证截断后仍是合法字符串。
5. 实现允许目录策略，支持已有路径解析、新文件路径解析、边界判断。
6. 覆盖路径在允许目录内、路径越界、`../` 绕出、写新文件父目录越界等测试。
7. 覆盖工具结果 JSON 序列化和 20KB 截断测试。

**验证：** 运行 `pytest tests/unit/test_tool_results.py tests/unit/test_tool_policy.py`，期望所有结果和路径边界测试通过。

## T4: 实现工具注册中心

**影响文件：** `artcode/tools/registry.py`、`tests/unit/test_tool_registry.py`

**依赖任务：** T3

**参考资料定位：** `spec.md` F2-F3、AC4；`plan.md` 的 `ToolRegistry`

**步骤：**

1. 实现工具注册中心，支持注册、按名查找和按名强制获取。
2. 处理重复注册或未知工具的错误结果路径。
3. 实现 OpenAI-compatible function tools 导出。
4. 创建默认注册中心入口。
5. 在默认注册中心中预留六个工具注册位置。
6. 补充测试确认六个工具名存在。
7. 补充测试确认导出格式包含 `type: function`、工具名、描述和参数 Schema。

**验证：** 运行 `pytest tests/unit/test_tool_registry.py`，期望注册、查找和导出测试通过。

## T5: 实现文本文件读写和精确修改工具

**影响文件：** `artcode/tools/file_tools.py`、`artcode/tools/registry.py`、`tests/unit/test_file_tools.py`

**依赖任务：** T3、T4

**参考资料定位：** `spec.md` F3、F5-F12、AC6-AC10；`plan.md` 的 `artcode.tools.file_tools`

**步骤：**

1. 实现 `read_file` 参数 Schema、预检和执行。
2. 支持整文件读取和可选行范围读取。
3. 读取 UTF-8 失败时返回 `decode_error`。
4. 实现 `write_file` 参数 Schema、预检和执行。
5. 默认拒绝覆盖已有文件；只有显式覆盖意图才允许继续。
6. 实现 `edit_file` 参数 Schema、预检和执行。
7. 使用严格原文唯一匹配替换；零次或多次匹配都不改文件。
8. 将三个工具接入默认注册中心。
9. 补充允许目录内成功、越界拒绝、覆盖拒绝、唯一匹配失败、文本截断等测试。

**验证：** 运行 `pytest tests/unit/test_file_tools.py tests/unit/test_tool_registry.py`，期望文件工具行为和注册测试通过。

## T6: 实现找文件和搜文本工具

**影响文件：** `artcode/tools/file_tools.py`、`artcode/tools/registry.py`、`tests/unit/test_file_tools.py`

**依赖任务：** T5

**参考资料定位：** `spec.md` F3、F5、F9-F10、AC13-AC14；`plan.md` 的 `find_files` 与 `search_text`

**步骤：**

1. 实现 `find_files` 参数 Schema、预检和执行。
2. 使用 glob 模式查找文件，只返回允许目录内路径。
3. 对查找结果应用 20KB 截断。
4. 实现 `search_text` 参数 Schema、预检和执行。
5. 使用普通文本匹配，不使用正则。
6. 跳过无法 UTF-8 解码的文件，并在结果摘要中保留可理解说明。
7. 返回文件路径、行号和匹配行摘要。
8. 将两个工具接入默认注册中心。
9. 补充 glob 查找、越界不返回、文本搜索、跳过二进制或不可解码文件测试。

**验证：** 运行 `pytest tests/unit/test_file_tools.py tests/unit/test_tool_registry.py`，期望查找和搜索测试通过。

## T7: 实现命令执行工具

**影响文件：** `artcode/tools/command_tool.py`、`artcode/tools/registry.py`、`tests/unit/test_command_tool.py`

**依赖任务：** T3、T4

**参考资料定位：** `spec.md` F5-F8、F13、AC11-AC12；`plan.md` 的 `artcode.tools.command_tool`

**步骤：**

1. 实现 `run_command` 参数 Schema、预检和执行。
2. 校验 shell 命令必须是非空字符串。
3. 支持可选工作目录，并保证工作目录在允许目录内。
4. 实现基础危险命令拦截。
5. 使用异步 subprocess 在允许目录内执行命令。
6. 使用 10 秒超时，超时后返回 `command_timeout`。
7. 捕获 stdout、stderr 和 exit code，并包装为结构化结果。
8. 对命令输出应用 20KB 截断。
9. 将命令工具接入默认注册中心。
10. 补充成功命令、非零退出、越界 cwd、危险命令、超时测试。

**验证：** 运行 `pytest tests/unit/test_command_tool.py tests/unit/test_tool_registry.py`，期望命令工具测试通过。

## T8: 扩展 Provider 工具调用解析

**影响文件：** `artcode/providers/base.py`、`artcode/providers/events.py`、`artcode/providers/tool_calls.py`、`artcode/providers/openai_compatible.py`、`tests/unit/test_provider_events.py`、`tests/unit/test_tool_calls.py`、`tests/unit/test_openai_provider.py`

**依赖任务：** T4

**参考资料定位：** `spec.md` F2、F14-F15、AC15-AC17；`plan.md` 的 Provider 事件、`ToolCallAccumulator`、`artcode.providers.openai_compatible`

**步骤：**

1. 扩展 Provider 协议，支持可选 tools 参数。
2. 增加 `tool_calls` Provider 事件类型和校验。
3. 实现 `ToolCall` 数据结构。
4. 实现按 index 聚合工具调用参数碎片的 accumulator。
5. 请求体传入 tools 时加入 `tools` 和自动工具选择。
6. 最终总结请求不传 tools 时不携带工具字段。
7. SSE 解析支持 `delta.tool_calls`。
8. 在流结束前累计到工具调用时产出一次 `tool_calls` 事件。
9. 补充事件格式、碎片拼接、请求体和 SSE 解析测试。

**验证：** 运行 `pytest tests/unit/test_provider_events.py tests/unit/test_tool_calls.py tests/unit/test_openai_provider.py`，期望 Provider 工具调用相关测试通过。

## T9: 扩展 Conversation Context 工具消息

**影响文件：** `artcode/conversation/context.py`、`artcode/conversation/__init__.py`、`tests/unit/test_context.py`

**依赖任务：** T3、T8

**参考资料定位：** `spec.md` F16、AC18；`plan.md` 的 `ConversationContext`

**步骤：**

1. 将消息类型从纯字符串消息扩展为通用消息对象。
2. 保留 user 和普通 assistant 消息追加能力。
3. 新增 assistant tool_call 消息写入。
4. 新增 tool result 消息写入。
5. 确保多个 tool call 时能写入对应数量的 tool result。
6. 确保导出消息仍返回深拷贝。
7. 补充普通对话兼容、工具调用消息、工具结果消息、多工具错误回灌消息测试。

**验证：** 运行 `pytest tests/unit/test_context.py`，期望普通消息和工具消息测试通过。

## T10: 扩展 TUI 工具展示和确认

**影响文件：** `artcode/tui/app.py`、`artcode/tui/render.py`、`artcode/tui/__init__.py`、`tests/unit/test_render.py`

**依赖任务：** T1、T3

**参考资料定位：** `spec.md` F6-F7、F17、AC1、AC8、AC11、AC19；`plan.md` 的 `artcode.tui`

**步骤：**

1. 启动状态展示 ch03 章节和允许目录摘要。
2. 渲染工具预览，包含工具名、参数摘要和影响路径或命令。
3. 实现工具确认输入，只接受 `yes/no` 和 `y/n`。
4. 渲染工具结果摘要，包含成功/失败、结果大小和截断状态。
5. 确保完整工具输出不会直接打印到 TUI。
6. 补充启动状态、工具预览、结果摘要、完整输出不泄露测试。

**验证：** 运行 `pytest tests/unit/test_render.py`，期望 TUI 展示测试通过。

## T11: 接入主流程

**影响文件：** `artcode/runtime/app.py`、`artcode/cli.py`、`tests/unit/test_runtime.py`

**依赖任务：** T1-T10

**参考资料定位：** `spec.md` F14-F17、AC5、AC8、AC16-AC18；`plan.md` 的 Runtime 单步工具编排和模块交互

**步骤：**

1. Runtime 增加工具注册中心和工具执行上下文依赖。
2. 首次模型请求传入默认工具列表。
3. 普通文本回复路径保持 ch02 行为。
4. 单工具调用路径写入 assistant tool_call 消息。
5. 解析工具 JSON 参数，解析失败时生成结构化错误。
6. 查找工具，工具不存在时生成结构化错误。
7. 调用工具 `prepare`，预检失败时回灌结构化错误。
8. 有副作用工具执行前调用 TUI 确认。
9. 用户拒绝时生成 `user_denied` 工具结果。
10. 用户确认后执行工具并写入 tool result 消息。
11. 多工具调用时不执行任何工具，为每个 tool call 写入 `too_many_tool_calls` 结果。
12. 工具结果回灌后发起最终总结请求，且不传 tools。
13. 将 CLI 入口改为创建工具注册中心和工具执行上下文后启动 Runtime。
14. 补充普通对话、单工具成功、拒绝确认、参数错误、多工具错误、最终总结不带 tools 测试。

**验证：** 运行 `pytest tests/unit/test_runtime.py`，期望 Runtime 编排测试通过；再运行 `pytest tests/unit`，期望全部单元测试通过。

## T12: 端到端验证

**影响文件：** `tests/integration/test_deepseek_live.py`、`tests/integration/README.md`、`README.md`、`tasks.md`

**依赖任务：** T11

**参考资料定位：** `spec.md` AC20-AC21；`plan.md` 的测试策略和端到端约定

**步骤：**

1. 更新 README，说明 ch03 工具系统、安全实验目录和用户确认边界。
2. 更新集成测试说明，提醒真实 API、网络依赖和额度消耗。
3. 保留 ch02 真实对话 smoke 验证。
4. 增加或准备 ch03 工具调用 smoke 验证，限定只操作允许目录内测试文件。
5. 如果真实模型工具调用不稳定，用模拟 Provider 完成确定性端到端测试，并在集成说明中记录限制。
6. 运行完整测试套件。
7. 手动执行一次“写入实验场文件 → 确认 → 工具执行 → 最终总结”的本地验证。
8. 记录实际验证命令和结果。

**验证：** 在存在有效 `artcode.yaml` 和网络可用时运行 `pytest`，期望单元测试和集成测试通过；若真实工具调用 smoke 因模型或网络不稳定无法作为默认测试，则至少用模拟 Provider 通过端到端测试，并说明原因。

## 执行顺序

```text
T1 → T2
  ↘
   T3 → T4 → T5 → T6
          ↘      ↘
           T7      T8 → T9
                    ↘
                     T10 → T11 → T12
```

## 覆盖检查

- 配置与允许目录：T1、T3、T10、T11、T12。
- 统一工具接口与注册中心：T3、T4。
- 六个核心工具：T5、T6、T7。
- Provider 工具调用解析：T8。
- Conversation 工具结果回灌：T9、T11。
- TUI 确认与摘要：T10、T11。
- 接入主流程：T11。
- 端到端验证：T12。
