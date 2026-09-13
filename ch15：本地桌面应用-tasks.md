# ch15：本地桌面应用 — Tasks

1. 明确最小交付范围。影响：本章三份文档。依赖：无。参考：Spec 全文、原接口文档第 14–17 节。
2. 新增桌面协议桥接器。影响：`artcode/desktop_server.py`。依赖：1。参考：Application Interface、现有 TerminalAdapter 的交互方法。
3. 接入桌面进程管理及有限 IPC。影响：`desktop/electron/`。依赖：2。参考：本章 Spec 设计骨架。
4. 完成通信类型、展示状态、页面与样式。影响：`desktop/src/`。依赖：2、3。参考：本章 Spec 能力清单。
5. 加入前端构建与 Python 打包。影响：`desktop/package.json`、`desktop/scripts/`、构建配置。依赖：3、4。参考：本章 Checklist 启动验收。
6. 接入主流程。影响：`desktop/README.md`、桥接器、Electron 主入口。依赖：2–5。参考：选择项目 → 打开 → 发送 → 审批/取消 → 退出。
7. 端到端验证。影响：`tests/application/test_desktop_bridge.py`、本章 Checklist。依赖：6。参考：启动期审批、重复提交拒绝、取消与清理、历史恢复、真实 Provider 与打包启动。
