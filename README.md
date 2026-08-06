# ArtCode

ArtCode 是一个本地 Python CLI Coding Agent 学习项目。

## ch09：会话恢复与长期记忆

ch09 让 ArtCode 在退出、终端中断或跨天之后继续先前任务，同时保持全部数据本地、可读、可删：

- 直接运行 `artcode` 会恢复当前 Workspace 最近的可用会话；`--new` 始终新建，`--resume SESSION_ID` 精确恢复指定会话。
- 会话按消息即时追加到 `<workspace>/.artcode/sessions/<session-id>.jsonl`。单行损坏会被隔离，半行和不完整工具协议会截断到最后一个安全边界。
- `/sessions` 显示最近 20 个会话；运行中不切换会话，避免把当前工具、权限或模型状态带进另一份历史。
- 启动时依次加载 `<workspace>/.artcode/instructions.md`、`<workspace>/ARTCODE.md`、`~/.artcode/instructions.md`。项目本地规则优先级最高。
- 指令可在独立行使用 `@include relative/path.md`，最多展开 5 层；绝对路径、非 Markdown、循环和越过所属用户目录或 Workspace 的引用会被跳过。
- 自动长期记忆保存在用户级或项目级 `memory/` 目录。每条事实是一份带 frontmatter 的 Markdown，`index.md` 只是可重建索引。
- 只有明确跨项目通用的用户偏好可以自动进入用户级记忆；纠正反馈、项目知识和参考资料默认只属于当前项目。
- 每轮自然结束后，后台模型以无工具、关闭 Thinking 的方式提炼最多 5 个变更；失败或超时不影响已经显示的回复和会话存档。
- `/memory` 只显示路径、计数和最近更新状态，不打印笔记正文。

本地布局：

```text
~/.artcode/
├── instructions.md
└── memory/
    ├── index.md
    └── mem-*.md

<workspace>/
├── ARTCODE.md
└── .artcode/
    ├── instructions.md
    ├── sessions/*.jsonl
    └── memory/
        ├── index.md
        └── mem-*.md
```

指令、会话和记忆不会同步到云端，也不加密；它们可能包含源代码片段或对话内容，应按普通本地敏感文件管理。可直接编辑指令和笔记，删除索引后 ArtCode 会从有效笔记重建；删除会话或笔记前建议先退出正在使用该 Workspace 的 ArtCode 进程。

## ch08：上下文管理

ch08 为长时间运行的 Agent 增加两层上下文保护：

- 每次模型请求前检查工具结果；单个结果超过 8,000 Token，或同轮结果合计超过 16,000 Token 时，将完整原文保存到 Workspace 内的 `.artcode/context/<session-id>/tool-results/`，对话只保留首尾预览和相对路径。
- 存盘文件必须通过 `read_file` 同时指定 `start_line` 与 `end_line` 分段回读，单次片段不能超过 8,000 Token。
- 上下文默认窗口为 200,000 Token，可在 200,000–1,000,000 之间配置；83.5% 自动摘要，88.5% 强制尝试。
- 重量压缩保留 System Prompt、近期约 10,000 Token 和至少 5 条消息；旧历史折叠为一份九段摘要，用户原始消息由程序逐字注入。
- 连续三次自动摘要失败会打开熔断器；真正的上下文超限最多触发一次紧急摘要和一次原请求重试。
- `/compact` 可以随时手动压缩，不会作为用户消息写入对话。
- Artifact 只服务当前运行：正常退出删除当前会话目录，下次启动清理确认失活的遗留目录。

配置示例：

```yaml
context:
  window_tokens: 200000
```

ArtCode 使用最近一次真实 API `prompt_tokens` 加字符差量近似估算上下文，不引入精确 tokenizer。未触发压缩时，Normal、Plan、Do、内置工具、MCP 与权限系统保持原有行为。

## ch07：MCP 协议

ch07 允许 ArtCode 通过官方 Python MCP SDK 复用外部 MCP Server 的工具：

- 支持本地 `stdio` 子进程和远程 `streamable_http`。
- 用户级 Server 写在 `~/.artcode/config.yml`；项目级 Server 写在 `<workspace>/.artcode/config.yml`。
- 项目配置只允许 `mcp_servers`，同名项目条目完整替换用户条目，不做字段继承。
- `env` 和 `headers` 支持 `${VAR}`；缺失变量只会跳过对应 Server。
- 项目级 Server 每次启动均需确认，且在确认前不会启动进程、连接网络或展开秘密。
- MCP 工具注册为 `mcp__<server>__<tool>`；Normal、Do 和 Plan 均可看到，但每次调用都必须二选一确认。
- 单个 Server 配置错误、超时或断开不会影响内置工具与其他 Server；断开后本次进程不自动重连。
- 仅接入 MCP Tools，不接入 Resources、Prompts、Sampling、Roots 或 OAuth。

项目级示例：

```yaml
mcp_servers:
  local_demo:
    transport: stdio
    command: python
    args: [./servers/demo.py]
    env:
      SERVICE_TOKEN: ${SERVICE_TOKEN}

  remote_demo:
    transport: streamable_http
    url: https://example.com/mcp
    headers:
      Authorization: Bearer ${MCP_TOKEN}
```

安全提示：stdio Server 是用户信任的外部进程，不受 ArtCode 文件工具的 Workspace 沙箱保护。Streamable HTTP 为兼容 MCP Server 允许跨域重定向，并会向重定向目标原样转发配置的全部自定义 Headers，包括认证信息。不要连接不可信 Server 或 URL。

常见错误包括传输字段混用、未知字段、`${VAR}` 未设置、项目配置包含其他顶层字段，以及远端工具 Schema 顶层不是 JSON object。上述错误会显示对应 Server 和失败阶段，但不会显示秘密值。

## ch06：权限系统

ch06 将 ArtCode 的工具安全模型改为单一 Workspace，并增加失败关闭的纵深权限系统：

- 默认 Workspace 是启动命令所在目录，可用 `artcode --workspace /path/to/project` 指定其他已有目录。
- 主配置固定为 `~/.artcode/config.yml`；用户权限为 `~/.artcode/permissions.yml`。
- 项目权限为 `<workspace>/.artcode/permissions.yml`，本地权限为 `<workspace>/permissions.local.yml`。
- 文件权限模式为 Default、Edit、Full，可用 `/permission` 查询或切换。
- Shell 策略为 Sandbox Auto、Sandbox Ask、Off，可用 `/sandbox` 查询或切换；Off 必须再次确认。
- Plan 始终只提供三个只读工具，不能被规则、模式或 HITL 提升。
- 高危命令、Workspace 越界和敏感路径属于硬拒绝。
- macOS Shell 默认通过 Seatbelt 执行，禁用网络，只允许写 Workspace 和本次运行的专用临时目录。

初始化配置：

```bash
mkdir -p ~/.artcode
cp config.example.yml ~/.artcode/config.yml
artcode --workspace /path/to/project
```

权限规则示例：

```yaml
rules:
  - match: read_file(src/**)
    action: allow
  - match: write_file(**/.env)
    action: deny
  - match: run_command(git status*)
    action: allow
```

Seatbelt 的 `sandbox-exec` 已被 Apple 标记为弃用；本项目仅将它用于本地 macOS 学习，不建议作为生产安全边界。

## ch05: System Prompt 设计

本章在 ch04 Agent Loop 的基础上，把 ArtCode 的全局指令升级为结构化 System Prompt 工程体系。

稳定 System Prompt 被拆成七个固定模块：身份、系统约束、任务模式、动作执行、工具使用、语气风格、文本输出。模块按固定优先级拼装，便于后续接入项目指令、Skill 和长期记忆，同时保护 Prompt Cache 的稳定前缀。

动态运行信息不再拼入稳定 System Prompt。ArtCode 会在每轮模型请求前临时注入 `<system-reminder>`，包含当前模式、工具边界、当前工作目录、允许访问目录和平台信息；这条提醒只参与本次 API 请求，不写入 Conversation Context。

ArtCode 继续暴露六个本地工具：读取文件、写入文件、按唯一精确文本替换编辑文件、执行 shell 命令、按 glob 模式查找文件，以及搜索文本。ch05 强化了这些工具的 description，让模型更稳定地遵守专用工具优先、编辑前先读、Plan Mode 只读等约定。

真实 DeepSeek / OpenAI-compatible 集成测试会读取项目根目录下的 `artcode.yaml`。ch05 要求真实 Prompt Cache 验证必须观察到缓存命中 token 大于 0，才能算完整验收通过。确定性的 fake provider 集成测试只会写入临时允许目录。
