from artcode.mcp.redaction import safe_json_preview, sanitize_external_text


def test_nested_secrets_are_redacted_and_preview_is_bounded() -> None:
    preview = safe_json_preview({"nested": {"api_key": "secret"}, "text": "x" * 3000})
    assert "secret" not in preview
    assert len(preview) == 2000


def test_external_text_is_single_line_and_secret_safe() -> None:
    assert sanitize_external_text("bad\nTOKEN", ("TOKEN",)) == "bad ***"
