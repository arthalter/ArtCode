# DeepSeek live integration tests

These tests read `artcode.yaml` from the project root and call the real DeepSeek API.

They require network access, depend on DeepSeek service availability, and consume DeepSeek API quota. If `artcode.yaml` is missing or still contains the placeholder API key, the tests are skipped.

ch03 also includes a deterministic tool-flow integration test that uses a fake provider. It exercises the full Runtime path for `write_file`: model tool request, user confirmation, file write inside a temporary allowed directory, tool-result回灌, and final summary. That test does not call DeepSeek and does not touch the real `实验场` directory.
