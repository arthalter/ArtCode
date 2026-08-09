from __future__ import annotations

import argparse
import subprocess
import sys
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def collect_node_ids(marker: str | None = None) -> list[str]:
    command = [sys.executable, "-m", "pytest", "--collect-only", "-q"]
    if marker:
        command.extend(("-m", marker))
    result = subprocess.run(command, cwd=ROOT, check=False, capture_output=True, text=True)
    if result.returncode != 0:
        sys.stderr.write(result.stdout)
        sys.stderr.write(result.stderr)
        raise SystemExit(result.returncode)
    return [line for line in result.stdout.splitlines() if "::" in line and not line.startswith("<")]


def category(node_id: str) -> str:
    if node_id.startswith("tests/unit/"):
        return "unit"
    if node_id.startswith("tests/integration/"):
        return "integration"
    if node_id.startswith(("tests/property/", "tests/fault/")):
        return "property_fault"
    if node_id.startswith("tests/live/"):
        return "live"
    if node_id.startswith("tests/soak/"):
        return "soak"
    return "other"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", type=int, required=True)
    parser.add_argument("--unit-min", type=int, default=0)
    parser.add_argument("--integration-min", type=int, default=0)
    parser.add_argument("--property-fault-min", type=int, default=0)
    parser.add_argument("--live-min", type=int, default=0)
    parser.add_argument("--soak-min", type=int, default=0)
    parser.add_argument("--total-min", type=int, default=0)
    args = parser.parse_args()

    all_nodes = collect_node_ids()
    new_nodes = collect_node_ids("ch10_5")
    duplicates = [node for node, count in Counter(all_nodes).items() if count > 1]
    if duplicates:
        print("duplicate node IDs:", *duplicates, sep="\n", file=sys.stderr)
        return 1

    counts = Counter(category(node) for node in new_nodes)
    expected = {
        "unit": args.unit_min,
        "integration": args.integration_min,
        "property_fault": args.property_fault_min,
        "live": args.live_min,
        "soak": args.soak_min,
    }
    failures = [f"{name}={counts[name]} < {minimum}" for name, minimum in expected.items() if counts[name] < minimum]
    if len(all_nodes) < max(args.baseline, args.total_min):
        failures.append(f"total={len(all_nodes)} < {max(args.baseline, args.total_min)}")
    if len(all_nodes) - len(new_nodes) < args.baseline:
        failures.append(
            f"non_ch10_5={len(all_nodes) - len(new_nodes)} < baseline={args.baseline}"
        )

    print(f"total={len(all_nodes)} baseline={args.baseline} ch10_5={len(new_nodes)}")
    for name in ("unit", "integration", "property_fault", "live", "soak", "other"):
        print(f"{name}={counts[name]}")
    if failures:
        print("inventory gate failed: " + "; ".join(failures), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
