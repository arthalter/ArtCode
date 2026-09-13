# ArtCode

ArtCode 是一个单机、单用户、功能全面的 CLI Coding Agent 学习项目。本文档只定义项目语言；功能、流程和实现决策属于 Spec 与 ADR。

## Language

**Session**:
一组可恢复的连续 Run，并拥有一份 Transcript。
_Avoid_: Conversation session, Task session

**Transcript**:
一个 Session 内按顺序追加的已提交对话事实。它是 append-only 的权威历史。
_Avoid_: Context, Prompt history, Conversation cache

**Prompt**:
一次实际发送给 Provider 的不可变请求。它是临时模型输入，不是 Session 历史。
_Avoid_: Conversation, Transcript snapshot

**Notice**:
需要在下一次适用 Prompt 中投递的一次性运行信息。它不是对话事实。
_Avoid_: System Message, Transcript Message

**Summary**:
对已提交 Transcript 前缀生成的可重建派生表示。它不是权威历史。
_Avoid_: Compressed Transcript, Session history

**Protocol Metadata**:
Provider 为续接 Assistant Tool Request 所要求的不透明字段。它不是用户内容或可提炼的事实。
_Avoid_: Reasoning content, Assistant answer

**Run**:
一次需要模型参与的完整执行，从接受明确目标开始，以明确的 Stop Reason 结束。
_Avoid_: Task, Session, Provider Turn

**Run Mode**:
Run 的工作意图：`chat`、`plan` 或 `act`。Plan 表示 Workspace 不可写，不表示进程完全无状态变化。
_Avoid_: Display Mode, Permission Mode, Skill Mode

**Task**:
对一个 Subagent Run 的调度与状态记录。它可以被主 Agent 等待，也可以在后台继续。
_Avoid_: User request, Run

**Subagent**:
由主 Agent 委派、使用独立 Run 状态执行 Task 的 Agent。
_Avoid_: Isolated Skill, Background Task

**Skill**:
可重用的操作说明与工具集合。Shared Skill 参与主 Run；Isolated Skill 使用临时 Transcript，但不是 Task 或 Subagent。
_Avoid_: Role, Subagent

**Tool Effect**:
Tool 对系统的语义影响：`observe`、`change`、`external` 或 `control`。
_Avoid_: Tool safety, Read-only flag

**Workspace**:
ArtCode 在当前运行中读取、理解和修改的项目根目录。
_Avoid_: Working directory, Repository
