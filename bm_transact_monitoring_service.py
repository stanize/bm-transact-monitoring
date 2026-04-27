#!/usr/bin/env python3
"""bm_transact_monitoring_service.py

Main Transact monitoring service runner.

Purpose:
- Run as a long-running systemd service.
- Execute all enabled MDP scripts on a fixed interval (configured in mdp_config.json).
- Publish a heartbeat metric on every cycle.
- Log to logs/bm-transact-monitoring.log with rotation.

MDP discovery:
- Reads mdp_scripts from config/mdp_config.json.
- Each entry has: script, metric_name, enabled.
- If the config file is missing or unreadable, the service exits with an error.
- Disabled entries (enabled: "n") are skipped with a log message.

Scheduling:
- Runs on a fixed interval — wall-clock aligned within each session.
- If scripts take 30s and interval is 300s, the next cycle starts at 300s,
  not at 330s.
- If scripts ever exceed the interval, the next cycle starts immediately
  with a warning logged.

Usage:
  ./bm_transact_monitoring_service.py            # run as continuous service
  ./bm_transact_monitoring_service.py --list     # print MDP list and exit
  ./bm_transact_monitoring_service.py <mdp>      # run only one MDP and exit
"""

import os
import signal
import sys
import time
import subprocess
from typing import Dict

from bm_transact_lib import (
    audit, log, log_warning, log_error,
    publish_gauge, build_base_labels,
    _load_config, get_service_config, setup_logging,
)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
MDP_DIR    = os.path.join(SCRIPT_DIR, "mdp")

# ---------------------------------------------------------------------------
# Graceful shutdown
# ---------------------------------------------------------------------------
_shutdown_requested = False


def _handle_signal(signum, frame) -> None:
    global _shutdown_requested
    _shutdown_requested = True
    audit(f"Shutdown signal received (signal {signum}) — will stop after current cycle")


signal.signal(signal.SIGTERM, _handle_signal)
signal.signal(signal.SIGINT,  _handle_signal)


# ---------------------------------------------------------------------------
# MDP runner
# ---------------------------------------------------------------------------
def run_mdp(entry: Dict) -> int:
    script_name = entry["script"]
    path = os.path.join(MDP_DIR, script_name)

    log(f"Running MDP: {script_name}", prefix="MONITOR")
    try:
        env = os.environ.copy()
        env["PYTHONPATH"] = SCRIPT_DIR + os.pathsep + env.get("PYTHONPATH", "")
        subprocess.check_call([sys.executable, path], env=env)
        log(f"{script_name} completed (rc=0)", prefix="MONITOR")
        return 0
    except subprocess.CalledProcessError as e:
        log_error(f"MDP FAILED: {script_name} rc={e.returncode}", prefix="MONITOR")
        return e.returncode or 2


# ---------------------------------------------------------------------------
# Heartbeat
# ---------------------------------------------------------------------------
def publish_heartbeat(metric_name: str) -> None:
    labels = build_base_labels(source="service")
    labels.append("component=transact_monitoring_service")
    publish_gauge(metric_name, 1, labels)


# ---------------------------------------------------------------------------
# Single cycle — run all enabled MDPs
# ---------------------------------------------------------------------------
def run_cycle(entries, heartbeat_metric: str, cycle_num: int) -> None:
    cycle_start = time.monotonic()
    audit(f"---- Cycle {cycle_num} started ----")

    # Heartbeat
    try:
        publish_heartbeat(heartbeat_metric)
        log(f"Heartbeat published: {heartbeat_metric} = 1", prefix="MONITOR")
    except Exception as e:
        log_error(f"Failed to publish heartbeat: {e}", prefix="MONITOR")

    enabled = [e for e in entries if e["enabled"] == "y"]
    skipped = [e for e in entries if e["enabled"] == "n"]

    for e in skipped:
        log(f"SKIPPED (disabled): {e['script']}", prefix="MONITOR")

    ok = 0
    failed = 0
    for entry in enabled:
        r = run_mdp(entry)
        if r == 0:
            ok += 1
        else:
            failed += 1

    elapsed = time.monotonic() - cycle_start
    audit(
        f"Cycle {cycle_num} finished — "
        f"{len(enabled)} MDPs ran, {ok} ok, {failed} failed, "
        f"duration={elapsed:.1f}s"
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main() -> int:
    svc_cfg   = get_service_config()
    log_cfg   = svc_cfg["logging"]
    interval  = svc_cfg["interval_seconds"]
    heartbeat = svc_cfg["heartbeat_metric_name"]

    setup_logging(
        level_name   = log_cfg["level"],
        max_bytes    = log_cfg["max_bytes"],
        backup_count = log_cfg["backup_count"],
    )

    entries = _load_config()

    # --list
    if len(sys.argv) >= 2 and sys.argv[1] in ("--list", "-l"):
        for e in entries:
            status = "enabled" if e["enabled"] == "y" else "disabled"
            print(f"{e['script']:<40} {e['metric_name']:<45} [{status}]")
        return 0

    # single MDP run (debug / manual)
    if len(sys.argv) >= 2:
        target  = sys.argv[1]
        matched = [e for e in entries if e["script"] == target]
        if not matched:
            log_error(f"'{target}' is not in configured MDP list. Use --list to see available MDPs.",
                      prefix="MONITOR")
            return 2
        setup_logging(level_name="DEBUG", max_bytes=log_cfg["max_bytes"],
                      backup_count=log_cfg["backup_count"])
        return run_mdp(matched[0])

    # --- continuous service loop ---
    pid = os.getpid()
    audit(f"Service started (pid={pid}, interval={interval}s, "
          f"log_level={log_cfg['level']}, log={os.path.join(SCRIPT_DIR, 'logs', 'bm-transact-monitoring.log')})")

    cycle_num = 0
    try:
        while not _shutdown_requested:
            cycle_num += 1
            cycle_start = time.monotonic()

            run_cycle(entries, heartbeat, cycle_num)

            if _shutdown_requested:
                break

            elapsed  = time.monotonic() - cycle_start
            sleep_for = interval - elapsed

            if sleep_for <= 0:
                log_warning(
                    f"Cycle {cycle_num} took {elapsed:.1f}s which exceeds interval {interval}s "
                    f"— next cycle starting immediately",
                    prefix="MONITOR",
                )
            else:
                log(f"Next cycle in {sleep_for:.0f}s", prefix="MONITOR")
                # Sleep in short chunks so we can respond to shutdown signals promptly
                deadline = time.monotonic() + sleep_for
                while time.monotonic() < deadline and not _shutdown_requested:
                    time.sleep(min(1.0, deadline - time.monotonic()))

    except Exception as e:
        log_error(f"Unexpected error in service loop: {e}", prefix="MONITOR")
        audit(f"Service terminated unexpectedly after {cycle_num} cycle(s): {e}")
        return 1

    audit(f"Service stopped cleanly after {cycle_num} cycle(s) (pid={pid})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
