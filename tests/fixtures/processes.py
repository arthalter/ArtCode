from __future__ import annotations

import sys


def process_tree_command(
    pid_file: str,
    *,
    ignore_term: bool = False,
    stdout_size: int = 0,
    stderr_size: int = 0,
) -> tuple[str, ...]:
    """Return a portable parent/child/grandchild process-tree command."""

    child_file = f"{pid_file}.child"
    grandchild_source = "import signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);time.sleep(60)"
    child_source = "\n".join(
        (
            "import os,pathlib,signal,subprocess,sys,time",
            "signal.signal(signal.SIGTERM,signal.SIG_IGN)",
            f"grandchild=subprocess.Popen([sys.executable,'-c',{grandchild_source!r}])",
            f"pathlib.Path({child_file!r}).write_text(str(os.getpid())+'\\n'+str(grandchild.pid))",
            "time.sleep(60)",
        )
    )
    lines = ["import os,pathlib,signal,subprocess,sys,time"]
    if ignore_term:
        lines.append("signal.signal(signal.SIGTERM,signal.SIG_IGN)")
    lines.extend(
        (
            f"child=subprocess.Popen([sys.executable,'-c',{child_source!r}])",
            f"child_file=pathlib.Path({child_file!r})",
            "deadline=time.monotonic()+5",
            "while not child_file.exists() and time.monotonic()<deadline: time.sleep(.005)",
            "child_pids=child_file.read_text().splitlines()",
            f"pathlib.Path({pid_file!r}).write_text('\\n'.join([str(os.getpid()),*child_pids]))",
        )
    )
    if stdout_size:
        lines.append(f"sys.stdout.write('x'*{stdout_size});sys.stdout.flush()")
    if stderr_size:
        lines.append(f"sys.stderr.write('y'*{stderr_size});sys.stderr.flush()")
    lines.append("time.sleep(60)")
    return (sys.executable, "-c", "\n".join(lines))
