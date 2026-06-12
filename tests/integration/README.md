# DeepSeek live integration tests

These tests read `artcode.yaml` from the project root and call the real DeepSeek API.

They require network access and depend on DeepSeek service availability.

When local configuration is available, real DeepSeek API tests are expected to run by default.

ch05 includes a hard Prompt Cache live check. The cache test must use a real API configuration, parse real usage fields, and observe cache hit tokens greater than 0 for ch05 validation to be complete. Missing API configuration, authentication failure, network failure, or cache hit 0 means ch05 validation is not complete.

Deterministic Agent Loop integration tests use a fake provider. They exercise multi-turn tool use, Plan Mode, `/do`, multi-tool batching, unknown-tool stopping, system-reminder injection, and final summaries. These tests do not call DeepSeek and only write inside temporary allowed directories.
