# ch10.5：总结重构手工验收

本清单严格包含 M01～M20 二十项。必须由用户在真实终端中逐项操作；自动测试结果不能替代这里的人工结论。

## 通用隔离准备

在项目根目录执行，整个验收过程都只使用 `ARTCODE_MANUAL_ROOT`，不要直接改动真实 Workspace、Session、Memory 或权限文件：

```bash
export ARTCODE_MANUAL_ROOT="$(mktemp -d /tmp/artcode-manual.XXXXXX)"
mkdir -p "$ARTCODE_MANUAL_ROOT/user-home/.artcode" "$ARTCODE_MANUAL_ROOT/workspace"
cp ~/.artcode/config.yml "$ARTCODE_MANUAL_ROOT/user-home/.artcode/config.yml"
```

若真实配置位于项目 `artcode.yaml`，改为复制该文件。每次启动都使用：

```bash
env HOME="$ARTCODE_MANUAL_ROOT/user-home" .venv/bin/artcode \
  --config "$ARTCODE_MANUAL_ROOT/user-home/.artcode/config.yml" \
  --workspace "$ARTCODE_MANUAL_ROOT/workspace"
```

每项结束后先保存脱敏日志、文件哈希、Session role 序列和退出码，再清理该项创建的子目录或进程。全部二十项完成后，确认变量非空且目录位于 `/tmp/artcode-manual.` 前缀，再删除隔离根。

## M01 冷启动与干净退出

- 准备：确认 Workspace 为空，记录隔离根外文件清单和进程数。
- TUI 操作：以 `--new` 启动，依次输入 `/status`、`/exit`。
- 预期：启动面板只出现一次；状态中的 Workspace、Session、Thinking、权限和沙箱一致，API Key 只显示 configured；退出码为 0。
- 失败证据：重复启动块、Traceback、锁文件残留、退出后仍存活的 MCP/子进程，或隔离根外新增文件。
- 清理：保存启动与关闭日志，确认 `.artcode/context/` 为空且 Session 未锁定。

## M02 严格配置拒绝

- 准备：复制配置为三份，分别加入两个顶层未知键、两个 `thinking` 未知键，并把 `mcp_servers` 改为 list。
- TUI 操作：分别用三份配置启动，不输入用户消息。
- 预期：三次均在 TUI/Provider/MCP 创建前以退出码 2 失败；前两次一次列出当前层全部未知键，第三次明确报告 map 类型错误。
- 失败证据：未知键被忽略、仅报告一个未知键、出现网络请求或错误文本泄漏 Key。
- 清理：保存脱敏 stderr 和退出码，删除三份变体。

## M03 Thinking off 真实请求

- 准备：设置 `thinking.enabled: false`，记录 Session 目录为空。
- TUI 操作：`--new` 启动，输入“只回复数字 7，不调用工具”，回答完成后 `/exit`。
- 预期：可见回答含 7 和真实 usage；请求显式关闭 Thinking；TUI 与 JSONL 没有 reasoning 文本。
- 失败证据：服务端默认开启推理、Session 出现内部推理、无完成事件或秘密泄漏。
- 清理：保存脱敏请求字段、回答和 JSONL role 清单。

## M04 Thinking high 连续工具续接

- 准备：设置 `thinking.enabled: true`，创建 `left.txt`、`right.txt`，内容各含一个唯一标记。
- TUI 操作：要求依次读取两文件、写入组合结果、再次读取核对；按提示允许写入。
- 预期：至少两轮模型请求后自然完成；后续 Assistant 工具消息携带协议所需 reasoning 字段，但终端不显示内部推理；结果文件正确。
- 失败证据：第二轮协议错误、推理内容显示到终端、漏掉核对读取或写入结果错误。
- 清理：保存工具调用顺序与文件 SHA-256，恢复 Thinking 配置。

## M05 超过十二轮仍继续

- 准备：打开两个终端；一端运行 `pytest -s tests/soak/test_unlimited_agent_loop.py -m soak` 观察确定性 13+ 轮证据，另一端用真实 TUI 运行普通长工具任务。
- TUI 操作：持续要求“继续下一步检查”直到观察到第 13 个工具轮次，再允许自然完成。
- 预期：第 13 次工具结果后仍可发起下一模型请求；没有默认最大轮数、重复工具启发式停止或自动续写状态。
- 失败证据：第 12 轮自动停止、出现 iteration limit、对话协议缺失结果或递归栈增长。
- 清理：保存轮次序号、Provider 计数和最终停止原因。

## M06 Ctrl+C 取消真实进程树

- 准备：创建会记录父/子/孙 PID 的长时间 Shell 脚本，所有输出写入隔离 Workspace。
- TUI 操作：要求 `run_command` 执行脚本；PID 写出后按一次 Ctrl+C，随后输入 `/status`、`/exit`。
- 预期：整个进程组被终止并回收；TUI 回到可用状态；半截 Assistant 不进入 JSONL，已确定 Tool call 有结构化取消结果。
- 失败证据：任一 PID 仍存活、需要二次 Ctrl+C、Session 有半截 Assistant 或未闭合工具协议。
- 清理：对记录的每个 PID 执行只读存活检查，保存 JSONL role 序列。

## M07 命令超时强制回收

- 准备：使用测试配置把命令 timeout 调为 1 秒，脚本创建忽略普通信号的父子孙进程树。
- TUI 操作：要求执行脚本并等待超时，然后要求模型解释工具结果。
- 预期：约 1 秒得到 `command_timeout`；进程组经 SIGKILL 回收；Agent 能继续并自然回答。
- 失败证据：后代继续写文件、超时后挂起、返回普通失败而非 timeout，或 Agent 中断。
- 清理：保存单调时钟耗时、PID/PGID 状态和工具结果。

## M08 自动创建多级目录

- 准备：确认 `alpha/` 不存在，记录初始目录树。
- TUI 操作：要求创建 `alpha/beta/gamma/result.txt`，内容精确为 `第一行\nsecond line\n`，并再次读取核对。
- 预期：三级父目录自动创建，内容和换行完全一致，Workspace 外没有新增路径。
- 失败证据：父目录不存在错误、部分目录、越界写入、内容被改写或读取未核对。
- 清理：保存目录树、文件 SHA-256 和 Tool result 后删除 `alpha/`。

## M09 审批期间符号链接目标变化

- 准备：在 Workspace 建内部目标和符号链接，在隔离 Workspace 外但仍在手工隔离根内建哨兵；准备审批窗口切换链接的第二终端。
- TUI 操作：要求写链接路径；出现审批时先切换链接到外部哨兵，再选择一次允许。
- 预期：执行前复核发现目标变化并结构化拒绝；内外目标哈希都不变。
- 失败证据：外部哨兵改变、内部目标部分修改、审批显示目标与执行目标不同却仍成功。
- 清理：保存审批前后 realpath 与哈希，删除链接和辅助进程。

## M10 权限四类选择

- 准备：备份隔离的 user/project/local 权限文件，创建四组等价安全写任务。
- TUI 操作：依次选择一次允许、永久允许、一次拒绝、永久拒绝；每组立刻重复同类操作。
- 预期：一次选择会再次询问；永久允许不再询问且执行；永久拒绝不再询问且拒绝；`/status` 与执行读取同一状态。
- 失败证据：规则写错层、永久选择不生效、一次选择被缓存，或拒绝后仍改盘。
- 清理：保存八次审批序列和规则 diff，删除隔离权限文件。

## M11 Seatbelt 网络全部禁止

- 准备：在隔离根启动本地 IPv4/IPv6 监听器，准备公网、DNS、127.0.0.1、`::1`、本地 listen 和子进程连接命令。
- TUI 操作：逐个用 `run_command` 执行六类网络操作，再执行一次 Workspace 内普通文件写入。
- 预期：全部网络操作失败，监听连接数为 0；普通文件写入成功；没有域名放行 UI。
- 失败证据：任一连接到达、能创建监听、子进程绕过沙箱或本地写入也被误拒。
- 清理：停止监听器，保存退出码、Seatbelt 日志和连接计数。

## M12 敏感文件保护

- 准备：在隔离配置、权限、Session、Memory 位置放不同哨兵；Workspace 放一个允许读取的普通文件。
- TUI 操作：依次要求读/改六类敏感目标，最后读取普通文件。
- 预期：敏感目标全部拒绝且终端/日志不出现哨兵；普通文件成功，Agent 可继续。
- 失败证据：秘密出现在输出、任一敏感文件哈希变化，或一次拒绝终止整个 Agent。
- 清理：保存秘密扫描结果和全部哈希。

## M13 Plan → Do 显式模式流

- 准备：创建两个输入文件、一个待修改文件，并配置隔离的测试 MCP Server。
- TUI 操作：输入多行 `/plan` 需求，确认磁盘不变；随后 `/do` 并批准写入。
- 预期：Plan 只提供只读工具，MCP 确认明确显示 Plan；Do 使用最近计划完成写入，结束后模式恢复 DEFAULT。
- 失败证据：Plan 写盘、Do 丢失计划、隐藏模式影响审批，或显示模式未恢复。
- 清理：保存 PlanMemory、模式事件和前后文件哈希。

## M14 MCP stdio 隔离与关闭

- 准备：项目配置加入健康的 `tests/integration/fixtures/mcp_test_server.py`、一个不存在命令和一个慢工具 Server。
- TUI 操作：观察启动报告，调用健康工具、取消慢调用、再调用内置读取工具，最后 `/exit`。
- 预期：坏 Server 只影响自身；健康工具与内置工具可用；取消结构化返回；退出后 stdio PID 全部消失。
- 失败证据：一个 Server 拖垮注册表、取消泄漏 Task、秘密 stderr 未脱敏或进程残留。
- 清理：保存 Server 报告、工具列表和 PID 审计。

## M15 MCP HTTP 重定向、取消与脱敏

- 准备：用同一 MCP Fixture 启动本地 streamable HTTP，配置隔离秘密 Header、重定向、慢调用和错误调用。
- TUI 操作：依次执行发现、正常、重定向、错误、慢调用取消，再调用健康工具。
- 预期：正常与重定向成功；错误/取消变成结构化结果；后续调用成功；日志不含秘密 Header。
- 失败证据：Header 泄漏、取消污染会话、重定向失败或健康 Server 被关闭。
- 清理：保存脱敏请求摘要，停止 HTTP Fixture 并确认端口释放。

## M16 多次上下文压缩仍保留用户原文

- 准备：窗口设为合法下限，准备含 Unicode、前后空白和不同换行的多条长用户文本。
- TUI 操作：提交至少三条真实用户消息并产生大工具结果，执行两次 `/compact`，最后要求复述唯一标记。
- 预期：每条 `role=user` 的字节、数量、顺序不变；摘要只替换允许的非用户历史；工具协议闭合。
- 失败证据：用户消息被摘要、合并、删减或重排，或压缩后请求无法继续。
- 清理：保存每轮 User SHA-256、摘要边界和 Session 副本。

## M17 恢复提醒只在真实发送时消费一次

- 准备：创建一个时间戳超过 24 小时的可恢复 Session，记录 ID。
- TUI 操作：精确 `--resume`；连续两次 `/status`，再发两条普通消息，最后 `/exit`。
- 预期：状态查询零 Provider 调用且不消费提醒；第一条真实请求含一次提醒，第二条没有；提醒不写 JSONL。
- 失败证据：`/status` 触发请求、提醒提前消失、重复出现或伪装成 User。
- 清理：保存请求计数、提醒计数和 JSONL role 清单。

## M18 损坏 Session 的安全恢复

- 准备：复制 Session，加入完整坏中间行、坏行后的安全 User、破坏工具协议的组和不完整尾部。
- TUI 操作：按 ID 精确恢复，查看警告与 `/status`，再发一条继续消息并退出；随后再次恢复。
- 预期：独立坏行被跳过；不完整尾部截断；工具协议只保留最大安全前缀；安全 User 原文不变且可继续追加。
- 失败证据：整个会话丢失、坏行后的安全 User 消失、孤儿 Tool result 或二次恢复失败。
- 清理：保存原始/修复 JSONL、警告和用户哈希。

## M19 双进程 Session 锁

- 准备：创建一个可恢复 Session，打开终端 A、B。
- TUI 操作：A 精确恢复并保持；B 精确恢复同一 ID，随后默认启动；两端分别发进程标记，退出 A 后 B 再精确恢复原 ID。
- 预期：B 首次精确恢复明确拒绝；默认启动创建新 Session；A 退出后原锁释放；JSONL 没有交叉标记。
- 失败证据：两个进程同时追加同一文件、静默抢锁、退出后锁无法取得。
- 清理：退出两个进程，保存 Session ID、锁状态和写入来源。

## M20 长期记忆成功与失败隔离

- 准备：使用隔离用户/项目 Memory；准备成功、timeout、非法响应和只读目录写失败四种运行条件。
- TUI 操作：成功保存一条明确长期偏好并重复一次；再分别触发三种失败；重启后询问已保存偏好。
- 预期：成功事实只有一条 active note 且重启可见；失败只影响 Memory 状态，不改变当前回复、Conversation、JSONL 或下一轮请求；退出后队列为空。
- 失败证据：重复 active note、失败污染回复/会话、重启丢失成功记忆或关闭仍有后台请求。
- 清理：保存 Note/index diff、Conversation/JSONL 哈希和队列状态，最后删除整个隔离根。

## 结果记录要求

把每项的执行时间、命令、状态（通过/失败/阻塞）、证据路径、失败摘要和清理结果写入 `ch10_5_results.md`。任何“未执行”、失败或阻塞都必须保留，不能标记为通过。
