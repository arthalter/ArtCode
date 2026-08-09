# DeepSeek live integration tests

These tests read `artcode.yaml` from the project root and call the real DeepSeek API.

They require network access and depend on DeepSeek service availability.

When local configuration is available, real DeepSeek API tests are expected to run by default.

ch06 keeps the hard Prompt Cache live check and additionally runs real macOS Seatbelt tests. The cache test must observe cache hit tokens greater than 0. Seatbelt tests cover Workspace writes, external and sensitive-path denial, child-process inheritance, and loopback-network denial.

Deterministic Agent Loop integration tests use a fake provider. They exercise multi-turn tool use, Plan Mode, `/do`, multi-tool batching, unknown-tool stopping, system-reminder injection, and final summaries. These tests do not call DeepSeek and only write inside temporary Workspaces.

ch08 adds a deterministic end-to-end context-management flow covering large tool-result persistence, automatic nine-section summarization, continuation requests, bounded artifact rereads, usage anchoring, and session cleanup. Its live DeepSeek test performs a real tool-free summary, verifies that analysis is discarded and verbatim user text survives, then continues the conversation from the compressed history.

ch09 adds a deterministic two-process persistence flow covering JSONL tool protocol storage, exact resume, layered instructions, asynchronous memory extraction, atomic index publication, and injection on the next process request. Its live DeepSeek test records an explicit cross-project preference twice and verifies that the second update does not create a duplicate active note.

## ch10.5 test categories

The summary refactor keeps deterministic, property/fault, real integration, and soak evidence separate:

- `pytest -m "not live and not slow"` runs the normal local regression set.
- `pytest tests/property tests/fault -m ch10_5` runs randomized invariants and deterministic failure injection.
- `pytest tests/live -m live -rs` runs real DeepSeek, macOS Seatbelt, process-tree, MCP, and multi-process Session checks.
- `pytest tests/soak -m soak` runs repeated lifecycle and resource-stability checks.
- `python tests/tools/verify_test_inventory.py --baseline 413` reports independently collected node IDs without counting the original baseline as new work.

Real tests are never skipped merely to avoid DeepSeek usage. A missing macOS Seatbelt binary, missing valid local configuration, or unavailable external service must be reported as an environment block or real failure; it is not a pass. Test output and saved evidence must redact API keys, authorization headers, cookies, and full configuration bodies.
