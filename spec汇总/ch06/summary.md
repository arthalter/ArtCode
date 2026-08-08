# ch06：权限系统总结

## 本章完成内容

ch06 将 ArtCode 从多允许目录模型升级为以单一 Workspace 为核心的纵深权限系统。工具调用不再只依赖提示词和简单确认，而是在产生副作用前依次经过硬安全边界、三层权限规则、权限模式、HITL 和 Seatbelt。

主要能力包括：

- 区分 `~/.artcode/` 应用数据与当前 Workspace。
- 主配置固定为 `~/.artcode/config.yml`。
- 文件工具只能访问 Workspace，阻止 `..`、相似路径前缀和符号链接逃逸。
- 主配置、三层权限文件、Skills、安全规则和 Seatbelt Profile 被列为敏感资源。
- Plan 保持独立硬只读状态。
- 提供 Default、Edit、Full 三种文件权限模式。
- 提供 Sandbox Auto、Sandbox Ask、Sandbox Off 三种 Shell 策略。
- 加载用户级、项目级、本地级三层 YAML 权限规则。
- 支持 ALLOW、ASK、DENY、同层最后匹配和跨层 DENY 优先。
- HITL 支持仅本次允许、仅本次禁止、以后允许、以后禁止。
- 长期决定以精确规则原子写入本地权限文件。
- 内置危险命令规则不可被模式、规则或 HITL 绕过。
- Shell 固定使用 `/bin/zsh -f -c`、安全环境变量和进程组超时。
- macOS Seatbelt 限制文件写入和全部网络访问，子进程继承限制。
- `/permission` 与 `/sandbox` 支持运行期查询和切换。
- 启动面板和动态提醒展示 Workspace 与权限状态。

## 权限判断顺序

```text
模型 ToolCall
  → 参数解析与工具预检
  → Plan 硬限制
  → 危险命令检查
  → Workspace 与敏感路径检查
  → 三层权限规则
  → 权限模式或 Shell 策略兜底
  → 必要时进入 HITL
  → 文件工具或受控 Shell 执行
  → 结构化 ToolResult 回灌模型
```

任何关键状态无法确定时均失败关闭，不自动退回更宽松的执行方式。

## 重要问题修复

开发后期发现，Agent Loop 在 assistant tool_calls 写入上下文后，如果 HITL 或工具执行被取消，可能缺少对应的 tool result，导致 DeepSeek 返回：

```text
An assistant message with 'tool_calls' must be followed by tool messages
responding to each 'tool_call_id'.
```

修复后：

- 取消时会为所有未完成工具补写结构化取消结果。
- Conversation Context 会检测未配对的 tool_calls。
- 缺失结果插入原 assistant tool_calls 后、后续用户消息前。
- 每轮模型请求前执行历史完整性检查。
- 多工具部分完成后取消，下一轮仍可正常请求 DeepSeek。

## 验收结果

- Checklist：254/254 已勾选。
- 完整测试：223 passed。
- 真实 DeepSeek 对话和工具调用：通过。
- 真实 Prompt Cache：通过。
- 真实 DeepSeek“读取—申请编辑—验证—总结”闭环：通过。
- 真实 macOS Seatbelt 文件和网络边界：通过。
- Seatbelt Profile 删除、损坏、无降级和重新初始化：通过。
- Shell 秘密环境隔离和超时进程组终止：通过。
- CLI 冷启动、wheel 安装和内置资源定位：通过。
- `compileall` 与 `git diff --check`：通过。

## 文档说明

- `spec.md`：需求范围、系统边界和完成标准。
- `plan.md`：架构、数据结构、模块交互和技术决策。
- `tasks.md`：T1-T14 的实现顺序和验证方式。
- `checklist.md`：254 项可观测验收记录。
- `summary.md`：本章实现与验收总结。
