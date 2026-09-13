# 同一 Run 的请求续接与 MCP 按需激活

2026-09-05，项目所有者批准修订 [ADR 0003](0003-core-contract-freeze.md) 冻结的 Session、Tool 与 Agent 相关公开契约，以修复长 Tool 循环只有 Run 开始时才检查压缩、lazy MCP 缺少模型搜索激活入口的问题。Session 继续拥有 Transcript 与 Prompt 投影，Agent 在完整 Tool 批次提交后统一准备同一 Run 的下一次请求；这个边界允许替换不可变 Prompt 和 Tool 快照，不新建 Run、不重复提交用户目标，也不重放已完成 Tool。

Session 的续接接口使用已提交事实及本 Run 冻结的指令、记忆、Skill contribution、模型选择和已投递 Notice 重建请求。自动及紧急压缩从已提交事实及冻结来源构造候选请求，构造时保留 User 原文顺序、最近完整 Tool 交换与 Protocol Metadata；确认完整请求缩短后再保存派生状态；失败、无收益或取消保留原 Summary、原请求与 Transcript。同一历史前缀去重，连续失败有界；只有明确的上下文超限允许有界恢复，网络和认证失败沿原失败路径报告。Fork 保留父 Prompt 原始前缀，只能压缩子 Run 可重建的历史，前缀本身过大时明确停止。

Tool 增加模型可见的 `mcp_search_tools`，它只搜索已发现目录并激活命中项，不发起远程 Tool 调用。激活后的 Schema 与执行目录从同一 Run 的下一次请求起成对更新，更新后重新计入完整请求预算；当前批次仍使用原快照。刷新只扩大到本 Run 原来允许的已知能力，不改变 Workspace、Run Mode、来源、权限、Skill 白名单或执行上下文；Plan、Subagent 及未授权 Skill 无法通过搜索扩大能力，实际 MCP 调用仍独立进入权限流程。激活状态由当前进程的 Tool 目录持有，可用于其 Session 后续 Run，不写入 Session 存档以跨进程恢复。

普通 Run、Shared Skill、Isolated Skill、定义式与 Fork 式 Subagent 复用上述请求准备路径，子 Run 继承配置中的上下文窗口。选择安全边界更新快照，使执行中的批次具有稳定能力；选择候选校验后保存，使 Summary 的可重建性质不转变为对权威 Transcript 的替代。

Spec、Tasks、Checklist 与 `tests/behavior/ch14_matrix.yml` 同步记录修订范围；本 ADR 记录获批决策，测试是否通过以 [ch14 验收记录](../../tests/manual/ch14_results.md) 为准。
