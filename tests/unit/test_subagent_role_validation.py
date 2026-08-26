from __future__ import annotations

from pathlib import Path

import pytest

from artcode.subagents import RoleCatalog, RoleSource
from artcode.tools import create_default_tool_registry


def _descriptors():
    return create_default_tool_registry().descriptors()


def _catalog(project_dir: Path) -> RoleCatalog:
    return RoleCatalog(
        project_dir=project_dir,
        user_dir=project_dir.parent / "user-agents",
        builtin_dir=project_dir.parent / "builtin-agents",
    )


def _role_text(**fields: str) -> str:
    default = {
        "name": "validator",
        "description": "校验角色",
        "tools": "\n  allow: [read_file]\n  deny: []",
        "model": "inherit",
        "max_rounds": "10",
        "permission_mode": "default",
        "isolation": "none",
    }
    default.update(fields)
    lines = ["---"]
    for key, value in default.items():
        lines.append(f"{key}: {value}")
    lines.append("---")
    lines.append("正文内容。")
    return "\n".join(lines) + "\n"


def _write(project_dir: Path, text: str, filename: str = "validator.md") -> Path:
    project_dir.mkdir(parents=True, exist_ok=True)
    path = project_dir / filename
    path.write_text(text, encoding="utf-8")
    return path


def _diagnostics_for(project_dir: Path) -> tuple[str, ...]:
    catalog = _catalog(project_dir)
    snapshot = catalog.refresh(_descriptors())
    return tuple(item.message for item in snapshot.diagnostics)


@pytest.mark.parametrize(
    "missing",
    ["name", "description", "tools", "model", "max_rounds", "permission_mode", "isolation"],
)
def test_role_missing_any_required_field_is_rejected(tmp_path: Path, missing: str) -> None:
    fields = {
        "name": "validator",
        "description": "校验角色",
        "tools": "\n  allow: [read_file]\n  deny: []",
        "model": "inherit",
        "max_rounds": "10",
        "permission_mode": "default",
        "isolation": "none",
    }
    del fields[missing]
    text = "---\n" + "\n".join(f"{k}: {v}" for k, v in fields.items()) + "\n---\n正文\n"
    path = _write(tmp_path / "agents", text)

    catalog = _catalog(tmp_path / "agents")
    snapshot = catalog.refresh(_descriptors())

    assert snapshot.get("validator") is None
    assert any("缺少字段" in item.message for item in snapshot.diagnostics)


def test_role_unknown_frontmatter_field_is_rejected(tmp_path: Path) -> None:
    _write(
        tmp_path / "agents",
        _role_text(extra_field="oops"),
    )

    messages = _diagnostics_for(tmp_path / "agents")

    assert any("未知字段" in message for message in messages)


@pytest.mark.parametrize(
    ("name", "filename", "accepted"),
    [
        ("reader", "reader.md", True),
        ("Reader", "Reader.md", False),
        ("reader_x", "reader_x.md", False),
        ("a" * 33, "a" * 33 + ".md", False),
        ("reader", "other.md", False),
    ],
)
def test_role_name_pattern_and_filename_consistency(
    tmp_path: Path, name: str, filename: str, accepted: bool
) -> None:
    _write(tmp_path / "agents", _role_text(name=name), filename=filename)

    catalog = _catalog(tmp_path / "agents")
    snapshot = catalog.refresh(_descriptors())

    assert (snapshot.get(name) is not None) is accepted


def test_role_description_single_line_and_bounded(tmp_path: Path) -> None:
    # A quoted YAML scalar with an escaped newline resolves to a multi-line
    # description and must be rejected.
    _write(
        tmp_path / "agents",
        "---\n"
        "name: validator\n"
        'description: "第一行\\n第二行"\n'
        "tools:\n"
        "  allow: [read_file]\n"
        "  deny: []\n"
        "model: inherit\n"
        "max_rounds: 10\n"
        "permission_mode: default\n"
        "isolation: none\n"
        "---\n"
        "正文。\n",
    )
    assert any("description" in m for m in _diagnostics_for(tmp_path / "agents"))

    long = "x" * 201
    _write(tmp_path / "agents", _role_text(description=long))
    assert any("description" in m for m in _diagnostics_for(tmp_path / "agents"))


def test_role_tools_structure_duplicates_and_overlap_are_rejected(tmp_path: Path) -> None:
    _write(
        tmp_path / "agents",
        _role_text(tools="\n  allow: [read_file]\n  deny: [read_file]"),
    )
    assert any("同一工具" in m for m in _diagnostics_for(tmp_path / "agents"))

    _write(
        tmp_path / "agents",
        _role_text(tools="\n  allow: [read_file, read_file]\n  deny: []"),
    )
    assert any("重复" in m for m in _diagnostics_for(tmp_path / "agents"))

    _write(
        tmp_path / "agents",
        _role_text(tools="\n  allow: [read_file]\n  deny: []\n  extra: []"),
    )
    assert any("未知字段" in m for m in _diagnostics_for(tmp_path / "agents"))


@pytest.mark.parametrize(
    ("value", "accepted"),
    [("inherit", True), ("haiku", True), ("sonnet", True), ("opus", True), ("gpt-5", False), ("1", False)],
)
def test_role_model_tier_requires_configured_mapping(
    tmp_path: Path, value: str, accepted: bool
) -> None:
    catalog = RoleCatalog(
        project_dir=tmp_path / "agents",
        user_dir=tmp_path / "user",
        builtin_dir=tmp_path / "builtin",
        model_tiers={"haiku": "model-h", "sonnet": "model-s", "opus": "model-o"},
    )
    _write(tmp_path / "agents", _role_text(model=value))

    snapshot = catalog.refresh(_descriptors())

    assert (snapshot.get("validator") is not None) is accepted


def test_role_model_tier_without_mapping_is_unavailable(tmp_path: Path) -> None:
    catalog = RoleCatalog(
        project_dir=tmp_path / "agents",
        user_dir=tmp_path / "user",
        builtin_dir=tmp_path / "builtin",
        model_tiers={},
    )
    _write(tmp_path / "agents", _role_text(model="sonnet"))

    snapshot = catalog.refresh(_descriptors())

    assert snapshot.get("validator") is None
    assert any("档位未配置" in item.message for item in snapshot.diagnostics)


@pytest.mark.parametrize(
    ("value", "accepted"),
    [("0", False), ("1", True), ("100", True), ("101", False), ("true", False), ("10.5", False)],
)
def test_role_max_rounds_bounds(tmp_path: Path, value: str, accepted: bool) -> None:
    _write(tmp_path / "agents", _role_text(max_rounds=value))

    catalog = _catalog(tmp_path / "agents")
    snapshot = catalog.refresh(_descriptors())

    assert (snapshot.get("validator") is not None) is accepted


def test_definition_role_source_is_project_when_found_there(tmp_path: Path) -> None:
    _write(tmp_path / "agents", _role_text())

    catalog = _catalog(tmp_path / "agents")
    snapshot = catalog.refresh(_descriptors())

    role = snapshot.get("validator")
    assert role is not None and role.source is RoleSource.PROJECT