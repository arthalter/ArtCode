# ArtCode

ArtCode 是一个本地 Python CLI Coding Agent 学习项目。

## ch05: System Prompt 设计

本章在 ch04 Agent Loop 的基础上，把 ArtCode 的全局指令升级为结构化 System Prompt 工程体系。

稳定 System Prompt 被拆成七个固定模块：身份、系统约束、任务模式、动作执行、工具使用、语气风格、文本输出。模块按固定优先级拼装，便于后续接入项目指令、Skill 和长期记忆，同时保护 Prompt Cache 的稳定前缀。

动态运行信息不再拼入稳定 System Prompt。ArtCode 会在每轮模型请求前临时注入 `<system-reminder>`，包含当前模式、工具边界、当前工作目录、允许访问目录和平台信息；这条提醒只参与本次 API 请求，不写入 Conversation Context。

ArtCode 继续暴露六个本地工具：读取文件、写入文件、按唯一精确文本替换编辑文件、执行 shell 命令、按 glob 模式查找文件，以及搜索文本。ch05 强化了这些工具的 description，让模型更稳定地遵守专用工具优先、编辑前先读、Plan Mode 只读等约定。

真实 DeepSeek / OpenAI-compatible 集成测试会读取项目根目录下的 `artcode.yaml`。ch05 要求真实 Prompt Cache 验证必须观察到缓存命中 token 大于 0，才能算完整验收通过。确定性的 fake provider 集成测试只会写入临时允许目录。
