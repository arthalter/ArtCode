# ArtCode

ArtCode 是一个单机、单用户、纯本地的 Python CLI Coding Agent 学习项目。ch14 版本使用统一领域语言与八个深模块，支持流式模型交互、Plan/Act、文件与 Shell Tool、权限审批、macOS Seatbelt、MCP、Session 恢复、上下文治理、长期记忆、Skill、Subagent Task 和隔离 Worktree。

## 安装与启动

```bash
python -m venv .venv
.venv/bin/python -m pip install -e '.[test]'
mkdir -p ~/.artcode
cp config.example.yml ~/.artcode/config.yml
.venv/bin/artcode --workspace /path/to/project
```

`python -m artcode` 与 `artcode` 进入同一 Application 组装路径。默认恢复当前 Workspace 最近可写的 Session，也可以选择：

```bash
.venv/bin/artcode --workspace /path/to/project --new
.venv/bin/artcode --workspace /path/to/project --resume session-1788520000000000-a1b2c3d4
```

可用 `--config` 指定用户配置，以 `--artcode-home` 指定本地 ArtCode 数据目录。

## 配置

最小配置：

```yaml
protocol: openai
model: your-model-id
base_url: https://your-openai-compatible-endpoint/v1
api_key: your-real-api-key
thinking:
  enabled: false
```

用户配置与 `<workspace>/.artcode/config.yml` 项目配置会在产生外部效果前分别严格校验并确定性合成。项目级 MCP Server 整体覆盖同名用户定义，并在启动前请求确认。MCP 支持 `stdio` 与 `streamable_http`，加载策略为 `eager` 或 `lazy`。

## 使用方式

普通输入启动 `chat` Run。常用命令：

- `/plan <目标>`：仅使用内置 observe Tool 生成计划。
- `/act [新增约束]`：执行最近一次成功计划。
- `/compact`：手动压缩较早的非 User 历史。
- `/permissions [default|edit|full]`：查看或改变权限模式。
- `/sandbox [auto|ask|off]`：控制 Shell 强制隔离；`off` 仍需逐次审批。
- `/skills`、`/skill <名称> [输入]`：查看或激活 Skill。
- `/tasks`、`/task <id>`、`/task-cancel <id>`：控制当前进程内 Task。
- `/worktrees`、`/worktree-discard <id>`：查看成果交接或直接确认危险丢弃。
- `/status`、`/session`、`/memory`：读取脱敏状态，不调用 Model、不消费 Notice。
- `/clear`、`/help`、`/exit`。

内置 Tool 为 `read_file`、`find_files`、`search_text`、`write_file`、`edit_file` 和 `run_command`。路径、敏感目录、符号链接与审批后目标变化由 Workspace 再次校验。Shell 默认使用 macOS Seatbelt 并禁止网络；隔离不可用时失败关闭。

## Session、Prompt 与记忆

Transcript 是追加式权威历史，只保存已提交事实。Prompt 是每次 Run 的不可变投影；指令、Notice、Summary、记忆、Skill 和 Transcript 使用明确来源标签。Notice 只在请求真正 dispatch 时消费。

新格式位于 `<workspace>/.artcode/ch14/sessions/`。记录使用带校验和的 JSONL：独立坏记录可隔离，不完整尾部可修复，不完整 Tool exchange 回退到最近安全前缀。ch14 不读取或迁移旧格式。

Summary 只替代较早的 Assistant/Tool 派生视图，所有 User 原文始终逐条、逐字、按顺序保留。只有自然完成 Run 的不可变快照会异步、串行更新用户偏好和项目事实；Markdown 来源可人工编辑，索引可重建。

## Skill、Subagent 与 Worktree

Skill 来源优先级为项目、用户、内置、扩展。同名高优先级定义无效时不会静默回退。启动目录只加载选择信息，激活时才加载 SOP。多个 Skill 的 Tool 范围取交集。Shared Skill 使用主 Session；Isolated Skill 使用临时 Transcript，只返回最终总结，不创建 Task 或 Worktree。

Subagent 通过统一 `agent` Tool 创建：

- `definition`：必须指定 Role，从干净 Transcript 开始，可前台等待或后台运行。
- `fork`：冻结父 Prompt 与 ToolSnapshot，可叠加 Role，始终后台运行。

Role 位于 `.artcode/agents/*.md` 或用户 `agents/*.md`，其能力只能继续收窄父能力。可能写盘的 Task 在首次 Model 请求前取得基于入队提交的独立 Worktree；主 Workspace 的未提交内容不会复制。无变化 Worktree 可自动清理，含未提交修改或本地新增提交的成果会保留。ArtCode 不自动 merge、rebase、push 或创建 PR。

## 八个核心模块

```text
Terminal Adapter → Application
                    ├─ Session → Model（Summary / Memory）
                    ├─ Agent → Model + Tool
                    ├─ Skill → frozen contribution
                    └─ Subagent → Agent + Workspace lease
Tool → Workspace + MCP Adapter + Subagent control Adapter
```

公开 Interface 位于 `artcode/core/`，具体实现位于对应的 `artcode/_*/` 私有包。Application 是唯一组装和生命周期协调者；Transcript、Run、Provider、Tool、Workspace、Skill 与 Task 状态分别只有一个权威所有者。

## 验证

```bash
.venv/bin/python tests/tools/verify_ch14_matrix.py --stage T14
.venv/bin/python tests/tools/verify_core_imports.py --stage T14
.venv/bin/pytest -q
.venv/bin/python -m compileall -q artcode tests
.venv/bin/python -m build --wheel
```
