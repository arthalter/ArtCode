__all__ = ["ArtCodeRuntime", "RuntimeState", "RuntimeStatusSnapshot", "StartupStatusSnapshot"]


def __getattr__(name: str):
    if name == "ArtCodeRuntime":
        from .app import ArtCodeRuntime

        return ArtCodeRuntime
    if name in {"RuntimeState", "RuntimeStatusSnapshot", "StartupStatusSnapshot"}:
        from .state import RuntimeState, RuntimeStatusSnapshot, StartupStatusSnapshot

        return {
            "RuntimeState": RuntimeState,
            "RuntimeStatusSnapshot": RuntimeStatusSnapshot,
            "StartupStatusSnapshot": StartupStatusSnapshot,
        }[name]
    raise AttributeError(name)
