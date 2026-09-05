# 冻结 ch14 核心领域语言与外部契约

2026-09-04，ArtCode 完成 ch14 一次性破坏性重写并切换到唯一新 Application。`CONTEXT.md` 中 Session、Transcript、Prompt、Notice、Summary、Protocol Metadata、Run、Run Mode、Task、Subagent、Skill、Tool Effect 与 Workspace 的含义，以及 `artcode/core/` 八个 Interface、CLI 命令、配置字段、新 Session 格式和模型可见 Tool Schema，构成冻结契约；后续实现优化默认发生在私有模块内部，修改这些契约必须由项目所有者明确批准并同步更新 Spec、行为矩阵、Checklist 与验收证据。

冻结依据为 `tests/behavior/ch14_matrix.yml` 的 139 项映射、T14 导入/删除审计、全部 Interface/Application 测试、真实 MCP/进程/Seatbelt/Git 验证、wheel 内容与临时安装验证。真实 Provider 验证已执行，但外部 `rightapi.ai / grok-4.6` 服务返回 HTTP 500 `Grok requires Postgres (DATABASE_URL)`，按 AC24 记录为外部服务阻塞，不以本地 Fake 结果替代。
