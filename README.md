# ArtCode

ArtCode is a local Python CLI coding agent learning project.

## ch04: 动手实现 Agent Loop

This chapter turns ArtCode's single-step tool flow into a ReAct-style Agent Loop.

普通用户输入 now enters an Agent Loop by default. The model can request tools, observe structured results, and continue for up to 12 iterations before ArtCode stops with a summary. A single model turn may request multiple tools; adjacent read-only tools run concurrently, while write/edit/command tools run serially.

ArtCode still exposes the six local tools from ch03: read files, write files, edit files by exact unique replacement, run shell commands, find files by glob, and search text. All tools remain restricted to configured allowed directories. By default, the allowed directory is `/Users/arthalter/Work/ArtCode/实验场`.

Plan Mode is available through `/plan 任务描述`, which only exposes read-only tools. `/do` executes the latest in-memory plan with the full tool set, and `/do 附加说明` adds extra execution constraints.

Live DeepSeek integration tests read `artcode.yaml` from the project root, call the real DeepSeek API, and are expected to run when local configuration is available. Deterministic fake-provider integration tests only write inside temporary allowed directories.
