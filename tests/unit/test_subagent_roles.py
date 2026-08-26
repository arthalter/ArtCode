from __future__ import annotations

from pathlib import Path

from artcode.subagents import RoleCatalog
from artcode.tools import ToolDescriptor, ToolEffect, ToolOrigin


def _descriptor(name: str, effect: ToolEffect = ToolEffect.READ) -> ToolDescriptor:
    return ToolDescriptor(
        name,
        name,
        {"type": "object", "properties": {}},
        effect,
        subagent_allowed=True,
    )


def _role(path: Path, *, name: str, body: str = "完成审查。", tools: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "---\n"
        f"name: {name}\n"
        "description: 测试角色\n"
        f"{tools or 'tools:\n  allow: [read_file]\n  deny: []\n'}"
        "model: inherit\n"
        "max_rounds: 10\n"
        "permission_mode: default\n"
        "isolation: none\n"
        "---\n"
        f"{body}\n",
        encoding="utf-8",
    )


def test_project_role_wins_as_a_whole_over_lower_priority_sources(tmp_path: Path) -> None:
    project, user, builtin = (tmp_path / item for item in ("project", "user", "builtin"))
    _role(user / "review.md", name="review", body="来自用户")
    _role(project / "review.md", name="review", body="来自项目")
    catalog = RoleCatalog(project_dir=project, user_dir=user, builtin_dir=builtin)

    snapshot = catalog.refresh((_descriptor("read_file"),))

    assert snapshot.get("review") is not None
    assert snapshot.get("review").system_prompt == "来自项目\n"


def test_invalid_project_role_blocks_same_lower_priority_role(tmp_path: Path) -> None:
    project, user, builtin = (tmp_path / item for item in ("project", "user", "builtin"))
    _role(user / "review.md", name="review")
    (project / "review.md").parent.mkdir(parents=True)
    (project / "review.md").write_text(
        "---\nname: review\ndescription: 坏角色\ntools:\n  allow: [missing]\n---\n正文\n",
        encoding="utf-8",
    )
    catalog = RoleCatalog(project_dir=project, user_dir=user, builtin_dir=builtin)

    snapshot = catalog.refresh((_descriptor("read_file"),))

    assert snapshot.get("review") is None
    assert any(item.blocking and item.role_name == "review" for item in snapshot.diagnostics)


def test_write_role_must_request_worktree(tmp_path: Path) -> None:
    project, user, builtin = (tmp_path / item for item in ("project", "user", "builtin"))
    _role(
        project / "writer.md",
        name="writer",
        tools="tools:\n  allow: [write_file]\n  deny: []\n",
    )
    catalog = RoleCatalog(project_dir=project, user_dir=user, builtin_dir=builtin)

    snapshot = catalog.refresh((_descriptor("write_file", ToolEffect.WRITE),))

    assert snapshot.get("writer") is None
    assert "isolation: worktree" in snapshot.diagnostics[0].message


def test_role_discovery_is_nonrecursive_and_rejects_symlinks(tmp_path: Path) -> None:
    project = tmp_path / "project"
    user = tmp_path / "user"
    builtin = tmp_path / "builtin"
    _role(project / "visible.md", name="visible")
    _role(project / "nested" / "hidden.md", name="hidden")
    _role(tmp_path / "outside.md", name="linked")
    (project / "linked.md").symlink_to(tmp_path / "outside.md")
    real_dir = tmp_path / "real-dir"
    _role(real_dir / "directory-role.md", name="directory-role")
    (tmp_path / "linked-dir").symlink_to(real_dir, target_is_directory=True)

    snapshot = RoleCatalog(
        project_dir=project,
        user_dir=user,
        builtin_dir=builtin,
        plugin_dirs=(tmp_path / "linked-dir",),
    ).refresh((_descriptor("read_file"),))

    assert set(snapshot.definitions) == {"visible"}


def test_empty_allow_list_grants_no_tools(tmp_path: Path) -> None:
    project, user, builtin = (tmp_path / item for item in ("project", "user", "builtin"))
    _role(
        project / "empty.md",
        name="empty",
        tools="tools:\n  allow: []\n  deny: []\n",
    )

    role = RoleCatalog(
        project_dir=project, user_dir=user, builtin_dir=builtin
    ).refresh((_descriptor("read_file"),)).get("empty")

    assert role is not None
    assert role.tool_allow == frozenset()


def test_role_cannot_reference_system_mcp_or_non_delegable_tools(tmp_path: Path) -> None:
    project, user, builtin = (tmp_path / item for item in ("project", "user", "builtin"))
    _role(
        project / "unsafe.md",
        name="unsafe",
        tools="tools:\n  allow: [system_tool]\n  deny: []\n",
    )
    system_descriptor = ToolDescriptor(
        "system_tool",
        "system",
        {"type": "object"},
        ToolEffect.READ,
        ToolOrigin.SYSTEM,
        False,
        True,
    )

    snapshot = RoleCatalog(
        project_dir=project, user_dir=user, builtin_dir=builtin
    ).refresh((system_descriptor,))

    assert snapshot.get("unsafe") is None
    assert "未知工具" in snapshot.diagnostics[0].message


def test_same_plugin_source_duplicate_blocks_role_independent_of_order(tmp_path: Path) -> None:
    plugin_a, plugin_b = tmp_path / "plugin-a", tmp_path / "plugin-b"
    _role(plugin_a / "review.md", name="review", body="A")
    _role(plugin_b / "review.md", name="review", body="B")
    catalog = RoleCatalog(
        project_dir=tmp_path / "project",
        user_dir=tmp_path / "user",
        builtin_dir=tmp_path / "builtin",
        plugin_dirs=(plugin_b, plugin_a),
    )

    snapshot = catalog.refresh((_descriptor("read_file"),))

    assert snapshot.get("review") is None
    diagnostic = snapshot.diagnostics[0]
    assert diagnostic.code == "duplicate_role"
    assert str(plugin_a / "review.md") in diagnostic.message
    assert str(plugin_b / "review.md") in diagnostic.message


def test_role_refresh_freezes_old_definition_and_loads_new_body(tmp_path: Path) -> None:
    project = tmp_path / "project"
    role_path = project / "review.md"
    _role(role_path, name="review", body="OLD {{literal}}")
    catalog = RoleCatalog(
        project_dir=project,
        user_dir=tmp_path / "user",
        builtin_dir=tmp_path / "builtin",
    )

    old = catalog.refresh((_descriptor("read_file"),)).get("review")
    _role(role_path, name="review", body="NEW {{literal}}")
    new = catalog.refresh((_descriptor("read_file"),)).get("review")

    assert old is not None and new is not None
    assert old.system_prompt == "OLD {{literal}}\n"
    assert new.system_prompt == "NEW {{literal}}\n"


def test_configured_model_tier_is_resolved_but_missing_tier_blocks(tmp_path: Path) -> None:
    project = tmp_path / "project"
    path = project / "modelled.md"
    _role(path, name="modelled")
    text = path.read_text(encoding="utf-8").replace("model: inherit", "model: sonnet")
    path.write_text(text, encoding="utf-8")

    missing = RoleCatalog(
        project_dir=project,
        user_dir=tmp_path / "user",
        builtin_dir=tmp_path / "builtin",
    ).refresh((_descriptor("read_file"),))
    configured = RoleCatalog(
        project_dir=project,
        user_dir=tmp_path / "user",
        builtin_dir=tmp_path / "builtin",
        model_tiers={"sonnet": "deepseek-chat"},
    ).refresh((_descriptor("read_file"),))

    assert missing.get("modelled") is None
    assert configured.get("modelled").model_tier == "sonnet"
