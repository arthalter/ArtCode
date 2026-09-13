from __future__ import annotations

from pathlib import Path
import sys

from artcode._application import LocalApplication
from artcode.core.application import ErrorOutput, StateOutput
from tests.application.conftest import FakeModel, options, write_config
from tests.contracts.test_skill_interface import write_skill


async def test_skill_can_reference_discovered_mcp_without_activating_it(tmp_path: Path) -> None:
    selected = options(tmp_path)
    fixture = Path(__file__).parents[1] / "integration" / "fixtures" / "mcp_test_server.py"
    write_config(
        selected.config_path,
        mcp={"loading": "lazy"},
        mcp_servers={"local": {"transport": "stdio", "command": sys.executable, "args": [str(fixture)]}},
    )
    write_skill(
        selected.workspace / ".artcode/skills",
        "review",
        tools=("mcp_search_tools", "mcp__local__echo"),
    )
    app = await LocalApplication.create(selected, model=FakeModel())
    try:
        events = await app.handle("/skill review")
        assert not [item for item in events if isinstance(item, ErrorOutput)]
        activation = next(item.value for item in events if isinstance(item, StateOutput) and item.name == "skill")
        assert activation.ok
        assert not app.tools.search_mcp("echo")[0].active
    finally:
        await app.close()
