from artcode.context_management import TokenEstimator, estimate_text_tokens


def test_text_estimator_counts_chinese_and_other_separately() -> None:
    assert estimate_text_tokens("中文") == 2
    assert estimate_text_tokens("abcdef") == 2
    assert estimate_text_tokens("中abcd") == 3


def test_request_estimate_is_stable_and_includes_tools() -> None:
    estimator = TokenEstimator()
    messages = [{"role": "user", "content": "hello"}]
    tools = [{"type": "function", "function": {"name": "read_file"}}]

    first = estimator.estimate_request(messages, tools)

    assert first == estimator.estimate_request(messages, tools)
    assert first > estimator.estimate_request(messages, None)


def test_usage_anchor_applies_only_character_delta() -> None:
    estimator = TokenEstimator()
    before = [{"role": "user", "content": "abc"}]
    after = [{"role": "user", "content": "abc"}, {"role": "assistant", "content": "abcdef"}]
    estimator.record_usage(100, before, None)

    expected_delta = (
        estimator.heuristic_request_tokens(after, None)
        - estimator.heuristic_request_tokens(before, None)
    )
    assert estimator.estimate_request(after, None) == 100 + expected_delta


def test_anchor_estimate_never_becomes_negative() -> None:
    estimator = TokenEstimator()
    estimator.record_usage(1, [{"role": "user", "content": "x" * 1000}], None)

    assert estimator.estimate_request([], None) == 0
