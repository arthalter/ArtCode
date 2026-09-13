# Issue tracker: GitHub

Issues、Spec、Wayfinder 地图和工作票据保存在本仓库的 GitHub Issues 中。在仓库目录内使用 `gh` CLI，由 Git remote 自动确定仓库。

## 常用操作

- 创建 Issue：`gh issue create --title "..." --body "..."`
- 读取 Issue 及评论：`gh issue view <number> --comments`
- 列出 Issue：`gh issue list --state open --json number,title,body,labels,comments`
- 评论：`gh issue comment <number> --body "..."`
- 添加或删除标签：`gh issue edit <number> --add-label "..."` / `--remove-label "..."`
- 关闭：`gh issue close <number> --comment "..."`

## Pull Request 入口

PR 不作为需求或 triage 入口。

## Skill 发布语义

- Skill 要求“发布到 issue tracker”时，创建 GitHub Issue。
- Skill 要求“读取相关票据”时，读取对应 Issue 正文、评论和标签。

## Wayfinding operations

- **Map**：一个标记为 `wayfinder:map` 的 Issue，保存 Destination、Notes、Decisions so far、Not yet specified 和 Out of scope。
- **Child ticket**：优先使用 GitHub sub-issue 关系；不可用时，在地图任务列表和票据正文中双向引用。票据标签使用 `wayfinder:research`、`wayfinder:prototype`、`wayfinder:grilling` 或 `wayfinder:task`。
- **Blocking**：优先使用 GitHub 原生 issue dependencies；不可用时，在票据顶部写 `Blocked by: #<number>`。
- **Frontier**：地图中尚未关闭、所有 blocker 已关闭且无 assignee 的子票据。
- **Claim**：开始处理前先执行 `gh issue edit <number> --add-assignee @me`。
- **Resolve**：发布决策评论，关闭票据，再向地图 `Decisions so far` 追加一行摘要和链接。

GitHub 支持原生依赖时，blocker 参数使用 Issue 的数字 database ID，不使用 `#number` 或 GraphQL node ID。
