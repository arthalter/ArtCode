# ArtCode

ArtCode is a local Python CLI coding agent learning project.

## ch03: 工具系统

This chapter adds the first local tool system to ArtCode.

ArtCode can expose six local tools to the model: read files, write files, edit files by exact unique replacement, run shell commands, find files by glob, and search text. All tools are restricted to configured allowed directories. By default, the allowed directory is `/Users/arthalter/Work/ArtCode/实验场`.

Write, edit, and command tools require user confirmation before execution. Tool results are returned to the model as structured messages, then ArtCode asks the model for a final natural-language summary without allowing another tool call in the same turn.

Live DeepSeek integration tests read `artcode.yaml` from the project root, call the real DeepSeek API, require network access, and consume DeepSeek API quota. A deterministic ch03 tool-flow integration test uses a fake provider and only writes inside a temporary allowed directory.
