from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path


def write_chta_workbook(
    report_json: Path,
    output_path: Path,
    *,
    node_binary: Path | None = None,
    node_modules: Path | None = None,
) -> Path:
    """Build the workbook with the supported artifact-tool runtime."""

    report_json = report_json.resolve()
    output_path = output_path.resolve()
    node = node_binary or _path_from_env("ARTCODE_NODE_BINARY")
    modules = node_modules or _path_from_env("ARTCODE_NODE_MODULES")
    if node is None or not node.is_file():
        raise RuntimeError("缺少 Node.js runtime；请设置 ARTCODE_NODE_BINARY")
    if modules is None or not modules.is_dir():
        raise RuntimeError("缺少 artifact-tool node_modules；请设置 ARTCODE_NODE_MODULES")
    source = Path(__file__).with_name("workbook_builder.mjs")
    if not source.is_file():
        raise RuntimeError("chTA 工作簿 builder 缺失")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="artcode-chta-workbook-") as raw_temp:
        work = Path(raw_temp)
        builder = work / source.name
        shutil.copy2(source, builder)
        (work / "node_modules").symlink_to(modules, target_is_directory=True)
        completed = subprocess.run(
            [str(node), str(builder), str(report_json), str(output_path)],
            cwd=work,
            text=True,
            capture_output=True,
            timeout=180,
        )
        if completed.returncode != 0:
            raise RuntimeError(
                "chTA 工作簿生成失败：" + (completed.stderr or completed.stdout)[-4000:]
            )
    if not output_path.is_file() or output_path.stat().st_size == 0:
        raise RuntimeError("chTA 工作簿未生成")
    return output_path


def _path_from_env(name: str) -> Path | None:
    value = os.environ.get(name)
    return Path(value).expanduser() if value else None


__all__ = ["write_chta_workbook"]
