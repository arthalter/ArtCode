# ch09：会话恢复与长期记忆 Checklist

> 每项都必须通过运行测试、启动真实 CLI 或检查生成文件获得实际证据；“代码看起来正确”不算通过。

## 路径、格式与权限

- [ ] 用户指令位于 `~/.artcode/instructions.md`，项目根指令位于 `<workspace>/ARTCODE.md`，项目本地指令位于 `<workspace>/.artcode/instructions.md`。（验证：在隔离 home 与 Workspace 构造路径，对比六个实际路径。）
- [ ] 会话只位于 `<workspace>/.artcode/sessions/*.jsonl`，用户级和项目级笔记分别位于 `~/.artcode/memory/` 和 `<workspace>/.artcode/memory/`。（验证：启动一次后检查目录树。）
- [ ] 新功能不创建 `~/.mewcode`、`<workspace>/.mewcode` 或任何并行命名空间。（验证：在空临时目录运行全流程并搜索 `.mewcode`。）
- [ ] ArtCode 自动创建的持久目录权限为 `0700`，JSONL、笔记、索引和临时文件最终权限为 `0600`。（验证：在 macOS 上检查 stat mode。）
- [ ] 指令、会话和笔记路径已纳入敏感路径，普通文件/命令工具不能绕过内部管道改写。（验证：通过 Tool Path Policy 对每类路径发起读写预检，观察均被拒绝。）
- [ ] 从不是源码目录的 Workspace 启动时，所有持久路径仍由用户 home 和 CLI Workspace 正确推导。（验证：在临时工作目录运行入口并检查落盘位置。）

## 三层指令

- [ ] 三份指令同时存在时，实际 System Prompt 中的顺序为固定系统约束 → 项目本地 → 项目根 → 用户级。（验证：给三层写入唯一标记，检查 Fake Provider 第一次请求中的位置。）
- [ ] 项目本地、项目根和用户级指令的 Prompt 优先级分别为 210、220、230，且不能排到固定系统约束之前。（验证：运行 Prompt Builder 顺序测试。）
- [ ] 指令入口不存在时安静跳过，单份不可读或非 UTF-8 时显示 issue 但不影响其他层。（验证：分别模拟缺失、权限错误和坏编码，检查 Bundle 与启动状态。）
- [ ] `@include relative/file.md` 独立行在原位置展开，不把指令内普通文字或代码块中的 `@include` 误识别。（验证：使用前/中/后标记和 fenced code 构造文件，检查展开文本。）
- [ ] 入口 A 引用 B、B 引用 C 时，相对路径分别以当前声明文件所在目录为基准。（验证：使用两个不同子目录的嵌套引用测试。）
- [ ] 从入口开始的第 1–5 层引用都能展开，第 6 层不读取并产生深度 issue。（验证：构造 7 份链式 Markdown，检查展开结果和 issue。）
- [ ] A → B → A 和 A → A 都被 resolved Path visited 集合截断，不出现递归死循环。（验证：运行循环引用测试并检查只读一次。）
- [ ] 绝对路径、非 `.md` 文件、相对跳出 Workspace/用户 ArtCode 目录和符号链接跳出都被拒绝。（验证：为四种情况各运行一个越界用例，确认外部秘密标记从未进入 Bundle。）
- [ ] 三层与引用展开后的注入总量不超过 64KB UTF-8，且高优先级完整内容优先保留。（验证：三层合计写入超过 64KB 的不同标记，检查字节数与保留顺序。）
- [ ] 最后部分指令在合法 UTF-8 字符和完整换行边界结束，界面显示被截止/省略的来源。（验证：在 64KB 边界附近放置中文和 Emoji，确认最终文本可 UTF-8 解码。）
- [ ] 手写指令只在启动时加载，运行中修改后本进程不热重载，重启后生效。（验证：在两次请求之间改文件，对比本进程和新进程 Prompt。）

## JSONL 会话写入

- [ ] 会话 ID 符合 `YYYYMMDD-HHMMSS-xxxx`，`xxxx` 是 4 位小写十六进制，同秒创建冲突时会重生成而不覆盖。（验证：固定 now 并注入首次后缀冲突，检查两份文件。）
- [ ] 一个会话只有一份 `<id>.jsonl`，同目录没有同 ID 的 meta/sidecar 文件。（验证：运行会话后列出 sessions 目录。）
- [ ] JSONL 每行都包含 `v=1`、UTC timestamp、entry ID、mode 和一份 OpenAI-compatible message，且可用标准 JSON 单行解析。（验证：对真实会话逐行 `json.loads`并检查 Schema。）
- [ ] 用户消息在调用 Provider 前已追加，assistant 工具调用在执行工具前已追加，tool 结果和最终 assistant 回复在各自确定时立即追加。（验证：在四个时点暂停 Fake Flow 并检查当时磁盘行数。）
- [ ] System Prompt、普通 system-reminder、时间跨度 reminder、ch08 conversation summary 和 context boundary 均不进入原始 JSONL。（验证：触发普通请求和 ch08 压缩，搜索五类内部标记。）
- [ ] ch08 替换大工具结果、替换历史摘要或重试请求不会在 JSONL 重复写入已有消息。（验证：触发大结果和自动压缩，按 entry ID 计数，每个只一行。）
- [ ] 单个工具结果会使 JSONL 行超过 4MB 时，存档写入包含原始字节数和有界预览的协议完整占位 tool 记录，当前 ch08 仍看到完整结果。（验证：执行返回大于 4MB 的 Fake Tool，对比 Conversation 和 JSONL。）
- [ ] 超过 4MB 的用户或助手纯文本不会生成未来必然跳过的存档行，用户看到明确错误。（验证：构造超限正文并检查未发送 Provider 请求。）
- [ ] 同一 JSONL 被一个 ArtCode 进程锁定后，第二个 Journal 不能获得写锁。（验证：用两个独立进程尝试打开同一文件。）
- [ ] close 可重复调用，解锁且不删除 JSONL，之后新进程可恢复并继续追加。（验证：两次 close 后重新打开并写入一行。）

## 会话扫描、恢复与清理

- [ ] 会话 ID 由文件名得到，标题、消息数、活动时间和坏行数都由扫描 JSONL 得到，不读取 meta 或缓存数据库。（验证：手工写一份 JSONL 后运行 Catalog，对比期望。）
- [ ] 会话标题来自第一条非空用户消息，折叠换行/多空格，最多 50 个 Unicode 字符并在超限时完整添加省略号。（验证：使用中文、Emoji、换行和超长首消息。）
- [ ] 会话列表按最后有效活动时间稳定降序，默认最多展示 20 个，不删除或忽略其他未过期会话。（验证：创建 25 份不同时间会话，检查顺序和显示数。）
- [ ] 默认启动恢复最近未锁定的可用会话；无可用会话时自动新建。（验证：分别在有/无历史的 Workspace 启动。）
- [ ] 默认目标已被另一进程锁定时新建会话并显示原因，不悄悄追加一份更旧历史。（验证：锁定最近会话后默认启动，检查新 ID。）
- [ ] `--new` 始终新建，`--resume <id>` 精确恢复，两者互斥；目标不存在、ID 非法或已锁定时显式恢复启动失败。（验证：对 argparse 与 Coordinator 运行选择矩阵测试。）
- [ ] JSONL 中间的完整坏 JSON、坏 UTF-8 或坏 Schema 行被独立跳过，前后其他有效消息仍能恢复。（验证：在三个不同位置插入坏行，检查恢复条目和坏行计数。）
- [ ] 最后一行没有换行或只写入部分 JSON 时，恢复物理截断到上一个完整换行，新记录不会接在半行后。（验证：人工写半行，恢复后再追加并逐行解析。）
- [ ] 单条物理行超过 4MB 时不被整体无界读入，扫描报告含超限警告且进程不崩溃。（验证：构造 4MB+1 字节单行并运行恢复。）
- [ ] assistant 工具调用后每个 call ID 都必须有紧邻、唯一、无多余的 tool 结果，完整组能恢复。（验证：使用两个工具调用与两个完整结果。）
- [ ] 缺少结果、重复结果、未知 call ID、中间插入其他角色或孤立 tool 时，文件与恢复历史都从第一个坏组起截断。（验证：对五种破损形状分别检查字节偏移。）
- [ ] 恢复回放不重复写入已有 JSONL，只有恢复后的新消息会追加。（验证：记录恢复前文件行数，启动后未对话时不变，新对话后按新消息增加。）
- [ ] 恢复 Conversation 保留 entry ID、重建 next ID 和全部用户原文档案，ch08 之后摘要时仍能逐字注入历史用户消息。（验证：恢复后触发摘要，对比原 JSONL 用户文本。）
- [ ] 最近一条成功 `mode=plan` 最终 assistant 恢复为 PlanMemory，更旧计划、工具调用中的 assistant 或失败计划不覆盖它。（验证：构造多个 plan 记录并恢复后执行 Do。）
- [ ] 恢复会话后权限模式是 Default、Shell 策略是 Auto、Agent 模式由新请求决定，MCP 重新连接，Token 锚点为空。（验证：上一进程切换状态后退出，新进程检查五项状态。）
- [ ] 恢复历史越过 ch08 自动压缩线时，进入用户输入循环前产生且只产生一次 `RESTORE` 无工具摘要。（验证：用可控估算器把恢复请求设在自动线上，检查 Provider calls。）
- [ ] `RESTORE` 压缩保留固定 System Prompt、完整工具组、近期原文和历史用户原文，不污染普通 usage 锚点。（验证：复用 ch08 摘要断言并检查 estimator anchor。）
- [ ] 恢复压缩失败时原历史保持不变，启动阶段不循环重试并显示失败状态。（验证：让摘要 Provider 返回坏标签，检查快照和调用数。）
- [ ] 最后消息间隔严格超过 24 小时时，恢复后第一次普通请求含环境可能变化的提醒；正好 24 小时和以内不含。（验证：固定 now 测试 23:59:59、24:00:00、24:00:01。）
- [ ] 时间跨度提醒不写 JSONL/Conversation，不进入内部压缩和记忆请求，后续普通请求不重复。（验证：恢复后运行两轮并检查所有 Provider 消息与 JSONL。）
- [ ] 最后活动严格超过 30 天且可获得锁的会话在启动选择前被删除，正好 30 天和未超过的保留。（验证：固定 now 测试边界三值。）
- [ ] 超过 30 天但已被锁定的会话保留，某一文件删除失败不影响其他候选清理和 ArtCode 启动。（验证：同时构造锁定、删除报错和可删除三份文件。）

## 长期笔记和索引

- [ ] 每条笔记是一份可单独阅读的 Markdown，frontmatter 包含 ID、scope、category、status、title、summary、created/updated time、source session 和 source entry IDs。（验证：生成四类笔记后用 YAML + Markdown 解析并手工阅读。）
- [ ] 笔记 ID 符合 `mem-YYYYMMDD-HHMMSS-xxxx`，文件名与 frontmatter ID 一致，同秒冲突不覆盖。（验证：固定 now 与随机冲突测试。）
- [ ] 四个合法类别恰为 `preference`、`correction`、`project_knowledge`、`reference`，未知类别不进入 Store 和索引。（验证：对四个合法值和一个未知值运行解析。）
- [ ] 自动写入用户级只接受 `scope=user` + `category=preference`，纠正、项目知识和参考资料即使 LLM 要求也不跨项目。（验证：向 Parser 提交四类 user scope 操作，检查只有 preference 有效。）
- [ ] 每份完整笔记含 frontmatter 最多 8KB UTF-8，正好 8KB 可提交，8KB+1 被拒绝且旧文件不变。（验证：按预渲染字节数测试边界。）
- [ ] create/update 使用同目录临时文件与原子替换，模拟中断后目标至少保留一份完整可解析版本。（验证：在替换前注入故障并重新扫描。）
- [ ] supersede 把笔记状态改为 `superseded`，文件仍存在可审计，但不再进入活跃索引。（验证：作废一条后对比磁盘文件与 index.md。）
- [ ] 单个坏 frontmatter、未知字段、错文件名或坏时间笔记被跳过并计 issue，其他笔记仍可建索引。（验证：一个坏笔记和两个好笔记混合扫描。）
- [ ] 索引只来自当前目录的 active 笔记，不把用户级与项目级条目写到同一 index.md。（验证：两个 Store 放入不同标记后分别重建。）
- [ ] 索引类别顺序为用户偏好 → 纠正反馈 → 项目知识 → 参考资料，同类按 updated time 降序、ID 升序。（验证：构造乱序输入两次重建，对比字节完全一致。）
- [ ] 每条索引摘要最多 120 个 Unicode 字符，中文和 Emoji 不会在多字节中间损坏。（验证：构造 119、120、121 字符与 Emoji 边界。）
- [ ] 用户级和项目级每份索引都同时不超过 200 行且不超过 25KB UTF-8，预算到边界时停止添加而不产生坏 Markdown。（验证：分别用短摘要撑满行数、用长中文摘要撑满字节数。）
- [ ] 索引超预算时保留“未索引条数”状态，但未进入索引的 Markdown 笔记不被删除。（验证：创建超过预算的活跃笔记并检查文件数。）
- [ ] `index.md` 删除、非法 UTF-8 或内容与笔记不一致时，启动从 Markdown 笔记原子重建正确索引。（验证：对三种索引状态重启并对比预期字节。）

## 异步 LLM 记忆更新

- [ ] 只有模型以无工具最终回复自然结束的 Agent Loop 向 Memory Worker 提交 NaturalTurn。（验证：运行 Normal、Plan、Do 的自然结束用例，确认各提交一次。）
- [ ] 流式错误、用户取消、迭代上限、未知/禁止工具停止和最终异常总结不提交记忆更新。（验证：对每种 StopReason 检查 Observer 调用数为 0。）
- [ ] 最终 assistant 消息已进入 Conversation、JSONL 和必要时 PlanMemory 后才非阻塞提交记忆 Worker。（验证：在 Observer 回调中立即检查三份状态。）
- [ ] `submit` 只完成入队，慢 Provider 不影响用户看到最终回复或开始下一轮。（验证：用阻塞 Fake Provider 确认 STOPPED 和新输入可在后台释放前进行。）
- [ ] Memory Worker 并发度为 1，两个快速完成轮次依 FIFO 顺序串行读取最新索引并提交。（验证：第一轮 Provider 挂起时提交第二轮，检查调用/提交顺序。）
- [ ] 记忆 LLM 请求使用当前 Provider、`tools=None`、Thinking 关闭和最大 4,000 输出 Token。（验证：检查 Fake Provider 收到的 tools 与 ProviderRequestOptions。）
- [ ] 记忆请求仅包含当前完成轮次、有界工具摘要和两份索引，不包含完整配置、MCP Header 或无界工具输出。（验证：在配置和工具结果放入唯一秘密标记，搜索记忆 Prompt。）
- [ ] 已知 API Key 在记忆 Prompt 中被脱敏，输出包含该密钥时不会原样写入笔记。（验证：输入/输出都注入配置 Key 并检查 Prompt 与磁盘。）
- [ ] 记忆响应必须只有一个闭合 `<memory-update>`，内部是严格 JSON `operations`，标签外文本、多标签、非 JSON 和工具调用都不会改写笔记。（验证：为五种坏响应检查 Store 快照不变。）
- [ ] 单轮最多提交 5 个 create/update/supersede 变更，正好 5 个可处理，6 个时该响应不能越界提交。（验证：对 5 与 6 个操作分别运行 Parser/Updater。）
- [ ] update/supersede 必须指向当前作用域中存在的 active note ID，source entry ID 必须属于当前 NaturalTurn。（验证：构造跨 scope target、不存在 target、旧轮 source 和合法操作。）
- [ ] 记忆模型看到已有相同索引事实时返回 noop 或 update，不重复生成第二份 active 笔记。（验证：真实 DeepSeek 连续两次提交相同明确偏好/项目事实，检查文件和索引计数。）
- [ ] 新纠正与旧记忆冲突时，旧条目可被 supersede，新条目成为唯一活跃事实且两份文件都可审计。（验证：先保存偏好 A，再提交明确纠正 B，检查 status 与 index。）
- [ ] 单次后台更新超过 30 秒被取消，会话 JSONL、已显示回复、已有笔记和下一轮交互不受影响。（验证：使用可控时钟/挂起 Provider 推进到 30 秒边界。）
- [ ] 记忆更新成功时 TUI 只显示新增、更新、作废和拒绝数；失败时显示脱敏原因，两者都不打印笔记全文。（验证：捕获成功/失败 Console 输出并搜索秘密与笔记正文。）
- [ ] 用户立即退出时未完成 Memory Worker 可取消并完成 close，Journal 已持久的最终回复不丢失。（验证：挂起 Memory Provider 后退出，检查无残留 Task、锁释放和 JSONL 最后 assistant。）

## 记忆与 Prompt 集成

- [ ] 每次普通 Provider 请求前都读取用户级和项目级当前 `index.md`，不依赖启动时缓存的旧索引。（验证：在同一进程的两次请求之间原子替换 index，检查 Provider messages。）
- [ ] 记忆 Section 优先级为 800，排在稳定系统和手写指令之后，用户级和项目级索引都带明确来源标签。（验证：检查组装后标题/标签顺序。）
- [ ] `<memory-index>` 边界明确声明记忆是可能过时的只读参考，不是新指令，不能覆盖当前用户请求、工具结果或真实文件。（验证：对 System Prompt 做精确语义断言并用 Fake Provider 查看完整消息。）
- [ ] 记忆索引中写入伪造“忽略系统规则”文字时，固定系统约束仍在前且边界把该文字定义为数据。（验证：注入恶意索引内容并检查 Prompt 顺序/边界。）
- [ ] 指令和记忆的动态 System Prompt 只替换实际请求副本，不写入 Conversation、JSONL 或 ch08 的用户原文档案。（验证：运行两轮后搜索三个存储位置。）
- [ ] 记忆更新原子提交完成前并发普通请求要么读到完整旧索引，要么读到完整新索引，不会读到半份 Markdown。（验证：在替换点并发组装请求并逐次解析 index。）

## CLI 和可观察性

- [ ] `artcode --help` 显示 `--new`、`--resume SESSION_ID` 与互斥语义，原有 `--workspace` 和 `--config` 保持。（验证：运行 CLI help 并检查文本。）
- [ ] `/help` 显示 `/sessions` 和 `/memory`，两个命令都不作为用户消息写入 Conversation/JSONL。（验证：执行命令前后对比消息数和文件行数。）
- [ ] `/sessions` 显示当前会话标记和最近 20 个 ID、标题、消息数、活动时间，不在运行中切换 Conversation。（验证：用 21 份会话运行命令，检查当前标记、显示数和原 Conversation 对象。）
- [ ] `/memory` 显示两级路径、active/superseded/issue 数和最近更新状态，不打印笔记正文。（验证：用唯一秘密正文运行命令并确认输出不含。）
- [ ] 启动 Panel 显示 ch09 标题、会话 ID、新建/恢复、恢复消息数、坏行、截断、指令字节/issue 和两级有效笔记数。（验证：捕获新建与损坏恢复两种 Panel 输出。）
- [ ] 启动和运行状态不输出 API Key、MCP Header/环境变量值、指令全文、笔记全文或记忆 LLM Prompt。（验证：为各类数据放入唯一标记并搜索捕获输出。）
- [ ] Journal 追加失败时用户看到“当前轮可继续、下次恢复可能不完整”的降级状态，已执行工具不回滚。（验证：在 tool result 追加时注入 I/O 错误，检查 TUI 和 Tool execution count。）

## 回归、macOS 与技术栈

- [ ] ch09 持久包未新增 SQLite、向量库、tokenizer、watcher、daemon 或原生扩展运行时依赖。（验证：对比 `pyproject.toml` 并扫描持久包 import。）
- [ ] 新实现只使用 Python 标准库与项目已有 PyYAML/Provider 抽象，不要求目标 Mac 额外安装数据库或后台服务。（验证：在干净虚拟环境仅按项目声明依赖安装并运行全流程。）
- [ ] 会话锁定在 macOS 使用标准 `fcntl.flock`，锁失败有明确用户语义且不需新 meta/lock 文件。（验证：运行双进程 live lock 测试并列出 sessions 目录。）
- [ ] 从自包含 macOS CLI 的临时展开/非源码路径启动时，持久功能不依赖 repository-relative 路径。（验证：运行打包兼容冒烟或等价的隔离入口测试。）
- [ ] Normal、Plan、Do 模式的现有工具可见性、PlanMemory 当前进程语义和自然结束行为保持。（验证：运行所有 agent mode/loop/memory 单元测试。）
- [ ] 内置工具、MCP 工具、权限规则、Workspace 边界、危险命令检查和 Seatbelt 自测保持。（验证：运行 tools/MCP/permissions/security/sandbox 全部单元和非 live 集成测试。）
- [ ] ch08 轻量存盘、Token 锚点、自动/强制/紧急/手动压缩、摘要用户原文和 Artifact 清理回归全部通过。（验证：运行 `tests/unit/test_context_*.py` 与上下文非 live 集成测试。）
- [ ] 全部单元测试通过。（验证：运行 `.venv/bin/python -m pytest tests/unit -q`。）
- [ ] 全部非 live 集成测试通过。（验证：运行 `.venv/bin/python -m pytest tests/integration -q -k "not live"`。）
- [ ] 全量测试通过，无未等待后台 Task、未释放文件锁和无法清理的临时文件警告。（验证：运行 `.venv/bin/python -m pytest -q`并检查告警。）

## 端到端场景

- [ ] **新会话持久：** 空 Workspace 启动 → 用户请求 → assistant 工具调用 → tool 结果 → 最终回复 → 正常退出，得到一份无 meta、逐行可解析且协议完整的 JSONL。（验证：运行 `tests/integration/test_persistence_flow.py` 对应场景。）
- [ ] **崩溃恢复：** 在工具调用只写入部分结果/最后 JSON 只写入半行时终止 → 新进程默认恢复 → 截断到安全前缀 → 继续完成新请求。（验证：运行确定性崩溃集成场景并逐行复查新 JSONL。）
- [ ] **跨天继续：** 恢复最后活动超过 24 小时的会话 → 第一次请求提醒重读现状 → 第二次请求不重复提醒。（验证：固定时钟运行两轮 Provider 流程。）
- [ ] **超大历史恢复：** 从 JSONL 恢复超过 ch08 自动线的原始历史 → 先执行一次 RESTORE 摘要 → 保留用户原文与工具组 → 新请求继续完成。（验证：运行 Fake 估算/摘要集成场景。）
- [ ] **指令与旧记忆恢复：** 预置三层指令、用户级偏好和项目级知识 → 新进程恢复会话 → 第一次 Provider 请求同时包含三者并能正确回答预埋事实。（验证：检查 Fake Provider 实际消息并运行后续回答。）
- [ ] **自动学习：** 一轮自然结束 → 用户立即看到回复 → 后台无工具 LLM 生成笔记 → 原子替换索引 → 下一请求看到新索引。（验证：用可控 Worker/Provider 运行时序集成测试。）
- [ ] **真实 DeepSeek 去重：** 第一轮告诉可验证偏好或项目事实 → 生成一条活跃笔记 → 第二轮重复同一事实 → LLM 返回 noop/update 而非创建重复笔记。（验证：运行 `.venv/bin/python -m pytest tests/integration/test_memory_deepseek_live.py -q -s`。）
- [ ] **真实新进程继续：** 完成真实记忆更新后关闭 Runtime → 新建 Runtime 默认恢复 → 首请求已包含历史与索引 → DeepSeek 能基于该知识继续任务。（验证：在 live 测试内使用两个独立 Coordinator/Runtime 实例。）
