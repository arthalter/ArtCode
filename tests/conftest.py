from __future__ import annotations

import pytest

from tests.fixtures.providers import ScriptedProvider


@pytest.fixture
def scripted_provider_factory():
    return ScriptedProvider.from_streams
