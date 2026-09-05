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
