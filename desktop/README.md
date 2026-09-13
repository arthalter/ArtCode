# ArtCode Desktop

本机单用户桌面入口。React 界面通过 Electron 与现有 Python Application 通信，日常使用直接打开打包后的 ArtCode.app。

## 使用

1. 打开应用，选择已有项目文件夹。
2. 默认读取 `~/.artcode/config.yml`；也可展开「模型配置与会话」选择现有 YAML 配置。配置格式与原 CLI 相同。
3. 点击「打开项目」，默认恢复最近会话。输入任务后点击发送或按 Command+Enter。
4. 工具或 MCP 需要授权时，在对话中作出决定。执行中可取消；退出应用会清理后台任务，保留已提交历史和文件成果。

同一会话不能同时由 CLI 与桌面打开；继续使用原 Session 独占锁。

`/skills`、`/tasks`、`/sandbox` 等命令会在对话区直接显示结果；没有条目时也会明确提示。它们是本地命令，不需要等待模型回复。原始详情仍可在右侧活动栏展开。命令展示记录不写入模型的持久对话历史。

## 开发与打包

在仓库根目录已有 `.venv` 并安装项目依赖后：

```sh
cd desktop
npm ci
npm start
```

默认使用仓库 `.venv/bin/python`；可用 `ARTCODE_PYTHON` 指定解释器。只改页面时可用 `npm run dev` 预览；普通浏览器不连接后端。

打包本机 macOS 应用：

```sh
../.venv/bin/python -m pip install 'pyinstaller>=6,<7'
npm run package
```

输出位于 `release/mac-arm64/ArtCode.app`（Intel Mac 为 `release/mac/`）。这是本地未公证应用，不附带用户配置、密钥、项目内容。

## 修改位置

| 需求 | 文件 |
| --- | --- |
| 布局和组件 | `src/main.tsx` |
| 配色、间距、字体 | `src/style.module.css` 的 CSS 变量与组件样式 |
| 展示状态与事件处理 | `src/store.ts` |
| 通信类型 | `src/api.ts` |
| 窗口、文件选择、进程管理 | `electron/main.cjs`、`electron/preload.cjs` |
| Python 接入 | `../artcode/desktop_server.py` |

## 首版协议与限制

使用 JSON-RPC 2.0 单行 JSON，协议名为 `artcode-desktop/0.1`，不是 ch15 草案 v1 的完整实现。方法为 initialize、open、input、answer、snapshot、cancel、background、close。open/input 返回接受结果，后续通过 event 通知输出和忙碌状态；不自动重试修改请求。关闭重连只恢复持久会话，不恢复后台进程。

审批事件含 `prompt_kind`，审批查询项含 `kind`。metadata 与 pending_notices 在展示投影中剔除。现有核心负责权限、沙箱、任务与会话语义；桥接层不重写这些规则。

文字回复实时显示；工具结果在现有批次完成后显示。右侧保留最近 100 条活动，后台任务通过只读快照更新。首版无完整 Shell 实时日志、逐工具开始事件、执行树重放、Markdown 富渲染和文件编辑器。所有现有命令仍可从输入框使用。
