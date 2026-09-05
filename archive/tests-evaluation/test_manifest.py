from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from artcode.evaluation.manifest import BenchmarkValidationError, load_benchmark


def test_load_valid_benchmark_has_stable_fingerprint(benchmark_file: Path) -> None:
    first = load_benchmark(benchmark_file)
    second = load_benchmark(benchmark_file)
    assert first.fingerprint == second.fingerprint
    assert len(first.fingerprint) == 64
    assert first.tasks[0].fixture.name == "fixture"


def test_semantic_change_changes_fingerprint(benchmark_file: Path) -> None:
    original = load_benchmark(benchmark_file).fingerprint
    text = benchmark_file.read_text(encoding="utf-8").replace(
        "Create result.txt", "Create output.txt"
    )
    benchmark_file.write_text(text, encoding="utf-8")
    assert load_benchmark(benchmark_file).fingerprint != original


@pytest.mark.parametrize(
    ("replacement", "message"),
    [
        ("version: 2", "version 必须为 1"),
        ("name: test-benchmark\nunknown: true", "未知字段"),
        ("repetitions: 0", "1～10"),
        ("timeout_seconds: 0", "1～1800"),
        ("max_iterations: 101", "1～100"),
        ("permission_mode: default", "无人值守评测"),
        ("type: mystery", "必须是"),
    ],
)
def test_invalid_benchmark_is_rejected(
    benchmark_file: Path,
    replacement: str,
    message: str,
) -> None:
    text = benchmark_file.read_text(encoding="utf-8")
    if replacement.startswith("version"):
        text = text.replace("version: 1", replacement)
    elif replacement.startswith("name"):
        text = text.replace("name: test-benchmark", replacement)
    elif replacement.startswith("type"):
        text = text.replace("type: file_exists", replacement)
    else:
        key = replacement.split(":", 1)[0]
        old = next(line.strip() for line in text.splitlines() if line.strip().startswith(key + ":"))
        text = text.replace(old, replacement)
    benchmark_file.write_text(text, encoding="utf-8")
    with pytest.raises(BenchmarkValidationError, match=message):
        load_benchmark(benchmark_file)


def test_duplicate_task_and_verifier_ids_are_rejected(benchmark_file: Path) -> None:
    raw = yaml.safe_load(benchmark_file.read_text(encoding="utf-8"))
    raw["tasks"][0]["verifiers"].append(dict(raw["tasks"][0]["verifiers"][0]))
    raw["tasks"].append(dict(raw["tasks"][0]))
    benchmark_file.write_text(yaml.safe_dump(raw), encoding="utf-8")
    with pytest.raises(BenchmarkValidationError) as caught:
        load_benchmark(benchmark_file)
    assert "id 重复" in str(caught.value)


@pytest.mark.parametrize("unsafe", ["/tmp/out", "../out", "a/../../out", "~/.ssh"])
def test_unsafe_verifier_paths_are_rejected(benchmark_file: Path, unsafe: str) -> None:
    benchmark_file.write_text(
        benchmark_file.read_text(encoding="utf-8").replace(
            "path: result.txt", f"path: {unsafe}"
        ),
        encoding="utf-8",
    )
    with pytest.raises(BenchmarkValidationError):
        load_benchmark(benchmark_file)


def test_fixture_escape_symlink_is_rejected(benchmark_file: Path, tmp_path: Path) -> None:
    (tmp_path / "fixture" / "escape").symlink_to(tmp_path.parent)
    with pytest.raises(BenchmarkValidationError, match="越界符号链接"):
        load_benchmark(benchmark_file)


def test_benchmark_symlink_is_rejected(benchmark_file: Path, tmp_path: Path) -> None:
    link = tmp_path / "linked.yml"
    link.symlink_to(benchmark_file)
    with pytest.raises(BenchmarkValidationError, match="不能是符号链接"):
        load_benchmark(link)
