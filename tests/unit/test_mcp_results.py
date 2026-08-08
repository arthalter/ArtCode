from types import SimpleNamespace

from artcode.mcp.results import convert_call_result


def test_mixed_result_uses_text_and_safe_metadata() -> None:
    result = SimpleNamespace(
        isError=False,
        content=[
            SimpleNamespace(type="text", text="hello"),
            SimpleNamespace(type="image", mimeType="image/png", data="SECRET-BINARY"),
        ],
        structuredContent={"answer": 42},
    )
    converted = convert_call_result("tool", result)
    assert converted.ok
    assert "hello" in converted.content
    assert "image/png" in converted.content
    assert "SECRET-BINARY" not in converted.content
    assert '"answer": 42' in converted.content
