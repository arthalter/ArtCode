# ch09：会话恢复与长期记忆 Plan

## 架构概览

ch09 新增 `artcode.persistence` 包，作为所有跨进程状态的唯一协调边界。对外只暴露指令上下文、会话恢复结果、活动会话日志和异步记忆观察者；包内部仍将指令、会话、笔记和 LLM 更新分为独立模块。

```text
启动
  ↓
构造持久路径、清理过期会话
  ↓
加载三层指令 ──────┐
  ↓                           │
选择/恢复/新建 JSONL 会话    │
  ↓                           │
恢复 Conversation + PlanMemory    │
  ↓                           │
重建两份记忆索引 ─────────┐  │
  ↓                                 │  │
初始化工具、MCP、ch08 管理器      │  │
  ↓                                 │  │
恢复历史过大时先压缩一次          │  │
  ↓                                 │  │
每次模型请求前重建实际 System Prompt ◀─┘  │
  ↓                                    │
Agent Loop：每条确定消息立即追加 JSONL        │
  ↓                                    │
无工具最终回复自然结束                    │
  ↓                                    │
串行后台 LLM 更新笔记并原子重建索引 ───────┘
```

`ConversationContext` 仍是当前进程中的对话真相，`ContextManager` 仍只负责上下文压缩。`SessionJournal` 保存未压缩的原始规范消息，因此 ch08 的摘要替换和临时 Artifact 不会破坏跨进程恢复。

## 命名与存储布局

项目已经使用 `~/.artcode` 和 `<workspace>/.artcode` 存放配置、权限、MCP 与上下文文件。本章不再引入初步想法中的 `.mewcode`，否则会出现两套用户主目录、敏感路径和打包规则。

```text
~/.artcode/
├── config.yml
├── permissions.yml
├── instructions.md                 # 用户级手写指令
└── memory/
    ├── index.md                    # 用户级生成索引
    └── mem-<timestamp>-<xxxx>.md   # 用户级笔记

<workspace>/
├── ARTCODE.md                      # 可随项目管理的根指令
└── .artcode/
    ├── instructions.md             # 项目本地指令，优先级最高
    ├── sessions/
    │   └── <session-id>.jsonl
    └── memory/
        ├── index.md
        └── mem-<timestamp>-<xxxx>.md
```

项目本地指令适合不准备提交的机器差异；根 `ARTCODE.md` 适合跟随项目的公共技术栈和规范；用户级 `instructions.md` 适合语言、交流方式等跨项目偏好。

目录创建为 `0700`，内部文件为 `0600`。所有临时文件在目标目录内创建，再用原子替换提交，避免跨文件系统移动。

## 固定参数

| 参数 | 固定值 | 语义 |
|---|---:|---|
| `@include` 最大深度 | 5 层 | 入口文件不计引用层，第 6 次向下引用停止 |
| 指令总预算 | 64KB | 三层及引用展开后的 UTF-8 总字节 |
| 时间跨度提醒 | 24 小时 | 严格超过才触发，只注入首次请求 |
| 会话保留 | 30 天 | 以最后有效记录时间为准 |
| 会话 ID 随机后缀 | 4 位 hex | 2 随机字节，冲突时重生成 |
| 会话标题 | 50 Unicode 字符 | 归一化空白后在字符边界省略 |
| 默认会话列表 | 20 个 | 只限制显示，不限制存档数量 |
| JSONL 单记录恢复上限 | 4MB | 超过则不进行无界解析 |
| 每轮记忆变更 | 5 个 | 新增、更新、合并、作废均计数 |
| 单条笔记 | 8KB | frontmatter 与正文的 UTF-8 总字节 |
| 索引单条摘要 | 120 Unicode 字符 | 不在多字节字符中间截断 |
| 每份索引 | 200 行且 25KB | 两个条件必须同时满足 |
| 记忆更新超时 | 30 秒 | 超时取消该后台请求 |
| 记忆更新最大输出 | 4,000 Token | 足够返回最多 5 个结构化操作 |
| 记忆工作器并发度 | 1 | 串行提交，避免索引覆盖 |

## 核心数据结构

### `DurablePaths`

```python
@dataclass(frozen=True)
class DurablePaths:
    user_instruction: Path
    project_instruction: Path
    local_instruction: Path
    sessions_dir: Path
    user_memory_dir: Path
    project_memory_dir: Path

    @classmethod
    def from_context(cls, app_paths: ArtCodePaths, workspace: Workspace) -> "DurablePaths": ...
```

所有新路径只由该结构生成。`ArtCodePaths` 与 `Workspace` 增加对应属性，其他模块不手写 `.artcode` 字符串。

### 指令模型

```python
class InstructionScope(StrEnum):
    PROJECT_LOCAL = "project_local"
    PROJECT_ROOT = "project_root"
    USER = "user"

@dataclass(frozen=True)
class InstructionDocument:
    scope: InstructionScope
    path: Path
    content: str
    byte_count: int
    included_paths: tuple[Path, ...]

@dataclass(frozen=True)
class InstructionIssue:
    source: Path
    code: str
    message: str

@dataclass(frozen=True)
class InstructionBundle:
    documents: tuple[InstructionDocument, ...]
    total_bytes: int
    issues: tuple[InstructionIssue, ...]
```

`InstructionBundle.documents` 永远按项目本地、项目根、用户级排序，空或不存在文件不产生 Document。

### 会话模型

```python
@dataclass(frozen=True)
class SessionRecord:
    version: int
    timestamp: datetime
    entry_id: str
    mode: str
    message: dict[str, Any]

@dataclass(frozen=True)
class SessionDescriptor:
    session_id: str
    path: Path
    title: str
    message_count: int
    last_active_at: datetime
    bad_line_count: int
    locked: bool

@dataclass(frozen=True)
class SessionRecoveryReport:
    descriptor: SessionDescriptor
    records: tuple[SessionRecord, ...]
    bad_line_count: int
    truncated: bool
    truncated_reason: str
    gap_reminder_required: bool
    recovered_plan: str | None
```

JSONL v1 的单行格式为：

```json
{"v":1,"timestamp":"2026-08-06T08:30:00Z","entry_id":"msg-00000002","mode":"normal","message":{"role":"user","content":"继续上次任务"}}
```

字段使用稳定、无缩写的 JSON key；写入使用紧凑 JSON 但保留 Unicode，一条记录一行。`message` 保留 OpenAI-compatible 规范消息，`mode` 只用于恢复最近 Plan，不发送给模型。

### 笔记模型

```python
class MemoryScope(StrEnum):
    USER = "user"
    PROJECT = "project"

class MemoryCategory(StrEnum):
    PREFERENCE = "preference"
    CORRECTION = "correction"
    PROJECT_KNOWLEDGE = "project_knowledge"
    REFERENCE = "reference"

class MemoryStatus(StrEnum):
    ACTIVE = "active"
    SUPERSEDED = "superseded"

@dataclass(frozen=True)
class MemoryNote:
    id: str
    scope: MemoryScope
    category: MemoryCategory
    status: MemoryStatus
    title: str
    summary: str
    body: str
    created_at: datetime
    updated_at: datetime
    source_session: str
    source_entry_ids: tuple[str, ...]

@dataclass(frozen=True)
class MemoryOperation:
    action: str                  # create | update | supersede | noop
    scope: MemoryScope
    category: MemoryCategory
    target_id: str | None
    title: str
    summary: str
    body: str
    source_entry_ids: tuple[str, ...]

@dataclass(frozen=True)
class MemoryUpdateReport:
    status: str
    created: int = 0
    updated: int = 0
    superseded: int = 0
    rejected: int = 0
    message: str = ""
```

作废不直接删除文件，而是将 `status` 改为 `superseded`。这样该笔记不再进入索引，但人工仍能审计和恢复。

### 自然结束轮次

```python
@dataclass(frozen=True)
class NaturalTurn:
    session_id: str
    mode: str
    user_content: str
    final_text: str
    entry_ids: tuple[str, ...]
    tool_summaries: tuple[dict[str, Any], ...]

class NaturalTurnObserver(Protocol):
    def submit(self, turn: NaturalTurn) -> None: ...
```

`AgentLoop` 不导入持久包，只面向通用 Observer 协议。轮次中的工具摘要仅包含名称、状态、结果摘要和有界内容，不将无界工具输出再次塞入记忆请求。

## 指令加载设计

### `InstructionLoader`

```python
class InstructionLoader:
    def __init__(self, paths: DurablePaths) -> None: ...
    def load(self) -> InstructionBundle: ...
```

每个入口文件分别带有受信边界：

| 入口 | 受信边界 | 优先级 |
|---|---|---:|
| `<workspace>/.artcode/instructions.md` | Workspace 真实路径 | 210 |
| `<workspace>/ARTCODE.md` | Workspace 真实路径 | 220 |
| `~/.artcode/instructions.md` | `~/.artcode` 真实路径 | 230 |

`@include` 只识别独立行，语法为 `@include relative/path.md`。路径相对于声明该引用的文件目录，必须以 `.md` 结尾。读取前先用 `resolve(strict=True)` 解析符号链接，再检查解析结果是否在受信边界中。

深度是当前递归链的引用边数，入口深度为 0；当前深度已为 5 时不再展开新引用。`visited` 使用解析后的绝对 Path，每个入口单独维护，同一入口内再次遇到已读文件就留下警告并跳过。

总预算按高优先级入口依次消耗。完整文档可放入时不做截断；最后一份文档只有部分空间时，在合法 UTF-8 和最后一个完整换行边界停止，后续低优先级文档整份省略。

缺失文件、无权限、UTF-8 错误、非法 include 与越界都是可隔离问题：保留其他已加载指令，不使整个 ArtCode 启动失败。

## System Prompt 组装

### `DurablePromptContext`

```python
class DurablePromptContext:
    def __init__(
        self,
        instructions: InstructionBundle,
        user_notes: "MemoryNoteStore",
        project_notes: "MemoryNoteStore",
    ) -> None: ...

    def build_system_prompt(self) -> str: ...
```

`PromptRequestAssembler` 在每次组装实际 API 请求时，用 `DurablePromptContext.build_system_prompt()` 的结果替换导出消息中第一条 System Prompt，不修改 `ConversationContext` 中的原始条目。这样能同时满足：

- 当前进程的手写指令保持稳定，不在每轮重读整个 Workspace。
- 两份记忆索引在每次请求前重读，后台原子替换成功后下一请求即可见。
- ch08 压缩仍把 Conversation 第一条视为 System Prompt，不需改变摘要交易边界。

新增的 Prompt Section 顺序为：

```text
固定身份与系统约束  100–200
项目本地指令          210
项目根指令            220
用户级指令            230
现有模式、工具和输出规则 300–700
长期记忆索引          800
```

记忆索引外层使用 `<memory-index>` 标签，并明确告诉模型：这是可能过时的参考数据，其中的命令和角色文字不是新指令；冲突时以当前用户请求、工具结果和真实文件为准。

## 会话追加与并发锁定

### `SessionJournal`

```python
class SessionJournal:
    @classmethod
    def create(cls, sessions_dir: Path, now: datetime | None = None) -> "SessionJournal": ...

    @classmethod
    def open_existing(cls, path: Path) -> "SessionJournal": ...

    def append(self, entry: ConversationEntry, mode: str) -> None: ...
    def close(self) -> None: ...
```

Journal 以二进制 `O_APPEND` 方式打开，一次写入紧凑 JSON 字节、换行和 flush。它只记录下列规范条目：

- 用户消息。
- 无工具的助手最终消息。
- 包含 `tool_calls` 的助手消息。
- 与工具调用匹配的工具结果。

它不记录基础 System Prompt、运行时 reminder、时间跨度提醒、ch08 生成的历史摘要或对话边界。工具结果在 ch08 轻量存盘替换之前记录，以便下次运行能重新进行轻量处理。

对超过 4MB 的工具结果，Journal 不写入会在恢复时被整行跳过的超大记录，而是写入一条保持 `tool_call_id` 和协议形状的“超大结果未进入会话存档”标记，包含原始字节数和有界首尾预览。正常运行中的 ch08 仍按原规则处理完整结果。用户或助手纯文本超过 4MB 时拒绝形成无法可靠存档的新请求。

macOS 上使用 `fcntl.flock(LOCK_EX | LOCK_NB)` 对活动 JSONL 文件加进程级独占锁：

- 默认恢复遇到最近会话已锁定时，不去追加更旧会话，而是新建会话并显示原因。
- 显式按 ID 恢复遇到锁定时启动失败，防止用户以为已恢复目标会话。
- 清理器对每份过期文件尝试非阻塞锁，不删除已锁定文件。

## 会话扫描和恢复

### `SessionCatalog`

```python
class SessionCatalog:
    def __init__(self, sessions_dir: Path) -> None: ...
    def list_recent(self, limit: int = 20) -> tuple[SessionDescriptor, ...]: ...
    def latest_available(self) -> SessionDescriptor | None: ...
    def get(self, session_id: str) -> SessionDescriptor | None: ...
    def cleanup_expired(self, now: datetime) -> "CleanupReport": ...
```

Catalog 只承认符合会话 ID 正则的 `.jsonl` 普通文件，不跟随符号链接。最近排序使用扫描到的最后有效 UTC 时间，相同时间按 session ID 降序，不依赖文件系统不稳定的遍历顺序。

标题从第一条非空用户消息提取：所有空白折叠为单空格，再限制到 50 个 Unicode 字符并在超限时添加省略号。不额外调用 LLM 生成标题。

### `SessionRecovery`

```python
class SessionRecovery:
    def recover(self, descriptor: SessionDescriptor, now: datetime) -> SessionRecoveryReport: ...
    def restore_conversation(
        self,
        report: SessionRecoveryReport,
        system_prompt: str,
        journal: SessionJournal,
    ) -> ConversationContext: ...
```

恢复分两遍：

1. **物理行扫描**：有界读取到换行，校验 4MB、UTF-8、JSON 和 v1 Schema。最后一段没有换行时视为不完整尾行，文件截断到上一个完整换行；中间的完整坏行只记数并跳过。
2. **工具协议校验**：遇到带 `tool_calls` 的 assistant 记录时，要求后续紧邻的 tool 记录与所有 call ID 一一对应，无重复、无缺失、无多余。第一个不完整协议组或孤立 tool 记录将使 JSONL 截断到该组起始字节偏移。

物理截断发生在获得独占锁后，并在继续追加前 flush。这避免将新 JSON 接在半行或已废弃协议尾部之后。

`ConversationContext` 增加从已校验记录恢复的工厂方法，原样保留 `entry_id`，重建 `_next_id`、用户原文档案和可解析的 `raw_tool_result`。恢复过程不触发 Journal 回写，完成后才绑定新消息观察者。

Plan 恢复从最后一条 `mode=plan`、`role=assistant`、不带 `tool_calls` 且正文非空的记录中得到。

## 恢复后的 ch08 压缩和时间提醒

`CompressionTrigger` 增加 `RESTORE`，其摘要语义与手动/自动压缩相同，但状态文本明确表示这是会话恢复预处理。

Runtime 在 MCP 和 Tool Registry 完成后组装一份 Normal Mode 实际请求，使用 ch08 `TokenEstimator` 无锚点完整估算。达到自动线时只调用一次 `compact(..., RESTORE)`，成功后再进入用户输入循环；失败则保留原历史、记录 ch08 失败状态，不做无限启动重试。

时间跨度不写入 Conversation 或 Journal。`PromptRequestAssembler` 持有一个可消耗的 `ResumeReminder`，首次带模式的普通请求将其合并进现有 `<system-reminder>`，组装成功后标记已消耗。内部压缩和记忆请求不消耗该提醒。

## 会话选择和清理

CLI 增加两个互斥参数：

```text
artcode                         # 恢复最近未锁定可用会话，无则新建
artcode --new                   # 始终新建
artcode --resume <session-id>   # 精确恢复，不存在/已锁定则报错
```

Slash Command 增加：

- `/sessions`：显示当前会话和最近 20 个会话，不切换运行中的 Conversation。
- `/memory`：显示用户级、项目级笔记与索引路径、有效数量和最近后台更新状态，不在终端打印笔记全文。

运行中不切换会话，因为这要同时替换 Conversation、ContextSummarizer、Token 锚点、PlanMemory 和 Journal，且容易把当前工具状态带入另一会话。用户通过重启并使用 `--resume` 选择历史会话。

清理在选择默认会话前执行。年龄由最后有效记录的 UTC 时间计算；空文件使用文件修改时间作为兜底。只删除安全文件名、普通文件且获得非阻塞锁的候选。

## 笔记文件与索引

### Frontmatter

每条笔记使用下列格式：

```markdown
---
id: mem-20260806-163000-a1b2
scope: project
category: project_knowledge
status: active
title: 上下文压缩保留用户原文
summary: ch08 的摘要由程序重新注入用户原文，不依赖 LLM 转抄。
created_at: 2026-08-06T08:30:00Z
updated_at: 2026-08-06T08:30:00Z
source_session: 20260806-162500-c3d4
source_entry_ids:
  - msg-00000012
  - msg-00000013
---

# 上下文压缩保留用户原文

ch08 在摘要响应中使用占位符，最终由程序按原顺序注入用户消息。
```

ID 与会话 ID 使用相同时间和 4 hex 后缀策略，前缀为 `mem-`。Frontmatter 只接受已知字段和枚举值，时间统一为 UTC ISO 8601。文件名必须与 `id` 一致。

### `MemoryNoteStore`

```python
class MemoryNoteStore:
    def __init__(self, root: Path, scope: MemoryScope) -> None: ...
    def scan(self) -> "MemoryScanReport": ...
    def apply(self, operations: Sequence[MemoryOperation], now: datetime) -> MemoryUpdateReport: ...
    def rebuild_index(self) -> "MemoryIndexReport": ...
    def read_index(self) -> str: ...
```

Store 在每次启动时扫描笔记并重建索引，因此 `index.md` 是可丢弃的派生文件，不需要独立 meta 或数据库保持同步。单个坏笔记记入 issue 后跳过。

索引固定按下列顺序排序：

1. 用户偏好。
2. 纠正反馈。
3. 项目知识。
4. 参考资料。

同类内按 `updated_at` 降序、ID 升序。只索引 `active` 笔记，每条用一行展示 ID、标题、最多 120 字符摘要和相对路径。按稳定顺序添加，下一行会使任一预算超限时停止，并在预留的尾部状态行记录未索引数量。

更新时先将每份新笔记写入同目录临时文件，校验文件小于等于 8KB 后原子替换目标；所有有效操作完成后重建并原子替换索引。如果在两步之间崩溃，下次启动会从已提交笔记重建正确索引。

## LLM 记忆更新

### `MemoryPromptBuilder` 与 `MemoryUpdateParser`

```python
class MemoryPromptBuilder:
    def build(
        self,
        turn: NaturalTurn,
        user_index: str,
        project_index: str,
    ) -> list[dict[str, Any]]: ...

class MemoryUpdateParser:
    def parse(self, text: str, tool_calls: Sequence[ToolCall]) -> tuple[MemoryOperation, ...]: ...
```

内部 Prompt 要求模型只输出一个 `<memory-update>` 标签，标签内是包含 `operations` 数组的严格 JSON。输入包含：

- 本轮用户请求与最终助手回复。
- 本轮工具名、成功/失败状态、结果摘要和有界内容。
- 当前用户级和项目级索引。
- 作用域、四类笔记、去重、敏感信息禁止和最多 5 个操作的内部规则。

模型必须先对照索引：相同事实选择 `noop`，新证据补充现有事实选择 `update`，新纠正使旧事实失效时先 `supersede` 再必要时 `create`。每个操作必须带本轮来源 entry ID，不允许用空泛表述伪造长期事实。

Parser 按整体语法、标签唯一性、JSON Schema、操作数量、枚举、目标 ID、来源 ID、摘要长度和预渲染文件字节数逐层校验。用户级操作只接受 `category=preference`；其他类别即使模型返回 `scope=user` 也会被拒绝。

### `MemoryUpdater`

```python
class MemoryUpdater:
    async def update(self, turn: NaturalTurn) -> MemoryUpdateReport: ...
```

Updater 使用当前 `StreamingProvider`，请求参数为：

```python
ProviderRequestOptions(
    max_output_tokens=4_000,
    thinking_enabled=False,
)
```

`tools=None`，外层使用 30 秒 `asyncio.timeout`。已知配置密钥在进入 Prompt 前使用现有脱敏能力替换；工具结果只传入有界摘要，不传入 MCP Header 或配置原文。

### `MemoryUpdateWorker`

```python
class MemoryUpdateWorker(NaturalTurnObserver):
    def submit(self, turn: NaturalTurn) -> None: ...
    async def close(self) -> None: ...
    @property
    def last_report(self) -> MemoryUpdateReport | None: ...
```

Worker 使用一个后台 asyncio Task 和 FIFO Queue，始终一次只执行一个更新。`submit` 只入队，不等待 LLM；结果通过一个轻量回调交给 TUI，只显示新增、更新、作废、拒绝数量和失败原因摘要。

用户立即退出时，Runtime 取消未完成的后台请求并等待任务完成取消清理；会话 JSONL 已经在最终回复确定时写入，因此退出不会破坏对话恢复。本章不引入持久后台队列。

## Conversation 和 Agent Loop 接入

### `ConversationEntry` 元数据

`ConversationEntry` 增加不导出给模型的 `mode: str = "normal"`。`ConversationContext` 接受可选的 `entry_observer`，仅在规范消息首次追加时通知，不在轻量存盘替换、摘要替换或恢复回放时重复通知。

```python
class ConversationEntryObserver(Protocol):
    def on_entry(self, entry: ConversationEntry) -> None: ...

class ConversationContext:
    @classmethod
    def from_records(
        cls,
        system_prompt: str,
        records: Sequence[SessionRecord],
        observer: ConversationEntryObserver | None = None,
    ) -> "ConversationContext": ...

    def set_entry_observer(self, observer: ConversationEntryObserver | None) -> None: ...
```

Agent Loop 在调用 `append_user`、`append_assistant_tool_call`、`append_tool_result` 和 `append_assistant` 时传入当前 mode。如果 Journal 追加失败，Conversation 仍保留当前消息，但观察者记录持久失败，TUI 必须提示“当前轮可继续，但下次运行可能无法完整恢复”。不因存盘失败回滚已执行的工具。

Agent Loop 在自然结束分支中，先追加最终 assistant 消息、必要时保存 PlanMemory，再向 `NaturalTurnObserver` 提交本轮摄取数据，最后产生 STOPPED 事件。Observer 的 `submit` 必须是非阻塞同步入队。

## `PersistenceCoordinator`

```python
class PersistenceCoordinator:
    @classmethod
    def start(
        cls,
        app_paths: ArtCodePaths,
        workspace: Workspace,
        provider: StreamingProvider,
        selection: SessionSelection,
        now: datetime | None = None,
    ) -> "PersistenceCoordinator": ...

    @property
    def conversation(self) -> ConversationContext: ...
    @property
    def plan_memory(self) -> PlanMemory: ...
    @property
    def prompt_context(self) -> DurablePromptContext: ...
    @property
    def turn_observer(self) -> NaturalTurnObserver: ...

    async def prepare_restored_context(
        self,
        context_manager: ContextManager,
        assembler: PromptRequestAssembler,
        mode: AgentMode,
        tools: list[dict[str, Any]],
        tool_context: ToolExecutionContext,
    ) -> "RestorePreparationReport": ...

    async def close(self) -> None: ...
```

Coordinator 负责将纯文件模块串成生命周期，但不实现 JSONL 解析、指令展开或笔记校验算法。启动顺序固定为：

1. 创建受控目录并清理过期会话。
2. 加载指令，扫描笔记并重建索引。
3. 按 CLI 选择恢复或新建会话，取得独占锁。
4. 恢复 Conversation 和 PlanMemory，再绑定 Journal Observer。
5. 创建异步记忆 Worker 和持久 Prompt Context。

`run_app` 仍负责 Provider、MCP、工具、权限、Seatbelt 和 ContextManager 的组装。在这些组件就绪后，调用 Coordinator 的恢复预压缩，再创建 `ArtCodeRuntime`。

## 错误隔离和敏感路径

| 失败点 | 行为 |
|---|---|
| 某层指令不可读 | 跳过该来源，保留其他指令，启动面板显示 issue |
| include 越界/环路/超深 | 跳过该 include，不中断当前文件其他内容 |
| 默认最近会话已锁定 | 新建会话并报告，不追加更旧会话 |
| 显式恢复目标不存在/已锁 | 启动失败，不悄悄切换到其他会话 |
| JSONL 局部坏行 | 跳过并计数，保留其他有效行 |
| JSONL 尾行/工具链不完整 | 获锁后截断到安全偏移，再继续追加 |
| 恢复压缩失败 | 保留原历史和 ch08 失败状态，不启动循环重试 |
| Journal 追加失败 | 当前轮继续，显示持久性降级，不回滚已有动作 |
| 坏笔记 | 跳过该笔记，用其他有效笔记重建索引 |
| 记忆 LLM 错误/超时/坏输出 | 不提交该批无效变更，会话和下一轮不受影响 |
| 索引丢失/替换中断 | 下次扫描笔记原子重建 |

`run_app` 将下列路径追加到现有 `sensitive_paths`：三份指令入口、项目 sessions 目录、用户和项目 memory 目录。内部持久代码直接操作这些路径，普通文件工具和 Shell 权限不因本章扩大。

## 终端状态设计

`SafeConfigStatus` 增加不含敏感内容的持久状态：会话 ID、是否恢复、恢复消息数、坏行数、是否截断、指令总字节和 issue 数、用户/项目有效笔记数。启动 Panel 只显示这些摘要。

新增 `PERSISTENCE_STATUS` 事件用于运行期 Journal 失败和记忆更新结果。TUI 不打印完整指令、笔记正文、工具输出或 LLM 记忆 Prompt。

## macOS 独立分发约束

本章不变更 Python 技术栈，新实现只使用标准库 `asyncio`/`json`/`os`/`pathlib`/`fcntl`/`secrets`/`datetime` 与已有 PyYAML、Provider 抽象。不增加 SQLite 扩展、watcher、tokenizer 或后台 daemon。

持久路径全部从 `Path.home()`、CLI Workspace 和 `ArtCodePaths` 推导，不依赖 `__file__` 附近的源码目录。因此未来将 Python 运行时一起打包到 macOS 命令行产物时，本章数据目录与功能无需改写。代码签名、公证和 Universal Binary 留给专门分发章节。

## 文件组织

```text
artcode/
├── persistence/
│   ├── __init__.py       # 稳定公开导出
│   ├── models.py         # 指令、会话、笔记和报告模型
│   ├── paths.py          # DurablePaths 与安全目录创建
│   ├── instructions.py   # 三层指令、include 和预算
│   ├── sessions.py       # Journal、Catalog、Recovery、锁和清理
│   ├── notes.py          # frontmatter 笔记、原子写和索引
│   ├── updater.py        # 记忆 Prompt、Parser、Updater 与 Worker
│   └── coordinator.py    # 启动/恢复/关闭生命周期
├── conversation/context.py    # 恢复工厂、mode 元数据和条目观察者
├── prompting/
│   ├── sections.py        # 持久指令和记忆 Section
│   └── assembler.py       # 每请求替换实际 System Prompt、一次性提醒
├── context_management/
│   ├── models.py          # RESTORE 压缩触发
│   └── manager.py         # 恢复预压缩报告
├── agent/
│   ├── events.py          # NaturalTurn、持久状态事件
│   └── loop.py            # Journal mode 和自然结束 Observer 时机
├── commands/builtin.py         # /sessions、/memory
├── runtime/app.py              # 运行期状态和命令调度
├── tui/render.py               # 恢复与记忆状态展示
├── workspace.py                # 新持久路径属性
├── config.py                   # ch09 启动安全状态
└── cli.py                      # --new、--resume 与主流程组装

tests/
├── unit/
│   ├── test_persistence_paths.py
│   ├── test_instruction_loader.py
│   ├── test_session_journal.py
│   ├── test_session_recovery.py
│   ├── test_memory_notes.py
│   ├── test_memory_updater.py
│   ├── test_persistence_coordinator.py
│   └── test_persistence_prompt_integration.py
└── integration/
    ├── test_persistence_flow.py
    └── test_memory_deepseek_live.py
```

现有测试文件根据接口改动同步更新，不通过新建一套重复假实现来绕过原回归。

## 关键技术决策

| 决策点 | 选择 | 理由 |
|---|---|---|
| 用户/项目目录 | 统一 `.artcode` | 复用现有路径、敏感目录和打包语义，避免 `.mewcode` 平行世界 |
| 持久架构 | 一个 Coordinator + 三类独立 Store | 主流程只对接一个生命周期，文件算法仍可独立测试 |
| 会话格式 | 单会话 JSONL，无 meta | 追加快、局部坏行可跳过，不维护双份状态 |
| 会话恢复内容 | 原始规范消息 | ch08 摘要是运行时上下文优化，不应取代持久原始历史 |
| 工具中断 | 物理截断到第一个不完整组 | 保证未来追加仍是合法协议，不对未完成动作伪造结果 |
| 并发会话 | `flock` 锁定 JSONL | macOS 标准库可用，不需新 lock/meta 文件 |
| 恢复过大历史 | 复用 ch08 压缩一次 | 保持用户原文和工具边界，不引入第二套摘要器 |
| 指令动态性 | 启动加载 | 符合“新会话恢复”目标，避免文件 watcher 和每轮遍历 |
| 记忆新鲜度 | 每请求重读两份索引 | 索引体积有上限且原子替换，可低成本看到后台最新提交 |
| 记忆去重 | LLM 对照索引决策 | 符合用户要求，不引入向量或脆弱字符串相似度 |
| 旧记忆删除 | 标记 superseded | 自动 LLM 不做不可恢复的硬删除，同时保持活跃索引清洁 |
| 记忆更新时机 | 自然结束后非阻塞入队 | 不从半截回复学习，也不拖慢最终回复 |
| 异步并发 | 单 Worker 串行 | 避免两个 LLM 基于同一旧索引互相覆盖 |
| 记忆注入语义 | System Prompt 中的只读参考区 | 模型请求前已经“读过”，但不允许旧笔记取代当前事实 |
| macOS 分发 | 不增加原生依赖 | 保留 Python 源码可读性和未来自包含 CLI 打包可行性 |

## Spec 覆盖映射

| Spec | 设计归属 |
|---|---|
| F1–F5 | `InstructionLoader`、`DurablePromptContext`、Prompt Section 优先级 |
| F6–F10 | `SessionJournal`、`SessionCatalog`、CLI SessionSelection |
| F11–F13 | `SessionRecovery` 有界行扫描和物理截断 |
| F14–F17 | Conversation/Plan 恢复、RESTORE 压缩、ResumeReminder、Cleanup |
| F18–F19 | `MemoryNoteStore`、frontmatter 与 Scope Policy |
| F20–F22 | `NaturalTurnObserver`、`MemoryUpdater`、单 Worker |
| F23–F25 | 稳定索引构建、原子替换、每请求 Prompt 替换 |
| F26–F27 | SafeConfigStatus、TUI、`/sessions`、`/memory` |
| F28 | 观察者边界、复用 ch08、全量回归测试 |
| N1–N3 | Markdown/JSONL、原子文件、确定性排序 |
| N4–N6 | resolve 后边界、sensitive_paths、无工具更新和脱敏 |
| N7–N8 | 非阻塞单 Worker、只读记忆标签 |
| N9–N10 | 标准库优先、无源码目录假设 |
| N11 | 0700/0600 权限与 `flock` |
