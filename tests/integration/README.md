# DeepSeek live integration tests

These tests read `artcode.yaml` from the project root and call the real DeepSeek API.

They require network access and depend on DeepSeek service availability.

When local configuration is available, real DeepSeek API tests are expected to run by default.

ch06 keeps the hard Prompt Cache live check and additionally runs real macOS Seatbelt tests. The cache test must observe cache hit tokens greater than 0. Seatbelt tests cover Workspace writes, external and sensitive-path denial, child-process inheritance, and loopback-network denial.

Deterministic Agent Loop integration tests use a fake provider. They exercise multi-turn tool use, Plan Mode, `/do`, multi-tool batching, unknown-tool stopping, system-reminder injection, and final summaries. These tests do not call DeepSeek and only write inside temporary Workspaces.
