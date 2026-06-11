# ArtCode 项目指令

请始终使用简体中文回复用户的所有问题。所有沟通、解释、代码注释都使用中文。

## 项目概述

ArtCode (v0.2.0) 是一个使用 Python 开发的本地 CLI Coding Agent 学习项目。当前处于 ch02 阶段——"让AI说话"，目标是打通 Coding Agent 最基础的能力：用户能在终端里和 AI 进行连续、流式、多轮对话。

- **语言**：Python >= 3.11
- **协议**：OpenAI-compatible（当前使用 DeepSeek API）
- **构建**：pyproject.toml + setuptools
- **依赖**：PyYAML、httpx、prompt_toolkit、rich（不依赖 OpenAI SDK、LangChain、Pydantic）

## 代码修改协作规则

- 修改代码前，必须先说明计划，列出 `1、2、3、4` 步骤，待用户批准后才能改动。
- 用户明确要求改动时，不要保守，应大胆完整地推进实现。
- 尽量为每个任务补充单元测试；无法补充时执行对应验证并说明原因。
- 任务完成后，如果用户要求 push，提交备注需包含：完成时间、任务序号、任务功能。

## 架构分层

ArtCode 采用严格分层架构，共 7 层，依赖方向自上而下：

```
cli.py（入口：组装各层 + asyncio.run）
  └── runtime/app.py（主循环：输入→命令判断→Provider→渲染→写入上下文）
       ├── config.py（YAML 加载 → 手写校验 → frozen dataclass → 脱敏展示）
       ├── providers/（StreamingProvider 协议 → OpenAI-compatible 实现 → SSE 解析 → 事件映射）
       ├── conversation/（ConversationContext：内存级消息管理，deepcopy 导出，无持久化）
       ├── commands/（CommandRegistry：精确匹配 / 命令，多行不触发）
       ├── tui/（prompt_toolkit 异步输入 + rich 流式渲染）
       └── errors.py（ArtCodeError → ConfigError | RequestError 及 6 个子类）
```

核心设计原则：
- **接口用 Protocol**，不用 ABC
- **配置用 frozen dataclass**，不可变
- **Provider 层不依赖 TUI**，TUI 层不感知模型细节
- **错误分层**：ConfigError（致命退出） vs RequestError（显示后继续运行）
- **deepcopy 导出**：不暴露内部可变状态引用

## 关键约定

- 消息格式统一用 `dict[str, str]`（`{"role": "...", "content": "..."}`），不用强类型 Message 子类
- 流式事件只分两类：`content_delta`（携带 text）和 `done`（无额外字段），错误通过异常抛出
- 取消的回复（CancelledError）返回 `None`，不写入 ConversationContext
- Thinking/reasoning 内容在 Provider 层丢弃，不展示、不记录
- 所有错误提示用中文，带排查建议（hint），不泄露完整 API key
- 配置文件 `artcode.yaml` 已 .gitignore，模板文件为 `artcode.example.yaml`

## 常用命令

```bash
# 开发调试启动
python -m artcode

# 安装后启动
pip install -e .
artcode

# 运行单元测试（不需要 API key）
pytest tests/unit/

# 运行集成测试（需要 artcode.yaml + 网络，会消耗 API 额度）
pytest tests/integration/
```

## 文件结构

```
artcode/
├── __init__.py          # __version__ = "0.2.0"
├── __main__.py          # python -m artcode 入口
├── cli.py               # 主入口：依赖注入 + asyncio.run
├── config.py            # 配置加载/校验/脱敏
├── errors.py            # 统一错误体系
├── prompts.py           # system prompt
├── commands/
│   ├── base.py          # CommandRegistry + CommandResult
│   └── builtin.py       # /exit, /quit, /help
├── conversation/
│   └── context.py       # ConversationContext
├── providers/
│   ├── base.py          # StreamingProvider 协议
│   ├── events.py        # 事件类型 + 工厂函数
│   ├── sse.py           # SSEDecoder
│   └── openai_compatible.py  # 核心：HTTP 流式 + 错误映射
├── runtime/
│   └── app.py           # ArtCodeRuntime 主循环 + 取消处理
└── tui/
    ├── app.py           # PromptToolkitTui
    ├── keybindings.py   # Enter 发送，Ctrl+J/Esc+Enter 换行
    └── render.py        # TuiRenderer（rich）
tests/
├── unit/                # 8 个单元测试文件（无外部依赖）
└── integration/         # DeepSeek 真实 API 测试
docs/                    # 知识汇总文档
├── 01-python知识汇总.md
├── 02-LangChain框架知识对标.md
├── 03-Agent知识汇总.md
└── 04-项目架构汇总.md
```

## 后续章节扩展点

为 tool use、文件编辑、权限控制预留的接口：
- `CommandRegistry.register()` — 添加新命令
- `StreamingProvider` 协议 — 添加新 Provider
- `ConversationContext` — 添加裁剪/持久化/加载
- `providers/events.py` — 添加 `tool_call` / `tool_result` 事件
- `ArtCodeRuntime` — 添加 tool call 循环
- `TuiRenderer` — 添加 Markdown 渲染/语法高亮
