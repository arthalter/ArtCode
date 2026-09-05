from __future__ import annotations

from pathlib import Path

from artcode._application import LocalApplication
from artcode.core.application import ClearDisplay, ErrorOutput, StateOutput
from tests.application.conftest import FakeModel, options


async def test_unknown_and_invalid_local_commands_never_call_model_or_transcript(tmp_path: Path) -> None:
    model = FakeModel()
    app = await LocalApplication.create(options(tmp_path), model=model)
    before = app.snapshot().session.facts

    unknown = await app.handle("/definitely-unknown")
    invalid = await app.handle("/permissions nope")

    assert isinstance(unknown[0], ErrorOutput)
    assert isinstance(invalid[0], ErrorOutput)
    assert model.requests == []
    assert app.snapshot().session.facts == before
    await app.close()


async def test_permission_sandbox_help_and_state_commands_are_local(tmp_path: Path) -> None:
    model = FakeModel()
    app = await LocalApplication.create(options(tmp_path), model=model)

    permission = await app.handle("/permissions edit")
    sandbox = await app.handle("/sandbox off")
    status = await app.handle("/status")
    help_result = await app.handle("/help")

    assert isinstance(permission[0], StateOutput)
    assert isinstance(sandbox[0], StateOutput)
    assert isinstance(status[0], StateOutput)
    assert "/plan" in help_result[0].text
    assert model.requests == []
    await app.close()


async def test_clear_only_changes_display_and_skill_activation(tmp_path: Path) -> None:
    selected = options(tmp_path)
    skill_dir = selected.workspace / ".artcode/skills"
    skill_dir.mkdir(parents=True)
    (skill_dir / "review.md").write_text(
        "---\nname: review\ndescription: review\ntools: ['read_file']\nmode: shared\n---\nSOP\n",
        encoding="utf-8",
    )
    app = await LocalApplication.create(selected, model=FakeModel())
    await app.handle("/skill review")
    before = app.snapshot().session

    result = await app.handle("/clear")

    assert result == (ClearDisplay(),)
    assert app.snapshot().skills.active == ()
    assert app.snapshot().session.facts == before.facts
    await app.close()
