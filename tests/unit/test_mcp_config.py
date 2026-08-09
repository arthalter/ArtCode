from pathlib import Path
from types import MappingProxyType

import pytest

from artcode.mcp.config import expand_config, load_mcp_configuration, safe_stdio_environment
from artcode.mcp.models import ServerSource, TransportKind


def test_immutable_runtime_mcp_mapping_is_accepted(tmp_path: Path) -> None:
    configs, issues = load_mcp_configuration(
        {"mcp_servers": MappingProxyType({})},
        tmp_path,
    )

    assert configs == ()
    assert issues == ()


def test_project_replaces_user_server_as_whole(tmp_path: Path) -> None:
    project_dir = tmp_path / ".artcode"
    project_dir.mkdir()
    (project_dir / "config.yml").write_text(
        "mcp_servers:\n  same:\n    transport: streamable_http\n    url: http://localhost/mcp\n",
        encoding="utf-8",
    )
    configs, issues = load_mcp_configuration(
        {"mcp_servers": {"same": {"transport": "stdio", "command": "python"}}},
        tmp_path,
    )
    assert not issues
    assert configs[0].source is ServerSource.PROJECT
    assert configs[0].transport is TransportKind.STREAMABLE_HTTP
    assert configs[0].command is None


def test_invalid_server_is_isolated(tmp_path: Path) -> None:
    configs, issues = load_mcp_configuration(
        {
            "mcp_servers": {
                "bad": {"transport": "stdio", "command": "x", "url": "http://bad"},
                "good": {"transport": "stdio", "command": "python"},
            }
        },
        tmp_path,
    )
    assert [item.name for item in configs] == ["good"]
    assert issues[0].server_name == "bad"


def test_expansion_reports_only_missing_name(tmp_path: Path) -> None:
    configs, _ = load_mcp_configuration(
        {"mcp_servers": {"one": {"transport": "stdio", "command": "x", "env": {"TOKEN": "${MISSING}"}}}},
        tmp_path,
    )
    with pytest.raises(ValueError, match="MISSING"):
        expand_config(configs[0], {})


def test_safe_environment_does_not_inherit_arbitrary_secret() -> None:
    result = safe_stdio_environment({"EXPLICIT": "ok"}, {"PATH": "/bin", "HOST_SECRET": "no"})
    assert result == {"PATH": "/bin", "EXPLICIT": "ok"}


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ("[broken", "无法读取"),
        ("- item\n", "顶层必须"),
        ("other: true\n", "只允许"),
    ],
    ids=("yaml", "top-level", "extra-key"),
)
def test_invalid_project_config_is_reported(tmp_path: Path, content: str, message: str) -> None:
    directory = tmp_path / ".artcode"
    directory.mkdir()
    (directory / "config.yml").write_text(content, encoding="utf-8")
    configs, issues = load_mcp_configuration({}, tmp_path)
    assert configs == ()
    assert message in issues[0].message


@pytest.mark.parametrize(
    ("servers", "message"),
    [
        (None, None),
        ([], "mcp_servers"),
        ({1: {}}, "Server 名"),
        ({"server": None}, "配置必须"),
        ({"server": {"transport": "bad"}}, "transport"),
        ({"server": {"transport": "stdio", "command": "x", "enabled": "yes"}}, "enabled"),
        ({"server": {"transport": "stdio", "command": ""}}, "command"),
        ({"server": {"transport": "stdio", "command": "x", "args": [1]}}, "args"),
        ({"server": {"transport": "stdio", "command": "x", "env": {"X": 1}}}, "env"),
        ({"server": {"transport": "streamable_http", "url": "file:///tmp/x"}}, "url"),
        ({"server": {"transport": "streamable_http", "url": "https://x", "headers": {"X": 1}}}, "headers"),
    ],
    ids=("none", "not-map", "bad-name", "not-object", "transport", "enabled", "command", "args", "env", "url", "headers"),
)
def test_server_configuration_validation_matrix(tmp_path: Path, servers, message) -> None:
    configs, issues = load_mcp_configuration({"mcp_servers": servers}, tmp_path)
    assert configs == ()
    if message is None:
        assert issues == ()
    else:
        assert message in issues[0].message


def test_expand_config_replaces_all_supported_fields(tmp_path: Path) -> None:
    configs, issues = load_mcp_configuration(
        {
            "mcp_servers": {
                "one": {
                    "transport": "stdio",
                    "command": "${BIN}",
                    "args": ["--token=${TOKEN}"],
                    "env": {"VALUE": "${TOKEN}"},
                }
            }
        },
        tmp_path,
    )
    assert not issues
    expanded = expand_config(configs[0], {"BIN": "python", "TOKEN": "secret"})
    assert expanded.command == "python"
    assert expanded.args == ("--token=secret",)
    assert expanded.env == {"VALUE": "secret"}
