#!/usr/bin/env python3
"""mdp_memory_used_mb.py

MDP: Memory used (MB)
- Reads used memory from `free -m`
- Publishes used MB as a gauge metric

Requires:
  - bm_otel_publish_metric.py available (BM_OTEL_WRAPPER)

Manual test:
  python3 mdp_memory_used_mb.py
"""

import os
import subprocess

from bm_transact_lib import log, build_base_labels, publish_gauge, get_metric_name

SCRIPT_NAME = os.path.basename(__file__)


def get_memory_used_mb() -> int:
    result = subprocess.run(["free", "-m"], text=True, capture_output=True)
    for line in result.stdout.splitlines():
        if line.startswith("Mem:"):
            parts = line.split()
            return int(parts[2])  # used column
    raise RuntimeError("Could not parse memory usage from free -m")


def main() -> int:
    metric_name = get_metric_name(__file__)

    try:
        used_mb = get_memory_used_mb()
        publish_gauge(
            metric_name,
            used_mb,
            build_base_labels(source="system") + [
                "component=memory",
            ],
        )
        log(f"{metric_name} = {used_mb} [{SCRIPT_NAME}]")
        return 0

    except Exception as e:
        log(f"ERROR [{SCRIPT_NAME}]: {e}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
