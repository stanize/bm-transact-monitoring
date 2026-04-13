#!/usr/bin/env python3

import os
import subprocess
from bm_transact_lib import log, publish_gauge, build_base_labels


def main() -> int:

    metric_name = os.getenv(
        "BM_JBOSS_METRIC_NAME",
        "bm_poc_jboss_status"
    )

    log("Checking JBoss service status via systemctl")

    try:
        result = subprocess.check_output(
            ["systemctl", "is-active", "jboss"],
            text=True
        ).strip()
    except Exception as e:
        log(f"ERROR checking JBoss status: {e}")
        result = "unknown"

    log(f"Raw JBoss status: '{result}'")

    value = 1 if result == "active" else 0

    labels = build_base_labels(source="system")
    labels.append("component=transact_monitoring_service")
    labels.append(f"jboss_state={result}")

    publish_gauge(metric_name, value, labels)

    log("JBoss status metric published successfully")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
