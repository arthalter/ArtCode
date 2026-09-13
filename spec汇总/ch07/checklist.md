# ch07：MCP协议 Checklist

## 配置

- [x] 用户级与 `.artcode/config.yml` 项目级 MCP 配置可以合并，同名项目条目整项覆盖。
- [x] 项目级配置包含 `mcp_servers` 之外的顶层字段时被拒绝，用户主配置不受影响。
- [x] stdio 与 Streamable HTTP 字段严格校验，单个错误 Server 不影响其他 Server。
- [x] `${VAR}` 只在项目 Server 获批后展开，缺失变量只暴露变量名。
- [x] stdio 仅继承 PATH、HOME、USER、TMPDIR、LANG、LC_ALL、SHELL、SYSTEMROOT、WINDIR 及显式变量。

## 固定边界

- [x] 参数预览最多 2,000 字符，工具结果最多 20,000 字节。
- [x] 注册名最多 64 字符，超长名称使用 SHA-256 前 10 位稳定后缀。
- [x] Server 启动并发最多 5 个。
- [x] 传输、初始化和单页发现超时均为 10 秒，调用超时为 60 秒。
- [x] 单 Server 最多发现 100 页、100 个工具，并检测重复 Cursor。
- [x] stderr 保留最近 100 行、总计 64 KiB、每行 2 KiB，外部错误展示最多 500 字符。
- [x] 退出时先等待调用取消 3 秒，每个 Server 关闭最多等待 5 秒。
- [x] HTTP 最多跟随 10 次重定向，跨域后仍转发配置的全部 Headers。

## 工具与审批

- [x] 合法工具以 `mcp__<server>__<tool>` 注册，冲突或无效 Schema 只跳过对应工具。
- [x] Normal、Do 暴露全部工具；Plan 暴露三个内置只读工具和全部 MCP 工具。
- [x] 每次 MCP 调用均二选一确认，不读取或写入长期权限规则。
- [x] 获批 MCP 调用并发执行，结果按模型原始顺序回灌。
- [x] 文本与结构化结果进入模型；图片、音频和资源只进入安全元数据。

## 生命周期与验收

- [x] 单 Server 启动、发现、调用、取消或关闭失败不影响其他 Server 与内置工具。
- [x] 传输断开、协议损坏或调用超时后 Server 快速标记不可用且不自动重连。
- [x] 退出后无 ArtCode 启动的遗留 stdio 子进程，HTTP 会话全部关闭。
- [x] 启动界面显示配置数、成功数、失败数、工具数及逐 Server 脱敏状态。
- [x] 真实 stdio 和 Streamable HTTP Server 均完成初始化、发现和调用。
- [x] 端到端验证证明 Agent 发现 MCP 工具、请求确认、执行并在下一模型轮次收到结果。
- [x] 一个 MCP Server 运行中断开时，另一个 MCP Server 和内置工具仍可调用。
- [x] 全部单元测试、集成测试和真实 DeepSeek API 测试通过。
