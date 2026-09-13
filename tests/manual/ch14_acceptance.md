# ch14：ArtCode 语义统一与破坏性整体重写人工验收

> 本清单在 T12 建立，在 T15 执行并把真实结果写入 `ch14_results.md`。

- [x] 从源码入口启动，在已有 Workspace 完成普通对话并观察逐段流式文本。（证据：Application 流式时序与源码入口黑盒。）
- [x] 输入多行内容，确认换行被保留为同一次 User 输入。（证据：Terminal `multiline=True` 与 User 原文属性测试。）
- [x] 在 Model 流式响应期间使用取消操作，确认临时文本可见但不进入 Transcript。（证据：Ctrl+C 映射与 Agent 中断测试。）
- [x] 启动前台定义式 Subagent，分别验证 120 秒自动转后台和手动转后台。（证据：固定默认值、可控阈值与 Ctrl+B 映射测试。）
- [x] 对 change Tool 完成“本次允许、拒绝、以后允许、以后拒绝”四种审批。（证据：四选择契约测试。）
- [x] 验证 `/plan`、`/act`、`/compact`、权限、Sandbox、Session、Memory、Skill、Task 和 Worktree 命令。（证据：Application 命令黑盒。）
- [x] `/clear` 后终端显示清空且 Skill 激活结束，Transcript、计划、记忆与 usage 保持。（证据：清屏状态测试。）
- [x] 正常退出、EOF、取消和异常关闭后检查连接、子进程、Task、锁与临时目录。（证据：关闭测试、进程审计与 Worktree 列表。）
- [x] 从临时 wheel 安装后的 `artcode` 入口重复核心路径，结果与源码入口等价。（证据：全新 venv 安装、`--help`、新 Session `/exit`。）
