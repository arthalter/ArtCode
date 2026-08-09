from __future__ import annotations

import argparse
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CRITICAL_SUFFIXES = (
    "artcode/config.py",
    "artcode/providers/deepseek.py",
    "artcode/providers/sse.py",
    "artcode/conversation/context.py",
    "artcode/context_management/retention.py",
    "artcode/persistence/sessions.py",
    "artcode/permissions/service.py",
    "artcode/tools/filesystem.py",
    "artcode/tools/process.py",
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--coverage-json", type=Path, default=ROOT / "coverage.json")
    parser.add_argument("--line-min", type=float, default=95.0)
    parser.add_argument("--branch-min", type=float, default=90.0)
    parser.add_argument("--critical-branch-min", type=float, default=95.0)
    args = parser.parse_args()

    payload = json.loads(args.coverage_json.read_text())
    totals = payload["totals"]
    failures: list[str] = []
    line = float(totals["percent_covered"])
    branch = 100.0 * totals["covered_branches"] / max(1, totals["num_branches"])
    if line < args.line_min:
        failures.append(f"line={line:.2f} < {args.line_min:.2f}")
    if branch < args.branch_min:
        failures.append(f"branch={branch:.2f} < {args.branch_min:.2f}")

    files = payload["files"]
    for suffix in CRITICAL_SUFFIXES:
        match = next((data for name, data in files.items() if name.endswith(suffix)), None)
        if match is None:
            failures.append(f"missing critical coverage: {suffix}")
            continue
        summary = match["summary"]
        percent = 100.0 * summary["covered_branches"] / max(1, summary["num_branches"])
        if percent < args.critical_branch_min:
            failures.append(f"{suffix} branch={percent:.2f} < {args.critical_branch_min:.2f}")

    print(f"line={line:.2f} branch={branch:.2f}")
    if failures:
        print("coverage gate failed: " + "; ".join(failures))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
