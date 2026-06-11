# ch03：工具系统 Checklist

> 每一项都通过运行测试、启动程序或观察文件变化来验证，聚焦可观测行为。

## 配置与启动

- [x] 启动状态显示 `ch03：工具系统`（验证：运行 `python -m artcode`，观察启动面板章节名）。
- [x] 缺少 `tools.allowed_dirs` 时使用默认允许目录 `/Users/arthalter/Work/ArtCode/实验场`（验证：运行 `pytest tests/unit/test_config.py`，观察默认配置测试通过）。
- [x] 默认允许目录不存在时会自动创建（验证：在临时配置测试中删除目录后加载配置，观察目录存在）。
- [x] `tools.allowed_dirs` 包含相对路径时启动失败并提示配置错误（验证：运行 `pytest tests/unit/test_config.py`，观察相对路径用例通过）。
- [x] `tools.allowed_dirs` 包含空字符串时启动失败并提示配置错误（验证：运行 `pytest tests/unit/test_config.py`，观察空路径用例通过）。
- [x] `tools.allowed_dirs` 包含非字符串值时启动失败并提示配置错误（验证：运行 `pytest tests/unit/test_config.py`，观察类型错误用例通过）。
- [x] 启动状态展示允许目录摘要且不泄露完整 API key（验证：运行渲染单元测试，观察 allowed_dirs 出现且 api_key 只显示脱敏值）。
- [x] `artcode.example.yaml` 包含 `tools.allowed_dirs` 示例（验证：打开示例配置，观察包含默认实验场绝对路径）。

## 工具注册

- [x] 默认工具注册中心包含 `read_file`（验证：运行 `pytest tests/unit/test_tool_registry.py`）。
- [x] 默认工具注册中心包含 `write_file`（验证：运行 `pytest tests/unit/test_tool_registry.py`）。
- [x] 默认工具注册中心包含 `edit_file`（验证：运行 `pytest tests/unit/test_tool_registry.py`）。
- [x] 默认工具注册中心包含 `run_command`（验证：运行 `pytest tests/unit/test_tool_registry.py`）。
- [x] 默认工具注册中心包含 `find_files`（验证：运行 `pytest tests/unit/test_tool_registry.py`）。
- [x] 默认工具注册中心包含 `search_text`（验证：运行 `pytest tests/unit/test_tool_registry.py`）。
- [x] 注册中心按已知工具名能查到工具对象（验证：运行 `pytest tests/unit/test_tool_registry.py`）。
- [x] 注册中心查找未知工具时返回可处理的错误路径（验证：运行 `pytest tests/unit/test_tool_registry.py`）。
- [x] 导出的工具列表符合 OpenAI-compatible function tools 形状（验证：运行 `pytest tests/unit/test_tool_registry.py`，断言每项包含 `type: function`、名称、描述和参数 Schema）。

## 路径边界

- [x] 允许目录内的文件路径可以解析成功（验证：运行 `pytest tests/unit/test_tool_policy.py`）。
- [x] 允许目录外的绝对路径会被拒绝（验证：运行 `pytest tests/unit/test_tool_policy.py`）。
- [x] 使用 `../` 绕出允许目录的路径会被拒绝（验证：运行 `pytest tests/unit/test_tool_policy.py`）。
- [x] 写新文件时父目录必须位于允许目录内（验证：运行 `pytest tests/unit/test_tool_policy.py`）。
- [x] 所有文件工具访问允许目录外路径时都不读取、不写入、不修改文件（验证：运行 `pytest tests/unit/test_file_tools.py`）。
- [x] 命令工具的工作目录必须位于允许目录内（验证：运行 `pytest tests/unit/test_command_tool.py`）。

## 文件工具

- [x] `read_file` 能读取允许目录内 UTF-8 文本文件（验证：运行 `pytest tests/unit/test_file_tools.py`）。
- [x] `read_file` 支持可选行范围读取（验证：运行 `pytest tests/unit/test_file_tools.py`，观察只返回指定行）。
- [x] `read_file` 遇到无法 UTF-8 解码的文件返回结构化错误（验证：运行 `pytest tests/unit/test_file_tools.py`）。
- [x] 工具结果超过 20KB 时被截断并标记 `truncated`（验证：运行 `pytest tests/unit/test_tool_results.py tests/unit/test_file_tools.py`）。
- [x] `write_file` 能在允许目录内写入新文本文件（验证：运行 `pytest tests/unit/test_file_tools.py`，观察目标文件内容）。
- [x] `write_file` 遇到已有文件且未声明覆盖时不覆盖文件（验证：运行 `pytest tests/unit/test_file_tools.py`）。
- [x] `write_file` 声明覆盖时可以覆盖允许目录内已有文件（验证：运行 `pytest tests/unit/test_file_tools.py`）。
- [x] `edit_file` 在原文严格匹配一次时完成替换（验证：运行 `pytest tests/unit/test_file_tools.py`，观察文件内容变化）。
- [x] `edit_file` 在原文匹配零次时不修改文件并返回结构化错误（验证：运行 `pytest tests/unit/test_file_tools.py`）。
- [x] `edit_file` 在原文匹配多次时不修改文件并返回结构化错误（验证：运行 `pytest tests/unit/test_file_tools.py`）。
- [x] `find_files` 使用 glob 返回允许目录内匹配文件（验证：运行 `pytest tests/unit/test_file_tools.py`）。
- [x] `find_files` 不返回允许目录外文件（验证：运行 `pytest tests/unit/test_file_tools.py`）。
- [x] `search_text` 使用普通文本匹配返回路径、行号和匹配行摘要（验证：运行 `pytest tests/unit/test_file_tools.py`）。
- [x] `search_text` 不使用正则语义解释搜索词（验证：运行 `pytest tests/unit/test_file_tools.py`，观察特殊字符按普通文本匹配）。
- [x] `search_text` 遇到无法解码文件时不会崩溃（验证：运行 `pytest tests/unit/test_file_tools.py`）。

## 命令工具

- [x] `run_command` 执行前能生成包含命令内容的确认摘要（验证：运行 `pytest tests/unit/test_command_tool.py tests/unit/test_render.py`）。
- [x] `run_command` 在允许目录内执行成功命令并返回 stdout（验证：运行 `pytest tests/unit/test_command_tool.py`）。
- [x] `run_command` 对非零退出命令返回 exit code、stdout 和 stderr 摘要（验证：运行 `pytest tests/unit/test_command_tool.py`）。
- [x] `run_command` 超过 10 秒时返回 `command_timeout`（验证：运行 `pytest tests/unit/test_command_tool.py`）。
- [x] 明显危险命令在执行前被拦截（验证：运行 `pytest tests/unit/test_command_tool.py`）。
- [x] 被拦截的危险命令不会实际执行（验证：运行 `pytest tests/unit/test_command_tool.py`，观察目标文件或目录未变化）。
- [x] 命令输出超过 20KB 时被截断并标记 `truncated`（验证：运行 `pytest tests/unit/test_command_tool.py`）。

## Provider 与工具调用解析

- [x] 首次模型请求携带工具列表和自动工具选择（验证：运行 `pytest tests/unit/test_openai_provider.py`，观察请求体断言通过）。
- [x] 最终总结请求不携带工具列表（验证：运行 `pytest tests/unit/test_openai_provider.py tests/unit/test_runtime.py`）。
- [x] 流式 `tool_calls` 参数碎片能按 index 拼接成完整工具调用（验证：运行 `pytest tests/unit/test_tool_calls.py`）。
- [x] JSON 参数碎片拼接后仍解析失败时返回结构化参数错误（验证：运行 `pytest tests/unit/test_runtime.py`）。
- [x] Provider 能产出 `tool_calls` 事件（验证：运行 `pytest tests/unit/test_provider_events.py tests/unit/test_openai_provider.py`）。
- [x] 模型没有请求工具时仍能收到并展示普通 `content_delta`（验证：运行 `pytest tests/unit/test_runtime.py`）。

## Conversation 与 Runtime

- [x] 普通对话路径仍会写入 user 和 assistant 消息（验证：运行 `pytest tests/unit/test_runtime.py tests/unit/test_context.py`）。
- [x] 单工具调用路径会写入 assistant tool_call 消息（验证：运行 `pytest tests/unit/test_context.py tests/unit/test_runtime.py`）。
- [x] 工具执行成功后会写入 tool result 消息（验证：运行 `pytest tests/unit/test_context.py tests/unit/test_runtime.py`）。
- [x] 用户拒绝有副作用工具时不执行工具，并写入 `user_denied` 工具结果（验证：运行 `pytest tests/unit/test_runtime.py`）。
- [x] 工具参数错误时不执行工具，并写入结构化错误结果（验证：运行 `pytest tests/unit/test_runtime.py`）。
- [x] 工具不存在时不执行工具，并写入结构化错误结果（验证：运行 `pytest tests/unit/test_runtime.py`）。
- [x] 同一轮多个工具调用时不执行任何工具（验证：运行 `pytest tests/unit/test_runtime.py`）。
- [x] 同一轮多个工具调用时每个 tool call 都有对应错误 tool result（验证：运行 `pytest tests/unit/test_context.py tests/unit/test_runtime.py`）。
- [x] 工具结果回灌后会再次请求模型生成最终自然语言回复（验证：运行 `pytest tests/unit/test_runtime.py`）。
- [x] 最终总结半截取消时不写入 assistant 消息（验证：运行 `pytest tests/unit/test_runtime.py`）。
- [x] 工具结果只保存在本次运行内 Conversation Context，不生成会话文件（验证：运行测试后检查项目目录没有新增会话记录文件）。

## TUI 行为

- [x] 写文件工具执行前显示工具名、参数摘要和影响路径（验证：运行 `pytest tests/unit/test_render.py`）。
- [x] 改文件工具执行前显示工具名、参数摘要和影响路径（验证：运行 `pytest tests/unit/test_render.py`）。
- [x] 执行命令工具执行前显示工具名、参数摘要和命令内容（验证：运行 `pytest tests/unit/test_render.py`）。
- [x] 用户输入 `yes` 或 `y` 会确认执行（验证：运行 TUI 确认输入单元测试）。
- [x] 用户输入 `no` 或 `n` 会拒绝执行（验证：运行 TUI 确认输入单元测试）。
- [x] 工具执行成功后 TUI 显示成功摘要和返回大小（验证：运行 `pytest tests/unit/test_render.py`）。
- [x] 工具执行失败后 TUI 显示失败摘要和错误类别（验证：运行 `pytest tests/unit/test_render.py`）。
- [x] 工具结果被截断时 TUI 摘要显示已截断（验证：运行 `pytest tests/unit/test_render.py`）。
- [x] TUI 不直接打印完整工具输出内容（验证：运行 `pytest tests/unit/test_render.py`，断言完整 content 不出现在渲染输出中）。

## 编译与测试

- [x] 全部单元测试通过（验证：运行 `pytest tests/unit`）。
- [x] 默认测试套件通过或明确说明真实 API 失败原因（验证：运行 `pytest`）。
- [x] 配置、工具、Provider、Conversation、Runtime、TUI 相关测试均被执行（验证：查看 `pytest tests/unit -q` 输出包含对应测试文件）。
- [x] 真实集成测试文档说明网络依赖和 API 额度消耗（验证：打开 `tests/integration/README.md`）。
- [x] README 说明 ch03 工具系统只操作允许目录并对副作用工具确认（验证：打开 `README.md`）。

## 端到端场景

- [x] 场景 1：用户要求写入实验场内新文件 → 模型请求 `write_file` → TUI 请求确认 → 用户确认 → 文件被写入 → 模型给出最终总结（验证：运行本地交互或模拟 Provider 端到端测试，观察文件内容和最终回复）。
- [x] 场景 2：用户要求读取实验场外文件 → 模型请求读文件 → ArtCode 拒绝越界访问 → 模型解释无法读取（验证：运行模拟 Provider 端到端测试，观察没有读取目标文件且最终回复说明路径越界）。
- [x] 场景 3：用户拒绝写文件 → ArtCode 不写入文件 → 模型说明操作被拒绝（验证：运行模拟 Provider 端到端测试，观察目标文件不存在或内容未变）。
- [x] 场景 4：模型同一轮请求多个工具 → ArtCode 不执行任何工具 → 每个 tool call 都收到错误结果 → 模型说明本章只支持单工具调用（验证：运行 Runtime 端到端单元测试）。
- [x] 场景 5：用户要求执行超过 10 秒的命令 → ArtCode 返回超时错误 → 模型说明命令超时（验证：运行命令工具或模拟 Provider 端到端测试）。
x