# ch10：斜杠命令系统 Checklist

> 本清单在实现阶段逐项执行。每项都必须通过运行测试、捕获调用或观察终端行为验证，不能只通过阅读代码判定。
>
> 验收完成于 2026-08-08：全量 413 项测试通过；真实 DeepSeek ch10 端到端、全部既有 live integration、wheel 构建与隔离安装冒烟均通过。

## 注册定义与元数据

- [x] 默认注册中心恰好包含 12 个公开规范名称：`/exit`、`/quit`、`/help`、`/plan`、`/do`、`/compact`、`/permission`、`/sandbox`、`/sessions`、`/memory`、`/clear`、`/status`。（验证：枚举默认 registry 并对比有序名称列表。）
- [x] 12 个内置定义的 aliases 都是空集合，`/exit` 与 `/quit` 返回不同定义对象。（验证：参数化读取元数据并比较对象身份和规范名称。）
- [x] 默认 registry 中隐藏命令数量为 `0`，不存在 `/session`、`/review` 或任何补全专用伪命令。（验证：枚举全部定义并搜索名称。）
- [x] 每个内置定义都有非空名称、简短描述、至少一条 usage、执行类型、handler；只有确实接收参数的命令提供参数提示。（验证：参数化校验 12 个定义字段。）
- [x] LOCAL 固定包含 `/exit`、`/quit`、`/help`、`/compact`、`/sessions`、`/memory`、`/status`。（验证：按类型分组 registry 定义。）
- [x] UI_STATE 固定包含 `/permission`、`/sandbox`、`/clear`。（验证：按类型分组 registry 定义。）
- [x] AI 固定包含 `/plan`、`/do`。（验证：按类型分组 registry 定义。）
- [x] 注册一个合法测试 alias 后，规范名称和 alias 都解析到同一命令定义。（验证：分别用两种标识查询 registry。）
- [x] 名称与已有名称只相差大小写时注册失败，错误同时指出冲突标识、已有命令和新命令。（验证：依次注册 `/Help` 与 `/help` 并断言异常内容。）
- [x] 新名称与已有 alias 冲突时注册失败。（验证：先注册带 `/h` alias 的定义，再注册规范名称 `/H`。）
- [x] 新 alias 与已有名称冲突时注册失败。（验证：先注册 `/help`，再注册 alias `/HELP`。）
- [x] 两个不同命令的 alias 冲突以及同一定义内部 alias 重复时都注册失败。（验证：分别构造两种 registry。）
- [x] 名称或 alias 不以 `/` 开头、含空格/Tab/换行或为空时注册失败。（验证：参数化非法标识。）
- [x] 描述为空、usage 为空或 handler 不可调用时注册失败。（验证：逐字段构造非法定义。）
- [x] 某次注册因一个坏 alias 失败后，该定义的名称和其他 alias 均无法查询，先前定义保持可用。（验证：比较失败前后的 registry 枚举和索引查询。）
- [x] 将冲突定义放入启动构造路径时，在第一次 `read_input` 前以非零状态失败并显示冲突信息。（验证：给 CLI/Runtime 注入冲突 registry builder，用 Spy 断言 TUI 未读取输入。）

## 输入解析与路由

- [x] `""`、空格、Tab 和多行纯空白都解析为 EMPTY，handler、Provider 和 Conversation 均无变化。（验证：参数化输入并统计三类调用。）
- [x] `"你好"`、`"  你好  "` 和 `"请解释 /help"` 都解析为 MESSAGE，交给 Agent 的内容与原始输入逐字一致。（验证：Fake Provider 捕获最后用户内容。）
- [x] `"/help"`、`"  /help"` 和 `"\t/help"` 都解析为 COMMAND 并命中 `/help`。（验证：参数化检查 route 和规范名称。）
- [x] `/HeLp`、`/HELP` 和 `/help` 都命中同一注册项。（验证：解析后通过 registry 查询并比较定义。）
- [x] `/plan 任务`、`/plan\t任务` 和 `/plan\n任务` 都以 `/plan` 为命令名，以 `任务` 为参数。（验证：参数化解析三个分隔符。）
- [x] 多行 `/plan 第一行\n  第二行\n第三行` 保留三行顺序与内部缩进，只去除参数整体两端空白。（验证：比较解析参数的完整字符串。）
- [x] `/unknown\n继续内容` 只进入命令路径，显示 `/unknown` 和 `/help`，不会成为普通用户消息。（验证：Provider 调用数为 `0`，Conversation 和 JSONL 行数不增加。）
- [x] 未知单行命令、未知大小写命令和带参数的未知命令都返回输入循环，不退出进程。（验证：每条未知命令后继续执行 `/status` 或 `/exit`。）
- [x] 同一输入只执行 COMMAND 或 MESSAGE 一条路径，不能既显示命令结果又追加用户消息。（验证：为 dispatcher 与 Agent 各装 Spy，逐类输入断言互斥计数。）
- [x] PromptSession 未安装命令 completer，按 Tab 不会触发命令补全或多候选菜单。（验证：检查 session 配置并运行按键交互测试。）

## Help 与参数提示

- [x] `/help` 总览恰好展示 12 个公开命令，并按默认 registry 登记顺序排列。（验证：捕获文本并比较名称出现顺序。）
- [x] `/help` 总览中每个命令都有类型、简短描述和首条 usage，不依赖静态 `HELP_TEXT`。（验证：为测试 registry 新增定义，输出自动出现且无需修改帮助常量。）
- [x] `/help /status` 展示 `/status` 的名称、LOCAL 类型、描述、全部 usage、无 alias、无参数提示和非隐藏状态。（验证：捕获单命令详情。）
- [x] `/help /plan` 展示必填任务提示和多行任务用法；`/help /do` 展示可选附加说明。（验证：捕获两条详情并断言参数提示。）
- [x] 测试隐藏定义不出现在 `/help` 总览，但 `/help /隐藏名称` 能查看详情，精确输入仍能执行。（验证：使用自定义 registry 和 Fake Controller。）
- [x] `/help /unknown` 显示未知名称与 `/help` 引导，不调用 Provider。（验证：捕获消息与 Provider Spy。）
- [x] `/exit`、`/quit`、`/compact`、`/sessions`、`/memory`、`/clear`、`/status` 收到任何非空参数时显示各自 usage，既不执行原动作也不退出。（验证：参数化 handler 调用计数。）

## Controller 与界面解耦

- [x] 命令定义、解析器、registry 和 dispatcher 的单元测试只使用 Fake Controller，不创建 Rich Console 或 Prompt Toolkit session。（验证：运行 `tests/unit/test_commands.py` 并检查 fixture 依赖。）
- [x] 命令包导入不会导入 `rich` 或 `prompt_toolkit`。（验证：扫描 `artcode/commands/` import，并在未导入两框架的干净解释器中导入命令包。）
- [x] Controller 可观察地支持显示消息、清屏、发送用户消息、设置显示模式、查询最近 Token 和刷新状态。（验证：用实现完整 Protocol 的 Fake Controller 执行相应内置命令。）
- [x] dispatcher 只 await 注册定义中的 handler，不再返回或解释 `plan`、`compact` 等字符串 action。（验证：自定义 handler 返回 CONTINUE/EXIT 并检查 Runtime 只处理 flow。）
- [x] 处理函数抛出未预期异常时不会被改送 Agent。（验证：注入抛异常 handler，断言 Provider 未调用且异常沿现有调用路径暴露。）

## 前序内置命令兼容

- [x] `/exit` 和 `/quit` 均显示既有退出消息并以状态 `0` 结束正常输入循环。（验证：分别启动隔离 Runtime。）
- [x] `/plan` 缺少任务时显示“需要任务描述”的用法提示，不调用 Provider、不改变最近计划。（验证：预置 PlanMemory 后执行并比较。）
- [x] 多行 `/plan` 使用且只使用 `read_file`、`find_files`、`search_text` 三个内置读工具，同时保留可用 MCP 工具的 ch07 语义。（验证：捕获发送给 Provider 的工具定义。）
- [x] `/plan` 自然完成后把最终计划写入 Conversation/JSONL 并保存为最近计划。（验证：检查消息 mode 和 PlanMemory。）
- [x] `/do` 没有最近计划时提示先执行 `/plan 任务描述`，不调用 Provider。（验证：空 PlanMemory + Provider Spy。）
- [x] `/do` 有最近计划时使用全工具 Agent Loop；附加说明存在时与最近计划一起进入执行目标。（验证：捕获用户消息与工具列表。）
- [x] `/compact` 不接受参数，不把命令写入 Conversation/JSONL，不触发 Agent 工具；存在旧历史时允许调用摘要 Provider。（验证：比较消息/文件行数、工具计数和 Provider 请求形状。）
- [x] `/compact` 在没有可压缩前缀时返回 `noop`，在自动线以下和熔断打开时仍可手动尝试，失败时原 Conversation 不变。（验证：复用 ch08 三组压缩 fixture。）
- [x] `/permission` 无参数时显示当前模式与 `default`、`edit`、`full`；三个合法值可切换，非法值不改变状态。（验证：依次查询、切换、非法输入、再查询。）
- [x] `/sandbox` 无参数时显示当前策略与 `auto`、`ask`、`off`；`auto`、`ask` 可切换，`off` 必须先确认，拒绝时状态不变。（验证：Fake 审批器覆盖允许和拒绝。）
- [x] `/sessions` 显示当前会话标记和最近 `20` 个有效会话的 ID、标题、消息数、活动时间，不替换运行中的 Conversation。（验证：构造 `21` 份会话并比较对象身份。）
- [x] `/memory` 显示用户级/项目级路径、active/superseded/issue 数和最近更新状态，不显示任一笔记正文。（验证：植入唯一秘密正文并扫描输出。）

## `/clear`、模式标记与 `/status`

- [x] 等待输入时提示符形如 `[DEFAULT] deepseek-v4-flash > `，普通请求和 Do 输出标签均包含 `[DEFAULT]`。（验证：固定模型名并捕获 TUI 输出。）
- [x] Plan 请求开始后、首个模型输出前可观察到 `[PLAN]`，规划自然结束后下一次提示符恢复 `[DEFAULT]`。（验证：使用受控两次输入和流式事件。）
- [x] Plan 请求被 Ctrl+C 取消、Provider 出错或达到停止条件后，下一次提示符仍恢复 `[DEFAULT]`。（验证：分别注入取消、错误和迭代上限。）
- [x] `/clear` 使此前终端内容从用户可见区域消失，且不会重建或关闭 PromptSession。（验证：真实记录终端/控制序列并比较 session 对象身份。）
- [x] `/clear` 前后的 Conversation 快照、JSONL 内容、PlanMemory、PermissionState、Shell 策略、会话 ID、记忆统计和最近 TokenUsage 完全一致。（验证：执行前后逐对象/文件比较。）
- [x] `/status` 固定展示模型、Workspace、`[DEFAULT]/[PLAN]`、权限模式、Shell 策略、Seatbelt 状态、会话 ID、会话状态、上下文估算、窗口上限、最近 Token 用量共 `11` 组信息。（验证：构造完整快照并逐字段搜索输出。）
- [x] 尚未收到 Provider usage 时，`/status` 的最近 Token 字段显示“不可用”，不伪造 `0`。（验证：首次输入直接执行 `/status`。）
- [x] 收到真实 usage 后，`/status` 显示最近一份 `prompt`、`completion`、`total`、`cached`、`cache_miss` 值；后续 usage 覆盖前值。（验证：连续注入两份 Token 事件。）
- [x] `/status` 的上下文估算使用当前 Default Prompt、工具定义和 ch08 anchor；ContextManager 缺失时显示“不可用”。（验证：带/不带 manager 捕获估算参数与输出。）
- [x] 执行上下文估算不会追加 Conversation/JSONL、运行压缩、更新 Token anchor、执行工具或调用 Provider。（验证：在五个边界安装 Spy 并比较前后快照。）
- [x] `/status` 输出不包含完整 API Key、MCP Header/环境变量值、三层指令正文、记忆正文、会话消息正文或摘要草稿。（验证：为每类数据植入不同秘密标记并扫描 Console 输出。）

## Provider、Conversation 与持久化边界

- [x] `/exit`、`/quit`、`/help`、`/permission`、`/sandbox` 查询/合法切换、`/sessions`、`/memory`、`/clear`、`/status` 均不调用 Provider。（验证：逐命令运行并断言 Fake Provider 请求数为 `0`；`/sandbox off` 使用 Fake 本地确认。）
- [x] 除 `/plan`、`/do` 外，命令原文均不作为 user 消息进入 Conversation 或 JSONL；`/compact` 只允许产生 ch08 摘要替换。（验证：逐命令比较消息与文件记录。）
- [x] `/plan` 写入的是任务参数而不是带 `/plan` 前缀的原命令；`/do` 写入的是最近计划和附加说明组合，而不是 `/do` 字面量。（验证：检查捕获的 user message。）
- [x] 未知命令、帮助查询失败和参数错误不改变 PlanMemory、PermissionState、Shell 策略、ContextManager circuit 或 Persistence 状态。（验证：预置非默认状态后执行错误集合并逐项比较。）
- [x] `/compact` 是唯一 LOCAL 类型中允许调用 Provider 的命令，其摘要请求不携带工具定义。（验证：遍历 LOCAL handler 并捕获 Provider 请求。）

## 编译、测试与打包

- [x] `artcode/commands/` 中不存在旧 `CommandResult`、字符串 `action` 分发或静态 `HELP_TEXT`。（验证：运行 `rg -n "CommandResult|command_result\.action|HELP_TEXT" artcode tests`，期望无有效命中。）
- [x] Runtime 输入循环不按具体命令名称写条件分支，只处理 EMPTY、MESSAGE、COMMAND 和 CONTINUE/EXIT。（验证：命令集成测试注册一个新测试命令，无需修改 Runtime 即可执行。）
- [x] `artcode/config.py` 的章节名称为 `ch10：斜杠命令系统`，启动 Panel 显示该标题。（验证：加载配置状态并捕获启动输出。）
- [x] `pyproject.toml` 未新增第三方运行时依赖，Prompt Toolkit 与 Rich 版本约束保持现有兼容范围。（验证：与 ch09 提交对比 dependencies。）
- [x] 全部单元测试通过。（验证：运行 `.venv/bin/python -m pytest tests/unit -q`。）
- [x] 全部非 live 集成测试通过。（验证：运行 `.venv/bin/python -m pytest tests/integration -q -k "not live"`。）
- [x] 真实 Seatbelt 测试通过且没有因 ch10 被 skip。（验证：运行 `.venv/bin/python -m pytest tests/integration/test_seatbelt_live.py -q -rs`。）
- [x] 真实 DeepSeek ch10 测试通过且没有因 API 成本被 skip。（验证：运行 `.venv/bin/python -m pytest tests/integration/test_ch10_live_e2e.py -q -rs`。）
- [x] 全量测试通过，没有未等待 Task、未释放会话锁、临时目录残留或资源警告。（验证：运行 `.venv/bin/python -m pytest -q` 并检查告警。）
- [x] wheel 构建成功，安装后的 `artcode` 能从非源码 Workspace 启动并执行 `/help`、`/status`、`/clear`、`/exit`。（验证：运行 `.venv/bin/python -m pip wheel . --no-deps`，在临时虚拟环境安装完整依赖，并验证 CLI 入口及 12 命令注册表。）

## 端到端场景

- [x] 场景一：启动 ArtCode → 看到 `[DEFAULT]` → 输入普通问题 → Agent 回复 → 输入 `/status` → 本地显示状态 → 输入 `/exit` → 正常退出；只有普通问题产生 Provider 请求和对话记录。（验证：确定性 Runtime 集成测试。）
- [x] 场景二：输入多行 `/plan` → 输出标记为 `[PLAN]` → 只读工具生成并保存计划 → 返回 `[DEFAULT]` → 输入 `/do 附加说明` → 全工具执行最近计划并完成验证。（验证：Fake Provider 集成测试与真实 DeepSeek 测试各执行一次。）
- [x] 场景三：输入 `/UNKNOWN\n不要交给模型` → 本地显示未知命令和 `/help` → 下一条 `/help` 列出 12 个命令 → Conversation/JSONL/Provider 均没有未知命令内容。（验证：持久化集成测试。）
- [x] 场景四：先产生一份真实 Token usage 和最近计划 → 执行 `/clear` → 再执行 `/status` 与 `/do` → 状态仍显示原 usage，Do 仍找到原计划，旧终端内容已清除。（验证：Runtime + 记录终端集成测试。）
- [x] 场景五：执行 `/permission edit`、`/sandbox ask`、`/sessions`、`/memory` → 状态查询反映新进程内设置且会话/记忆只显示元数据 → 重启后权限恢复 Default、Sandbox 恢复 Auto。（验证：两次进程生命周期集成测试。）
- [x] 场景六：构造名称/alias 大小写冲突的启动 registry → ArtCode 在首次输入前显示冲突双方并以非零状态退出 → 未创建任何对话消息或 Provider 请求。（验证：CLI 启动集成测试。）
