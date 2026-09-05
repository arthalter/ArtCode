from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

from hypothesis import given, settings, strategies as st

from artcode._session import LocalSession
from artcode.core.session import AssistantCompletion, AssistantFact, SessionSelection, UserFact


TEXT = st.text(
    alphabet=st.characters(blacklist_categories=("Cs",), blacklist_characters=("\x00",)),
    max_size=500,
)


@given(st.lists(st.tuples(st.booleans(), TEXT), max_size=30))
@settings(max_examples=40)
def test_arbitrary_unicode_facts_round_trip_in_original_order(items: list[tuple[bool, str]]) -> None:
    with TemporaryDirectory() as raw:
        root = Path(raw)
        session = LocalSession(root, SessionSelection.new())
        expected = []
        for is_user, text in items:
            if is_user:
                session.commit_user(text)
                expected.append(UserFact(text))
            else:
                session.commit_assistant(text, AssistantCompletion.NATURAL)
                expected.append(AssistantFact(text, AssistantCompletion.NATURAL))
        identifier = session.snapshot().session_id
        session.close()

        restored = LocalSession(root, SessionSelection.exact(identifier))
        assert restored.snapshot().facts == tuple(expected)
        restored.close()
