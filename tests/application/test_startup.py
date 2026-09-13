from __future__ import annotations

from pathlib import Path

import pytest

from artcode._application import ConfigurationFailure, LocalApplication
from artcode.core.application import ApplicationOptions
from artcode.core.session import SessionSelection
from tests.application.conftest import FakeModel, options, write_config


async def test_startup_builds_all_modules_after_configuration_validation(tmp_path: Path) -> None:
    selected = options(tmp_path)
    model = FakeModel()

    app = await LocalApplication.create(selected, model=model)

    snapshot = app.snapshot()
    assert snapshot.workspace == selected.workspace.resolve()
    assert snapshot.session.restored is False
    assert snapshot.permission.mode.value == "default"
    assert snapshot.closed is False
    await app.close()


async def test_invalid_config_reports_same_layer_issues_before_external_effects(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    home = tmp_path / "home"
    workspace.mkdir()
    home.mkdir()
    config = write_config(home / "config.yml", protocol="bad", model="", unknown="x")
    model = FakeModel()

    with pytest.raises(ConfigurationFailure) as caught:
        await LocalApplication.create(
            ApplicationOptions(workspace, config, home, SessionSelection.new()),
            model=model,
        )

    message = str(caught.value)
    assert "protocol" in message and "model" in message and "unknown" in message
    assert not (workspace / ".artcode/ch14").exists()
    assert model.requests == [] and model.closed == 0


async def test_project_configuration_deterministically_overrides_user_value(tmp_path: Path) -> None:
    selected = options(tmp_path)
    project = selected.workspace / ".artcode/config.yml"
    write_config(project, model="project-model")
    model = FakeModel()

    app = await LocalApplication.create(selected, model=model)

    assert app.config.model.model == "project-model"
    await app.close()
