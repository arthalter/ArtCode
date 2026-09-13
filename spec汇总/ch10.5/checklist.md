# ch10.5：总结重构 Checklist

> 每一项只能在实际执行验证并保存证据后勾选。测试代码“看起来会通过”、某个相邻场景通过、或达到测试数量，都不能代替该项自己的可观察结果。

## 验收记录规则

- 自动验证证据统一记录：执行时间、Git commit、Python 版本、macOS 版本、命令、退出码、收集数、通过/失败/跳过数和耗时。
- 真实集成测试额外记录：DeepSeek 模型、Seatbelt 可用性、MCP Fixture 版本和脱敏后的外部错误；任何 API key、Authorization header、Cookie 或完整用户配置都不得进入证据。
- 外部服务失败与环境阻塞必须保持未勾选，并分别标注“真实失败”或“环境阻塞”；不得写成通过。
- 手工验收由用户本人操作真实 ArtCode TUI；脚本可以准备隔离环境和核对结果，但不能代替用户的输入、确认、观察和最终勾选。
- `tests/manual/run_case.py` 必须把每个场景放在权限为 `0700` 的独立临时目录，通过显式 `artcode_home` 隔离会话、记忆和权限文件，不改写系统 HOME，也不写入真实 `~/.artcode`。
- 手工场景使用真实配置时只读取 `~/.artcode/config.yml` 并在内存中应用非秘密覆盖；不得把 API key 复制到仓库或证据目录。
- 每项手工场景统一使用以下命令形状：

```text
.venv/bin/python tests/manual/run_case.py prepare MXX --source-config ~/.artcode/config.yml
.venv/bin/python tests/manual/run_case.py launch MXX
.venv/bin/python tests/manual/run_case.py verify MXX
.venv/bin/python tests/manual/run_case.py collect MXX
.venv/bin/python tests/manual/run_case.py cleanup MXX
```

`collect` 只保存脱敏日志、PID/PGID 状态、文件哈希、消息角色/数量和用户实际填写的结果；`cleanup` 只删除 prepare 返回并登记的单一临时目录。

## A. 实现与架构完整性

- [ ] A01：从 `artcode` 和 `python -m artcode` 启动时，生产依赖各只构造一次，二者进入同一个应用主流程。（验证：运行 Bootstrap 构造计数集成测试，两种入口的 Provider、Session、Memory、MCP、Sandbox、Tool Registry 和 Runtime 计数均为 1。）
- [ ] A02：CLI 只把 `--workspace`、`--config`、`--new`、`--resume SESSION_ID` 转成启动选项并映射退出码，不自行组装 Provider、工具或持久化服务。（验证：CLI 契约测试和依赖图检查通过；`artcode --help` 只显示既有启动项。）
- [ ] A03：正常退出按确定的逆序关闭已创建资源，每个网络客户端、MCP 会话、Session、Memory worker、上下文 artifact store 和 Seatbelt 资源只关闭一次。（验证：正常生命周期 Spy 测试的 close 顺序与预期完全一致且无重复记录。）
- [ ] A04：启动在每个资源创建阶段分别失败时，只关闭此前已经创建的资源，原始错误被稳定展示且进程退出码为 2。（验证：参数化启动故障测试逐阶段通过，未创建资源 close 计数为 0。）
- [ ] A05：Ctrl+C 和请求取消后，应用返回可用输入状态或以 130 退出，已经登记的资源均被关闭且没有悬空异步任务。（验证：取消集成测试与应用生命周期 Soak 通过，关闭后任务集合和资源计数归零。）
- [ ] A06：权限模式、Shell 策略、显示模式和最近 Token 用量各只有一个权威运行值，执行与状态展示读取同一轮快照。（验证：切换状态后同时触发 `/status` 和工具批次，二者报告的 mode/policy 值一致。）
- [ ] A07：状态快照只含白名单字段，API key、MCP Authorization、环境变量秘密、完整请求 body 和 Session 原始内容均不可见。（验证：秘密探针测试扫描 Rich 文本、异常、日志和快照结果零命中。）
- [ ] A08：Runtime 在测试和生产构造中都要求显式依赖，不再通过动态属性兜底或内部创建第二套 Provider、Persistence、Tools。（验证：构造契约测试和兼容模式搜索通过。）
- [ ] A09：Agent Loop 只推进模型轮次与工具结果，不直接拥有配置解析、权限持久化、路径复核、进程清理、Session 恢复或 Memory 更新策略。（验证：依赖图测试无这些反向依赖，跨服务行为由相应集成测试通过。）
- [ ] A10：TUI 只处理输入、显示和人工确认；Provider、MCP、Persistence、Context 和 Tool 服务不依赖具体 Rich/PromptToolkit 渲染对象。（验证：使用无 Rich 的记录型 TUI Fake 跑完整 Runtime 集成测试通过。）
- [ ] A11：MCP 继续保持 Config、Manager、Session、Adapter、Transport 的独立边界；Command 继续保持 Registry、Parser、Dispatcher 边界，没有为重构重写成第二套框架。（验证：模块契约测试和公开调用方检查通过。）
- [ ] A12：生产运行时依赖没有新增；Hypothesis 与 pytest-cov 只出现在 test extra。（验证：对比 `pyproject.toml`，构建 wheel 后检查 METADATA，生产 Requires-Dist 不含两项测试依赖。）
- [ ] A13：仓库没有为 Skill、插件市场、热加载、网络域名代理或重复工具调用检测预建生产抽象。（验证：对生产导出、配置字段和入口进行范围扫描，结果只包含当前已批准能力。）
- [ ] A14：网络权限未来扩展只在一处文档/沙箱边界中说明，当前生产判断只有“全部禁止”，工具中不存在分散白名单或域名特判。（验证：沙箱策略契约测试与网络相关代码搜索共同通过。）

## B. 配置与 DeepSeek Provider

- [ ] B01：配置顶层同时出现两个或更多未知字段时，启动一次列出该层全部未知字段及其层级，不只报告第一个。（验证：运行顶层未知键参数化测试，错误文本包含完整排序后的键集合。）
- [ ] B02：`thinking`、`context` 和每个 MCP Server 内同时出现多个未知字段时，各自在可定位层级一次列全。（验证：嵌套未知键单元与 Property 测试通过。）
- [ ] B03：`mcp_servers` 存在但为 list、string、number、boolean 或 null 时明确失败，不静默视为空配置。（验证：五种类型独立 case ID 全部得到配置错误且 Provider 调用数为 0。）
- [ ] B04：合法最小配置默认得到模型 `deepseek-v4-flash` 对应的 V4 Flash 0731 基线、1,000,000 Token 窗口及同比例自动/强制压缩阈值。（验证：配置解析和阈值精确值断言通过。）
- [ ] B05：显式 200,000～1,000,000 范围内的合法较小窗口被保留，两个相对阈值随窗口同比变化且边界取整确定。（验证：边界值与随机合法整数 Property 测试通过。）
- [ ] B06：窗口为 boolean、float、string、低于 200,000 或高于 1,000,000 时启动失败。（验证：所有错误类型和上下界外 case ID 通过。）
- [ ] B07：Thinking 配置只接受 `enabled`；开启与关闭都不再接受 low/medium 等多档输入，启用后的内部强度固定为 high。（验证：严格配置测试和配置示例快照通过。）
- [ ] B08：Thinking 关闭的普通 Agent 请求在真实发出的 payload 中显式关闭 Thinking，摘要与 Memory 请求也显式关闭。（验证：Provider payload 契约测试捕获三个请求源的脱敏 body 并断言关闭字段。）
- [ ] B09：Thinking 开启的普通 Agent 请求只使用 high，状态展示不提供可选择的其他档位。（验证：Provider payload 和 `/status` 展示测试通过。）
- [ ] B10：Provider 对外只产生文本增量、推理增量、已组装工具调用、usage 和 stream completed 五类结构化事件，消费端对每类都有显式处理。（验证：Provider/Stream Collector 契约测试覆盖联合类型全部成员和未知事件拒绝。）
- [ ] B11：SSE 在任意字节、行、CRLF、多 data 行边界切分时产生相同事件序列。（验证：Hypothesis 任意分片测试与未切分基准逐事件相等。）
- [ ] B12：Tool call delta 按交错 index、名称增量和参数增量组装；缺失 index、非法 JSON 或不完整结束产生稳定 Provider 错误。（验证：Tool Delta 属性与故障测试通过。）
- [ ] B13：文本、reasoning、工具调用、usage 和 finish reason 能在同一流中按协议收集，`finish_reason=length` 不改写已生成文本。（验证：组合流测试逐字段比对输入和 `ModelTurn`。）
- [ ] B14：应用生命周期内多次模型请求复用同一 HTTP Client，退出和启动中途失败都只关闭一次。（验证：Client 身份、连接调用和 close 计数测试通过。）
- [ ] B15：认证、限流、上下文超限、HTTP 错误、坏 SSE、流中断和取消被分别分类，错误内容不包含 API key、Authorization 或旧章节路径。（验证：错误矩阵测试与秘密扫描通过。）
- [ ] B16：真实 DeepSeek Thinking off 返回可见回答和真实 usage，脱敏请求证据显示 Thinking 被显式关闭。（验证：对应 live case 通过。）
- [ ] B17：真实 DeepSeek Thinking high 连续执行至少两轮工具调用，后续请求包含前序 Assistant 所需 reasoning content 且服务端不报协议错误。（验证：Thinking+tools live case 自然完成并保存会话结构证据。）
- [ ] B18：真实 DeepSeek 的流取消、上下文错误和 length/完成原因均按设计返回，终端与日志不泄露秘密。（验证：三个 live/fault case 逐项通过或保持真实失败未勾选。）

## C. Agent Loop、请求组装与上下文

- [ ] C01：正常交互默认没有工具迭代上限，确定性场景完成第 13 轮后仍继续并最终自然结束。（验证：长循环集成测试观察到至少 13 个 Provider 请求且无旧上限错误。）
- [ ] C02：测试或自动化显式传入正整数上限时，在精确轮数处确定停止；0、负数、boolean 和错误类型立即拒绝。（验证：上限边界参数化测试通过。）
- [ ] C03：无限循环只因自然完成、用户取消、准备/Provider 失败或确定不可继续而停止，不存在重复工具启发式、Claude 风格轮数限制或自动停机分支。（验证：终止原因状态机测试覆盖并穷尽全部分支。）
- [ ] C04：相同显式输入重复调用请求组装器，得到值相等的消息与工具列表，Conversation、Reminder、Context anchor、Session 和 Memory 均不变化。（验证：深快照前后比较测试通过。）
- [ ] C05：Token 估算、`/status`、压缩前试组装和准备阶段失败都不消费恢复提醒。（验证：依次执行四类 preview 后 pending 状态仍为 true。）
- [ ] C06：携带恢复提醒的首次适用请求只有在 Provider 调用真正开始时消费；该请求以后再次组装和发送均不重复提醒。（验证：dispatch commit 集成测试的前后请求计数分别为 1 和 0。）
- [ ] C07：Provider 调用开始前取消或失败时，恢复提醒保留到下一次真实发送。（验证：准备/连接前故障注入后第二次请求仍含提醒。）
- [ ] C08：`finish_reason=length` 只保存模型实际产生的文本，不添加“未完成”标记、不自动续写、不创建额外 Session 状态。（验证：长度结束后 Provider 调用数不增加，Conversation 文本逐字等于流输入。）
- [ ] C09：每次用户提交都生成一条独立真实 User 记录，空白、换行、Unicode 和长文本逐字保存，不 trim、不合并、不改写。（验证：User 消息 round-trip 参数化测试比较字节和条目数。）
- [ ] C10：轻量工具结果存盘只替换允许存盘的 Tool 内容，不修改任何 User Entry。（验证：压缩前后 User entry ID、role、文本和顺序一致。）
- [ ] C11：重量摘要只折叠较旧 Assistant、Tool 和内部 System 历史，摘要引用用户内容后仍由程序重新注入原始独立 User Entry。（验证：Retention 集成测试核对最终消息角色序列和用户原文哈希。）
- [ ] C12：固定 System、摘要、历史标记、旧 User 原文、边界和近期历史按批准顺序组装，工具调用—结果协议保持闭合。（验证：不同历史形状的请求快照测试通过。）
- [ ] C13：多次轻量与重量压缩后，全部 User Entry 的数量、原文、顺序和独立身份仍与第一次提交一致。（验证：Property 和重复压缩 Soak 对每轮哈希清单断言相等。）
- [ ] C14：摘要 Provider、解析、artifact 写入、Conversation 替换或取消任一步失败时，压缩不提交且原 Conversation 快照不变。（验证：逐阶段故障注入测试通过。）
- [ ] C15：不可压缩的超大 User 原文没有专用预检、分片、回滚或状态机；超过服务能力时按普通 Provider 错误展示。（验证：超大输入集成测试只观察到普通请求和 Provider 错误类型。）
- [ ] C16：上下文超限最多触发一次普通压缩重试；重试仍失败时停止且不自动新建会话或搬运消息。（验证：Provider 调用/压缩调用计数测试通过。）
- [ ] C17：流取消或流错误的半截 Assistant 只在终端出现，不进入 Conversation、JSONL 或 Memory 队列。（验证：取消后检查三处记录零命中。）
- [ ] C18：流中已经确定的 Tool call 在取消或异常时得到结构化中断结果，后续保存的安全前缀不存在悬空 Tool call。（验证：协议完整性测试通过。）

## D. 工具、权限、文件、进程与沙箱

- [ ] D01：新增一个测试工具只声明一次名称、来源、副作用和规则能力，就能同时参与 Plan 过滤、批次规划和权限判断。（验证：单一 Descriptor 集成测试三处都产生预期策略。）
- [ ] D02：Normal/Do 可见全部已注册工具；Plan 只允许内置 READ，MCP 在 Plan 中仍可见但每次明确显示 Plan 状态并人工确认。（验证：模式—工具矩阵测试通过。）
- [ ] D03：READ 工具可安全同批并发；WRITE/SHELL 串行；EXTERNAL 同批并发但逐调用确认；最终 Tool 结果按原 call 顺序回填。（验证：带时间栅栏的批次测试和结果顺序断言通过。）
- [ ] D04：未知工具返回稳定结构化结果，不抛出到 Agent Loop，也不丢失同批其他结果。（验证：混合已知/未知批次测试通过。）
- [ ] D05：缺字段、错误类型、额外字段和坏 JSON 参数分别返回可定位的结构化非法参数结果。（验证：参数 Schema 错误矩阵通过。）
- [ ] D06：模式禁止、规则拒绝、一次性审批拒绝和永久拒绝分别产生稳定结构化结果。（验证：四类拒绝结果的 code/message/schema 快照通过。）
- [ ] D07：一个工具抛出意外异常或被取消时，同批已完成结果保留，尚未执行项得到明确中断结果。（验证：混合批次故障注入测试通过。）
- [ ] D08：权限“一次允许、永久允许、一次拒绝、永久拒绝”保持现有可见行为；永久选择原子写入正确规则层，下一批次读取新快照。（验证：四选择集成矩阵和 YAML round-trip 通过。）
- [ ] D09：MCP 工具不能通过永久规则绕过逐次确认，权限 YAML 拒绝不可配置工具名。（验证：MCP rule-configurable 契约测试通过。）
- [ ] D10：写入 Workspace 内不存在的多级父目录时自动创建目录并写入精确内容。（验证：三层以上目录集成测试检查路径、内容和权限。）
- [ ] D11：Workspace 内指向内部真实目标的符号链接可读写；指向 Workspace 外或敏感范围的链接被拒绝。（验证：内部/外部/敏感 symlink 矩阵通过。）
- [ ] D12：权限展示后、执行前替换路径或 symlink 目标时，执行阶段重新解析并拒绝偏离目标，不触碰外部文件。（验证：TOCTOU 故障测试比较外部哨兵文件哈希不变。）
- [ ] D13：默认写入不覆盖已存在文件；精确编辑只有原文唯一命中时成功，零次或多次命中时文件字节不变。（验证：覆盖和匹配矩阵通过。）
- [ ] D14：文件写入/编辑在 flush、fsync、replace 或清理阶段失败时，不留下半文件或可见临时文件。（验证：原子写逐阶段故障测试和目录快照通过。）
- [ ] D15：每条 Shell 命令进入独立进程组，正常完成后 stdout、stderr 和退出码语义保持可观察。（验证：真实进程集成测试检查 PID/PGID 和输出。）
- [ ] D16：命令 timeout 直接 SIGKILL 整个进程组并等待父、子、孙进程回收，返回结构化 timeout 结果。（验证：真实进程树测试结束后所有 PID 均不存在。）
- [ ] D17：用户取消命令时直接 SIGKILL 整个进程组并等待回收，不先进入优雅退出状态机。（验证：取消测试记录 SIGKILL 路径且所有 PID 消失。）
- [ ] D18：进程“刚好退出”、kill 时已不存在、输出读取仍在结束等竞态不会产生僵尸进程、双重异常或悬空任务。（验证：故障测试和进程清理 Soak 通过。）
- [ ] D19：Seatbelt 中公网、DNS、回环连接、本地监听和子进程网络全部失败，Workspace 内正常文件操作仍成功。（验证：五类真实网络拒绝和一类正常本地操作 live case 通过。）
- [ ] D20：敏感配置、权限、Session、Memory、内置策略文件均不能通过文件或 Shell 工具读取/修改，拒绝信息不回显秘密。（验证：敏感路径矩阵和秘密扫描通过。）

## E. MCP、命令与终端界面

- [ ] E01：一个 MCP Server 配置错误、连接失败或启动超时，不影响内置工具和其他健康 Server 的发现与调用。（验证：多 Server 隔离集成测试通过。）
- [ ] E02：MCP 工具名与内置工具或另一 Server 冲突时，冲突被明确报告且未覆盖原工具。（验证：冲突矩阵检查 Registry 最终绑定。）
- [ ] E03：MCP 调用成功、工具返回错误、调用超时、用户取消和连接中断都转换为稳定工具结果，其他 Server 会话保持可用。（验证：stdio/HTTP 故障矩阵通过。）
- [ ] E04：MCP stdio 的启动、分页发现、调用、stderr、超时、断线和关闭均有真实测试证据。（验证：全部 stdio live case 通过。）
- [ ] E05：MCP HTTP 的 headers、重定向、脱敏、调用取消、Server 错误和关闭均有真实测试证据。（验证：全部 HTTP live case 通过，证据中秘密零命中。）
- [ ] E06：Plan mode 通过当前 ToolRunContext 显式传递给 MCP 审批展示，不读取执行器上的隐藏可变标记。（验证：同一 Adapter 在 Normal/Plan 上下文中显示不同明确状态且无共享状态污染。）
- [ ] E07：既有斜杠命令继续通过 Registry、Parser、Dispatcher 工作，本章没有新增命令或 alias。（验证：命令元数据快照与 ch10 批准集合一致。）
- [ ] E08：普通多行消息只进入 Agent，未知多行斜杠命令只进入命令错误展示，二者不会互相转发。（验证：输入分流集成测试的 Provider/Conversation 调用计数符合预期。）
- [ ] E09：连续执行 `/status` 不调用 Provider、不追加 Conversation/JSONL、不消费 Reminder、不改变 Context anchor、不入 Memory 队列。（验证：调用前后深快照与计数完全一致。）
- [ ] E10：TUI 在 Default、Plan、Do、取消和异常路径显示稳定事件，并在请求结束后恢复正确默认显示模式。（验证：记录型 Renderer 事件序列测试通过。）
- [ ] E11：用户审批文本清楚显示工具名、目标/命令、当前模式和选择，不包含 API key、MCP secret 或不可见内部对象 repr。（验证：审批渲染快照与秘密探针通过。）

## F. Session、恢复与长期记忆

- [ ] F01：每条确定的真实 User、Assistant 和 Tool 消息同步追加到 JSONL；进程异常终止前已经返回的 append 调用对应磁盘完整行。（验证：写后立即读取和强制终止集成测试通过。）
- [ ] F02：恢复提醒、摘要草稿、Runtime 状态、Token 估算和内部 System 请求不伪装成真实 User 记录。（验证：运行这些操作后枚举 JSONL role/type，内部记录数为 0。）
- [ ] F03：Session 新建、默认恢复最近可用会话、按 ID 精确恢复和退出释放锁保持现有主要行为。（验证：四条 Session 生命周期集成测试通过。）
- [ ] F04：完整但损坏的独立 JSONL 记录被跳过并显示一次可定位警告，其前后其他安全记录继续恢复。（验证：坏中间行测试检查恢复序列和警告计数。）
- [ ] F05：文件尾部不完整记录被截断，恢复到最后一条完整安全记录；下次追加后 JSONL 仍可逐行解析。（验证：尾部截断—追加—再恢复集成测试通过。）
- [ ] F06：坏记录会破坏 Assistant Tool call 与 Tool result 协议时，只恢复最大安全前缀，不产生悬空或错误配对。（验证：协议组故障矩阵通过。）
- [ ] F07：任何恢复路径都不删除、合并、trim 或摘要化 User 消息；坏行前后的安全 User 原文逐字存在。（验证：随机损坏 Property 测试对安全 User 哈希序列断言一致。）
- [ ] F08：两个进程不能同时追加同一 Session；精确恢复冲突被明确拒绝，默认恢复冲突按既有策略选择可写新会话。（验证：真实双进程锁测试比较 Session ID 与文件追加来源。）
- [ ] F09：过期清理只删除满足规则且未锁定的 Session，当前、活动锁和边界时间会话保留。（验证：时间边界与锁定清理矩阵通过。）
- [ ] F10：JSONL v1、既有 Markdown Note 和索引文件无需迁移即可被新代码读取，新增记录仍保持人类可读。（验证：历史 Fixture 兼容测试与 round-trip diff 通过。）
- [ ] F11：只有无工具的自然完成轮次产生不可变 CompletedTurn；取消、失败、length 或工具未完成轮次不入 Memory 队列。（验证：完成原因矩阵检查 enqueue 计数。）
- [ ] F12：Memory 以单消费者顺序处理 CompletedTurn，不访问可变 Conversation；后续 Conversation 改动不改变已排队副本。（验证：深拷贝与队列顺序测试通过。）
- [ ] F13：Memory timeout、Provider 失败、非法响应、重复事实、磁盘失败和关闭取消分别被隔离，不改变当前回复、Conversation、JSONL 或 Agent 终止原因。（验证：六类故障前后快照相等。）
- [ ] F14：Memory 成功时更新正确的用户级或项目级 Note 和索引，重复事实不生成第二条 active note。（验证：分类、去重和原子索引测试通过。）
- [ ] F15：Memory 成功结果在下一次请求和进程重启后可观察，失败结果不会以伪造记忆进入 Prompt。（验证：两进程持久化集成测试通过。）
- [ ] F16：Session、Durable Prompt 和 Memory 可以分别替换为 Fake 独立测试，任一非关键服务失败不升级为当前正常回复失败。（验证：服务隔离契约测试通过。）

## G. 迁移清理、文档与范围控制

- [ ] G01：T1～T14 每项都有“目标测试先失败—实现后通过—相关集成通过—全量非 live 回归通过”的时间顺序证据。（验证：逐任务验收记录包含四段命令与退出码。）
- [ ] G02：每个 BFS Wave 结束时应用可以冷启动、执行 `/status` 并退出，进入下一 Wave 时没有已知确定性回归失败。（验证：Wave checkpoint 记录通过。）
- [ ] G03：`openai_compatible.py`、`agent/tools.py`、`persistence/coordinator.py` 已删除，生产与测试没有导入旧路径。（验证：文件存在性检查和全仓库导入搜索均为零。）
- [ ] G04：`AllowedPathPolicy`、`SafeConfigStatus`、`AgentRunResult`、`PreparedToolExecution`、重复工具名集合、未使用 approval 字段和 Runtime Fake `getattr` 兼容分支均无生产/测试引用。（验证：批准的残留扫描命令零命中。）
- [ ] G05：生产用户可见文本中不存在 ch03、ch05、ch06、ch09、ch10 章节编号；错误提示指向真实配置文件或字段路径。（验证：`rg` 扫描和错误快照测试通过。）
- [ ] G06：普通 Provider 主协议仍只有一套已验证的流式对话路径，没有并存迁移协议。（验证：Provider 调用图和真实请求捕获只出现单一路径。）
- [ ] G07：权限用户模型、Session JSONL v1、Memory Markdown+index、Command 集合和 MCP 分层没有借重构发生未批准的产品变化。（验证：重构前行为 Fixture 与重构后兼容矩阵通过。）
- [ ] G08：工作树中重构前已存在的无关修改和未跟踪文件内容、哈希及状态没有被本次命令改写或清理。（验证：前后范围清单对比，差异只属于 ch10.5 批准文件。）
- [ ] G09：README 描述最简启动、虚拟环境、`--new`、`--resume`、配置、Thinking、1M 窗口、网络全拒绝和测试命令，与实际 `--help` 和代码行为一致。（验证：文档命令逐条 smoke 通过。）
- [ ] G10：`spec.md`、`plan.md`、`tasks.md`、`checklist.md` 的标题均为 ch10.5，架构图的节点、文件和依赖方向与实际导入图一致。（验证：文档扫描和架构对照记录通过。）
- [ ] G11：所有已知未完成项只出现在明确的验收失败/环境阻塞记录中；文档没有未填占位符、含糊“之后处理”或把失败描述为完成。（验证：占位符扫描与结果表人工复核通过。）

## H. 自动测试数量、覆盖与构建门槛

- [ ] H01：`pytest --collect-only` 最终收集至少 1293 个独立 node ID，其中至少 880 个标记为 ch10.5 新增场景。（验证：运行 inventory 脚本并保存机器可读输出。）
- [ ] H02：ch10.5 新增单元测试不少于 550 个独立场景。（验证：inventory 分类值 `unit >= 550`。）
- [ ] H03：ch10.5 新增确定性集成测试不少于 180 个独立场景。（验证：inventory 分类值 `integration >= 180`。）
- [ ] H04：ch10.5 新增 Property / 故障注入测试不少于 100 个独立场景。（验证：inventory 分类值 `property_fault >= 100`。）
- [ ] H05：ch10.5 新增真实集成测试不少于 20 个独立场景。（验证：inventory 分类值 `live >= 20`，并逐项具有真实环境结果。）
- [ ] H06：ch10.5 新增 Soak / 压力测试不少于 30 个独立场景。（验证：inventory 分类值 `soak >= 30`。）
- [ ] H07：场景 ID 不重复；仅替换无意义输入但断言与路径完全相同的参数组合不计入最低数量。（验证：inventory 重复/低差异审计通过并人工抽查每类至少 10 个 case。）
- [ ] H08：全部 unit、deterministic integration、property 和 fault 测试通过，退出码为 0，无 xfail 掩盖已确认缺陷。（验证：运行非 live 主测试命令并保存 summary。）
- [ ] H09：全项目行覆盖率不低于 95%，分支覆盖率不低于 90%。（验证：pytest-cov XML/JSON 和覆盖门禁脚本通过。）
- [ ] H10：Config、Provider payload/SSE、Conversation、Retention、Session Recovery、Permission、WorkspaceFileAccess 和 ProcessSupervisor 各自分支覆盖率不低于 95%。（验证：关键模块覆盖门禁逐项输出达标。）
- [ ] H11：每个被捕获的异常分支至少有一个测试实际触发，不能只靠 pragma 排除。（验证：异常分支清单与 coverage branch 明细一一对应。）
- [ ] H12：每个公开 Protocol 至少有一个真实实现与一个 Fake 共同通过同一契约测试。（验证：Protocol 契约矩阵全部通过。）
- [ ] H13：配置 YAML、SSE 分片、Tool Delta、Permission glob、Workspace 路径、Session JSONL 和摘要保留七类 Hypothesis 测试均执行而非被 marker 排除。（验证：Property 测试 summary 分类别非零且通过。）
- [ ] H14：全部 DeepSeek live 测试执行，覆盖 Thinking off/high、连续工具、usage、length/上下文错误、摘要和 Memory。（验证：live 报告逐项通过；真实失败保持未勾选。）
- [ ] H15：全部 Seatbelt 与真实 Process 测试执行，覆盖 Workspace 写入、敏感拒绝、网络全拒绝、子进程继承、timeout、取消和无残留 PID。（验证：live 报告与 PID 证据通过。）
- [ ] H16：全部 MCP stdio/HTTP live 测试执行，覆盖发现、调用、错误、timeout、取消、断线、冲突、脱敏和关闭。（验证：live 报告逐项通过。）
- [ ] H17：真实双进程 Session 锁测试执行，两个进程没有并发追加同一文件，退出后锁可重新取得。（验证：进程日志、Session ID 和锁状态证据通过。）
- [ ] H18：全部 Soak 测试执行，长循环、重复压缩、进程清理、Session/Memory 生命周期和应用启停没有持续资源增长。（验证：Soak summary 通过且资源计数回到基线。）
- [ ] H19：完整 `.venv/bin/python -m pytest -q` 通过，不依赖测试执行顺序，随机顺序复跑的关键子集也通过。（验证：全量结果和随机顺序结果退出码均为 0。）
- [ ] H20：wheel 构建成功，在全新临时虚拟环境安装后，`artcode --help`、最简启动/退出和 `python -m artcode` 均成功。（验证：构建与安装 smoke 日志通过。）
- [ ] H21：测试结束后没有残留子进程、Session 锁、MCP Server、HTTP Client、临时 artifact 或手工场景秘密副本。（验证：资源审计脚本与临时目录扫描通过。）
- [ ] H22：全部生产与测试 Python 文件可以编译；项目没有既有 lint 配置，因此本章不为形式检查额外引入 lint 依赖。（验证：`.venv/bin/python -m compileall -q artcode tests` 退出码为 0，并确认 `pyproject.toml` 没有未执行的 lint 配置。）

### 自动验证命令

```text
.venv/bin/python tests/tools/verify_test_inventory.py --baseline 413 --unit-min 550 --integration-min 180 --property-fault-min 100 --live-min 20 --soak-min 30 --total-min 1293
.venv/bin/python -m pytest tests/unit tests/integration tests/property tests/fault -q -m "not live and not slow" --cov=artcode --cov-branch --cov-report=term-missing --cov-report=json
.venv/bin/python tests/tools/verify_coverage.py
.venv/bin/python -m pytest tests/soak -q -m soak
.venv/bin/python -m pytest tests/live -q -m live -rs
.venv/bin/python -m pytest -q
.venv/bin/python -m compileall -q artcode tests
.venv/bin/python -m build
```

## I. 用户亲自执行的二十项手工验收

以下部分严格只有 M01～M20 二十个场景。每项都必须完成 prepare、真实 TUI 操作、verify、collect 和 cleanup；用户在 `tests/manual/ch10_5_results.md` 写下实际结果后才能勾选。

- [ ] M01：冷启动与干净退出。
  - 目标风险：重复组装、启动污染、资源未关闭。
  - 准备：运行 `prepare M01`，Fixture 创建空 Workspace、隔离 ArtCode 根和合法真实配置引用。
  - 操作：运行 `launch M01`；看到提示符后依次输入 `/status`、`/exit`。
  - 预期：只出现一次启动信息；状态中有唯一 Session ID、正确 Workspace、Thinking/沙箱状态且秘密已遮蔽；退出码为 0，无重复 MCP 启动或关闭警告。
  - 证据：启动/关闭事件序列、Session ID、退出码、资源存活计数。
  - 清理：先运行 `collect M01`，再运行 `cleanup M01`；verify 必须报告隔离目录外零写入。

- [ ] M02：严格配置拒绝。
  - 目标风险：未知字段被忽略、MCP 错误类型被当成空配置。
  - 准备：`prepare M02` 生成三个无真实 API 调用的配置变体：顶层两个未知键、`thinking` 内两个未知键、`mcp_servers` 为 list。
  - 操作：按 Fixture 打印顺序分别运行三次 `launch M02 --variant top|thinking|mcp-type`。
  - 预期：三次均在 TUI 启动前以退出码 2 失败；前两次一次列出当前层全部未知键及路径；第三次明确指出容器类型错误；Provider/MCP 启动计数为 0。
  - 证据：三份脱敏 stderr、退出码和构造计数。
  - 清理：运行 `collect M02` 和 `cleanup M02`。

- [ ] M03：Thinking 关闭的真实请求。
  - 目标风险：关闭配置被省略后由服务端默认开启。
  - 准备：`prepare M03` 从真实配置生成内存覆盖 `thinking.enabled=false`，启用脱敏 payload 观察器。
  - 操作：`launch M03`，输入“只回复数字 7，不调用工具”，等待完整回答后输入 `/exit`。
  - 预期：终端显示 7 和真实 usage；发出的普通请求显式关闭 Thinking；没有 reasoning 文本泄漏到 TUI、JSONL 或证据。
  - 证据：脱敏 payload 字段、可见回答、usage、Session role 列表。
  - 清理：运行 `collect M03` 和 `cleanup M03`。

- [ ] M04：Thinking high 连续工具续接。
  - 目标风险：Assistant 工具消息缺失 reasoning content 导致第二轮协议失败。
  - 准备：`prepare M04` 开启 Thinking high，并在 Workspace 放置两个必须先读取再组合的文本文件。
  - 操作：`launch M04`，要求读取两个文件、写入 `result.txt`、再次读取核对；按提示允许 Workspace 内操作。
  - 预期：至少发生两次模型请求和连续工具轮次并自然完成；`result.txt` 内容正确；后续请求包含协议所需 reasoning content，但 TUI 和人类可读结果不显示内部推理。
  - 证据：请求轮数、脱敏消息字段存在性、工具结果、文件哈希和最终回答。
  - 清理：运行 `collect M04` 和 `cleanup M04`。

- [ ] M05：超过十二轮仍继续。
  - 目标风险：旧 12 轮限制或新的隐式轮数限制残留。
  - 准备：`prepare M05` 启动兼容 DeepSeek SSE 的确定性本地 Provider Fixture，预编排 13 次只读工具调用后返回最终文本。
  - 操作：`launch M05`，输入“执行完整检查直到模型自然结束”，允许只读工具，观察轮数显示。
  - 预期：第 13 次工具结果后仍发起下一次模型请求并自然显示最终文本；没有“达到最大迭代数”提示，也没有自动终止或重复工具检测。
  - 证据：Provider 请求序号、13 次 Tool call/result、最终 finish reason 和 Session 协议序列。
  - 清理：运行 `collect M05` 和 `cleanup M05`。

- [ ] M06：Ctrl+C 取消真实进程树。
  - 目标风险：半截 Assistant 被保存、子孙进程残留。
  - 准备：`prepare M06` 创建会记录父/子/孙 PID 的长时间命令 Fixture。
  - 操作：`launch M06`，要求运行该命令；命令开始并显示 PID 后按一次 Ctrl+C，回到提示符后输入 `/status` 和 `/exit`。
  - 预期：取消直接终止整个进程组，TUI 可继续接收命令；所有记录 PID 不存在；取消前半截 Assistant 不在 Conversation/JSONL，已确定 Tool call 有结构化中断结果。
  - 证据：按键时间、PID/PGID 存活检查、Session 消息序列、退出码。
  - 清理：运行 `collect M06` 和 `cleanup M06`。

- [ ] M07：命令超时强制回收。
  - 目标风险：父进程超时后后代继续运行。
  - 准备：`prepare M07` 把命令 timeout 设为 1 秒，并创建忽略普通信号的父/子/孙进程树。
  - 操作：`launch M07`，要求执行 Fixture 命令并等待超时，然后询问模型解释可见结果。
  - 预期：约 1 秒后得到结构化 timeout；进程组经 SIGKILL 回收，所有 PID 消失；Agent 能读取 Tool result 并给出最终回答。
  - 证据：单调时钟耗时、终止信号、PID 状态、Tool result 和最终文本。
  - 清理：运行 `collect M07` 和 `cleanup M07`。

- [ ] M08：自动创建多级目录。
  - 目标风险：写新文件因父目录不存在失败或创建到 Workspace 外。
  - 准备：`prepare M08` 创建空 Workspace 并记录初始目录树。
  - 操作：`launch M08`，要求创建 `alpha/beta/gamma/result.txt`，内容精确为两行 `第一行`、`second line`，再读取核对；批准写入。
  - 预期：三级父目录自动创建，文件内容和换行精确匹配；Workspace 外没有新增路径；最终回答报告核对成功。
  - 证据：前后目录树、文件 SHA-256、读取 Tool result 和外部写入审计。
  - 清理：运行 `collect M08` 和 `cleanup M08`。

- [ ] M09：审批期间符号链接目标变化。
  - 目标风险：审批看到内部路径，执行时链接已指向外部。
  - 准备：`prepare M09` 创建 Workspace 内链接、内部目标、外部哨兵文件和在审批窗口切换链接的辅助进程。
  - 操作：`launch M09`，要求写链接路径；出现审批时按 Fixture 指示切换链接后再选择一次允许。
  - 预期：执行前复核发现目标变化并拒绝；外部哨兵哈希不变；内部旧目标也没有部分修改；TUI 显示结构化路径拒绝。
  - 证据：审批前/执行前 realpath、链接切换时间、两份目标哈希和 Tool result。
  - 清理：运行 `collect M09`，确认辅助进程已退出，再运行 `cleanup M09`。

- [ ] M10：权限四类选择。
  - 目标风险：一次/永久、允许/拒绝语义混淆或状态不同步。
  - 准备：`prepare M10` 创建四个等价安全写任务和隔离的 user/project/local 权限文件。
  - 操作：在同一 TUI 中依次对四组任务选择“一次允许”“永久允许”“一次拒绝”“永久拒绝”，每组立即重复同类操作一次。
  - 预期：一次允许的重复操作再次询问；永久允许的重复操作不再询问并执行；一次拒绝的重复操作再次询问；永久拒绝的重复操作不询问且拒绝。状态展示与执行结果一致。
  - 证据：八次审批/执行序列、规则文件 diff、每批 PermissionSnapshot 和文件结果。
  - 清理：运行 `collect M10` 和 `cleanup M10`，真实权限文件哈希必须未变化。

- [ ] M11：Seatbelt 网络全部禁止。
  - 目标风险：公网、DNS、回环或本地监听存在漏网路径。
  - 准备：`prepare M11` 启动隔离本地监听 Fixture，并提供分别尝试公网、DNS、127.0.0.1、`::1`、本地 listen 和子进程连接的命令。
  - 操作：`launch M11`，要求逐个执行六类网络命令，再执行一次 Workspace 内创建普通文件的命令。
  - 预期：全部网络操作失败且没有连接抵达监听 Fixture；本地文件操作成功；没有出现域名授权或交互网络放行选项。
  - 证据：六个退出结果、监听连接计数 0、Seatbelt 日志和本地文件哈希。
  - 清理：运行 `collect M11`，关闭监听 Fixture，再运行 `cleanup M11`。

- [ ] M12：敏感文件保护。
  - 目标风险：工具读取配置、权限、Session、Memory 或内置安全策略。
  - 准备：`prepare M12` 在每类敏感位置放置不同秘密哨兵，并在 Workspace 放置一个允许读取的普通文件。
  - 操作：`launch M12`，依次要求读取或修改配置、权限、Session、Memory、危险命令配置和 Seatbelt profile，最后读取普通文件。
  - 预期：六类敏感目标均拒绝且 TUI/日志不出现任何哨兵；普通文件读取成功；拒绝不影响后续 Agent 继续工作。
  - 证据：Tool result 序列、秘密扫描零命中、敏感文件哈希不变和普通文件内容。
  - 清理：运行 `collect M12` 和 `cleanup M12`。

- [ ] M13：Plan → Do 显式模式流。
  - 目标风险：Plan 执行写操作、模式藏在执行器状态、Do 丢失计划。
  - 准备：`prepare M13` 创建需要读取两个文件后再修改第三个文件的任务，并接入一个可见的测试 MCP 工具。
  - 操作：输入 `/plan` 加多行需求；在 Plan 中允许只读操作并观察 MCP 确认；确认磁盘未改后输入 `/do`，批准写入并等待完成。
  - 预期：Plan 阶段只读、MCP 每次确认且明确显示 Plan；Do 读取最近计划并完成写入；请求结束后显示模式恢复默认。
  - 证据：模式事件、PlanMemory 快照、审批文本、Plan 前后磁盘哈希和 Do 后结果。
  - 清理：运行 `collect M13` 和 `cleanup M13`。

- [ ] M14：MCP stdio 隔离与关闭。
  - 目标风险：单 Server 故障拖垮全部工具、子进程关闭不完整。
  - 准备：`prepare M14` 配置一个健康分页 stdio Server、一个启动失败 Server 和一个可超时工具。
  - 操作：`launch M14`，观察启动报告；调用健康工具并确认；调用超时工具并取消；再调用内置只读工具，最后 `/exit`。
  - 预期：失败 Server 只报告自身问题；分页工具完整发现；健康调用成功；超时/取消结构化返回；内置工具仍可用；退出后 stdio PID 全部消失。
  - 证据：Server 状态、工具清单、审批/结果、PID 和关闭事件。
  - 清理：运行 `collect M14` 和 `cleanup M14`。

- [ ] M15：MCP HTTP headers、重定向、取消与脱敏。
  - 目标风险：HTTP 认证泄漏、重定向错误、取消污染其他服务。
  - 准备：`prepare M15` 启动本地 HTTP MCP Fixture，配置秘密 header、允许的重定向、慢调用和错误调用。
  - 操作：`launch M15`，依次执行发现、正常调用、重定向调用、错误调用和慢调用取消，再调用一个健康工具。
  - 预期：正常与重定向成功；错误/取消变成结构化结果；后续健康调用成功；TUI、日志和证据均不出现秘密 header。
  - 证据：HTTP 请求类型的脱敏摘要、Tool result、取消后的连接状态和秘密扫描。
  - 清理：运行 `collect M15`，关闭 HTTP Fixture，再运行 `cleanup M15`。

- [ ] M16：多次上下文压缩仍保留全部用户原文。
  - 目标风险：摘要替换、合并或改写用户消息。
  - 准备：`prepare M16` 生成带唯一 Unicode 标记和不同空白的长对话，并把窗口调小到合法下限以触发多轮轻量/重量压缩。
  - 操作：`launch M16`，按 Fixture 提示继续提交至少三条真实用户消息、执行工具并触发两次压缩，最后要求逐条复述标记。
  - 预期：请求可继续；每条用户消息仍是独立 `role=user` 且字节、数量、顺序不变；摘要只替换允许的非 User 历史；工具协议闭合。
  - 证据：每轮 User SHA-256 清单、消息角色序列、摘要边界、Tool call/result 配对和最终回答。
  - 清理：运行 `collect M16` 和 `cleanup M16`。

- [ ] M17：恢复提醒只在真实发送时消费一次。
  - 目标风险：`/status` 或估算提前吃掉提醒，或提醒重复进入后续请求。
  - 准备：`prepare M17` 创建可恢复 Session 和 pending 恢复提醒，并启用脱敏请求观察器。
  - 操作：`launch M17 --resume <fixture-session-id>`；连续输入两次 `/status`；再发第一条普通消息，完成后发第二条普通消息，最后 `/exit`。
  - 预期：两次状态查询零 Provider 调用且提醒仍 pending；第一条真实请求包含一次提醒；第二条不再包含；提醒不作为 User 记录写入 JSONL。
  - 证据：四次操作后的 Provider 计数、提醒字段计数、Conversation/JSONL role 列表和状态快照。
  - 清理：运行 `collect M17` 和 `cleanup M17`。

- [ ] M18：损坏 Session 的安全恢复。
  - 目标风险：一条坏记录导致整个会话丢失，或错误跳过后破坏工具协议。
  - 准备：`prepare M18` 生成包含安全前缀、完整坏中间行、坏行后的安全 User、损坏 Tool 协议组和不完整尾部的 JSONL。
  - 操作：按 Fixture ID 运行 `launch M18 --resume <fixture-session-id>`，观察警告并输入 `/status`，再发一条继续消息后退出。
  - 预期：独立坏行被跳过并警告；其前后安全记录恢复；尾部截断；破坏协议的部分只保留最大安全前缀；所有恢复 User 原文不变，后续追加后可再次恢复。
  - 证据：原始/修复后 JSONL 副本、警告、恢复消息序列、安全 User 哈希和二次恢复结果。
  - 清理：运行 `collect M18` 和 `cleanup M18`。

- [ ] M19：双进程 Session 锁。
  - 目标风险：两个进程并发追加同一 JSONL。
  - 准备：`prepare M19` 创建一个可恢复 Session，并打印两条独立终端启动命令。
  - 操作：终端 A 精确恢复该 Session 并保持运行；终端 B 先精确恢复同一 ID，再执行默认恢复；分别发一条带进程标记的消息，最后退出 A，再次在 B 精确恢复原 ID。
  - 预期：B 的首次精确恢复明确拒绝且未追加；默认恢复选择可写新 Session；A 退出后原锁释放，B 可精确恢复；任一 JSONL 都没有交叉进程标记。
  - 证据：两个终端日志、Session ID、锁状态、JSONL 写入来源和退出后重取锁结果。
  - 清理：运行 `collect M19`，确认两个进程退出，再运行 `cleanup M19`。

- [ ] M20：长期记忆成功与失败隔离。
  - 目标风险：后台记忆失败改变当前回复，或成功记忆重复/重启丢失。
  - 准备：`prepare M20` 创建隔离用户/项目记忆目录，并提供成功、timeout、非法响应和磁盘失败四种可切换 Memory Fixture。
  - 操作：先用成功模式完成一轮明确偏好并等待队列；重复同一事实；再依次切换三种失败模式完成普通对话；最后重启并询问已保存偏好。
  - 预期：成功事实只产生一条 active note 并在重启后注入；三种失败均只显示状态，不改变各轮最终回答、Conversation、JSONL 或下一次正常请求；关闭时队列无残留。
  - 证据：每轮最终文本、Conversation/JSONL 哈希、Note/index diff、重复 active 数、重启请求和队列关闭状态。
  - 清理：运行 `collect M20` 和 `cleanup M20`。

## J. 最终端到端判定

- [ ] J01：在全新隔离环境中执行“冷启动 → 普通真实 DeepSeek 对话 → Thinking 工具链 → Plan → Do → 文件写入 → `/status` → 退出 → `--resume` → 再次对话”，所有步骤经过唯一主流程且 Session 可恢复。（验证：综合 E2E 的事件、文件、JSONL、usage 和关闭证据全部通过。）
- [ ] J02：在同一综合流程中触发一次上下文压缩后，恢复前后全部 User 原文哈希、数量和顺序一致，恢复提醒只进入一次真实请求。（验证：E2E 前后消息清单和请求捕获通过。）
- [ ] J03：综合流程结束后，Workspace 结果正确，所有进程/MCP/HTTP/Session/Memory 资源归零，隔离根外无写入且日志秘密扫描零命中。（验证：资源与文件系统终审脚本通过。）
- [ ] J04：H01～H22 全部勾选，M01～M20 恰好二十项全部由用户记录为通过，且不存在真实失败或环境阻塞项。（验证：自动验收报告、`ch10_5_results.md` 和本 Checklist 交叉核对。）
- [ ] J05：最终 README、测试说明、四份 ch10.5 文档和架构图与运行中的代码一致；未通过项为零后才可宣布 ch10.5 重构完成。（验证：文档审计、全量测试和用户最终确认三项同时存在。）

## Spec 验收标准映射

| Spec 验收标准 | 对应检查项 |
|---|---|
| AC1 | A01～A10、E09、M01、M06 |
| AC2 | B01～B06、M02 |
| AC3 | B07～B18、M03～M04 |
| AC4 | C01～C08、M05、M17 |
| AC5 | C09～C18、M06、M16 |
| AC6 | D01～D09、M10、M13 |
| AC7 | D10～D14、M08～M09、M12 |
| AC8 | D08、D15～D20、M06～M07、M10～M11 |
| AC9 | E01～E11、M13～M15 |
| AC10 | F01～F10、M17～M19 |
| AC11 | F11～F16、M20 |
| AC12 | G01～G08 |
| AC13 | H01～H22 |
| AC14 | M01～M20 |
| AC15 | G09～G11、J01～J05 |

全部 AC1～AC15 均有自动或手工可观察检查项；全部 F1～F44 通过其所属 AC 和对应分区得到验收。任何一项未勾选时，只能报告“部分完成”或具体阻塞，不能报告本章完成。
