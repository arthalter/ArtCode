from __future__ import annotations

import sys


def process_tree_command(pid_file: str, *, ignore_term: bool = False) -> tuple[str, ...]:
    """Return a portable Python command that creates a parent/child process tree."""

    source = (
        "import os,pathlib,signal,subprocess,sys,time;"
        + ("signal.signal(signal.SIGTERM,signal.SIG_IGN);" if ignore_term else "")
        + "child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)']);"
        + f"pathlib.Path({pid_file!r}).write_text(str(os.getpid())+'\\n'+str(child.pid));"
        + "time.sleep(60)"
    )
    return (sys.executable, "-c", source)
