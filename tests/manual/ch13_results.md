# ch13 验收结果记录

> 本文件记录 ch13「子 Agent 与 Worktree 隔离」验收执行的真实结果，
> 与 `ch13_acceptance.md` 步骤对应；自动化证据以 `checklist.md` 勾选为准。

## 执行环境

- 日期：2026-08-26
- 系统：macOS（arm64），Python 3.14
- 模型 API：`~/.artcode/config.yml`（OpenAI 兼容协议，真实在线调用；模型 grok-4.6 via rightapi.ai）
- 分支：`codex/ch10-5-summary-refactor`（ch13 全部实现处于工作树未提交状态）

## 自动化测试结果

### 全量非 live 测试

```text
1021 passed, 4 deselected in 9.92s
```

说明：`-m 'not live'` 排除 4 个真实 API 用例；本章新增 41 个测试（hypothesis 属性测试、
故障注入、角色校验矩阵、后台状态机、前台超时、运行时状态隔离、Fork 冻结快照、轮次边界、
文件读取缓存、Worktree 危险删除命令、并发隔离与 cwd 探针）。

### 真实 API 端到端测试（tests/live/，2026-08-26 运行）

```text
4 passed in 172.45s
```

| 测试 | 结果 | 证据摘要 |
|------|------|----------|
| test_definition_read_only_e2e | PASS | 定义式干净上下文：父标记 PARENT HISTORY UNIQUE MARKER 在子请求零命中；只读角色未创建 Worktree；结论与真实 Token 用量回传 |
| test_definition_foreground_to_background_and_result_visibility | PASS | 前台定义式任务自然完成，Agent 工具直接返回任务详情（completed、natural、rounds≥1、最终文本） |
| test_fork_answers_from_parent_history_e2e | PASS | Fork 正确回答依赖父历史的暗号 blue42；首次请求与父 PreparedModelRequest 消息前缀逐字一致；cache_prefix_preserved=True；用量字段来自真实 payload |
| test_parallel_write_worktrees_e2e | PASS | 同一 HEAD 创建两个不同分支/Worktree，同名 shared.txt 分别含 ALPHA/BETA 互不覆盖；主工作区含未提交修改（uncommitted.txt + 追加行）未被复制进子目录；交接摘要含基准/分支/路径/保留/脏文件分类；两个分支在仓库中可查 |

真实 API 期间观察到一次“流式响应中途断开”（rightapi 服务端偶发，definition 用例已加入一次重试后通过）。

## 编译与构建

```text
python -m compileall -q artcode tests   # 通过
python -m build --wheel                 # 成功，artcode-0.2.0-py3-none-any.whl
```

## checklist 勾选情况

- 共 136 项，勾选 **136 项（100%）**；证据来源已写入各节首行。

### 补勾的 9 项及其证据（2026-08-26 第二轮）

| 项 | 证据测试 |
|----|----------|
| D11 | tests/fault/test_subagent_mcp_denial.py：父确认一次后，子 Agent 伪造 MCP 调用仍自动拒绝，工具实现零调用 |
| E10 | tests/fault/test_subagent_cancel_protection.py：写入文件后阻塞并取消，文件不回滚、Worktree 保留、主工作区不受影响 |
| E14 | tests/fault/test_task_notification_timing.py：任务完成只进收件箱，进行中的请求不变，下一安全边界注入且只投递一次 |
| E16 | tests/fault/test_subagent_restart_persistence.py：模拟进程死亡后新管理器识别遗留 Worktree、任务不复活 |
| E17 | 同文件：任务详情无任何跨进程持久化文件（除预期的 Worktree 元数据） |
| F07 | tests/fault/test_worktree_dirty_baseline.py：已跟踪/未跟踪/暂存三类脏状态矩阵，脏内容不复制、主工作区保持、交接消息声明基准 |
| G06 | tests/fault/test_worktree_stop_reason_matrix.py：自然完成/轮次上限/Provider 错误/取消 × 干净/脏 8 组合，保护判断与停止原因无关 |
| H10 | 同重启文件：真实子进程创建并退出，重启后无变化 Worktree 无残留、未推送提交 Worktree 文件与提交完整可识别 |
| E2E-03 | tests/fault/test_subagent_auto_background_cancel_e2e.py：前台超时自动转后台→取消→Worktree 保留→重启扫描不删→详情可定位成果 |

## 人工验收记录

自动化端到端已覆盖：定义式只读、前台自然完成、Fork 父历史与缓存、双写 Worktree 隔离、
主工作区未提交修改不复制。以下人工 TUI 步骤待用户在真实终端按 `ch13_acceptance.md` 执行后补记：

- [ ] 1. Ctrl+B 手动转后台的可见交互（自动化已有 prompt_toolkit 键盘事件测试）
- [ ] 2. /worktree-drop 危险删除的 yes/no 交互（自动化已有命令层测试）
- [ ] 3. /exit 三选一退出保护（自动化已有三个分支测试）

## 已知限制与遗留

- 真实 API 偶发断流：重试一次仍失败时如实记录为环境阻塞，不使用 Fake 结果冒充。
- 内置角色目录 `artcode/subagents/builtin/` 仅含 `.gitkeep`，无预置角色（符合 T2 计划，B01 用临时目录验证）。
- `Path.cwd()` 兜底残留仅剩 `workspace.py:60`（主工作区默认值，启动语义）；工具路径全部走显式 default_cwd。