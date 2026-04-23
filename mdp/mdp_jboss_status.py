#!/usr/bin/env python3
"""mdp_jboss_status.py

MDP: JBoss service status
- Checks JBoss service state via systemctl
- Publishes a gauge metric (1=active, 0=anything else)

Requires:
  - bm_otel_publish_metric.py available (BM_OTEL_WRAPPER)

Manual test:
  python3 mdp_jboss_status.py
"""

import os
import sys
import subprocess

from bm_transact_lib import log, publish_gauge, build_base_labels, get_metric_name

SCRIPT_NAME = os.path.basename(__file__)


def main() -> int:
    metric_name = get_metric_name(__file__)

    try:
        result = subprocess.run(
            ["systemctl", "is-active", "jboss"],
            text=True,
            capture_output=True,
        )
        state = result.stdout.strip() or "unknown"
        value = 1 if state == "active" else 0

        labels = build_base_labels(source="system")
        labels.append("component=transact_monitoring_service")
        labels.append(f"jboss_state={state}")

        publish_gauge(metric_name, value, labels)
        log(f"{metric_name} = {value} [{SCRIPT_NAME}]")
        return 0

    except Exception as e:
        log(f"ERROR [{SCRIPT_NAME}]: {e}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
