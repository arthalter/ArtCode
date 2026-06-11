# ArtCode

ArtCode 是一个本地 Python CLI Coding Agent 学习项目。

## ch04: 动手实现 Agent Loop

本章把 ArtCode 从 ch03 的单步工具调用流程，升级为 ReAct 风格的 Agent Loop。

普通用户输入默认进入 Agent Loop。模型可以根据任务需要请求工具、观察结构化结果，并继续下一轮推理和行动；循环最多执行 12 轮，超过后 ArtCode 会停止并生成总结。模型在同一轮中可以请求多个工具；相邻的只读工具会并发执行，写文件、改文件和执行命令这类有副作用工具会串行执行。

ArtCode 继续暴露 ch03 中已有的六个本地工具：读取文件、写入文件、按唯一精确文本替换编辑文件、执行 shell 命令、按 glob 模式查找文件，以及搜索文本。所有工具仍然受到允许目录限制；默认允许目录是 `/Users/arthalter/Work/ArtCode/实验场`。

Plan Mode 可以通过 `/plan 任务描述` 进入。该模式只暴露只读工具，用于先理解项目并生成计划。`/do` 会使用完整工具集执行最近一次保存在内存中的计划；`/do 附加说明` 可以在执行计划时追加额外约束。

真实 DeepSeek 集成测试会读取项目根目录下的 `artcode.yaml`，调用真实 DeepSeek API；只要本地配置可用，就应当执行这些测试。确定性的 fake provider 集成测试只会写入临时允许目录。
