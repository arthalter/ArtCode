from __future__ import annotations

import asyncio
from contextlib import contextmanager

from prompt_toolkit.key_binding.key_processor import KeyPress
from prompt_toolkit.keys import Keys

from artcode.adapters.terminal import TerminalAdapter


class FakeInput:
    closed = False

    def __init__(self, key, stop: asyncio.Event) -> None:
        self.key = key
        self.stop = stop

    @contextmanager
    def raw_mode(self):
        yield

    @contextmanager
    def attach(self, callback):
        callback()
        yield

    def read_keys(self):
        self.stop.set()
        return [KeyPress(self.key, "")]


class FakeConsole:
    def print(self, *args, **kwargs):
        return None


class FakeApplication:
    def __init__(self) -> None:
        self.backgrounded = 0
        self.cancelled = 0

    def background_current_task(self):
        self.backgrounded += 1
        return True

    def cancel_current(self):
        self.cancelled += 1
        return True


async def test_ctrl_b_maps_to_immediate_foreground_task_backgrounding() -> None:
    stop = asyncio.Event()
    terminal = object.__new__(TerminalAdapter)
    terminal.input = FakeInput(Keys.ControlB, stop)
    terminal.console = FakeConsole()
    application = FakeApplication()

    await terminal.monitor_controls(application, stop)

    assert application.backgrounded == 1
    assert application.cancelled == 0


async def test_ctrl_c_maps_to_current_run_cancellation() -> None:
    stop = asyncio.Event()
    terminal = object.__new__(TerminalAdapter)
    terminal.input = FakeInput(Keys.ControlC, stop)
    terminal.console = FakeConsole()
    application = FakeApplication()

    await terminal.monitor_controls(application, stop)

    assert application.cancelled == 1
    assert application.backgrounded == 0


def test_default_prompt_session_enables_multiline_input() -> None:
    terminal = TerminalAdapter()
    try:
        assert terminal.prompt.multiline is True
    finally:
        if terminal.input is not None:
            terminal.input.close()
