from __future__ import annotations

import asyncio
from pathlib import Path
import shutil
import tempfile

from artcode.core.workspace import SeatbeltUnavailable


def _quote(path: Path) -> str:
    text = str(path.resolve()).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{text}"'


class Seatbelt:
    def __init__(
        self,
        workspace: Path,
        sensitive_paths: tuple[Path, ...],
        *,
        executable: Path,
        isolation_root: Path | None = None,
        readable_paths: tuple[Path, ...] = (),
    ) -> None:
        self.workspace = workspace
        self.sensitive_paths = sensitive_paths
        self.executable = executable
        self.isolation_root = isolation_root
        self.readable_paths = readable_paths
        self._directory: Path | None = None
        self._profile: Path | None = None
        self._ready = False

    async def prefix(self) -> tuple[str, ...]:
        if self._ready and self._profile is not None and self._profile.is_file():
            return (str(self.executable), "-f", str(self._profile))
        if not self.executable.is_file():
            raise SeatbeltUnavailable(f"找不到 sandbox-exec：{self.executable}")
        directory = Path(tempfile.mkdtemp(prefix="artcode-seatbelt-"))
        profile = directory / "seatbelt.sb"
        sensitive = "\n".join(
            f"  (subpath {_quote(path)})" for path in (*self.sensitive_paths, profile)
        ) or '  (literal "/dev/null/artcode-impossible")'
        template = Path(__file__).with_name("seatbelt.sb").read_text(encoding="utf-8")
        rendered = (
            template.replace("{{WORKSPACE}}", _quote(self.workspace))
            .replace("{{TEMP_DIR}}", _quote(directory))
            .replace("{{SENSITIVE_RULES}}", sensitive)
            .replace(
                "{{ISOLATION_RULE}}",
                _isolation_rule(
                    self.isolation_root,
                    (self.workspace, *self.readable_paths),
                ),
            )
        )
        try:
            profile.write_text(rendered, encoding="utf-8")
            process = await asyncio.create_subprocess_exec(
                str(self.executable),
                "-f",
                str(profile),
                "/usr/bin/true",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await process.communicate()
        except (OSError, ValueError) as exc:
            shutil.rmtree(directory, ignore_errors=True)
            raise SeatbeltUnavailable(f"Seatbelt 自检无法启动：{exc}") from exc
        if process.returncode != 0:
            detail = stderr.decode("utf-8", errors="replace").strip()
            shutil.rmtree(directory, ignore_errors=True)
            raise SeatbeltUnavailable(f"Seatbelt 自检失败：{detail}")
        self._directory = directory
        self._profile = profile
        self._ready = True
        return (str(self.executable), "-f", str(profile))

    def close(self) -> None:
        if self._directory is not None:
            shutil.rmtree(self._directory, ignore_errors=True)
        self._directory = None
        self._profile = None
        self._ready = False


def _isolation_rule(root: Path | None, allowed: tuple[Path, ...]) -> str:
    if root is None:
        return ""
    resolved_root = root.resolve(strict=True)
    traversal: set[Path] = {resolved_root}
    exclusions: list[Path] = []
    for path in allowed:
        resolved = path.resolve(strict=True)
        if resolved == resolved_root or resolved_root not in resolved.parents:
            raise SeatbeltUnavailable("Seatbelt 隔离例外必须位于隔离根内。")
        exclusions.append(resolved)
        cursor = resolved.parent
        while cursor != resolved_root and resolved_root in cursor.parents:
            traversal.add(cursor)
            cursor = cursor.parent
    filters = "\n".join(
        [
            *(f"    (require-not (literal {_quote(path)}))" for path in sorted(traversal)),
            *(f"    (require-not (subpath {_quote(path)}))" for path in exclusions),
        ]
    )
    return (
        "(deny file-read* file-write*\n"
        "  (require-all\n"
        f"    (subpath {_quote(resolved_root)})\n"
        f"{filters}\n"
        "  ))"
    )
