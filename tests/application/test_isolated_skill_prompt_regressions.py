from __future__ import annotations

from pathlib import Path

import pytest

from artcode._application import LocalApplication
from artcode.core.application import StateOutput
from artcode.core.agent import StopReason
from artcode.core.model import ModelRequest
from tests.application.conftest import FakeModel, options, write_config
from tests.contracts.test_skill_interface import write_skill


def system_text(request: ModelRequest) -> str:
    return "\n".join(item.content or "" for item in request.prompt if item.role == "system")


@pytest.mark.parametrize("entry", ("/skill inspect examine files", "inspect examine files"))
@pytest.mark.parametrize("with_shared", (False, True))
async def test_isolated_sop_and_model_do_not_enter_later_main_run(
    tmp_path: Path, entry: str, with_shared: bool
) -> None:
    selected = options(tmp_path)
    write_config(
        selected.config_path,
        agents={"models": {"haiku": "isolated-model", "sonnet": "shared-model"}},
    )
    skill_root = selected.workspace / ".artcode/skills"
    write_skill(
        skill_root,
        "inspect",
        mode="isolated",
        history_turns=0,
        model="isolated-model",
        sop="ISOLATED-ONLY-INSTRUCTIONS",
    )
    if with_shared:
        write_skill(
            skill_root,
            "review",
            tools=("read_file", "find_files"),
            model="shared-model",
            sop="SHARED-PERSISTENT-INSTRUCTIONS",
        )
    model = FakeModel()
    app = await LocalApplication.create(selected, model=model)
    try:
        if with_shared:
            await app.handle("/skill review")
        events = await app.handle(entry)
        result = next(
            item.value for item in events
            if isinstance(item, StateOutput) and item.name == "isolated_skill"
        )
        assert result.stop_reason is StopReason.NATURAL
        isolated_request = model.requests[0]
        assert "ISOLATED-ONLY-INSTRUCTIONS" in system_text(isolated_request)
        assert isolated_request.model == "isolated-model"

        await app.handle("hello")
        main_request = next(
            request for request in model.requests
            if request.prompt[-1].role == "user" and request.prompt[-1].content == "hello"
        )
        assert "ISOLATED-ONLY-INSTRUCTIONS" not in system_text(main_request)
        assert main_request.model == ("shared-model" if with_shared else None)
        assert ("SHARED-PERSISTENT-INSTRUCTIONS" in system_text(main_request)) is with_shared
        assert {item.name for item in main_request.tools} == {"read_file"}
        assert {item.name for item in isolated_request.tools} == {"read_file"}
    finally:
        await app.close()
