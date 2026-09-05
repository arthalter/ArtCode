# ch12：Skill 系统 Tasks

## 文件清单

| 操作 | 文件 | 职责 |
|---|---|---|
| 新建 | `artcode/skills/__init__.py` | Skill 子系统公开边界 |
| 新建 | `artcode/skills/models.py` | 元信息、目录、诊断、运行快照等不可变模型 |
| 新建 | `artcode/skills/discovery.py` | 三级目录扫描、frontmatter 解析、覆盖、指纹 |
| 新建 | `artcode/skills/service.py` | 最后有效目录、激活、刷新、清空 |
| 新建 | `artcode/skills/prompt.py` | 目录与激活 SOP 的系统消息 |
| 新建 | `artcode/skills/load_tool.py` | 系统级 Skill 加载工具 |
| 新建 | `artcode/skills/commands.py` | 动态斜杠 Skill 命令解析与帮助信息 |
| 新建 | `artcode/skills/execution.py` | 共享/独立执行协调、历史轮次选择、摘要回流 |
| 修改 | `artcode/workspace.py` | 暴露项目级 Skill 根目录 |
| 修改 | `artcode/bootstrap.py` | 启动发现、未知工具校验和依赖组装 |
| 修改 | `artcode/prompting/assembler.py` | 注入 Skill 目录、激活 SOP 与精确工具集合 |
| 修改 | `artcode/agent/request.py`、`loop.py`、`stream.py`、`modes.py` | 每轮运行快照、自然语言加载后编排、模型覆盖、组合白名单 |
| 修改 | `artcode/providers/base.py`、`deepseek.py` | 请求级模型覆盖 |
| 修改 | `artcode/tools/base.py`、`registry.py`、`execution.py` | 系统工具来源、加载工具注册、按名执行复核 |
| 修改 | `artcode/commands/*`、`artcode/runtime/app.py` | `/Skill名` 同轮执行、`/help` 发现与 `/clear` 联动 |
| 修改 | `tests/runtime_factory.py`、相关 fake / fixture | 注入 SkillService 和隔离执行依赖 |
| 新建 | `tests/unit/test_skills_*.py` | 领域、发现、状态、提示词、工具策略、执行单元测试 |
| 新建 | `tests/fault/test_skills_*.py` | 损坏文件、热更新、加载/隔离失败测试 |
| 新建 | `tests/integration/test_skills_*.py` | 主流程、权限、会话和命令集成测试 |
| 新建 | `tests/live/test_skills_*.py` | 配置可用时的真实 Provider 验证 |

## T1：建立 Skill 领域模型与公开边界

**影响文件：** `artcode/skills/__init__.py`、`artcode/skills/models.py`、`tests/unit/test_skill_models.py`  
**依赖任务：** 无  
**参考资料：** Spec F1、F3、F4、F7；Plan「Skill 数据模型」

1. 定义三层来源、两种执行模式、单项诊断、有效定义、目录快照、激活项和运行快照的不可变模型。
2. 为 frontmatter 的允许字段、名字、说明、工具列表、模式、历史轮数和可选模型定义严格校验规则。
3. 明确单文件入口和目录包入口的资源清单表达，防止附属文件被当作新的 Skill。
4. 只从 `artcode.skills` 导出稳定领域接口，避免调用方依赖内部文件布局。

**验证：** 运行 `pytest tests/unit/test_skill_models.py -q`；有效定义可构造，所有非法值得到可定位错误。

## T2：实现三级发现、frontmatter 解析与优先级覆盖

**影响文件：** `artcode/skills/discovery.py`、`artcode/workspace.py`、`tests/unit/test_skill_discovery.py`、`tests/fault/test_skill_discovery_faults.py`  
**依赖任务：** T1  
**参考资料：** Spec F1、F3、F5～F8；Plan「目录与来源」

1. 暴露 `.artcode/skills/` 项目级根目录，并复用既有用户级 `~/.artcode/skills/` 与包内资源定位方式。
2. 只发现根目录 Markdown 单文件和目录内 `SKILL.md` 入口，拒绝越界、符号链接、非普通文件和错误编码。
3. 使用安全 YAML 解析 frontmatter、分离正文、收集目录包资源，并稳定排序。
4. 实现同层重名检测与项目 > 用户 > 内置的覆盖规则。
5. 将解析失败归为可跳过诊断，不让单个候选破坏整份目录。

**验证：** 运行 `pytest tests/unit/test_skill_discovery.py tests/fault/test_skill_discovery_faults.py -q`；覆盖、目录包、损坏文件和确定性排序断言全部通过。

## T3：实现启动校验与最后有效目录刷新

**影响文件：** `artcode/skills/service.py`、`artcode/bootstrap.py`、`tests/unit/test_skill_service.py`、`tests/fault/test_skill_refresh_faults.py`  
**依赖任务：** T2  
**参考资料：** Spec F6、F8、F22、F23；Plan「发现、刷新与激活状态」

1. 创建持有目录、激活项、诊断和文件指纹的 SkillService。
2. 在启动组装完成全部普通工具和 MCP 工具后，校验所有有效 Skill 的白名单；未知工具阻止启动。
3. 在每次新用户请求前按文件指纹刷新目录，采用候选快照验证后原子替换。
4. 实现已激活 Skill 的最后有效版本保留、删除诊断和清空激活状态。

**验证：** 运行 `pytest tests/unit/test_skill_service.py tests/fault/test_skill_refresh_faults.py -q`；启动未知工具失败，运行时损坏更新不破坏最后有效激活版本。

## T4：构造两阶段 Skill 环境提示词

**影响文件：** `artcode/skills/prompt.py`、`artcode/prompting/assembler.py`、`artcode/agent/request.py`、`tests/unit/test_skill_prompt.py`、`tests/unit/test_prompt_assembler.py`  
**依赖任务：** T1、T3  
**参考资料：** Spec F2、F9～F11、N1、N6；Plan「提示词与两阶段加载」

1. 用目录快照生成只含名字和一句说明的系统消息。
2. 用激活快照生成独立、显著且稳定排序的 SOP 系统消息，不将它写入 Conversation。
3. 调整请求组装，使真实请求、估算、压缩重组和紧急重试均从同一快照生成目录和激活消息。
4. 证明未激活 Skill 正文、目录包附属文本和占位符替换逻辑不会进入请求。

**验证：** 运行 `pytest tests/unit/test_skill_prompt.py tests/unit/test_prompt_assembler.py -q`；启动请求不含 SOP，激活后所有重建请求都含完整 SOP。

## T5：扩展按工具名收窄的模式与执行复核

**影响文件：** `artcode/agent/modes.py`、`artcode/tools/base.py`、`artcode/tools/registry.py`、`artcode/tools/execution.py`、`tests/unit/test_skill_tool_policy.py`、`tests/unit/test_tool_execution.py`  
**依赖任务：** T1、T3  
**参考资料：** Spec F15～F17、AC7、AC8；Plan「系统级加载工具与白名单」

1. 扩展工具来源，清楚区分普通工具、MCP 工具与系统工具。
2. 为 ToolAccessPolicy 增加按名字限制，并与既有 Plan/Do 效果限制组合为只收窄的策略。
3. 由激活 Skill 的白名单计算普通工具交集；无激活 Skill 时维持现有普通工具集合。
4. 让请求可见工具过滤与 ToolExecutionService 的调用复核共享同一策略；系统工具始终允许但不放宽普通工具。
5. 回归确认权限、Seatbelt、路径检查、危险命令和 MCP 审批仍在系统工具以外的原链路中运行。

**验证：** 运行 `pytest tests/unit/test_skill_tool_policy.py tests/unit/test_tool_execution.py -q`；隐藏工具的伪造调用被拒绝，Plan 模式和权限行为不回退。

## T6：实现受控的系统级加载工具

**影响文件：** `artcode/skills/load_tool.py`、`artcode/skills/service.py`、`artcode/tools/registry.py`、`artcode/tools/__init__.py`、`tests/unit/test_skill_load_tool.py`、`tests/fault/test_skill_load_faults.py`  
**依赖任务：** T3、T5  
**参考资料：** Spec F10、F13、F16、N3；Plan「系统级加载工具与白名单」

1. 实现只按目录中 Skill 名字加载的工具，拒绝路径、未知名字和非法参数。
2. 加载成功时原子激活定义、记录顺序、保留其完整 SOP，并返回最少必要的结构化结果。
3. 保证加载工具始终存在于模型可调用集合，不经普通工具白名单裁剪。
4. 验证加载不会泄露未激活 SOP、用户认证信息或任意能力包资源正文。

**验证：** 运行 `pytest tests/unit/test_skill_load_tool.py tests/fault/test_skill_load_faults.py -q`；自然语言模拟调用后下一轮请求看到 SOP，错误加载不污染激活状态。

## T7：打通请求级模型覆盖

**影响文件：** `artcode/providers/base.py`、`artcode/providers/deepseek.py`、`artcode/agent/stream.py`、`artcode/agent/request.py`、`tests/unit/test_skill_model_override.py`、`tests/unit/test_openai_provider.py`  
**依赖任务：** T1、T4  
**参考资料：** Spec F21、AC10；Plan「执行协调」

1. 让准备后的模型请求、流收集器和 Provider 请求能携带可选模型覆盖。
2. Provider payload 有覆盖时使用它，否则精确保留既有会话默认模型行为。
3. 将覆盖绑定到一次 Skill 执行周期；后续普通请求自动回到默认模型。
4. 对 Provider 拒绝或模型不可用的情况保留现有安全错误映射，禁止静默替换。

**验证：** 运行 `pytest tests/unit/test_skill_model_override.py tests/unit/test_openai_provider.py -q`；payload、失败和恢复默认模型均可观察。

## T8：实现共享与独立 Skill 执行协调

**影响文件：** `artcode/skills/execution.py`、`artcode/agent/loop.py`、`artcode/agent/request.py`、`artcode/conversation/context.py`、`tests/unit/test_skill_execution.py`、`tests/fault/test_skill_isolation_faults.py`  
**依赖任务：** T4～T7  
**参考资料：** Spec F18～F21、N4；Plan「执行协调」

1. 统一建模“当前一次 Skill 执行”的用户附加要求、模式和一次性模型选择，禁止模板替换。
2. 共享模式复用主 Conversation 与 Agent Loop，保持既有会话、工具和记忆观察者行为。
3. 实现完整历史单元选择，建立不绑定主会话日志、长期记忆和主压缩状态的临时 Conversation。
4. 独立模式复用权限、路径、Seatbelt 与组合工具策略，隔离所有子对话中间记录。
5. 将独立模式最终总结或失败摘要以确定方式回流主历史，确保取消或异常不损坏主 Conversation。

**验证：** 运行 `pytest tests/unit/test_skill_execution.py tests/fault/test_skill_isolation_faults.py -q`；完整历史不拆工具对，主历史不含子对话中间记录。

## T9：实现动态斜杠入口与清空联动

**影响文件：** `artcode/skills/commands.py`、`artcode/commands/base.py`、`artcode/commands/dispatcher.py`、`artcode/commands/builtin.py`、`artcode/runtime/app.py`、`tests/unit/test_skill_commands.py`、`tests/unit/test_commands.py`  
**依赖任务：** T3、T6、T8  
**参考资料：** Spec F12、F14、F24；Plan「提示词与两阶段加载」

1. 在既有命令分发前安全解析目录中可用的 `/<Skill 名>`，禁止与静态命令冲突。
2. 将尚未激活和已激活的短命令都收敛到同一“加载并立即执行”协调器。
3. 成功加载后让帮助系统展示动态命令的描述与用法；未知斜杠输入保留现有提示。
4. 让 `/clear` 在不改变其余既有状态语义的前提下清理 Skill 激活项。

**验证：** 运行 `pytest tests/unit/test_skill_commands.py tests/unit/test_commands.py -q`；短命令同轮执行、帮助展示、冲突拒绝和清空行为都通过。

## T10：补齐 Skill 子系统的单元、故障与安全回归覆盖

**影响文件：** `tests/runtime_factory.py`、`tests/fixtures/skills.py`、`tests/unit/test_skills_*.py`、`tests/fault/test_skills_*.py`、`tests/property/test_skill_*.py`  
**依赖任务：** T1～T9  
**参考资料：** Spec AC1～AC12、N1～N6；Plan 全文

1. 为测试工厂加入可替换的 SkillService、目录、加载工具和隔离执行依赖。
2. 覆盖优先级、解析隔离、启动阻断、热更新、删除、激活顺序、多 Skill 工具交集和模型覆盖。
3. 以故障注入覆盖读文件错误、YAML 错误、并发刷新、加载异常、子任务失败、取消和 Provider 错误。
4. 增加属性测试，验证目录结果不依赖文件创建顺序，白名单不会扩大既有模式权限。

**验证：** 运行 `pytest tests/unit/test_skill_*.py tests/fault/test_skill_*.py tests/property/test_skill_*.py -q`；无随机失败且所有安全不变量通过。

## T11：接入主流程

**影响文件：** `artcode/bootstrap.py`、`artcode/runtime/app.py`、`artcode/agent/*`、`artcode/prompting/assembler.py`、`artcode/tools/*`、`tests/integration/test_skill_main_flow.py`、`tests/integration/test_skill_permission_flow.py`  
**依赖任务：** T1～T10  
**参考资料：** Spec F9～F25、AC4～AC13；Plan「架构概览」

1. 在生产 Bootstrap 中按正确顺序组装目录发现、工具注册、未知工具启动校验、SkillService、请求准备、执行协调和运行时入口。
2. 验证模型自然语言加载后的下一轮主请求、斜杠直达、共享模式、独立模式、清空和热更新穿过真实主链路。
3. 回归普通对话、Plan/Do、权限、MCP、会话恢复、记忆与上下文管理，确认未使用 Skill 时完全兼容。

**验证：** 运行 `pytest tests/integration/test_skill_main_flow.py tests/integration/test_skill_permission_flow.py tests/integration/test_command_flow.py tests/integration/test_agent_request_flow.py -q`；所有场景通过。

## T12：端到端验证

**影响文件：** `tests/live/test_skill_e2e.py`、`tests/live/test_skill_model_override.py`、`config.example.yml`（仅在确有配置变化时）  
**依赖任务：** T11  
**参考资料：** Spec 全部验收标准；Checklist「端到端场景」

1. 在临时项目、临时用户目录和内置测试资源中构造三级 Skill，执行覆盖、解析错误、白名单和热更新全流程。
2. 使用可控 Provider 运行共享和独立两条完整用户路径，检查请求消息、工具集合、主会话内容和子会话隔离。
3. 已配置真实 DeepSeek API 时运行真实加载、工具调用和模型覆盖测试；无法运行时报告缺失的本地配置，不把模拟测试冒充真实验证。
4. 执行全量回归并记录实际结果、跳过原因和证据。

**验证：** 运行 `pytest -q`，随后在配置可用时运行 `pytest tests/live/test_skill_e2e.py tests/live/test_skill_model_override.py -q`；全部本地测试通过，真实测试结果被如实记录。

## 执行顺序

```
T1 → T2 → T3 → T4 → T5 → T6 → T8 → T9 → T10 → T11 → T12
                   ↘ T7 ───────────────────↗
```
