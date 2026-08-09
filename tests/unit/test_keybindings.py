from __future__ import annotations

from types import SimpleNamespace

from artcode.tui.keybindings import create_input_keybindings


def test_input_keybindings_send_and_insert_newlines() -> None:
    bindings = create_input_keybindings().bindings
    buffer = SimpleNamespace(text="message", inserted=[])
    buffer.insert_text = buffer.inserted.append
    app = SimpleNamespace(current_buffer=buffer, results=[])
    app.exit = lambda *, result: app.results.append(result)
    event = SimpleNamespace(app=app, current_buffer=buffer)

    enter = next(item for item in bindings if tuple(key.value for key in item.keys) == ("c-m",))
    control_j = next(item for item in bindings if tuple(key.value for key in item.keys) == ("c-j",))
    escape_enter = next(item for item in bindings if tuple(key.value for key in item.keys) == ("escape", "c-m"))
    enter.handler(event)
    control_j.handler(event)
    escape_enter.handler(event)

    assert app.results == ["message"]
    assert buffer.inserted == ["\n", "\n"]
