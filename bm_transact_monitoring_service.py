#!/usr/bin/env python3
"""bm_transact_monitoring_service.py

Main Transact monitoring service runner.

Purpose:
- Run one or more MDP scripts (metric data points) as separate executables.
- Keep the OTEL publisher wrapper unchanged.

MDP discovery:
- Reads mdp_scripts from mdp_config.json (must be in the same directory as this script).
- Each entry has: script, metric_name, enabled.
- If the config file is missing or unreadable, the service exits with an error.
- Disabled entries (enabled: "n") are skipped with a log message.
- Each MDP script resolves its own metric name from the config via get_metric_name(__file__).

Usage:
  ./bm_transact_monitoring_service.py            # run all enabled MDPs
  ./bm_transact_monitoring_service.py --list     # print MDP list and exit
  ./bm_transact_monitoring_service.py <mdp>      # run only one MDP (by filename)

Notes:
- This runner is intentionally simple.
- Scheduling (every 5 minutes) should be done by systemd timer or cron.
"""

import os
import sys
import subprocess
from typing import Dict

from bm_transact_lib import publish_gauge, log, build_base_labels, _load_config


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


def mlog(msg: str) -> None:
    """Monitoring service log — always prefixed with [MONITOR]."""
    log(msg, prefix="MONITOR")


def run_mdp(entry: Dict) -> int:
    script_name = entry["script"]
    path = os.path.join(SCRIPT_DIR, script_name)

    mlog(f"Running MDP: {script_name} metric={entry['metric_name']}")
    try:
        subprocess.check_call([sys.executable, path])
        mlog(f"MDP OK: {script_name}")
        return 0
    except subprocess.CalledProcessError as e:
        mlog(f"MDP FAILED: {script_name} rc={e.returncode}")
        return e.returncode or 2


def publish_heartbeat():
    metric_name = os.getenv("BM_HEARTBEAT_METRIC_NAME", "bm_poc_monitoring_heartbeat")

    try:
        labels = build_base_labels(source="service")
        labels.append("component=transact_monitoring_service")

        mlog(f"Publishing heartbeat: {metric_name} = 1")
        publish_gauge(metric_name, 1, labels)
        mlog("Heartbeat published successfully")

    except Exception as e:
        mlog(f"ERROR publishing heartbeat: {e}")


def main() -> int:

    publish_heartbeat()

    entries = _load_config()

    if len(sys.argv) >= 2 and sys.argv[1] in ("--list", "-l"):
        for e in entries:
            status = "enabled" if e["enabled"] == "y" else "disabled"
            print(f"{e['script']:<40} {e['metric_name']:<45} [{status}]")
        return 0

    # If user provides an arg, run only that one (regardless of enabled flag)
    if len(sys.argv) >= 2:
        target = sys.argv[1]
        matched = [e for e in entries if e["script"] == target]
        if not matched:
            mlog(f"ERROR: '{target}' is not in configured MDP list")
            mlog("Use --list to see available MDPs")
            return 2
        return run_mdp(matched[0])

    # Run all enabled
    mlog("Transact monitoring service started")
    rc = 0
    for entry in entries:
        if entry["enabled"] == "n":
            mlog(f"SKIPPED (disabled): {entry['script']}")
            continue
        r = run_mdp(entry)
        if r != 0:
            rc = r
    mlog("Transact monitoring service completed")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
