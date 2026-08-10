# ArtCode

ArtCode 是一个本地 Python CLI Coding Agent 学习项目。当前实现提供流式 DeepSeek 对话、Agent Loop、Plan/Do、本地工具、权限审批、macOS Seatbelt、MCP、上下文压缩、会话恢复和长期记忆。

## 安装与启动

建议使用 Python 3.11 或更高版本的虚拟环境：

```bash
python -m venv .venv
.venv/bin/python -m pip install -e '.[test]'
mkdir -p ~/.artcode
cp config.example.yml ~/.artcode/config.yml
```

编辑 `~/.artcode/config.yml`，填入真实 DeepSeek API Key，然后在已有项目目录启动：

```bash
.venv/bin/artcode --workspace /path/to/project
```

`python -m artcode` 与 `artcode` 使用同一入口。默认恢复当前 Workspace 最近的可写会话；也可以明确选择：

```bash
.venv/bin/artcode --workspace /path/to/project --new
.venv/bin/artcode --workspace /path/to/project --resume 20260810-120000-a1b2
```

`--config /path/to/config.yml` 可以覆盖默认配置位置。`--new` 与 `--resume` 互斥。

## 配置

最小配置如下：

```yaml
protocol: openai
model: deepseek-v4-flash
base_url: https://api.deepseek.com
api_key: your-real-api-key

thinking:
  enabled: false

context:
  window_tokens: 1000000
```

配置采用严格字段校验，未知字段会阻止启动。Thinking 关闭时请求会显式关闭 Thinking；开启时固定使用 high 强度。上下文窗口默认 1,000,000 Token，可显式配置为 200,000–1,000,000，压缩阈值随窗口等比例变化。

用户级 MCP Server 写在 `~/.artcode/config.yml`，项目级 Server 写在 `<workspace>/.artcode/config.yml`。支持 `stdio` 与 `streamable_http`；单个 Server 的配置、连接或调用失败不会阻断内置工具和其他 Server。

## 使用方式

普通输入进入无默认迭代上限的 Agent Loop。内置工具包括：

- `read_file`、`find_files`、`search_text`
- `write_file`、`edit_file`
- `run_command`

常用本地命令：

- `/plan <任务>`：只提供只读工具，生成计划。
- `/do`：执行最近计划。
- `/status`：显示脱敏运行快照，不调用模型或改变会话状态。
- `/permission`、`/sandbox`：查看或切换权限与 Shell 策略。
- `/compact`：手动压缩较早的非用户历史。
- `/sessions`、`/memory`：查看会话和长期记忆状态。
- `/clear`、`/help`、`/exit`。

文件工具只允许访问当前 Workspace。新文件可自动创建 Workspace 内缺失的多级父目录；越界路径、敏感路径和在审批后改变目标的路径会被拒绝。精确编辑要求原文唯一匹配，写已有文件默认拒绝覆盖。

Shell 默认通过 macOS Seatbelt 运行，并禁止公网、回环和本地监听网络访问。`/sandbox off` 需要再次确认。域名白名单、动态网络授权和代理不在当前实现范围内；网络策略保持集中式全拒绝。

## 本地数据

```text
~/.artcode/
├── config.yml
├── instructions.md
├── permissions.yml
└── memory/

<workspace>/
├── ARTCODE.md
├── permissions.local.yml
└── .artcode/
    ├── config.yml
    ├── instructions.md
    ├── permissions.yml
    ├── sessions/*.jsonl
    ├── memory/
    └── context/
```

会话消息同步追加为 JSONL。单条完整坏记录会跳过，不完整尾部会截断，破坏工具协议的记录只恢复安全前缀。长期记忆使用可编辑 Markdown 文件和可重建索引，由自然完成轮次的不可变副本在后台串行更新；失败不会改变当前回复或会话。

这些数据不会同步到云端，也不加密，可能包含对话和代码片段。删除活动 Workspace 的会话或记忆前应先退出 ArtCode。

## 当前架构

生产依赖只在 `Bootstrap` 中组装，并由统一异步生命周期管理资源：

```text
__main__ → cli → Bootstrap → ArtCodeRuntime → AgentLoop
                         ├─ RequestPreparer → ContextManager
                         ├─ DeepSeekChatProvider
                         ├─ ToolExecutionService → PermissionService
                         │                        → WorkspaceFileAccess / ProcessSupervisor
                         ├─ SessionService / DurablePromptSource / MemoryService
                         └─ McpManager / PromptToolkitTui / CommandDispatcher
```

`RuntimeState` 是权限、Shell、显示模式和最近 Token 用量的进程内权威来源；请求级工具上下文使用其不可变权限快照。Runtime 只协调交互，不隐式创建第二套生产组件。

## Agent 评测

`artcode-eval` 是与被测 Agent 分离的本地 Harness。它从版本化 Benchmark 创建独立 Workspace，经同一个 `Bootstrap/AgentLoop` 执行任务，记录脱敏 Trace，以文件、命令、Trace 和指标 Verifier 判断结果，并输出 JSON/Markdown 报告。可选 LLM Judge 只做语义评分，不能覆盖确定性失败。

```bash
.venv/bin/artcode-eval validate benchmarks/agent_eval/benchmark.yml
.venv/bin/artcode-eval run benchmarks/agent_eval/benchmark.yml \
  --config ~/.artcode/config.yml \
  --output-dir artcode-eval-runs
.venv/bin/artcode-eval compare BASELINE/report.json CANDIDATE/report.json \
  --output-dir artcode-eval-compare
```

官方 Benchmark 覆盖编码结果、危险命令权限拒绝和大工具结果上下文外置。每次尝试保留独立 Trace、Verifier 证据、Workspace 变更摘要及 Token、轮次、工具调用、重复调用、权限拒绝、上下文节省和耗时指标。若需 Judge，另传 `--judge-config`；建议使用与被测 Agent 独立的模型配置。

## 验证

```bash
.venv/bin/python -m pytest -q -m "not live and not slow"
.venv/bin/python -m pytest tests/property tests/fault -q
.venv/bin/python -m pytest tests/live -q -m live -rs
.venv/bin/python -m pytest tests/soak -q -m soak
.venv/bin/python -m pytest tests/evaluation tests/integration/test_evaluation_agent_flow.py -q
.venv/bin/python tests/tools/verify_test_inventory.py --baseline 413
.venv/bin/python -m build
```

真实测试会使用本机 DeepSeek 配置，并覆盖真实 Seatbelt、进程树、MCP、CLI 和多进程 Session。缺少配置或系统能力应明确报告为环境阻塞，不能作为通过；DeepSeek 调用不会因为成本而跳过。
