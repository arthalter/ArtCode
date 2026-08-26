# ch13 人工验收指南

> 本文档记录 ch13「子 Agent 与 Worktree 隔离」的**人工可观察验收步骤**。
> 自动化证据见各测试目录与 `checklist.md` 勾选记录；真实 API 证据见 `ch13_results.md`。

## 环境准备

1. 在临时目录创建真实 Git 仓库并保留主工作区未提交修改：

```bash
mkdir -p /tmp/artcode-ch13 && cd /tmp/artcode-ch13
git init -q && git config user.email you@example.com && git config user.name You
printf 'main original\n' > shared.txt
git add . && git commit -qm initial
echo 'uncommitted main change' >> shared.txt      # 主工作区未提交修改
```

2. 项目角色目录 `.artcode/agents/` 放置以下角色文件：

**reader.md**（只读，不建 Worktree）

```markdown
---
name: reader
description: 只读核查角色
tools:
  allow: [read_file]
  deny: []
model: inherit
max_rounds: 10
permission_mode: default
isolation: none
---
只阅读必要文件并返回精简结论。
```

**writer.md**（写角色，必须 Worktree）

```markdown
---
name: writer
description: 隔离写角色
tools:
  allow: [read_file, write_file]
  deny: []
model: inherit
max_rounds: 10
permission_mode: edit
isolation: worktree
---
只能在隔离 Worktree 中修改文件；不要访问主工作区。
```

3. 在仓库内启动 ArtCode。

## 验收步骤

### 1. 定义式只读任务（F2、F13、AC2、AC6）

- 让主 Agent 委派：`用 reader 角色读取 shared.txt 并总结内容`
- 预期：
  - 子任务自然结束，主对话只收到结论 + 用量，不出现完整工具轨迹
  - `/tasks` 可见一条 completed 任务，`/task <id>` 显示轮次、用量、无 Worktree 交接信息
  - `git worktree list` 无新增条目

### 2. 前台转后台（F15、F16、E04/E05）

- 委派一个会运行较久的 reader 任务
- 运行期间按 `Ctrl+B`：立即返回输入区并显示任务 ID，任务继续运行
- `/tasks` 中该任务 mode 变为“后台”；完成后只出现一次 `<task-notification>`

### 3. 并行写任务与 Worktree 隔离（F30~F42、AC10、AC17、E2E-01）

- 让主 Agent 同时委派两个 writer 任务：分别“以 ALPHA 身份修改 shared.txt”“以 BETA 身份修改 shared.txt”
- 预期：
  - `git worktree list --porcelain` 出现两个 `agent-xxxxxxxx` 目录，分支为 `worktree-agent-xxxxxxxx`
  - 两个目录中的 `shared.txt` 内容各自包含 ALPHA/BETA，互不覆盖
  - 主工作区 `shared.txt` 仍是 `main original + uncommitted main change`，未被子 Agent 修改
  - 主工作区未提交修改未被复制进任何 Worktree
  - 任务详情展示基准提交、分支、路径、保留状态、脏文件分类

### 4. Fork 任务继承父上下文（F3、C03、C04、E2E-02）

- 在对话中先声明“暗号是 blue42”
- 让主 Agent 委派 fork 任务：“父对话中的暗号是什么”
- 预期：Fork 能回答 blue42；`/task <id>` 中 Fork 前缀保真为 true；缓存用量字段为真实值或“不可用”

### 5. 取消与成果保护（F23、G06、E2E-03）

- 启动一个 writer 任务写入文件后（尚未完成时）执行 `/task-cancel <id>`
- 预期：任务状态 cancelled；已写入文件仍在保留的 Worktree 中；`/task <id>` 可见路径与保留状态
- 普通清理（重启应用后的过期扫描）不会删除该目录

### 6. 危险删除确认（F44、G12、G13）

- 对上一个被保留的 Worktree 执行 `/worktree-drop <task-id>`
- 预期：
  - 界面列出任务、路径、分支、脏文件数、新增提交数并要求 yes/no
  - 输入 no：零删除，目录与分支仍在
  - 输入 yes：仅删除该精确目标（目录 + 分支 + 元数据），相邻 Worktree 不受影响

### 7. 退出保护（F24、E15）

- 有活动任务时输入 `/exit`
- 预期：出现三选一（等待全部完成 / 取消后退出 / 返回 ArtCode），不会静默结束进程

## 记录要求

逐项记录实际结果到 `ch13_results.md`：命令输入、观察到的输出摘要、Git 状态、异常与原因。
