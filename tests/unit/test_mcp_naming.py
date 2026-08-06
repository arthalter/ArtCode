from artcode.mcp.naming import registered_tool_name


def test_name_is_normalized_and_bounded() -> None:
    assert registered_tool_name("my server", "a/b.c") == "mcp__my_server__a_b_c"
    first = registered_tool_name("s" * 80, "t" * 80)
    assert len(first) == 64
    assert first == registered_tool_name("s" * 80, "t" * 80)
