#!/usr/bin/env python3
"""bm_transact_monitoring_service.py

Main Transact monitoring service runner.

Purpose:
- Run one or more MDP scripts (metric data points) as separate executables.
- Keep the OTEL publisher wrapper unchanged.

MDP discovery:
- By default runs the built-in list: mdp_tsm_status.py, mdp_concurrent_users.py
- Override with env var BM_MDP_SCRIPTS as a comma-separated list of script filenames.
  Example:
    BM_MDP_SCRIPTS="mdp_tsm_status.py,mdp_concurrent_users.py,mdp_business_date_offset.py"

Usage:
  ./bm_transact_monitoring_service.py            # run all configured MDPs
  ./bm_transact_monitoring_service.py --list     # print MDP list and exit
  ./bm_transact_monitoring_service.py <mdp>      # run only one MDP (by filename)

Notes:
- This runner is intentionally simple.
- Scheduling (every 5 minutes) should be done by systemd timer or cron.
"""

import os
import sys
import subprocess
from typing import List

from bm_transact_lib import publish_gauge, log, build_base_labels


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

DEFAULT_MDPS = [
    "mdp_tsm_status.py",
    "mdp_concurrent_users.py",
    "mdp_license_expiry_days.py",
    "mdp_jboss_status.py",
]


def get_mdp_list() -> List[str]:
    raw = os.environ.get("BM_MDP_SCRIPTS", "").strip()
    if not raw:
        return DEFAULT_MDPS
    return [p.strip() for p in raw.split(",") if p.strip()]


def run_mdp(script_name: str) -> int:
    path = script_name
    if not os.path.isabs(path):
        path = os.path.join(SCRIPT_DIR, script_name)

    log(f"Running MDP: {script_name}")
    try:
        subprocess.check_call([sys.executable, path])
        log(f"MDP OK: {script_name}")
        return 0
    except subprocess.CalledProcessError as e:
        log(f"MDP FAILED: {script_name} rc={e.returncode}")
        return e.returncode or 2


def publish_heartbeat():
    metric_name = os.getenv("BM_HEARTBEAT_METRIC_NAME", "bm_poc_monitoring_heartbeat")

    try:
        labels = build_base_labels(source="service")
        labels.append("component=transact_monitoring_service")

        log(f"Publishing monitoring heartbeat metric: {metric_name} value=1")
        publish_gauge(metric_name, 1, labels)
        log("Heartbeat metric published successfully")

    except Exception as e:
        log(f"ERROR publishing heartbeat: {e}")



def main() -> int:

    publish_heartbeat()

    mdps = get_mdp_list()

    if len(sys.argv) >= 2 and sys.argv[1] in ("--list", "-l"):
        for m in mdps:
            print(m)
        return 0

    # If user provides an arg, run only that one.
    if len(sys.argv) >= 2:
        target = sys.argv[1]
        if target not in mdps:
            log(f"ERROR: '{target}' is not in configured MDP list")
            log("Use --list to see available MDPs")
            return 2
        return run_mdp(target)

    # Run all
    log("Transact monitoring service started")
    rc = 0
    for m in mdps:
        r = run_mdp(m)
        if r != 0:
            rc = r
    log("Transact monitoring service completed")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())

