from pathlib import Path

import pytest

from artcode.mcp.config import expand_config, load_mcp_configuration, safe_stdio_environment
from artcode.mcp.models import ServerSource, TransportKind


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
