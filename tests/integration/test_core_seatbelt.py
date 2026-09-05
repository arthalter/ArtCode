from __future__ import annotations

from pathlib import Path
import platform
import shutil
import sys

import pytest

from artcode._workspace import LocalWorkspace
from artcode.core.workspace import IsolationMode, ProcessRequest


pytestmark = pytest.mark.skipif(
    platform.system() != "Darwin" or not Path("/usr/bin/sandbox-exec").is_file(),
    reason="真实 Seatbelt 只在带 sandbox-exec 的 macOS 可验证",
)


async def test_real_seatbelt_allows_workspace_write_and_blocks_outside_write(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    outside = tmp_path / "outside.txt"
    scope = LocalWorkspace(root)

    inside_outcome = await scope.run_process(
        ProcessRequest(
            argv=(sys.executable, "-c", "from pathlib import Path; Path('inside.txt').write_text('ok')"),
            isolation=IsolationMode.ENFORCED,
        )
    )
    outside_outcome = await scope.run_process(
        ProcessRequest(
            argv=(sys.executable, "-c", f"from pathlib import Path; Path({str(outside)!r}).write_text('bad')"),
            isolation=IsolationMode.ENFORCED,
        )
    )

    assert inside_outcome.returncode == 0
    assert (root / "inside.txt").read_text(encoding="utf-8") == "ok"
    assert outside_outcome.returncode != 0
    assert not outside.exists()


async def test_real_seatbelt_blocks_network(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    scope = LocalWorkspace(root)

    outcome = await scope.run_process(
        ProcessRequest(
            argv=(
                sys.executable,
                "-c",
                "import socket; socket.create_connection(('127.0.0.1', 9), timeout=.1)",
            ),
            isolation=IsolationMode.ENFORCED,
        )
    )

    assert outcome.returncode != 0
