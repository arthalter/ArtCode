from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

from hypothesis import given, settings, strategies as st

from artcode._session import LocalSession
from artcode._tool import LocalTools
from artcode._workspace import LocalWorkspace
from artcode.core.model import Completed, ModelRequest, TextDelta
from artcode.core.session import AssistantCompletion, CompactionTrigger, SessionSelection
from artcode.core.tool import RunMode


class SummaryModel:
    def __init__(self) -> None:
        self.calls = 0

    async def stream(self, request: ModelRequest):
        self.calls += 1
        yield TextDelta("derived summary")
        yield Completed("stop")

    async def close(self) -> None:
        return None


TEXT = st.text(alphabet=st.characters(blacklist_categories=("Cs",)), max_size=100)


@given(st.lists(TEXT, min_size=6, max_size=20))
@settings(max_examples=25)
def test_every_user_message_remains_independent_verbatim_and_ordered(users: list[str]) -> None:
    import asyncio

    async def scenario() -> None:
        with TemporaryDirectory() as raw:
            root = Path(raw)
            workspace = LocalWorkspace(root)
            tools = LocalTools()
            session = LocalSession(root, SessionSelection.new(), recent_fact_count=2)
            for index, user in enumerate(users):
                session.commit_user(user)
                session.commit_assistant(f"assistant-{index}", AssistantCompletion.NATURAL)
            await session.compact(SummaryModel(), CompactionTrigger.MANUAL)
            lease = await session.prepare_run("latest", tools.open_run(workspace, RunMode.CHAT))
            projected = [item.content for item in lease.prompt_preview.prompt if item.role == "user"]
            assert projected == [*users, "latest"]
            assert session.snapshot().facts[::2] == tuple(__import__("artcode.core.session", fromlist=["UserFact"]).UserFact(item) for item in users) + (__import__("artcode.core.session", fromlist=["UserFact"]).UserFact("latest"),)
            session.close()

    asyncio.run(scenario())
