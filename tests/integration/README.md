# DeepSeek live integration tests

These tests read `artcode.yaml` from the project root and call the real DeepSeek API.

They require network access, depend on DeepSeek service availability, and consume DeepSeek API quota. If `artcode.yaml` is missing or still contains the placeholder API key, the tests are skipped.
