# ch14：ArtCode 语义统一与破坏性整体重写验收结果

## T13 切换前门槛

- 行为矩阵：139 行通过 T13 校验。
- 架构：4 项依赖与状态所有权测试通过；新核心导入审计通过。
- 新核心固定集合：158 passed。
- 全量非 live：610 passed，12 deselected。
- 真实 MCP、进程、Seatbelt、Git Worktree：通过。
- 编译与 wheel 构建：通过。
- 真实 Provider：已执行；外部 `rightapi.ai / grok-4.6` 返回 HTTP 500 `Grok requires Postgres (DATABASE_URL)`，记录为外部服务阻塞。

## T14 一次性切换

- `python tests/tools/verify_core_imports.py --stage T14`：通过，旧业务包、旧顶层模块和旧入口导入残留为零。
- `python tests/tools/verify_ch14_matrix.py --stage T14`：139 行通过。
- Application 与入口测试：18 passed。
- 切换后全量非 live：160 passed，1 deselected。
- 源码 `python -m artcode` 与 console script 的 `--help`、新 Session、`/exit` 路径等价。
- 干净构建 `artcode-0.3.0-py3-none-any.whl` 成功；最终 85 个归档文件中旧核心残留为零。
- 全新虚拟环境安装 wheel 及其依赖成功；安装后的 `artcode` 完成 `--help` 与 `/exit`，并生成新格式空 Transcript。
- `MAX_STREAM_ATTEMPTS`、旧 Provider 重试循环与成功重试测试已随旧核心删除。

## T15 最终验收

- `pytest -q`：180 passed，1 skipped；skip 为本轮真实 Provider 外部服务阻塞。
- `python -m compileall -q artcode tests`：通过。
- `verify_core_imports.py --stage T14`：通过；旧核心与自动重试残留为零。
- `verify_ch14_matrix.py --stage T15`：139 项完整映射通过。
- `git diff --check`：通过。
- 最终 wheel：`artcode-0.3.0-py3-none-any.whl`，85 个文件，旧核心残留 0。
- 全新虚拟环境安装最终 wheel：成功；`--help` 成功；新 Session `/exit` 退出码 0，Transcript 数量 1。
- 资源审计：无 MCP fixture、Seatbelt 临时会话或 Subagent 进程；Git 仅列出当前主 Worktree，无 `.artcode/worktrees/` 残留。
- `checklist.md` 与 `ch14_acceptance.md` 已逐项绑定可观测证据；`README.md`、`CONTEXT.md`、公开 Interface 和冻结 ADR 一致。

## 2026-09-05 请求续接与 MCP 按需激活修复验收

- 完成时间：2026-09-05 12:13 +0800。
- 任务范围：上一会话已批准的 bug #5（同一 Run 的上下文压缩）与 bug #7（lazy MCP 搜索激活），对应 ch14 T6/T8/T9/T14/T15；保留此前 9 项局部修复。
- 请求续接：完整 Tool 批次提交后，Session 重建同一 Run 的下一份请求；User 原文、最近完整 Tool exchange、Protocol Metadata、冻结指令、Skill、Notice 和模型设置保持。自动/紧急摘要无收益、生成失败或保存失败时保留原状态；上下文恢复有界，网络/认证失败不进入恢复。
- MCP：`mcp_search_tools` 激活已发现且当前能力允许的工具；下一次请求与执行快照一起更新，当前批次不提前获得工具。新增 Schema 独立计入预算，普通 Run 和受限 Shared Skill 均通过真实 stdio 的搜索、压缩、echo 调用组合验证。
- 五路径：Application 的 normal/shared/isolated/definition/fork 各完成 24 批真实文件读取，在 Run 内发生压缩，并于第 25 轮自然完成；原用户输入及冻结上下文保持，隔离 Skill 的工具过程未进入主 Transcript。
- 额外取消回归：真实文件已写成功与取消同时到达时，修复前两个用例误把结果记录为 cancelled；修复后保留成功事实并返回 CANCELLED，包括同时到达轮次限制的情况。普通模型流结束时的取消仍不提交临时文本。
- 额外资源回归：Summary 返回非法 ToolRequests 时，修复前自动续接与公开 compact 两条路径均未立即关闭 Provider 流；修复后两条路径都关闭流并保留原请求/历史。

| 验证 | 本轮结果 |
| --- | --- |
| `.venv/bin/pytest -q -rs` | **265 passed in 17.37s**，无跳过；包含真实 Provider、MCP stdio/HTTP、进程、Seatbelt、Git Worktree |
| `tests/application/test_request_continuation_paths.py` | 7 passed：五条长任务路径及普通/Shared Skill 的 MCP 与压缩组合 |
| `tests/contracts/test_mcp_schema_budget.py` | 2 passed：只增加远程 Schema 即增加预算，并覆盖真实 usage 校准 |
| `tests/integration/test_agent_request_continuation.py` | 有界恢复、网络/认证失败、取消、成功 Tool 不重放，均包含在最终全量中 |
| `tests/fault/test_session_continuation_failures.py` | 摘要失败/无收益/取消/保存失败、前缀去重及 Provider 流清理，均包含在最终全量中 |
| `verify_ch14_matrix.py --stage T15` | 139 项映射通过 |
| `verify_core_imports.py --stage T14` | 导入与核心边界审计通过 |
| `python -m compileall -q artcode tests`、`git diff --check` | 通过 |
| 临时目录 wheel 构建、内容与导入检查 | `artcode-0.3.0-py3-none-any.whl`，87 项归档；包含 continuation.py 和 mcp_search.py；解包后隔离工作目录导入成功 |

本轮构建验证使用已有依赖环境进行 wheel 解包导入，未重复全新虚拟环境安装或人工终端验收；前述 T14/T15 记录保留其历史含义。本轮未提交或推送 GitHub。
