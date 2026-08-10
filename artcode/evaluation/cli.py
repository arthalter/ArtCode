from __future__ import annotations

import argparse
import asyncio
import sys
from contextlib import AsyncExitStack
from pathlib import Path

from artcode.config import load_config
from artcode.providers import DeepSeekChatProvider

from .compare import (
    ReportComparisonError,
    compare_reports,
    load_report,
    write_comparison,
)
from .judge import LlmJudge
from .manifest import BenchmarkValidationError, load_benchmark
from .redaction import Redactor
from .runner import EvaluationRunner


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="artcode-eval",
        description="ArtCode 本地 Agent 评测与审计工具",
    )
    subcommands = parser.add_subparsers(dest="command", required=True)

    validate = subcommands.add_parser("validate", help="严格校验 Benchmark")
    validate.add_argument("benchmark", type=Path)

    run = subcommands.add_parser("run", help="运行 Agent Benchmark")
    run.add_argument("benchmark", type=Path)
    run.add_argument("--config", type=Path, required=True, help="被测 Agent 配置")
    run.add_argument(
        "--output-dir",
        type=Path,
        default=Path("artcode-eval-runs"),
        help="评测运行根目录",
    )
    run.add_argument("--judge-config", type=Path, help="可选独立 Judge 配置")

    compare = subcommands.add_parser("compare", help="对比两份评测报告")
    compare.add_argument("baseline", type=Path)
    compare.add_argument("candidate", type=Path)
    compare.add_argument(
        "--output-dir",
        type=Path,
        default=Path("artcode-eval-compare"),
    )
    compare.add_argument("--allow-incompatible", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "validate":
            benchmark = load_benchmark(args.benchmark)
            print(
                f"Benchmark 有效：{benchmark.name} | tasks={len(benchmark.tasks)} | "
                f"sha256={benchmark.fingerprint}"
            )
            return 0
        if args.command == "compare":
            baseline = load_report(args.baseline)
            candidate = load_report(args.candidate)
            comparison = compare_reports(
                baseline,
                candidate,
                allow_incompatible=args.allow_incompatible,
            )
            json_path, markdown_path = write_comparison(
                args.output_dir.expanduser().resolve(),
                comparison,
                redactor=Redactor(),
            )
            print(f"对比完成：{json_path}")
            print(f"Markdown：{markdown_path}")
            return 0
        return asyncio.run(_run_benchmark(args))
    except KeyboardInterrupt:
        print("评测已由用户中断；已完成证据已保留。", file=sys.stderr)
        return 130
    except (BenchmarkValidationError, ReportComparisonError, OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"评测工具无法运行：{exc}", file=sys.stderr)
        return 2


async def _run_benchmark(args: argparse.Namespace) -> int:
    benchmark = load_benchmark(args.benchmark)
    agent_config = load_config(args.config)
    judge_config = load_config(args.judge_config) if args.judge_config else None
    secrets = [agent_config.api_key]
    if judge_config is not None:
        secrets.append(judge_config.api_key)
    redactor = Redactor(secrets)
    async with AsyncExitStack() as resources:
        judge = None
        if judge_config is not None:
            provider = DeepSeekChatProvider(judge_config)
            resources.push_async_callback(provider.close)
            judge = LlmJudge(provider, redactor)
        runner = EvaluationRunner(
            config_path=args.config,
            output_root=args.output_dir,
            redactor=redactor,
            judge=judge,
            repository=_repository_root(Path.cwd()),
            model_info={
                "protocol": agent_config.protocol,
                "model": agent_config.model,
                "base_url": redactor.redact(agent_config.base_url),
                "thinking_enabled": agent_config.thinking.enabled,
                "judge_enabled": judge is not None,
                "judge_model": judge_config.model if judge_config is not None else None,
                "judge_uses_same_config": (
                    args.config.expanduser().resolve()
                    == args.judge_config.expanduser().resolve()
                    if args.judge_config is not None
                    else None
                ),
            },
        )
        result = await runner.run(benchmark)
    passed = sum(item.status.value == "passed" for item in result.attempts)
    print(
        f"评测完成：passed={passed}/{len(result.attempts)} | "
        f"report={result.report_json}"
    )
    print(f"Markdown：{result.report_markdown}")
    if result.interrupted:
        return 130
    return 0 if result.passed else 1


def _repository_root(start: Path) -> Path | None:
    current = start.resolve()
    for candidate in (current, *current.parents):
        if (candidate / ".git").exists():
            return candidate
    return None


__all__ = ["build_parser", "main"]
