from __future__ import annotations

import inspect

import pytest

from artcode.runtime import ArtCodeRuntime


pytestmark = pytest.mark.ch10_5


def test_runtime_constructor_has_no_implicit_dependency_defaults() -> None:
    signature = inspect.signature(ArtCodeRuntime)
    for name, parameter in signature.parameters.items():
        assert parameter.default is inspect.Parameter.empty, name
