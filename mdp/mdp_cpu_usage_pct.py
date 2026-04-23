#!/usr/bin/env python3
"""mdp_cpu_usage_pct.py

MDP: CPU usage percentage
- Takes a single CPU snapshot using `top -bn1`
- Extracts idle % and calculates used % as (100 - idle)
- Publishes CPU used percentage as a gauge metric

Requires:
  - bm_otel_publish_metric.py available (BM_OTEL_WRAPPER)

Manual test:
  python3 mdp_cpu_usage_pct.py
"""

import os
import re
import subprocess

from bm_transact_lib import log, build_base_labels, publish_gauge, get_metric_name

SCRIPT_NAME = os.path.basename(__file__)


def get_cpu_usage_pct() -> float:
    result = subprocess.run(["top", "-bn1"], text=True, capture_output=True)
    for line in result.stdout.splitlines():
        if "Cpu(s)" in line or "%Cpu" in line:
            match = re.search(r"(\d+[\.,]\d+)\s*id", line)
            if match:
                idle = float(match.group(1).replace(",", "."))
                return round(100.0 - idle, 2)
    raise RuntimeError("Could not parse CPU usage from top -bn1")


def main() -> int:
    metric_name = get_metric_name(__file__)

    try:
        cpu_pct = get_cpu_usage_pct()
        publish_gauge(
            metric_name,
            cpu_pct,
            build_base_labels(source="system") + [
                "component=cpu",
            ],
        )
        log(f"{metric_name} = {cpu_pct} [{SCRIPT_NAME}]")
        return 0

    except Exception as e:
        log(f"ERROR [{SCRIPT_NAME}]: {e}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
