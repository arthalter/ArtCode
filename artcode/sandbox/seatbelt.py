from __future__ import annotations

import asyncio
import shutil
import tempfile
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path


class SeatbeltError(RuntimeError):
    pass


def _quote(value: Path) -> str:
    text = str(value.resolve()).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{text}"'


@dataclass
class SeatbeltSession:
    workspace: Path
    sensitive_paths: tuple[Path, ...]
    sandbox_exec: Path = Path("/usr/bin/sandbox-exec")
    temp_dir: Path | None = None
    profile_path: Path | None = None
    self_tested: bool = False

    async def start(self) -> SeatbeltSession:
        if not self.sandbox_exec.is_file():
            raise SeatbeltError(f"找不到 sandbox-exec：{self.sandbox_exec}")
        if self.temp_dir is None:
            self.temp_dir = Path(tempfile.mkdtemp(prefix="artcode-"))
        template_path = Path(str(files("artcode.sandbox").joinpath("seatbelt.sb")))
        try:
            template = template_path.read_text(encoding="utf-8")
            profile_path = self.temp_dir / "seatbelt.sb"
            sensitive_paths = (*self.sensitive_paths, template_path, profile_path)
            sensitive_rules = "\n".join(
                f"  (subpath {_quote(path)})" for path in sensitive_paths
            )
            profile = (
                template.replace("{{WORKSPACE}}", _quote(self.workspace))
                .replace("{{TEMP_DIR}}", _quote(self.temp_dir))
                .replace("{{SENSITIVE_RULES}}", sensitive_rules or '  (literal "/dev/null/impossible")')
            )
            self.profile_path = profile_path
            self.profile_path.write_text(profile, encoding="utf-8")
        except OSError as exc:
            self.close()
            raise SeatbeltError(f"无法生成 Seatbelt Profile：{exc}") from exc
        process = await asyncio.create_subprocess_exec(
            str(self.sandbox_exec),
            "-f",
            str(self.profile_path),
            "/usr/bin/true",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await process.communicate()
        if process.returncode != 0:
            message = stderr.decode("utf-8", errors="replace").strip()
            path = self.profile_path
            self.close()
            raise SeatbeltError(f"Seatbelt 自检失败（Profile: {path}）：{message}")
        self.self_tested = True
        return self

    def command_prefix(self) -> tuple[str, ...]:
        if not self.self_tested or self.profile_path is None or not self.profile_path.is_file():
            raise SeatbeltError("Seatbelt 尚未自检成功，或 Profile 已丢失")
        return (str(self.sandbox_exec), "-f", str(self.profile_path))

    def close(self) -> None:
        if self.temp_dir is not None:
            shutil.rmtree(self.temp_dir, ignore_errors=True)
        self.profile_path = None
        self.temp_dir = None
        self.self_tested = False

    async def __aenter__(self) -> SeatbeltSession:
        return await self.start()

    async def __aexit__(self, *_args: object) -> None:
        self.close()
