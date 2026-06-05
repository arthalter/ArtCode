from __future__ import annotations

from prompt_toolkit.key_binding import KeyBindings


def create_input_keybindings() -> KeyBindings:
    bindings = KeyBindings()

    @bindings.add("enter")
    def _(event) -> None:
        event.app.exit(result=event.app.current_buffer.text)

    @bindings.add("c-j")
    def _(event) -> None:
        event.current_buffer.insert_text("\n")

    @bindings.add("escape", "enter")
    def _(event) -> None:
        event.current_buffer.insert_text("\n")

    return bindings
