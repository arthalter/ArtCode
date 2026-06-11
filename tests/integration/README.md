# DeepSeek live integration tests

These tests read `artcode.yaml` from the project root and call the real DeepSeek API.

They require network access and depend on DeepSeek service availability. If `artcode.yaml` is missing or still contains the placeholder API key, the tests are skipped.

When local configuration is available, real DeepSeek API tests are expected to run by default.

ch04 also includes deterministic Agent Loop integration tests that use a fake provider. They exercise multi-turn tool use, Plan Mode, `/do`, multi-tool batching, unknown-tool stopping, and final summaries. These tests do not call DeepSeek and only write inside temporary allowed directories.
