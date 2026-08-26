from __future__ import annotations

import pytest

from artcode.background.models import (
    BackgroundTaskStatus,
    ensure_transition,
    is_terminal,
)


def test_initial_status_is_queued_and_non_terminal() -> None:
    assert not is_terminal(BackgroundTaskStatus.QUEUED)
    assert not is_terminal(BackgroundTaskStatus.RUNNING)


@pytest.mark.parametrize(
    "status",
    [
        BackgroundTaskStatus.COMPLETED,
        BackgroundTaskStatus.FAILED,
        BackgroundTaskStatus.MAX_ROUNDS,
        BackgroundTaskStatus.CANCELLED,
    ],
)
def test_terminal_statuses_never_transition(status: BackgroundTaskStatus) -> None:
    with pytest.raises(ValueError, match="invalid background task transition"):
        ensure_transition(status, BackgroundTaskStatus.RUNNING)


def test_queued_allows_running_cancelled_and_failed() -> None:
    ensure_transition(BackgroundTaskStatus.QUEUED, BackgroundTaskStatus.RUNNING)
    ensure_transition(BackgroundTaskStatus.QUEUED, BackgroundTaskStatus.CANCELLED)
    ensure_transition(BackgroundTaskStatus.QUEUED, BackgroundTaskStatus.FAILED)
    with pytest.raises(ValueError):
        ensure_transition(BackgroundTaskStatus.QUEUED, BackgroundTaskStatus.COMPLETED)
    with pytest.raises(ValueError):
        ensure_transition(BackgroundTaskStatus.QUEUED, BackgroundTaskStatus.MAX_ROUNDS)


def test_running_only_accepts_terminal_states() -> None:
    for terminal in (
        BackgroundTaskStatus.COMPLETED,
        BackgroundTaskStatus.FAILED,
        BackgroundTaskStatus.MAX_ROUNDS,
        BackgroundTaskStatus.CANCELLED,
    ):
        ensure_transition(BackgroundTaskStatus.RUNNING, terminal)
    with pytest.raises(ValueError):
        ensure_transition(BackgroundTaskStatus.RUNNING, BackgroundTaskStatus.QUEUED)
