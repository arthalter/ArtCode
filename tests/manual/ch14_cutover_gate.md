# ch14：T13 一次性切换门槛

## 固定检查

- [x] `python tests/tools/verify_ch14_matrix.py --stage T13`：139 项需求全部存在，T1～T12 无未完成行，已到期旧私有测试完成处置。
- [x] `python tests/tools/verify_core_imports.py --stage T13`：八个公开 Interface 与八个私有实现包齐全，新核心不导入旧业务包、测试替身或越权私有模块。
- [x] `pytest tests/architecture/test_core_dependencies.py -q`：4 项通过；状态所有权唯一，依赖图无环，公开核心不暴露具体 Adapter。
- [x] T2～T12 的固定目标测试全部通过：158 passed。
- [x] 全部非 live 测试通过：610 passed，12 deselected。
- [x] 真实 DeepSeek 已执行并记录环境阻塞：本地配置为 `rightapi.ai / grok-4.6`，服务端 HTTP 500 报告 `Grok requires Postgres (DATABASE_URL)`；Adapter 脱敏并按单次请求失败处理。
- [x] 真实 stdio/Streamable HTTP MCP、进程树、Seatbelt 和双 Worktree 测试已包含在固定 158 项中并通过。
- [x] `python -m compileall -q artcode tests` 与 `python -m build --wheel` 成功。

## T14 冻结删除清单

- 旧业务包：`agent`、`background`、`commands`、`context_management`、`conversation`、`mcp`、`permissions`、`persistence`、`prompting`、`providers`、`runtime`、`sandbox`、`security`、`skills`、`subagents`、`tools`、`tui`、`worktrees`。
- 旧顶层模块：`bootstrap.py`、`config.py`、`errors.py`、`prompts.py`、`workspace.py`。
- 旧入口测试、旧 live Subagent 测试、章节式基线和所有只服务旧私有 seam 的剩余测试。
- `MAX_STREAM_ATTEMPTS`、首事件前重试循环及其断言。
- T14 同时切换 `python -m artcode` 和 console script，不保留 Feature Flag、双写或旧格式回退。
