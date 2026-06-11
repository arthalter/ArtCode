from __future__ import annotations

import json

from artcode.tools.results import denied_result, error_result, success_result, truncate_text


def test_success_result_serializes_for_model() -> None:
    result = success_result("read_file", "读取成功。", "你好")

    payload = json.loads(result.to_model_content())
    assert payload["tool_name"] == "read_file"
    assert payload["ok"] is True
    assert payload["status"] == "success"
    assert payload["content"] == "你好"


def test_error_result_contains_error_code() -> None:
    result = error_result("read_file", "file_not_found", "文件不存在。")

    payload = json.loads(result.to_model_content())
    assert payload["ok"] is False
    assert payload["status"] == "error"
    assert payload["error_code"] == "file_not_found"


def test_denied_result_marks_user_denied() -> None:
    result = denied_result("write_file")

    assert result.status == "denied"
    assert result.error_code == "user_denied"


def test_truncate_text_keeps_valid_unicode() -> None:
    text = "你" * 10

    truncated, did_truncate, bytes_returned = truncate_text(text, 5)

    assert truncated == "你"
    assert did_truncate is True
    assert bytes_returned == len("你".encode("utf-8"))


def test_success_result_marks_truncated_content() -> None:
    result = success_result("read_file", "读取成功。", "abcdef", max_bytes=3)

    assert result.content == "abc"
    assert result.truncated is True
    assert result.bytes_returned == 3
