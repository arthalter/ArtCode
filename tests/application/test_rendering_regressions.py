from __future__ import annotations

from dataclasses import dataclass
from io import StringIO
import json

import pytest
from rich.console import Console

from artcode.adapters.terminal import TerminalAdapter
from artcode.core.application import ErrorOutput, RunStopped, StateOutput, TextOutput


def terminal_output():
    output = StringIO()
    terminal = TerminalAdapter(
        prompt=object(),
        console=Console(file=output, width=1000, color_system=None),
    )
    return terminal, output


@pytest.mark.parametrize(
    "chunks",
    [
        ("items[i] = values[j]",),
        ("```python\nitems[i] = values[j]\n```",),
        ("before [bold]literal", "[/bold] after :smile:"),
        ("[", "i]", " = values[j]"),
    ],
)
def test_streaming_text_preserves_model_characters_across_chunks(chunks) -> None:
    terminal, output = terminal_output()

    for chunk in chunks:
        terminal.render(TextOutput(chunk, streaming=True))

    assert output.getvalue() == "".join(chunks)


def test_error_output_preserves_unmatched_rich_tags_as_literal_text() -> None:
    terminal, output = terminal_output()
    message = "Cannot render items[i]: [/bold] :smile:"

    terminal.render(ErrorOutput(message))

    assert output.getvalue() == message + "\n"


def test_state_output_preserves_json_string_values() -> None:
    @dataclass
    class State:
        code: str

    terminal, output = terminal_output()
    value = State("items[i] = values[j]; [/bold] :smile:")

    terminal.render(StateOutput("result", value))

    assert json.loads(output.getvalue()) == {"code": value.code}


def test_run_stopped_keeps_the_application_message() -> None:
    terminal, output = terminal_output()

    terminal.render(RunStopped("natural", 2))

    assert output.getvalue() == "\nstopped: natural (2 rounds)\n"
