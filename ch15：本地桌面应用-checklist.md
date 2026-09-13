# ch15：本地桌面应用 — Checklist

- [x] Python 核心已有文件无本次新增修改，新增桥接器直接复用 Application。
- [x] 前端 TypeScript 检查和 Vite 构建成功。
- [x] 三个聚焦桥接边界的测试通过，不运行整仓测试。
- [x] 启动期 MCP 审批可在打开操作尚未完成时答复。
- [x] 执行中再次提交返回 BUSY，取消可解除待答审批。
- [x] 前端恢复历史中不包含 Provider metadata 或模型待投递 Notice。
- [x] 使用真实本地目录打开、发送任务、接收真实模型文字及工具结果。
- [x] 重开同一目录后可恢复已提交 Session。
- [ ] 后台 Task 状态在约 0.75 秒的观察周期更新。
- [x] 打包的 macOS 应用可以启动内置 Python 后端。
- [x] 关闭应用会结束所属执行并回收后端进程。
- [x] 交付应用路径、开发启动命令及已知范围说明。
- [x] /skills、/tasks、/sandbox、/worktrees 在对话区显示命令结果，空列表也有明确提示。

## 验证记录 · 2026-09-09

- `pytest tests/application/test_desktop_bridge.py -q`：3 passed。包括打开期审批、忙碌保护、审批重复答复、取消、并发关闭只清理一次、历史投影过滤。
- `npm run build`：TypeScript 与 Vite 成功。
- PyInstaller + electron-builder：生成 `desktop/release/mac-arm64/ArtCode.app`，实际窗口显示「已连接」。
- 内置后端通过临时本地 HTTP 脚本模型驱动真实文件、Shell、MCP；三个工具结果均成功，第二次启动恢复已提交回复，两次正常退出。该验证不冒充真实 Provider 通过。
- 本地联调记录目录：`/var/folders/79/bz8zj0d10bqgqq988qnclprh0000gn/T/artcode-desktop-smoke-4uj1ugp8`。临时脚本：`/private/tmp/artcode_desktop_smoke.py`。
- 早先真实桌面调用 grok-4.6：服务返回 HTTP 503 / model_not_found / No available channel；界面正确展示失败并解除忙碌。
- 后续按用户要求切换为 deepseek-v4-flash，Grok 配置注释保留于用户配置文件。通过原模型适配器收到真实回复，并在打包桌面当前会话中完成只读任务：run_command 执行 pwd，工具 ok=true、exit_code=0，stdout 为 /Users/arthalter/temp；模型报告目录，Run 以 natural、2 轮结束。真实 Provider 阻塞已解除。本轮保留用户当前会话，不重复关闭；退出清理沿用上述已通过的独立验证。
- 后台 Task 观察已实现，但本次按最少测试约束未新增完整子 Agent 场景；该项保留未勾选。
- 修复命令看似无回应：StateOutput 原先仅写入右侧活动栏；现在同时生成对话反馈，usage/tool_batch 仍留在活动栏。`npm run test:commands` 覆盖四个命令及 usage 过滤，修复前失败、修复后通过；TypeScript/Vite 构建通过。Python 核心和协议不变。
