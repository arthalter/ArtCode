# ch15：前后端接口与执行过程可视化

接口文档草案 v0.1 · 2026-09-09

本文定义拟议的 ArtCode 客户端协议 v1.0，供 TUI、Python App Server 和未来 macOS GUI 共同实现。**方法、事件和默认值均为待实现契约，不代表当前代码已经支持。** 本次只编写接口文档；既有 ch14 Spec、Tasks、Checklist、ADR 和代码保持各自原状态。章节暂接 ch14 使用 ch15，编号可以调整。

## 阅读导航

- 先了解范围与通信：[1. 范围](#1-范围与前提)、[2. 通信](#2-通信与版本)、[3. 身份](#3-对象身份与作用范围)。
- 实现请求与状态：[4. 通用约定](#4-请求响应与操作约定)、[5. 方法](#5-方法目录)、[6. 数据结构](#6-共享数据结构)。
- 实现实时界面：[7. 订阅](#7-订阅快照与重同步)、[8. 事件](#8-事件契约)、[9. 状态](#9-状态迁移与取消)、[10. 输出](#10-工具输出与详情读取)。
- 检验完整闭环：[11. 示例](#11-完整通信示例)、[12. 错误](#12-错误契约)、[15. 验收](#15-可观察验收清单)。

## 1. 范围与前提

### 1.1 首版接口覆盖

主 Run、Plan/Act、文件与 Shell Tool、审批、权限与沙箱、Session 恢复与历史、Shared/Isolated Skill、Subagent Task、MCP 状态、上下文压缩、记忆更新状态、Worktree 成果及工具输出详情。

用户必须能在执行结束前看到实际活动：谁创建了子任务、哪个 Agent 正在调用哪个工具、工具是否等待审批、命令已经输出了什么、任务是否转入后台。主 Agent 返回最终文字后，仍在运行的后台 Task 继续产生事件。

### 1.2 v0.1 草案采用的运行基线

| 决策 | 本草案基线 |
| --- | --- |
| 后端数量 | 每个 App Server 进程管理一个 Application，绑定一个主 Workspace 和主 Session |
| 控制客户端 | 每个 App Server 一个控制连接；Electron 主进程持有连接并向窗口分发状态 |
| TUI | 可在自己的 Python 进程内直接调用同一 Application Interface，不要求经过 Electron |
| GUI | React → preload 暴露的有限接口 → Electron 主进程 → stdio → Python App Server |
| Session 写入 | 保留现有独占锁；两套独立后端不能同时写同一 Session |
| 执行中发新目标 | 同一 Session 的前台执行/压缩未结束时返回 BUSY；查询、审批、取消仍可处理 |
| 后台存活 | stdio 管道关闭、父进程退出或显式关闭 Application 时，清理所属执行和资源 |
| 过程历史 | 同一后台存活期间有界保留；后台重启后恢复已提交 Session 历史，不恢复进程内 Task |

这些是为了使草案可实现而提出的基线，尚未替用户决定长期产品形态。双端同时控制同一次执行、独立常驻后台、关闭整个桌面应用仍继续任务、多主 Session 并行、完整过程跨重启回放，在第 16 节列为待决策范围。

### 1.3 各模块职责

- Application 协调客户端操作、交互登记、观察关联和展示投影；App Server 只处理协议接入。
- Agent、Tool、Workspace、Skill、Subagent 在真实状态变化处产生各自的观察事件，Application 通过注入的 Adapter 汇集。低层模块不反向依赖 Application 或任何 UI。
- Session 继续拥有 Transcript、Prompt、Notice 和持久化。展示事件不直接追加到 Transcript。
- Subagent 继续拥有 Task 调度与子 Run。新增可观察性不放宽其工具范围、交互审批或再次委派限制。
- 维持八个核心状态所有者及无环依赖。协议类型和投递实现不是新的独立业务状态权威。

## 2. 通信与版本

### 2.1 传输

首版采用标准 JSON-RPC 2.0，每个 UTF-8 JSON 对象占一行，以 LF 分帧；字符串内换行必须转义。stdout 只发送协议消息，日志写 stderr 或日志文件。Python 不输出终端颜色码、提示符或进度条供 GUI 解析。

请求使用 `method`、`params`、`id`；响应包含同一 `id` 和 `result` 或 `error`。客户端请求 ID 使用字符串。服务端事件使用无 `id` 的 notification，方法固定为 `event`。不使用 JSON-RPC batch；除服务端 notification 外，不接受无 ID 的业务请求。

```json
{"jsonrpc":"2.0","id":"request-1","method":"initialize","params":{"protocol":{"major":1,"minor":0},"client":{"name":"artcode-desktop","version":"0.1.0"}}}
```

### 2.2 初始化结果

`initialize` 只协商连接，不打开 Workspace、不调用模型、不启动 MCP。返回：

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| `protocol` | `{major: integer, minor: integer}` | 实际选用版本；major 必须相同，minor 选择双方共同支持版本 |
| `instance_id` | string | 本次后台启动的唯一标识，重启后改变 |
| `server_version` | string | ArtCode 程序版本，不等于协议版本 |
| `methods` | string[] | 本次实现确实可调用的方法 |
| `event_types` | string[] | 本次实现确实会发送的事件类型 |
| `capabilities` | object | `subagent_activity`、`isolated_skill_activity`、`shell_output_stream`、`mcp_progress`、`subscription_resume` 等布尔能力；MCP progress 能力不保证每个服务器都报告进度 |
| `limits` | object | 第 13 节规定的实际限额 |
| `next_command_seq` | integer | 下一个修改状态请求应使用的序号，初值为 1 |

同一连接以相同参数再次 initialize 返回相同协商信息及最新 next_command_seq；变更协商参数返回 INVALID_STATE。GUI 不能因为文档列有方法就假定当前后端已实现，必须检查协商结果。

### 2.3 修改接口的规则

添加可选响应字段或协商能力可提升 minor；删除字段、改变字段含义、增加必填参数或改变终态语义需要提升 major，或提供明确兼容方案。客户端忽略未知可选响应字段；不认识的事件不能被猜测为某种已有事件。

本地学习阶段可同步升级前后端，不要求永久兼容旧版本；版本不匹配时在产生业务效果前明确失败。协议升级和 Session 持久格式迁移分别评估，不能仅因协议升级就清空既有历史。

## 3. 对象身份与作用范围

| 标识 | 含义与有效期 |
| --- | --- |
| `instance_id` | 后台进程身份，是其他运行期 ID 的外层作用域 |
| `application_id` | 一次 Application 打开尝试的身份；接受 open 时分配，失败也不复用 |
| `session_id` | 用户正在观察的主 Session 的既有持久身份 |
| `operation_id` | 一次长用户操作的跟踪记录，如打开项目、开始 Run、压缩、关闭；不新增一种领域 Task |
| `run_id` | 实际开始的一次 Run；主 Run、子 Run、Isolated Skill Run 各有自己的 ID |
| `task_id` | 真实 Subagent 的 Task；排队或准备失败时可能从未产生子 run_id |
| `parent_run_id` | 创建该 Subagent 的父 Run；父 Run 已结束也保持原值 |
| `parent_tool_call_id` | 创建 Task 的那次 agent 工具调用；后续 task_get/task_cancel 调用不替换它 |
| `tool_call_id` | 模型生成的调用 ID，只在所属 Run 中使用，不假定全局唯一 |
| `item_id` | 后台为一条消息或一次工具展示条目分配的稳定 ID，同一 instance 内唯一 |
| `interaction_id` | 一次具体人工交互；启动确认、工具审批、丢弃确认和退出选择使用不同 kind |
| `output_id` | 一份可读取文本输出的句柄；不是文件路径，也不是客户端可自行拼接的 result 引用 |
| `subscription_id`、`snapshot_id` | 一次逻辑订阅与一次不可变快照的运行期身份 |

子 Run 事件的 session_id 始终指向用户所观察的主 Session。子执行内部的临时 Session 不冒充主历史身份，也不向前端暴露其临时存储路径。

`operation_id` 是来源关系，不是任务存活范围：主操作结束后，后台 Task 的事件仍可带原 operation_id。Isolated Skill 不创建 Task；其 task_id 为 null，直接由用户触发且没有真实父 Run 时，parent_run_id 和 parent_tool_call_id 也为 null。

## 4. 请求、响应与操作约定

### 4.1 类型约定

字段表中带 `?` 的参数可省略，默认值在表中注明；`T | null` 表示必须提供字段但允许值为 null。整数使用非负安全整数，不超过 2^53−1；UTC 时间为 RFC3339 字符串，未知时间为 null，不用零值伪装已知。耗时由单调时钟计算，单位毫秒。

Workspace 与配置路径在请求中使用绝对路径；输出中的工具目标可使用相对其执行 Workspace 的显示路径，并同时保留 Workspace 归属。用户文本不 trim 后改写进 Transcript；只用 trim 判断是否全空白。

公开对象按本文字段白名单序列化；不直接序列化内部 dataclass、任意 Any、异常堆栈或 ModelRequest。请求未知参数返回 INVALID_PARAMS；各响应允许将来的可选扩展。

### 4.2 请求配对与防重复执行

JSON-RPC `id` 只配对响应。所有表中标为 M 或 L 的方法，在 params 中还必须包含 `client_command_seq`。

- 服务端维护最高已消费序号 H。新修改请求必须是 H+1；客户端收到其确认后才发送下一个修改请求，但不必等待该长操作完成。
- 序号可识别且等于 H+1 的请求先登记，再校验业务参数。因此 BUSY、非法业务参数等确定响应也消费该序号，客户端下一次新意图使用 H+1。
- 相同序号、相同请求内容在结果缓存有效时返回原逻辑结果，不重复创建 Run、写入用户事实或执行工具；同号不同内容返回 COMMAND_CONFLICT。内容指 method 和规范化后的业务 params，不含 JSON-RPC id；响应仍回显本次请求 id，并填入当前 last_command_seq。
- 序号大于 H+1 返回 COMMAND_OUT_OF_ORDER，不消费；旧序号已无缓存则返回 COMMAND_RESULT_EXPIRED，仍不重新执行。
- 所有修改请求响应，以及此类错误的 error.data，返回最新 `last_command_seq`。有限缓存之外仅保留水位，避免承诺无限期保存全部请求结果。
- 无法解析的帧、未知方法或无法识别序号的请求不消费序号。断连后先判断 instance_id；新后台不能盲目重发旧业务请求。

Q 为只读查询，O 为观察操作，均不消费 command_seq。O 可以改变订阅资源，不得改变 Agent 业务状态。

### 4.3 长操作

L 方法校验通过后立即返回 `Accepted`：

```json
{"operation_id":"op-1","application_id":"app-1","state":"accepted","last_command_seq":1}
```

实际启动和结束通过 operation 事件报告，可随时调用 operations.get 查询。请求的接受响应先写入协议发送队列，再发送该操作产生的事件。其他正在运行的 Task 的事件可以交错到达。

`OperationView` 的 state 为 `accepted | running | waiting_interaction | cancelling | completed | failed | cancelled`。completed 表示已得到该操作的结构化结果，不保证 Run 达成目标；必须继续检查 Run 的 stop_reason。准备失败为 failed；Run 尚未创建前取消为 cancelled。已创建 Run 的取消以 RunOutcome 报告，操作可以 completed。

同一操作不会在等待模型、子任务或审批时阻塞整个协议读取循环。统一列为 L 的方法即使立即完成也保留相同返回形式。

### 4.4 订阅要求

首次启动顺序为 `initialize → events.subscribe → application.open`。L 方法要求存在有效订阅，否则返回 SUBSCRIPTION_REQUIRED，避免启动审批无人可见。重同步期间可短暂停止新 L 操作；取消、回答审批和读取状态始终有独立处理路径。

## 5. 方法目录

除 initialize 外均要求完成协议初始化。Q/M/L 方法在已分配 Application 后必须传 application_id；启动前查询快照、operations、interaction 时 application_id 可为 null。方法表省略通用 application_id 和 M/L 的 client_command_seq。

### 5.1 连接、Application 与操作

| 方法 | 类别 | 参数 | 结果 |
| --- | --- | --- | --- |
| `initialize` | Q | 第 2 节 | 初始化结果 |
| `events.subscribe` | O | `after?: Cursor`；省略表示新建快照订阅 | `SubscriptionView`，见第 7 节 |
| `events.unsubscribe` | O | `subscription_id: string` | `{unsubscribed: boolean}`；重复解除返回 false |
| `application.open` | L | `workspace: string`；`config_path?: string`；`artcode_home?: string`；`session: SessionSelection` | Accepted；操作结果 `{application_id, session_id, restored, recovery_issues}` |
| `application.snapshot` | Q | `snapshot_id?: string`；`page_cursor?: string`；`limit?: integer=100` | `SnapshotPage`；不传 snapshot_id 则创建独立查询快照，不隐式订阅 |
| `application.close` | L | `active_policy: "ask" | "wait" | "cancel"` | Accepted；结果 `{closed: boolean, reason: "closed" | "user_returned"}` |
| `operations.get` | Q | `operation_id: string` | OperationView；缓存淘汰返回 OPERATION_EXPIRED |
| `operations.cancel` | M | `operation_id: string` | `{requested: boolean, state, last_command_seq}`；仅取消目标操作的可取消阶段 |

SessionSelection 为以下互斥对象：`{kind:"new"}`、`{kind:"latest"}`、`{kind:"exact",session_id:string}`。配置省略时沿用 CLI 的路径解析规则；请求和响应均不携带 API key。latest 保留跳过已占用 Session 的现有行为；exact 占用时报 SESSION_BUSY。

一个后台只允许一个成功打开的 Application。opening/ready/closing 时再次 open 返回 INVALID_STATE；打开失败或打开被取消后，清理临时资源并回到可 open 状态，新尝试分配新 application_id。成功关闭后发送终态与 application.closed、完成控制帧发送，再退出进程。

关闭策略：ask 在存在活动主 Run 或 Task 时发出 exit 交互；wait 等它们结束并拒绝新的执行；cancel 请求停止所有所属执行再清理。用户选择 return，或在可取消阶段取消 wait/ask 关闭操作，则恢复 ready。资源回收阶段不可逆，operations.cancel 返回 NOT_CANCELLABLE。新增“等待活动主 Run”属于接口编排，不能误称现有 close() 已具备。

stdio EOF、进程异常或持续写通道故障直接使用资源清理策略，不等待无法得到的交互答复。关闭窗口本身不直接映射 application.close，由桌面生命周期设计决定。

### 5.2 Session、Run 与人工交互

| 方法 | 类别 | 参数 | 结果 |
| --- | --- | --- | --- |
| `session.history` | Q | `session_id: string`；`cursor?: string`；`limit?: integer=100` | `{session_id, history_revision, facts: HistoryFact[], next_cursor}` |
| `run.start` | L | `session_id: string`；`intent: RunIntent` | Accepted；操作结果为 RunOutcomeView，准备失败则 operation.failed |
| `run.cancel` | M | `run_id: string` | `{requested: boolean, state, last_command_seq}` |
| `interaction.list` | Q | `operation_id?: string`；`cursor?:string`；`limit?:integer=100` | `{interactions: InteractionView[],next_cursor:string|null}`，固定查询版本，只列未解决项 |
| `interaction.respond` | M | `interaction_id: string`；`answer: InteractionAnswer` | `{resolution, last_command_seq}` |

RunIntent：chat/plan 使用 `{mode:"chat"|"plan",text:string}`；act 使用 `{mode:"act",constraints?:string}`，由后端读取最近成功计划，缺计划返回 PLAN_REQUIRED，不接受前端伪造“最近计划”正文。

同一 Session 已有前台 Run、Isolated Skill 或压缩时，新的 run.start/context.compact/skills.run 返回 BUSY。后台 Task 不占前台操作名额。run.cancel 只接受主 Run 或直接由用户触发的 Isolated Skill Run；子 Run 取消必须通过 tasks.cancel，避免绕过 Task 调度和交接。Run 已终止时 requested=false，未知 Run 返回 NOT_FOUND。

历史分页首次读取固定 `history_revision`（有效已提交事实前缀的身份）；游标绑定该前缀、Session 与下一条位置。新提交不会挤乱旧分页。HistoryFact 的 fact_id 由 Session、该条已提交记录的稳定校验值和事实位置派生，普通追加不得改变已有 fact_id；它不依赖不断增长的整段历史版本。旧事实没有可靠 Run ID 或时间时返回 null。损坏恢复导致游标所绑定的有效前缀变化时，旧游标返回 HISTORY_CHANGED。

### 5.3 配置、Skill、Task 与其他能力

| 方法 | 类别 | 参数 | 结果 |
| --- | --- | --- | --- |
| `permissions.get` | Q | 无 | PermissionView |
| `permissions.set` | M | `mode: PermissionMode` | `{permission: PermissionView,last_command_seq}` |
| `sandbox.set` | M | `policy: ShellPolicy` | `{permission: PermissionView,last_command_seq}` |
| `skills.list` | Q | `cursor?: string`；`limit?: integer=100` | `{items: SkillSummary[],active:string[],diagnostics:Diagnostic[],next_cursor}` |
| `skills.refresh` | M | 无 | `{revision,diagnostics:Diagnostic[],last_command_seq}`；列表另用 skills.list |
| `skills.activate` | M | `name: string` | `{activation: SkillActivationView,last_command_seq}` |
| `skills.clear` | M | 无 | `{active:[],last_command_seq}`；只解除全部激活，不删除 Skill 文件 |
| `skills.run` | L | `name: string`；`text: string` | Accepted；操作结果 `{run:RunOutcomeView,source_kind,summary:TextView}` |
| `tasks.list` | Q | `cursor?: string`；`limit?: integer=100` | `{items:TaskView[],next_cursor}` |
| `tasks.get` | Q | `task_id:string` | TaskView，包括当前工具条目 ID 与结果预览 |
| `tasks.cancel` | M | `task_id:string` | `{requested:boolean,task:TaskView,last_command_seq}`；请求取消不等于清理已结束 |
| `tasks.background` | M | `task_id:string` | `{changed:boolean,task:TaskView,last_command_seq}` |
| `mcp.status` | Q | `cursor?:string`；`limit?:integer=100` | `{summary:McpSummary,servers:McpServerView[],next_cursor}` |
| `context.compact` | L | `session_id:string` | Accepted；操作结果 CompactionView，公开触发来源固定 manual |
| `memory.status` | Q | `session_id:string` | `{pending:integer,last_report:MemoryReportView|null}` |
| `worktrees.list` | Q | `cursor?:string`；`limit?:integer=100` | `{items:WorktreeView[],next_cursor}` |
| `worktrees.discard` | L | `task_id:string` | Accepted；操作结果 `{task_id,discarded:boolean}` |
| `outputs.read` | Q | `output_id:string`；`offset?:integer=0`；`max_bytes?:integer=16384` | OutputSlice，见第 10 节 |

业务限制：

- permissions.set/sandbox.set 修改当前进程的默认设置，不声称写入配置文件；已冻结 Run 继续使用原快照，后续 Run 使用新设置。审批中的 allow_always/deny_always 继续按原规则持久化精确授权。
- skills.list 只读；现有 `/skills` 的刷新行为通过 skills.refresh 后再 list 保留。目录分页游标绑定版本，版本改变返回 CURSOR_STALE。激活/清除对已冻结 Run 不追溯生效。
- skills.run 根据 Skill 的既定 mode 走 Shared 或 Isolated 路径，不允许前端随意改其 mode；Isolated 不创建 Task/Worktree。自动选择 Skill 的普通输入仍由后端处理。
- tasks 仅表示当前进程的 Subagent Task；没有 GUI 任意创建子任务、恢复旧 Task 或开启再次委派的方法。结束的 Task 再 cancel/background 不复活它。
- mcp.status 是实际连接与目录状态的新投影；不能直接返回启动时缓存的旧报告冒充当前状态。本文不新增 GUI 任意调用 MCP 工具、修改 MCP 配置或重连的能力。
- worktrees.discard 延续当前可验证的进程内 Task 归属与精确确认。列表中的历史保留 Worktree 若暂不支持该入口，返回 discard_supported=false 和原因，不能暗示全部可丢弃。
- 列表分页绑定一次只读查询版本/水位；后续变化通过活动订阅反映。超时或版本失效返回 CURSOR_STALE，客户端重开第一页。

## 6. 共享数据结构

### 6.1 枚举

| 类型 | 合法值 |
| --- | --- |
| PermissionMode | `default`、`edit`、`full` |
| ShellPolicy | `sandbox_auto`、`sandbox_ask`、`explicit_unsafe`；CLI 的 auto/ask/off 仅是输入映射 |
| RunMode | `chat`、`plan`、`act` |
| StopReason | `natural`、`limit`、`cancelled`、`model_failure`、`length`、`cannot_continue` |
| TaskState | `queued`、`running`、`completed`、`failed`、`limit`、`cancelled` |
| SourceKind | `application`、`main`、`subagent`、`isolated_skill`；application 是展示来源，不新增 ToolSource |
| ToolEffect | `observe`、`change`、`external`、`control` |
| ToolStatus | `requested`、`waiting_approval`、`running`、`succeeded`、`rejected`、`invalid`、`failed`、`timed_out`、`cancelled`、`not_started` |
| MessageStatus | `streaming`、`completed`、`interrupted` |
| McpServerState | `disabled`、`rejected`、`invalid`、`ready`、`unavailable`、`closed`；启动中由 phase 表达 |
| CompactionStatus | `success`、`noop`、`failed`；仅适用于正常返回的报告，操作取消不伪造报告 |
| CompactionTrigger | `automatic`、`forced`、`emergency`、`manual` |

### 6.2 通用展示类型

以下为字段契约，嵌套字段同样不得替换为不透明的任意对象。所有 ID 字段遵循第 3 节。

| 类型 | 字段 |
| --- | --- |
| Cursor | `instance_id:string, sequence:integer` |
| TextView | `preview:string, truncated:boolean, output_id:string|null`；长正文通过 output_id 分页读取 |
| UsageView | `input_tokens,output_tokens,total_tokens,cached_tokens,cache_miss_tokens: integer|null`；null 表示未知，不补 0 |
| ErrorView | `code:string, category:string, message:string, retryable:boolean`；不包含堆栈和秘密 |
| SourceView | `kind:SourceKind, name:string|null`；name 可显示 Role 或 Skill 名 |
| OperationView | `operation_id,application_id,method,state,run_id:null|string,result:null|OperationResult,error:null|ErrorView,cancellable:boolean` |
| RunOutcomeView | `run_id,stop_reason:StopReason,rounds:integer,usage:UsageView,final_text:TextView,tool_batches:integer,detail:string,error:ErrorView|null`；模型或执行失败保留结构化类别 |
| PermissionView | `mode:PermissionMode,shell_policy:ShellPolicy,rules:PermissionRuleView[],rules_truncated:boolean,rules_output_id:string|null,applies_to:"future_runs"`；规则过多时 rules 只含预览，rules_output_id 提供同一规则快照的完整 JSON 文本 |
| PermissionRuleView | `tool_name:string,target:string,allow:boolean` |
| Diagnostic | `name:string,source:string,message:string` |
| SkillSummary | `name,description,source:"project"|"user"|"builtin"|"extension",mode:"shared"|"isolated"` |
| SkillActivationView | `name,mode:null|"shared"|"isolated",ok:boolean,message:string,already_active:boolean` |
| CompactionView | `trigger:"automatic"|"forced"|"emergency"|"manual",status:CompactionStatus,summarized_facts:integer,detail:string` |
| MemoryReportView | `status:"success"|"failed",user_preferences_added:integer,project_facts_added:integer,detail:string` |

OperationResult 按 method 判别，取第 5 节明确的操作结果类型。run.start 的 RunOutcome 与 skills.run 的 run 结果可以是 length、limit、cancelled 等非自然停止，前端必须如实显示。

### 6.3 执行、Task 与工具条目

RunView：`run_id, source:SourceView, task_id:string|null, parent_run_id:string|null, operation_id:string, mode:RunMode, phase:"preparing"|"model"|"tools"|"waiting_interaction"|"cancelling"|"finished", workspace:string, started_at:string|null, finished_at:string|null, outcome:RunOutcomeView|null`。

TaskView：`task_id, kind:"definition"|"fork", task:TextView, role:string|null, state:TaskState, phase:string, background:boolean, run_id:string|null, parent_run_id:string, parent_tool_call_id:string, current_item_ids:string[], rounds:integer, usage:UsageView, result:TextView, permission_events:string[], handoff:WorktreeView|null, created_at:string|null, started_at:string|null, finished_at:string|null, elapsed_ms:integer|null`。

Task phase 在本版限定为 `queued | preparing | executing | cancelling | finalizing | finished`；TaskState 不新增 preparing/cancelling 等枚举。时间是新观察投影需要记录的数据，当前 Task 中的单调时钟读数不能直接当作 UTC 时间输出。

MessageView：`item_id, run_id, source:SourceView, status:MessageStatus, content:TextView, utf8_bytes:integer, committed_to_owner_session:boolean, fact_id:string|null`。一次 Run 中多轮模型响应各自分配条目；是否提交给主 Session 与消息是否生成完是不同字段。

ToolView：`item_id,run_id,task_id:string|null,tool_call_id,tool_name,effect:ToolEffect|null,origin:"builtin"|"mcp"|"system"|null,status:ToolStatus,target:string|null,workspace:string,arguments:TextView,interaction_id:string|null,outputs:OutputView[],result:ToolResultView|null,started_at:string|null,finished_at:string|null,elapsed_ms:integer|null`。

tool.requested 时未知工具或非法参数可能没有可信 effect/origin/target，使用 null；确定后通过 tool.state_changed 或 tool.started 中的完整 ToolView 补齐，不能猜测属性。OutputView 为 `{output_id:string,kind:"stdout"|"stderr"|"tool_result"|"message"|"history",available_bytes:integer,producer_finished:boolean,capture_truncated:boolean,available:boolean}`。运行中就登记 outputs，快照不能等到最终 result 才提供输出句柄。

ToolResultView：`ok:boolean,error_code:string|null,error_message:string|null,content:TextView,output_ids:string[],metadata:ContentMetadata[]`。ContentMetadata 为 `{kind:"image"|"audio"|"binary"|"resource",mime_type:string|null,size_bytes:integer|null,label:string|null}`；当前二进制内容只展示元数据，不许假装已返回可预览媒体。

### 6.4 历史、MCP 与 Worktree

HistoryFact 公共字段：`fact_id,index:integer,kind:"user"|"assistant"|"tool_exchange",run_id:string|null,created_at:string|null`。user 的内容为 `text:TextView`；assistant 增加 `text:TextView,completion:"natural"|"length"`；tool_exchange 增加 `assistant_text:TextView,calls:HistoryToolCall[]`。

HistoryToolCall：`call_id,tool_name,arguments:TextView,result:ToolResultView|null`。Protocol Metadata 永不进入 HistoryFact。历史保存的工具输出若只剩预览和已失效引用，content.truncated=true，并通过 outputs.read 或 error 明确说明详情不可用，不宣称保存了全量输出。

McpSummary：`configured_count,connected_count,discovered_tool_count,active_tool_count:integer,loading:"eager"|"lazy"`。McpServerView：`name,source:"user"|"project",state:McpServerState,phase:"idle"|"starting"|"discovering"|"ready"|"failed"|"closed",tool_count:integer,detail:string,truncated:boolean`。

WorktreeView：`task_id,baseline,branch,path,retained:boolean,tracked_changes,staged_changes,untracked_changes,commits_ahead:integer,has_upstream:boolean,all_commits_pushed:boolean,inspection_error:string,discard_supported:boolean,discard_unavailable_reason:string|null`。它不包含编辑器缓冲区、完整 diff 或自动合并能力。

### 6.5 人工交互

InteractionView 公共字段：`interaction_id,kind,operation_id,application_id,session_id:string|null,run_id:string|null,task_id:string|null,tool_call_id:string|null,state:"pending",created_at,expires_at:string|null,payload`。expires_at=null 表示无固定计时截止；所属操作取消、完成或应用关闭仍会使其失效。

| kind | payload | InteractionAnswer |
| --- | --- | --- |
| `tool_approval` | `tool_name,target,effect,workspace,permission_mode,shell_policy,source:SourceView` | `{choice:"allow_once"|"deny_once"|"allow_always"|"deny_always"}` |
| `mcp_server` | `server_name,summary,workspace,source:"project"` | `{allow:boolean}` |
| `worktree_discard` | `handoff:WorktreeView,confirmation_token:string` | `{confirm:boolean,confirmation_token:string}` |
| `exit` | `active_run_ids:string[],active_task_ids:string[]` | `{choice:"wait"|"cancel"|"return"}` |

确认丢弃所用 token 绑定后端展示的精确目标，客户端只回传；再次执行前仍按现有规则核验归属。工具审批也必须在真正执行前重新校验目标。

第一个有效答复生效，后续新命令对已解决交互返回 INTERACTION_RESOLVED；相同 command_seq 的传输重发返回原响应。任务已取消、目标变化或交互到期返回 INTERACTION_EXPIRED，并更新显示状态。Subagent 当前不能交互审批，需要人工确认时保留 permission_denied；Isolated Skill 当前也未连接人工 approver，需要人工确认时保留 permission_required。可视化接入不自动接通这两条审批路径；改变规则需要另行确定。

## 7. 订阅、快照与重同步

### 7.1 订阅结果

SubscriptionView：`subscription_id,mode:"snapshot"|"replay",cursor:Cursor,snapshot_id:string|null,oldest_available:Cursor`。

- 不传 after：在单一观察水位 S 创建不可变快照并登记订阅，返回 mode=snapshot、cursor=S、snapshot_id；随后只发送 sequence>S 的事件。
- after 有效：返回 mode=replay、cursor=已接受的 after、snapshot_id=null，依次补发 after 之后仍保留的事件，再接实时流，不重复制造新 sequence。
- after 的 instance 不同或已淘汰：返回 RESYNC_REQUIRED，不偷偷从最新事件接着发；客户端重新无 after 订阅。
- after.sequence 大于后台当前水位返回 INVALID_PARAMS。oldest_available 表示可接受的最早 after 水位：若最早保留事件为 E，则该水位为 E−1；空实例为 0。
- 首版每个连接最多一个有效逻辑订阅。创建新订阅成功后使旧订阅失效，客户端忽略旧 subscription_id 的在途消息。

订阅创建响应必须先进入发送队列，再发送该 subscription_id 的补发或实时事件。创建新快照/订阅失败时保留旧订阅，不提前切断原观察路径。

订阅覆盖当前实例的全部用户可见事件，包括 opening 阶段尚无 Session 的交互。不同 Run/Task 的筛选由客户端按 ID 处理，不通过多次订阅抢读同一队列。

### 7.2 快照分页

SnapshotPage：`snapshot_id,cursor:Cursor,expires_at,summary:ApplicationSummary,entries:SnapshotEntry[],next_page_cursor:string|null`。

ApplicationSummary：`application_id:string|null,state:"idle"|"opening"|"ready"|"closing"|"closed",workspace:string|null,session_id:string|null,restored:boolean|null,active_operation_id:string|null,history_revision:string|null,permission:PermissionView|null,active_skills:string[],memory_pending:integer,retention:{oldest_sequence:integer,details_pruned:boolean}`。

SnapshotEntry 为 `{kind:"operation"|"run"|"task"|"message"|"tool"|"interaction",value:对应View}`；同一次 snapshot_id 的所有页固定在同一水位，不逐页读取实时状态。保留所有活动对象和保留窗口内的终态条目；超过保留范围的历史细节不假装完整。分页超时返回 SNAPSHOT_EXPIRED。snapshot_id 数量和累计字节均受第 13 节预算约束；先清理过期快照，仍不足时返回 LIMIT_EXCEEDED，不静默淘汰仍有效的正在分页快照。

客户端拉取快照全部页期间暂存 sequence>S 的实时事件，替换旧投影后按序应用。缓存也应有界；取页失败或暂存超限则重新订阅取快照。纯 application.snapshot 查询不会自动获得后续事件。

### 7.3 缺口与恢复范围

订阅积压超限时废止该订阅，通过独立控制容量发送 subscription.gap，再要求重订阅。gap 不是正常执行事件，不占用全局业务 sequence，格式见第 8 节。

快照重建必须清除旧的运行中卡片：新快照有终态就更新；旧条目已淘汰则标记“过程详情不可恢复”，不能猜测成功或永久显示运行中。Task 轻量终态在实例内保留至其结果保留策略淘汰；完整消息/输出可先淘汰，但不得把缺少详情当作任务仍运行。

这里的恢复仅指 Electron 仍持有 stdio 时，GUI 页面重载或逻辑订阅中断后的恢复。stdio 自身断开会清理后台，不能重新连接原 Python 子进程继续 Run。

## 8. 事件契约

### 8.1 统一信封

```json
{
  "jsonrpc":"2.0",
  "method":"event",
  "params":{
    "subscription_id":"sub-1",
    "event":{
      "schema_version":1,
      "instance_id":"backend-1",
      "sequence":42,
      "emitted_at":"2026-09-09T08:00:00.000Z",
      "type":"tool.started",
      "application_id":"app-1",
      "session_id":"session-1",
      "operation_id":"op-2",
      "run_id":"run-child-1",
      "task_id":"task-1",
      "parent_run_id":"run-main-1",
      "parent_tool_call_id":"call-agent-1",
      "tool_call_id":"call-read-1",
      "item_id":"item-17",
      "source":{"kind":"subagent","name":"reader"},
      "payload":{
        "tool":{
          "item_id":"item-17","run_id":"run-child-1","task_id":"task-1",
          "tool_call_id":"call-read-1","tool_name":"read_file","effect":"observe",
          "origin":"builtin","status":"running","target":"README.md",
          "workspace":"/Users/example/Projects/demo",
          "arguments":{"preview":"{\"path\":\"README.md\"}","truncated":false,"output_id":null},
          "interaction_id":null,"outputs":[],"result":null,
          "started_at":"2026-09-09T08:00:00.000Z","finished_at":null,"elapsed_ms":null
        }
      }
    }
  }
}
```

信封中的身份字段必须出现，不适用时为 null；instance_id、sequence、emitted_at、type、source、payload 不可为 null。source.kind=application 的启动事件可无 application_id；接受 open 后使用已分配 ID。tool 事件必须有 run_id、tool_call_id、item_id；task 事件必须有 task_id，创建早期的 run_id 允许 null。

sequence 表示后台发布顺序，不表示并行工具的模型请求顺序，也不是进程间全局时钟。客户端用 `(instance_id,sequence)` 去重；前端不按模型输出文案推测来源。

### 8.2 事件及 payload

未在表中标可选的 payload 字段均必填。事件在产生事实的位置发布，更新后的查询投影至少包含该事件所表达的变化。

| type | payload | 触发点 |
| --- | --- | --- |
| `operation.started` | `{operation:OperationView}` | 接受响应后开始处理 |
| `operation.changed` | `{operation:OperationView}` | 等待交互、取消中等状态改变 |
| `operation.finished` | `{operation:OperationView}` | 操作得到结果、失败或准备期取消 |
| `application.opened` | `{application_id,session_id,restored,recovery_issues:string[]}` | 核心初始化与 Session 打开成功 |
| `application.closed` | `{application_id,reason:string}` | 所属资源清理结束 |
| `run.started` | `{run:RunView}` | Run 已实际开始，不在准备失败时伪造 |
| `run.phase_changed` | `{phase:RunView.phase}` | 进入模型请求、工具批次、等待或取消阶段 |
| `run.finished` | `{outcome:RunOutcomeView}` | 确定停止原因；监督层保证存活进程内终态收敛 |
| `message.started` | `{message:MessageView}` | 一条公开模型消息开始 |
| `message.delta` | `{offset:integer,text:string,next_offset:integer}` | 同一消息的规范 UTF-8 文本增量，偏移规则同第 10 节 |
| `message.finished` | `{message:MessageView}` | 消息完成或中断；尚未提交时 fact_id=null |
| `tool.requested` | `{tool:ToolView}` | 完整工具请求已确定，尚未保证通过校验/审批 |
| `tool.state_changed` | `{tool:ToolView}` | 进入等待审批等非终态，也用于补齐已确定的工具属性 |
| `tool.started` | `{tool:ToolView}` | 校验与审批通过，真正开始执行，status=running |
| `tool.output` | `{output_id,stream:"stdout"|"stderr"|"result",offset:integer,text:string,next_offset:integer}` | 有真实可展示输出可用 |
| `tool.progress` | `{message:string|null,completed:number|null,total:number|null}` | 工具/服务器实际报告进度；不存在则不发送数值 |
| `tool.finished` | `{status:ToolStatus,result:ToolResultView,elapsed_ms:integer|null}` | 单次工具的确定终态，不等待整批工具结束 |
| `task.created` | `{task:TaskView}` | Task 进入调度记录，运行前即有父子关联 |
| `task.changed` | `{task:TaskView}` | 排队、准备、执行、转后台和 finalizing 状态变化 |
| `task.finished` | `{task:TaskView}` | 子执行与资源交接已收敛；准备失败也有终态 |
| `interaction.requested` | `{interaction:InteractionView}` | 需要用户答复 |
| `interaction.resolved` | `{interaction_id,resolution:"answered"|"cancelled"|"expired",answer:InteractionAnswer|null}` | 答复生效或交互失效 |
| `permission.changed` | `{permission:PermissionView}` | 默认权限/隔离策略或精确规则更新 |
| `skill.changed` | `{revision:string,active:string[],reason:"refresh"|"activate"|"clear"}` | 目录/激活状态改变；详细列表按需查询 |
| `mcp.server_changed` | `{server:McpServerView}` | 真实连接、发现或失败状态改变 |
| `mcp.catalog_changed` | `{summary:McpSummary}` | 已发现/激活目录改变 |
| `compaction.started` | `{compaction_id:string,trigger:CompactionTrigger}` | 压缩实际开始，尚无虚构百分比 |
| `compaction.finished` | `{compaction_id,report:CompactionView|null,cancelled:boolean,error:ErrorView|null}` | 成功、无收益、失败或取消 |
| `memory.changed` | `{pending:integer,last_report:MemoryReportView|null}` | 自然完成后的异步记忆队列/报告变化 |
| `usage.updated` | `{scope:"run",usage:UsageView,basis:"cumulative"}` | 该 Run 的模型累计报告，父子 Run 分开计数 |
| `session.committed` | `{history_revision:string,fact_ids:string[],item_links:{item_id:string,fact_id:string}[]}` | 主 Session 权威事实已经提交；关联消息可据此标记已提交 |
| `worktree.changed` | `{handoff:WorktreeView,reason:string}` | 成果保留、交接或丢弃状态变化 |
| `output.changed` | `{output:OutputView}` | 输出句柄创建、完结、捕获截断或被淘汰，同时更新 ToolView.outputs |

subscription.gap 是控制通知，使用 `method:"subscription.gap"`，params 为 `{subscription_id,instance_id,last_enqueued_sequence:integer,reason:"subscriber_overflow",action:"resubscribe"}`；客户端即使已收到后续在途帧，也应按 gap 废止该订阅并获取新快照。

tool.state_changed 仅用于 requested/waiting_approval/running 等非终态；tool.finished 的 status 必须为终态。客户端不得通过一条 state_changed 推断工具已经结束。

session.committed 只反映主 Session 的权威提交。子临时 Session 自己的提交不得直接转发为这个事件；其消息仍作为子 Run 的展示条目。Isolated Skill 按既有逻辑向主 Session 提交输入/总结时，正常发送主 Session 的提交事件。

所有正常执行事件只陈述公开文字、工具和状态事实。模型内部 reasoning、Provider 不透明 metadata 不作为活动输出；“等待模型响应”不等于能够知道模型内部正在思考什么。

## 9. 状态迁移与取消

### 9.1 三种终态不能混用

- operation.finished：一次用户操作有了结果；它创建的后台 Task 可以仍活跃。
- run.finished：一个 Run 停止；stop_reason 决定具体原因。
- task.finished：一个 Subagent Task 已结束且完成必要资源交接。此前的 agent 工具返回 Task ID 只表示委派调用已返回。

准备失败可以是 operation.started → operation.finished(failed)，没有 Run；Task 也可 created → finished(failed)，run_id 始终为 null。

### 9.2 单工具顺序

```text
requested → waiting_approval → running → succeeded / failed / timed_out / cancelled
requested → running → succeeded / failed / timed_out / cancelled
requested → rejected / invalid / not_started / cancelled
waiting_approval → rejected / cancelled
```

tool.started 只在真正运行时发送。被拒绝、参数无效或执行前取消仍必须发送 tool.finished，但不能假装出现过 started。工具成功产生的文件效果不会因之后取消主 Run 而变成“从未执行”。

连续 observe Tool 的实时完成事件按实际完成顺序发布；最终模型 ToolResult 仍按请求顺序提交。ToolBatchEvent 的既有提交意义可以留在核心，客户端不把整批提交当作每个工具刚刚开始或结束。

### 9.3 取消作用范围

| 操作 | 影响 |
| --- | --- |
| run.cancel | 指定主 Run/直接 Isolated Skill Run；不自动取消其他已创建 Task |
| operations.cancel | 打开、执行准备、压缩、可取消关闭阶段；创建 Run 后委托其既定取消路径；丢弃已进入执行阶段不承诺撤销 |
| tasks.cancel | 指定 Task 及其子 Run/进程，等待结束状态与 Worktree 交接 |
| application.close(cancel) / stdio EOF | 处理整个 Application 所属执行、连接和临时资源 |
| events.unsubscribe | 只解除观察，不取消任何执行 |

当前前台子任务等待超时、手工转后台，或等待因为主 Run 取消而被解除，Task 保持同一个 ID 并转后台继续。不得在 UI 上把它标成已取消，或让它归属于后续新主 Run。

每个真正开始的对象，在后台正常存活的成功、失败和取消路径中都应收敛到唯一逻辑终态。当前 AgentRunner 硬取消路径可能不 yield RunFinished，拟实现必须由执行监督层兜底且去重；进程崩溃无法发送终态时，通过连接故障和 instance 变化表达中断/未知。

### 9.4 展示与模型上下文

子 Agent 的 message/tool 活动可供用户展开，但不逐条加入主 Session Transcript。主 Agent 仍通过现有 ToolResult 或适用的 Task Notice 获得结果。UI 看过通知、重放事件、查询快照均不消费 take_notifications 队列。

Isolated Skill 使用同样的 Run 与工具事件，source.kind=isolated_skill、task_id=null；父 Transcript 保留既有输入和总结语义。Shared Skill 属于实际主 Run，不创建另一份虚假执行。

## 10. 工具输出与详情读取

### 10.1 文本与字节偏移

输出先进行增量解码和展示字段处理，再以规范 UTF-8 文本保存。offset/next_offset 表示**这份规范文本的 UTF-8 字节偏移**，不是 Python 字符数，也不是未经解码的原始进程字节。

stdout、stderr 分别拥有 output_id。tool.output 与 outputs.read 使用同一份字节序列和偏移。首个输出块之前先登记句柄并发布 output.changed；每个块同步更新 ToolView.outputs 的 available_bytes，重新取快照时即使工具暂时没有新输出也能发现已有内容。tool.output 的 stream=result 对应 OutputView.kind=tool_result。

max_bytes 至少 4，最大值见 limits；返回块不能截断 UTF-8 字符。错误字符边界返回 INVALID_OFFSET，客户端始终用 next_offset 继续读取。

OutputSlice：

```json
{"output_id":"output-1","kind":"stdout","offset":0,"text":"测试通过\n","next_offset":13,"available_bytes":13,"producer_finished":false,"capture_truncated":false,"available":true}
```

kind 为 `stdout | stderr | tool_result | message | history`。在生成中读到末尾可以返回空 text、next_offset 不变、producer_finished=false；读取 offset 大于 available_bytes 返回 INVALID_OFFSET。producer_finished 与 capture_truncated 独立：捕获上限到达时，进程可能还在运行。

### 10.2 保留策略与既有 result 引用

现有 Workspace 的 result 引用可能随子 scope 关闭被删除。**为了让用户在子 Task 结束后仍能展开近期工具结果，本版拟新增有界的展示输出保留**，不能直接承诺旧 result 引用永远有效。

- Workspace 继续拥有输出文件；Application 只维护公开 output_id 与所属存储的映射。子 Run 的观察数据经受限路径进入展示存储，不因此获得读写主 Workspace 的能力。
- 运行期工具输出至少保留到所属生产者结束，再按实例总容量淘汰已结束输出。每份输出超限保留前缀并标记 capture_truncated，继续排空真实进程管道以免阻塞执行。
- 子 Task scope 清理前，已选择保留的展示数据需完成转存或已持续写入独立展示存储；仍保留的 output_id 可在 Task 结束后回读。若失败，明确标记 unavailable，不让前端拿主 scope 强读子 scope。
- 已提交历史正文由 Session 的权威事实提供，outputs.read 可通过只读句柄分段读取；不为此新增第二份权威 Transcript。旧历史只保存了预览的工具输出不会凭空补全。
- 输出被淘汰/后台已重启返回 OUTPUT_EXPIRED；底层损坏或原本未保存返回 OUTPUT_UNAVAILABLE。空字符串不代表过期。
- 后台退出清理运行期展示存储。跨重启完整过程和输出保留另行决策。

模型、工具的文字块可在进入观察流前按大小拆分。协议层不事后合并已经分配序号的事件，避免吞掉中间状态；客户端可自行批量刷新绘制。

## 11. 完整通信示例

以下均为拟议协议示例，不是现有程序实测日志。为便于阅读，JSON 展示关键帧；实际所有响应遵守第 4 节通用字段规则。

### 11.1 启动与启动期审批

```json
{"jsonrpc":"2.0","id":"q1","method":"initialize","params":{"protocol":{"major":1,"minor":0},"client":{"name":"artcode-desktop","version":"0.1.0"}}}
```

```json
{"jsonrpc":"2.0","id":"q2","method":"events.subscribe","params":{}}
```

```json
{"jsonrpc":"2.0","id":"q2","result":{"subscription_id":"sub-1","mode":"snapshot","cursor":{"instance_id":"backend-1","sequence":0},"snapshot_id":"snapshot-1","oldest_available":{"instance_id":"backend-1","sequence":0}}}
```

客户端取完 snapshot-1，再发送打开请求；路径为示例，须换成实际本地项目。

```json
{"jsonrpc":"2.0","id":"q3","method":"application.open","params":{"client_command_seq":1,"workspace":"/Users/example/Projects/demo","session":{"kind":"latest"}}}
```

```json
{"jsonrpc":"2.0","id":"q3","result":{"operation_id":"op-open","application_id":"app-1","state":"accepted","last_command_seq":1}}
```

此时允许出现 kind=mcp_server 的 interaction.requested，session_id/run_id 均为 null。客户端立即答复，不能等待 open 结束：

```json
{"jsonrpc":"2.0","id":"q4","method":"interaction.respond","params":{"client_command_seq":2,"application_id":"app-1","interaction_id":"interaction-startup-1","answer":{"allow":true}}}
```

之后出现 interaction.resolved、application.opened、operation.finished。应用进入 ready 后才接受 run.start。

### 11.2 主 Agent 委派并转后台

```json
{"jsonrpc":"2.0","id":"q5","method":"run.start","params":{"client_command_seq":3,"application_id":"app-1","session_id":"session-1","intent":{"mode":"chat","text":"分析项目，并委派一个子 Agent 检查测试。"}}}
```

一条可能的事件顺序如下；多个 Task 并发时可以交错，但对象内部因果关系必须保持。

| 顺序 | 事件 | 归属与解释 |
| --- | --- | --- |
| 1 | operation.started | op-run 接受后开始 |
| 2 | run.started | run-main，source=main |
| 3 | message.started / delta / finished | 主 Agent 的公开说明 |
| 4 | tool.requested / started | run-main 的 call-agent，工具名 agent |
| 5 | task.created | task-1，父为 run-main/call-agent，此时子 run_id 可空 |
| 6 | task.changed | task-1 准备工作目录，phase=preparing |
| 7 | run.started | run-child，task_id=task-1，source=subagent |
| 8 | tool.requested / started | run-child 的 read_file |
| 9 | tool.finished | 子工具读取完成 |
| 10 | tool.requested / started / output | 子 Run 执行 Shell，命令未结束但输出已经可见 |
| 11 | task.changed | 前台等待超时转后台；仍是 task-1/run-child |
| 12 | tool.finished | 父 call-agent 返回 Task ID，不表示 task-1 完成 |
| 13 | message.started / delta / finished | 主 Agent 继续公开回复；与子 Agent 消息使用不同 item_id |
| 14 | session.committed | 主 Session 已提交事实，与展示事件分开 |
| 15 | run.finished / operation.finished | 主 Run 与 op-run 结束，订阅保持 |
| 16 | tool.output / tool.finished | 后台子 Run 的 Shell 继续输出并结束 |
| 17 | message.started / delta / finished | 子 Agent 的公开结论 |
| 18 | run.finished | 子 Run 停止 |
| 19 | task.changed / worktree.changed | 有需要时进入 finalizing，完成成果交接 |
| 20 | task.finished | Task 最终结果可查；模型 Notice 仍待适用时投递 |

GUI 把这些事件组织为“主 Run → agent 工具 → Task → 子 Run → 工具与输出”。TUI 可以用缩进日志和活动摘要展示相同关系。

### 11.3 运行中取消与审批失效

```json
{"jsonrpc":"2.0","id":"q6","method":"run.cancel","params":{"client_command_seq":4,"application_id":"app-1","run_id":"run-main"}}
```

若主 Run 仍在执行，返回 requested=true，随后关闭其未解决审批、停止主 Run。已创建的后台 Task 继续按第 9 节规则运行。若 Run 已结束，返回 requested=false，不对新 Run 生效。

```json
{"jsonrpc":"2.0","id":"q7","method":"tasks.cancel","params":{"client_command_seq":5,"application_id":"app-1","task_id":"task-1"}}
```

显式取消子 Task 后，观察工具终态、子 Run 终态、必要 Worktree 交接和 task.finished。客户端不能在收到“取消请求已接受”时提前把所有资源视为已清理。

## 12. 错误契约

协议与请求错误使用 JSON-RPC error；已接受的长操作失败使用 operation.finished.error；单工具失败通常使用 tool.finished，不直接终止 Application。

```json
{"jsonrpc":"2.0","id":"q8","error":{"code":-32000,"message":"当前 Session 已有前台执行。","data":{"code":"BUSY","category":"state","retryable":true,"last_command_seq":6,"details":{"active_operation_id":"op-active"}}}}
```

| 数字 code | 含义 |
| --- | --- |
| -32700 | JSON 解析失败 |
| -32600 | 请求结构无效或不支持 batch |
| -32601 | 方法未知或未协商支持 |
| -32602 | 参数类型、枚举或必填字段错误 |
| -32603 | 内部错误，信息必须脱敏 |
| -32000 | ArtCode 业务/状态错误，具体类型读取 error.data.code |

业务错误码：`NOT_INITIALIZED`、`VERSION_MISMATCH`、`INVALID_STATE`、`BUSY`、`SESSION_BUSY`、`NOT_FOUND`、`PLAN_REQUIRED`、`PERMISSION_DENIED`、`NOT_CANCELLABLE`、`INTERACTION_RESOLVED`、`INTERACTION_EXPIRED`、`SUBSCRIPTION_REQUIRED`、`RESYNC_REQUIRED`、`CURSOR_STALE`、`SNAPSHOT_EXPIRED`、`HISTORY_CHANGED`、`OUTPUT_EXPIRED`、`OUTPUT_UNAVAILABLE`、`INVALID_OFFSET`、`COMMAND_CONFLICT`、`COMMAND_OUT_OF_ORDER`、`COMMAND_RESULT_EXPIRED`、`OPERATION_EXPIRED`、`LIMIT_EXCEEDED`、`UNSUPPORTED`。

error.data.category 为 `protocol | validation | state | permission | transport | model | tool | storage | internal`；message 供用户阅读，客户端不能解析文案判断类别。retryable 仅表示条件改变后可重试，不授权自动重新执行写操作。未知错误保留诊断，不显示原始堆栈或配置。

模型错误保留认证、网络、超时、上下文窗口、协议、流中断等既有 category；工具拒绝、超时、取消和参数错误保持独立状态。不能将全部异常拼成一种“运行失败”而失去原有语义。

## 13. 有界资源与背压

下列数值为 v0.1 建议默认值，后端在 initialize.limits 中报告实际值；前端按报告值工作，不散落硬编码。

| limits 字段 | 建议值 | 行为 |
| --- | --- | --- |
| `max_frame_bytes` | 1048576 | 1 MiB 单帧上限；超长字段转引用/分页，不静默截断请求 |
| `max_chunk_bytes` | 16384 | 单条文字/输出增量最多 16 KiB，UTF-8 字符完整 |
| `max_preview_bytes` | 8192 | TextView.preview 最多 8 KiB，长内容用 output_id，并在 UTF-8 字符边界截断 |
| `max_page_items` | 200 | 各分页 limit 上限，默认 100 |
| `max_output_read_bytes` | 65536 | 单次输出读取上限 64 KiB，默认 16 KiB |
| `event_retention_count` | 5000 | 与字节上限共同约束，先到上限先淘汰最早事件 |
| `event_retention_bytes` | 8388608 | 事件尾部最多 8 MiB，不含可回读的正文文件 |
| `subscription_queue_count` | 1024 | 逻辑订阅待发队列上限 |
| `subscription_queue_bytes` | 2097152 | 逻辑订阅待发队列最多 2 MiB |
| `transport_queue_bytes` | 4194304 | 整条 stdout 待发数据最多 4 MiB，另预留控制容量 |
| `control_queue_bytes` | 262144 | gap、错误、取消确认等控制消息容量，不能排在无限输出后面 |
| `snapshot_ttl_seconds` | 60 | 不可变快照分页读取期限；到期明确失败 |
| `max_snapshot_count` | 4 | 同时保留的不可变快照数量上限 |
| `max_snapshot_bytes` | 16777216 | 所有不可变快照合计最多 16 MiB，创建时检查 |
| `command_result_cache_count` | 512 | 已结束请求结果缓存；水位仍阻止过期请求重复执行 |
| `max_runtime_output_bytes` | 8388608 | 每份临时工具输出保存前缀最多 8 MiB |
| `runtime_output_total_bytes` | 134217728 | 运行期展示输出总预算 128 MiB，淘汰结束项；不足时明确截断新捕获 |

活动 Run/Task 的控制信息不能仅因事件尾部淘汰而消失；结束对象的详情按保留窗口裁剪。若活动控制记录或快照资源预算不足，应在接受更多执行前返回 LIMIT_EXCEEDED，不把已有执行悄悄移除。

所有分页同时受条数与单帧字节限制，后端可少于 limit 返回，只要 next_cursor/next_page_cursor 正确。单条仍超限时只能通过已声明的 TextView 或规则输出引用缩小长内容；不得临时更改字段类型。仍无法容纳的单条返回 LIMIT_EXCEEDED。人工交互目标等不能安全截断的关键字段必须完整呈现，否则明确失败，不能让用户批准未展示清楚的对象。

慢逻辑订阅者溢出时，删除其待发普通事件并用预留控制容量发送 gap；核心仍推进。正常响应与控制消息具有独立调度机会，不能被大量 stdout 长期饿死。若整条 stdio 管道持续不可写，无法保证任何消息交付，进入连接故障关闭流程；不承诺无限存活与无限缓存。

## 14. 与当前实现的对应及变更边界

| 当前证据 | 可复用能力 | 必须新增的实现 |
| --- | --- | --- |
| `artcode/core/application.py:72` | Interaction 与 Application 分离 | 类型化客户端操作、独立订阅、操作登记、明确 DTO |
| `artcode/_application/events.py:7` | 文本、usage、压缩、工具结果转换 | RunStarted 与全部来源关联、保留错误类别 |
| `artcode/_agent/runner.py:172` | 正确等待工具并提交协议 | 等待期间观察事件、消息条目和取消终态兜底 |
| `artcode/_tool/catalog.py:220` | 参数、策略、审批和执行统一入口 | requested/started/finished，精确审批关联 |
| `artcode/_subagent/execution.py:78` | 复用 AgentRunner 执行子 Run | 逐条转发，增量更新 Task，不收齐后才展示 |
| `artcode/_subagent/catalog.py:172` | 前台等待、转后台、取消 | Task 关系和实时状态，不改变已有取消作用范围 |
| `artcode/_skill/execution.py:81` | 隔离执行及既定总结提交 | Isolated Skill 过程实时可见 |
| `artcode/_workspace/processes.py:67` | 进程树、超时、输出回收 | 持续读取两条流与展示输出保留 |
| `artcode/_tool/mcp.py:89` | 发现、激活、实际调用与错误 | 当前状态投影、真实可用时的 progress 转发 |
| `artcode/_application/lifecycle.py:440` | 一次性模型 Task 通知 | 独立 UI 观察，不消费模型 Notice |
| `artcode/_session/locking.py:10` | Session 独占锁 | 保留；新增协议不能绕过它 |

协议方法名、分页、快照 DTO、UTC 观察时间、实例游标、幂等序号、输出生命周期均属新接口工作。现有业务能力不等于相应点号方法已经可调用。

TUI 的 `/clear` 当前还解除 Skill 激活；仅拆分接口不静默改变这个产品行为。可由 TUI 组合 skills.clear 和本地清屏，GUI 使用清楚的操作名称。是否最终把两个动作分开，由后续需求确认。

## 15. 可观察验收清单

这些是未来实现的验收项，本次文档工作不将其勾选为已通过。

- [ ] initialize 无业务效果，版本不匹配时不启动 MCP、不打开 Session。
- [ ] 启动期 MCP 审批可在 application.open 未完成时接收并回复，不发生等待死锁。
- [ ] 一次目标接受后有唯一 operation；相同 command_seq 重发不会重复提交用户事实或启动 Run。
- [ ] 结果缓存淘汰后重发旧序号得到明确过期错误，不再次执行。
- [ ] 主工具未结束时已收到 started；真实 Shell 尚未退出时已收到至少一段输出。
- [ ] 两个并发子 Task 的工具及文字正确归属，交错到达也不串卡片。
- [ ] agent 工具返回后台 Task ID 后，子 Task 的事件持续更新；父 Run 结束后仍可接收。
- [ ] 取消父 Run 不把继续运行的子 Task 显示为取消；显式 tasks.cancel 才终结目标 Task。
- [ ] Role/Worktree 准备失败时可看到 Task 失败，全程不伪造子 Run。
- [ ] 工具拒绝、参数失败、超时、取消及硬取消均有正确终态，没有永久运行卡片。
- [ ] 同一个 Task 前台转后台保持编号，最终交接与完成只发生一次。
- [ ] 并发工具显示实际完成顺序，模型 ToolResult 仍保持原请求顺序。
- [ ] 查看、重放和重新订阅不消费模型 Notice；子 Agent 中间输出不污染主 Transcript。
- [ ] Isolated Skill 实时可见，但不新增 Task/Worktree，不改变权限语义。
- [ ] Subagent 需交互审批的工具继续按既有规则拒绝，不因 GUI 而获得权限。
- [ ] 旧审批被取消/解决后，迟到答复不能推进工具执行；重复传输返回原决定。
- [ ] 快照所有分页来自同一水位；分页期间产生的事件随后可顺序应用，无夹缝丢失。
- [ ] 游标过期与输出过期明确区分；重同步不会把丢失终态的工具永久标成运行中。
- [ ] 子 Task scope 关闭后，仍在运行期保留预算内的展示输出可以回读；被淘汰时明确报错。
- [ ] 中文跨块不损坏，byte offset 不跳字；生成中的输出末尾与真正结束可区分。
- [ ] 无 MCP 进度的调用只显示运行中，不制造百分比或内部动作。
- [ ] 协议与展示队列均有界，慢订阅不阻塞其他执行；持续管道故障按明确规则清理。
- [ ] 快照/历史/事件不包含 Protocol Metadata、配置密钥或鉴权头。
- [ ] TUI 和 stdio 消费者分别完成普通对话、Plan/Act、审批、取消和 Session 历史恢复。
- [ ] 真实集成完成“主 Agent → agent 工具 → 子 Run → 文件/Shell 工具 → 后台/前台结束 → 主结论”并证明过程在最终结果之前到达。
- [ ] 真实 Shell、Git、MCP、进程清理与已配置 Provider 检查记录实际结果；外部阻塞不冒充 live 通过。

## 16. 待决定的产品范围

| 问题 | 本草案状态 |
| --- | --- |
| 是否两端同时控制同一 Run | 未决定；v0.1 按独立入口与单控制连接设计 |
| 关窗口、退出桌面应用分别如何处理 | 未决定；本文只定义后端 close 与传输断开行为 |
| 是否保留跨重启完整子 Agent 执行树 | 未决定；当前仅权威 Session 历史跨重启 |
| 多主 Session、全局项目和历史列表 | 后续工作台范围，不把现有单 Session Application 声称为已支持 |
| 文件编辑器、完整 diff、媒体预览 | 后续 GUI 能力，需要另补接口与验收 |
| 新章节编号 | 暂用 ch15，可按用户章节安排调整 |

## 17. 文档与实现同步

修改接口时同步四项：本文契约、Python 类型与序列化、TUI/GUI 消费方式、对应验收。可在实现阶段由单一协议定义生成 JSON Schema 与 TypeScript 类型；本次文档不生成或修改程序代码。

正式实施需根据批准范围同步章节 Spec/Tasks/Checklist、行为矩阵及必要 ADR。现有 `docs/adr/0003-core-contract-freeze.md` 的冻结契约仍然有效；这份草案不自行替代它。原 `docs/双界面接口设计草案.md` 转为本文入口，避免维护两份相互冲突的接口定义。
