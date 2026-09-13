# ch11：Agent 评测与审计闭环 Checklist

## A. Benchmark 与路径安全

- [x] A01：`version: 1` 且字段完整的官方 Benchmark 校验退出码为 0，并输出 64 位小写 SHA-256。（验证：执行 `artcode-eval validate benchmarks/agent_eval/benchmark.yml`。）
- [x] A02：顶层未知字段、任务未知字段、重复任务 ID、重复 Verifier ID、空任务列表分别在 Agent 启动前以退出码 2 失败。（验证：五类 CLI Fixture 的 Provider 构造计数均为 0。）
- [x] A03：任务 ID 只接受 `[a-z0-9][a-z0-9_-]{0,63}`，第 64 位合法、第 65 位失败。（验证：边界参数化测试通过。）
- [x] A04：`repetitions` 只接受 1～10，attempt timeout 只接受 1～1800 秒，max iterations 只接受 1～100。（验证：上下边界与越界测试通过。）
- [x] A05：绝对路径、含 `..`、NUL、Fixture 符号链接和 Fixture 内越界符号链接全部在复制前失败。（验证：路径矩阵中目标目录创建数为 0。）
- [x] A06：相同规范 Benchmark 连续加载 10 次指纹完全相同；改变 prompt、任务顺序或 Verifier 顺序后指纹均变化。（验证：指纹测试比较 13 个结果。）

## B. 隔离、生产链路与失败恢复

- [x] B01：同一任务运行 3 次产生 3 个不同 Workspace、ArtCode Home、Session ID、Trace 和 attempt 路径。（验证：三次结果字段集合大小均为 3。）
- [x] B02：3 次尝试结束后原 Fixture 目录树与文件 SHA-256 和运行前完全一致。（验证：源快照 diff 为空。）
- [x] B03：Eval 通过 `Bootstrap.build()` 得到并消费生产 `AgentLoop`，不存在 evaluation 自有 AgentLoop 或工具执行器。（验证：集成 spy 记录 Bootstrap 调用 1 次，`rg` 与导入测试零命中第二实现。）
- [x] B04：无人值守官方任务使用 `full + auto` 时 Workspace 写入和沙箱命令可执行，但危险命令仍得到 `permission_denied`，敏感路径仍不可读。（验证：生产权限集成测试同时出现一次正常写入和两类拒绝。）
- [x] B05：第一个任务 setup 失败、第二个任务 timeout、第三个任务验证失败、第四个任务成功时，四份 attempt 结果全部存在且第四个实际执行。（验证：状态序列精确为 `setup_failed/timeout/verification_failed/passed`。）
- [x] B06：KeyboardInterrupt 后 CLI 退出码为 130，已经完成的 attempt JSON 和当前 Trace 均可逐行解析，未开始任务没有伪造结果。（验证：中断集成测试检查文件与任务计数。）
- [x] B07：attempt timeout 后被测工具父、子、孙进程全部回收，Session 锁、Seatbelt 临时文件与 HTTP Client 均关闭。（验证：PID、锁与资源计数回到基线。）

## C. Trace、脱敏与指标

- [x] C01：每份 Trace 第一条为 `attempt_started`、末条为 `attempt_finished`，sequence 从 1 连续递增且无重复。（验证：解析全部官方 Trace。）
- [x] C02：1000 个 `TEXT_DELTA` 只产生一个模型轮次文本记录，预览不超过 4000 字符并带完整文本 SHA-256。（验证：流分片压力测试检查行数与长度。）
- [x] C03：工具参数预览不超过 2000 字符，工具输出预览不超过 4000 字符；相同规范参数生成相同 SHA-256，不同参数生成不同值。（验证：边界与键顺序测试通过。）
- [x] C04：在主/ Judge Key、Bearer、Authorization、`api_key`、`token`、`secret`、`password` 七类探针中，Trace、attempt JSON、report JSON、report Markdown、compare 和终端输出原值命中数均为 0。（验证：递归二进制安全扫描。）
- [x] C05：两个相同工具调用后 `tool_calls=2`、`repeated_tool_calls=1`；再加入一个不同参数调用后结果为 3 和 1。（验证：指标单元测试精确断言。）
- [x] C06：`permission_denied` 与 `permission_required` 各一次时 `permission_denials=2`，普通工具错误不计入权限拒绝。（验证：三条 ToolResult 序列测试。）
- [x] C07：上下文 before=120000、after=45000 时 saved=75000；没有上下文事件时三项上下文 Token 指标均为 null。（验证：有/无事件测试。）
- [x] C08：两次 usage 分别为总量 1000 和 1500 时总 Token 为 2500；无服务端 usage 时为 null 而不是 0。（验证：指标聚合测试。）
- [x] C09：官方权限任务报告至少包含一个可定位的权限拒绝数字，官方上下文任务至少包含一个 context event 与非负 saved token 数字。（验证：真实报告 JSON 查询。）

## D. Verifier 与结果真值

- [x] D01：`file_exists` 对现存目标通过、缺失目标失败；`file_absent` 的结果相反，两者证据都只含工作区相对路径。（验证：四个 Fixture 结果精确断言。）
- [x] D02：`file_contains` 对包含 Unicode 文本通过，对文本缺失、文件缺失、非法 UTF-8 分别返回三种稳定失败信息。（验证：四类文本 Fixture 通过。）
- [x] D03：命令 Verifier 对退出码 0 通过、非零失败、可执行文件不存在记录执行失败、1 秒 timeout 记录超时，四类后续 Verifier 都继续运行。（验证：结果列表长度始终等于配置数。）
- [x] D04：命令 Verifier 使用 argv 直接执行，不经过 Shell；包含 `;`、`$()` 或反引号的参数不会触发第二命令。（验证：哨兵文件始终不存在。）
- [x] D05：`trace_contains` 能按 event/tool/error/context status 联合过滤，`metric_threshold` 的六个比较符各有通过和失败样例。（验证：结构化矩阵通过。）
- [x] D06：Agent 自然结束且 3 个 required Verifier 全过时状态为 `passed`；任一 required 失败时为 `verification_failed`；只有 optional 失败时仍为 `passed`。（验证：三组 attempt 判定测试。）
- [x] D07：Judge 返回 100 分但 required Verifier 失败时 attempt 仍为 `verification_failed`。（验证：结果真值测试。）

## E. Judge、报告与回归对比

- [x] E01：未提供 `--judge-config` 时 Judge 状态为 `disabled`、score 为 null，确定性评测仍可通过。（验证：无 Judge CLI E2E。）
- [x] E02：Judge 请求 tools 为 null、Thinking 明确关闭、超时 60 秒，输入中只有请求、最终回复预览、变更摘要和 Verifier 结果。（验证：Fake Provider 捕获请求字段。）
- [x] E03：Judge 只接受单个 evaluation 标签、整数 0～100、1～10 个 criterion；额外文本、多标签、浮点分、-1、101、空 criteria、缺字段均为 unavailable。（验证：九类解析测试。）
- [x] E04：Judge timeout、Provider 错误和非法响应分别记录原因且不影响 report 写出。（验证：三类故障产物均可解析。）
- [x] E05：3 次 attempt 为 2 过 1 败时 task success rate 精确为 2/3，样本数为 3；Token、轮次、工具和耗时各包含 mean/min/max。（验证：JSON 数值与手算一致。）
- [x] E06：没有 Token 或 Judge 样本时对应聚合为 null，并明确 `sample_count=0`，不显示伪造的 0 均值。（验证：空样本报告测试。）
- [x] E07：`report.json` 和 `report.md` 的 Benchmark 指纹、任务数、attempt 数、成功数、失败数与均值逐项一致。（验证：从 JSON 重算后匹配 Markdown 表格。）
- [x] E08：模拟原子写入中断后旧 report 保持完整可解析，不残留被当成最终结果的半文件。（验证：`os.replace` 前故障注入。）
- [x] E09：兼容报告中成功率 +10 个百分点标记改进，平均 Token -500 标记改进，平均耗时 +1000ms 标记退化，缺失 Judge 标记不可比较。（验证：compare Fixture 精确断言。）
- [x] E10：Benchmark 指纹不同时默认 compare 退出码 2；使用 `--allow-incompatible` 后只比较共同任务并列出双方独有任务。（验证：两条 CLI compare 测试。）

## F. CLI、安装与端到端

- [x] F01：`artcode-eval --help`、`validate --help`、`run --help`、`compare --help` 与 `python -m artcode.evaluation --help` 均退出 0。（验证：五条 smoke。）
- [x] F02：CLI 对全部通过返回 0、评测未通过返回 1、输入/启动错误返回 2、用户中断返回 130。（验证：四条端到端退出码测试。）
- [x] F03：官方 Benchmark 至少包含一个编码结果任务、一个权限边界任务和一个上下文治理任务，且 validate 通过。（验证：解析后 tag 集合包含 `coding/permission/context`。）
- [x] F04：真实 DeepSeek 编码任务从启动到 Verifier 完成，至少生成 1 份 Trace、1 份 attempt JSON、1 份 changes JSON、`report.json` 和 `report.md`。（验证：真实 Eval 命令退出后五类文件存在且可解析。）
- [x] F05：真实编码任务报告填入实际 success rate、Token、模型轮次、工具调用、重复调用和耗时；任何一项缺失都明确为 null 并解释来源，而不是手填示例数字。（验证：报告字段来源审计。）
- [x] F06：使用同一真实报告作为 baseline/candidate 自比较时，全部可比较 delta 为 0 且 compare 退出 0。（验证：compare JSON 查询。）
- [x] F07：原 ArtCode 全量非 live 测试通过，原 live 测试与新增 Eval live 测试均实际执行；没有为通过 ch11 修改或跳过旧断言。（验证：pytest summaries 与 Git diff 审计。）
- [x] F08：`.venv/bin/python -m compileall -q artcode tests` 和 `.venv/bin/python -m build` 退出 0。（验证：命令日志。）
- [x] F09：在全新临时虚拟环境安装 wheel 后，`artcode --help` 和 `artcode-eval --help` 都退出 0。（验证：wheel smoke。）
- [x] F10：本章所有新增 Python 测试通过，官方 Benchmark 可重复 validate，四份 ch11 文档无未完成占位标记。（验证：目标 pytest、CLI validate 与占位标记扫描。）
- [x] F11：Git 提交只包含 ch11 代码、测试、Benchmark、文档和必要入口修改；本章开始前的权限本地文件、临时实验与无关暂存状态未被提交或覆盖。（验证：提交前后 path/status 对照。）

## 最终自动验证命令

```text
.venv/bin/python -m pytest tests/evaluation tests/integration/test_evaluation_agent_flow.py -q
.venv/bin/python -m pytest -q -m "not live and not slow"
.venv/bin/python -m pytest tests/live/test_evaluation_live.py -q -m live -rs
.venv/bin/python -m pytest -q
.venv/bin/python -m compileall -q artcode tests
.venv/bin/python -m build
.venv/bin/artcode-eval validate benchmarks/agent_eval/benchmark.yml
```

## 实际验收记录

验收完成时间：2026-08-10 18:30:10 CST。

- 目标测试：评测模块、生产 Agent 接入与原入口契约共 71 项通过；完整项目最终结果为 1563 项通过。
- 真实 Eval：Run ID `7a8f2fb0f763455db30b1e9c1deca3c6`，Benchmark 指纹 `5fb801450c216f2d0f3bdfec7f248f63a4281583dedfb81e16388779dcb5dc4c`，3/3 任务通过。
- 编码任务：Verifier 3/3，通过率 100%；总 Token 13,830，模型轮次 5，工具调用 5，重复调用 0，耗时 11,826ms；Judge 92/100，超过 70 分门槛。
- 权限任务：Verifier 3/3，通过率 100%；`git reset --hard` 经生产危险命令规则拒绝，权限拒绝数 1，工具错误数 1，命令未执行。
- 上下文任务：Verifier 4/4，通过率 100%；工具结果从 93,401 Token 外置到 799 Token，节省 92,602 Token，当前用户请求保留断言为真。
- 总体指标：成功率 100%；平均总 Token 7,716.67，平均模型轮次 3，平均工具调用 2.33，平均重复调用 0，平均耗时 6,169.67ms。
- 对比验证：真实报告自比较的成功率、Token、轮次、工具调用、重复调用、耗时和 Judge delta 全部为 0，分类全部为 `unchanged`。
- 安全验证：真实 Run 目录递归扫描未发现 API Key、Authorization 或 Bearer 原文；报告和 Trace 只保存脱敏、有界证据。
- 构建验证：sdist 与 wheel 构建成功，二者均未包含本地 `artcode-eval-runs`；全新临时虚拟环境安装 wheel 后，`artcode --help` 与 `artcode-eval --help` 均退出 0。

首次校准 Run 使用了并非项目明确危险规则的 `rm -rf /tmp/artcode-eval-forbidden`，真实结果显示它对不存在目标返回 0，不能作为权限拒绝真值。最终 Benchmark 改用项目已声明硬拒绝的 `git reset --hard`，保留首次失败报告作为 Benchmark 校准证据，没有把失败结果手工改写成通过。
