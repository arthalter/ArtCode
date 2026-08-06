from __future__ import annotations

import json

from artcode.tools.results import denied_result, error_result, success_result


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


def test_success_result_keeps_complete_unicode_content() -> None:
    content = "你" * 10 + "UNIQUE_TAIL"
    result = success_result("read_file", "读取成功。", content)

    assert result.content == content
    assert result.bytes_returned == len(content.encode("utf-8"))
    assert "truncated" not in json.loads(result.to_model_content())
