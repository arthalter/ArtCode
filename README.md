# ArtCode

ArtCode 是一个本地 Python CLI Coding Agent 学习项目。当前实现提供流式 OpenAI-compatible 对话、Agent Loop、Plan/Do、本地工具、权限审批、macOS Seatbelt、MCP、上下文压缩、会话恢复和长期记忆。

## 安装与启动

建议使用 Python 3.11 或更高版本的虚拟环境：

```bash
python -m venv .venv
.venv/bin/python -m pip install -e '.[test]'
mkdir -p ~/.artcode
cp config.example.yml ~/.artcode/config.yml
```

编辑 `~/.artcode/config.yml`，填入模型服务配置，然后在已有项目目录启动：

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
model: your-model-id
base_url: https://your-openai-compatible-endpoint/v1
api_key: your-real-api-key

thinking:
  enabled: false

context:
  window_tokens: 200000
```

配置采用严格字段校验，未知字段会阻止启动。模型、服务地址和 API Key 均为必填项。不同模型的推理参数兼容性由 Provider 处理；上下文窗口默认 1,000,000 Token，可显式配置为 200,000–1,000,000，压缩阈值随窗口等比例变化。

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
- `/tasks`、`/task <task-id>`、`/task-cancel <task-id>`：查看、读取或取消子 Agent 任务。
- `/clear`、`/help`、`/exit`。

## 子 Agent 与隔离 Worktree

主 Agent 可使用 `agent` 工具把能够独立完成的工作交给子 Agent。工具有两种创建方式：

- `definition`：必须指定角色，从干净对话开始；可以前台等待，超过 120 秒会继续在后台运行。
- `fork`：冻结创建瞬间的主对话快照，可选择叠加角色；始终立即作为后台任务返回。

角色文件放在项目的 `<workspace>/.artcode/agents/*.md` 或用户目录 `~/.artcode/agents/*.md`。项目角色优先于用户角色；同名高优先级文件无效时会阻止回退到低优先级版本。最小角色示例：

```md
---
name: reviewer
description: 只读代码审查
tools:
  allow: [read_file, find_files, search_text]
  deny: []
model: inherit
max_rounds: 30
permission_mode: default
isolation: none
---

检查指定改动，指出可验证的问题和建议；不要修改文件。
```

角色 frontmatter 固定包含 `name`、`description`、`tools`、`model`、`max_rounds`、`permission_mode`、`isolation` 七个字段；未知字段会使该角色失效。允许 `write_file`、`edit_file` 或 `run_command` 的角色必须写明 `isolation: worktree`。这类任务从入队时的 Git 提交创建位于 `<workspace>/.artcode/worktrees/` 的独立目录，不会复制主工作区未提交修改；有未提交修改或尚未安全推送的本地提交会保留，ArtCode 不会自动合并、推送或丢弃成果。

前台任务执行时按 `Ctrl+B` 可将其转入后台并立即返回输入区。退出时若仍有活动任务，可选择等待、全部取消或返回。后台任务完成后，主对话只会在下一次安全请求边界收到精简的 `<task-notification>`；完整结果、累计用量和 Worktree 交接信息保留在任务详情中。

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
    ├── context/
    ├── agents/*.md
    └── worktrees/
```

会话消息同步追加为 JSONL。单条完整坏记录会跳过，不完整尾部会截断，破坏工具协议的记录只恢复安全前缀。长期记忆使用可编辑 Markdown 文件和可重建索引，由自然完成轮次的不可变副本在后台串行更新；失败不会改变当前回复或会话。

这些数据不会同步到云端，也不加密，可能包含对话和代码片段。删除活动 Workspace 的会话或记忆前应先退出 ArtCode。

## 当前架构

生产依赖只在 `Bootstrap` 中组装，并由统一异步生命周期管理资源：

```text
__main__ → cli → Bootstrap → ArtCodeRuntime → AgentLoop
                         ├─ RequestPreparer → ContextManager
                         ├─ OpenAI-compatible Provider
                         ├─ ToolExecutionService → PermissionService
                         │                        → WorkspaceFileAccess / ProcessSupervisor
                         ├─ SessionService / DurablePromptSource / MemoryService
                         ├─ AgentTool → SubagentFactory → BackgroundTaskManager
                         │                           └─ isolated Worktree
                         └─ McpManager / PromptToolkitTui / CommandDispatcher
```

`RuntimeState` 是权限、Shell、显示模式和最近 Token 用量的进程内权威来源；请求级工具上下文使用其不可变权限快照。Runtime 只协调交互，不隐式创建第二套生产组件。

## 验证

```bash
.venv/bin/python -m pytest -q
```

当前测试聚焦核心主干：配置、Provider/SSE、会话恢复、权限、文件安全、进程、上下文压缩、Agent Loop、命令和少量端到端链路。
