#!/usr/bin/env python3
"""bm_transact_monitoring_preflight.py

Pre-deployment preflight check for bm-transact-monitoring.

Validates that all config files, binaries, DB connectivity, OTEL network
reachability, and MDP scripts are in order before the service is started.

Usage:
  python3 bm_transact_monitoring_preflight.py

Output:
  - Printed to terminal with colour-coded results
  - Written to logs/bm-preflight.log in the same directory as this script

Exit codes:
  0  All checks passed
  1  One or more warnings (service may still work, but review recommended)
  2  One or more failures (service will likely not work correctly)
"""

import json
import os
import re
import socket
import subprocess
import sys
from datetime import datetime

# ---------------------------------------------------------------------------
# Paths — all derived from script location, no hardcoded paths
# ---------------------------------------------------------------------------
SCRIPT_DIR      = os.path.dirname(os.path.abspath(__file__))
CONFIG_DIR      = os.path.join(SCRIPT_DIR, "config")
MDP_DIR         = os.path.join(SCRIPT_DIR, "mdp")
LOG_DIR         = os.path.join(SCRIPT_DIR, "logs")
LOG_PATH        = os.path.join(LOG_DIR, "bm-preflight.log")

DB_CONFIG_PATH  = os.path.join(CONFIG_DIR, "db_config.json")
MDP_CONFIG_PATH = os.path.join(CONFIG_DIR, "mdp_config.json")
OTEL_CONFIG_PATH = os.path.join(CONFIG_DIR, "otel_config.json")
ENV_CONFIG_PATH = os.path.join(CONFIG_DIR, "env_config.json")
WRAPPER_PATH    = os.path.join(SCRIPT_DIR, "bm_otel_publish_metric.py")

# ---------------------------------------------------------------------------
# Terminal colours
# ---------------------------------------------------------------------------
_USE_COLOUR = sys.stdout.isatty()

def _c(text: str, code: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _USE_COLOUR else text

def green(t):  return _c(t, "32")
def yellow(t): return _c(t, "33")
def red(t):    return _c(t, "31")
def bold(t):   return _c(t, "1")
def cyan(t):   return _c(t, "36")

# ---------------------------------------------------------------------------
# Result tracking
# ---------------------------------------------------------------------------
PASS    = "PASS"
WARN    = "WARN"
FAIL    = "FAIL"
INFO    = "INFO"

_results = []   # list of (status, section, message)
_log_lines = []


def _record(status: str, section: str, message: str) -> None:
    _results.append((status, section, message))

    # Format for log file (no colour codes)
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    _log_lines.append(f"[{ts}] [{status:<4}] [{section}] {message}")

    # Format for terminal
    label = {
        PASS: green(f"[{PASS}]"),
        WARN: yellow(f"[{WARN}]"),
        FAIL: red(f"[{FAIL}]"),
        INFO: cyan(f"[{INFO}]"),
    }.get(status, f"[{status}]")

    print(f"  {label}  {message}")


def passed(section: str, message: str)  -> None: _record(PASS, section, message)
def warned(section: str, message: str)  -> None: _record(WARN, section, message)
def failed(section: str, message: str)  -> None: _record(FAIL, section, message)
def info(section: str, message: str)    -> None: _record(INFO, section, message)


def section_header(title: str) -> None:
    line = f"\n{bold(title)}"
    print(line)
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    _log_lines.append(f"\n[{ts}] --- {title} ---")


def pause() -> None:
    """Wait for user to press Enter before continuing to the next section."""
    try:
        input(f"\n  {cyan('Press Enter to continue...')}")
    except (EOFError, KeyboardInterrupt):
        # Non-interactive or Ctrl+C — just continue without pausing
        print()


# ---------------------------------------------------------------------------
# Log file writer
# ---------------------------------------------------------------------------
def write_log() -> None:
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        with open(LOG_PATH, "w", encoding="utf-8") as f:
            f.write(f"bm-transact-monitoring preflight check\n")
            f.write(f"Run at : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"Host   : {os.uname().nodename}\n")
            f.write(f"User   : {_current_user()}\n")
            f.write("=" * 60 + "\n")
            for line in _log_lines:
                f.write(line + "\n")
        print(f"\n  Log written to: {LOG_PATH}")
    except Exception as e:
        print(f"\n  {yellow('[WARN]')}  Could not write log file: {e}")


def _current_user() -> str:
    try:
        import pwd
        return pwd.getpwuid(os.getuid()).pw_name
    except Exception:
        return str(os.getuid())


# ---------------------------------------------------------------------------
# Check 1 — Config files
# ---------------------------------------------------------------------------
def check_config_files() -> dict:
    """
    Validate all four JSON config files.
    Returns parsed configs for use by later checks.
    """
    section_header("1. Config Files")
    configs = {}

    files = {
        "db_config.json":   DB_CONFIG_PATH,
        "mdp_config.json":  MDP_CONFIG_PATH,
        "otel_config.json": OTEL_CONFIG_PATH,
        "env_config.json":  ENV_CONFIG_PATH,
    }

    for name, path in files.items():
        sec = f"config/{name}"
        if not os.path.exists(path):
            failed(sec, f"{name} not found: {path}")
            continue
        try:
            with open(path, "r") as f:
                cfg = json.load(f)
            configs[name] = cfg
            passed(sec, f"{name} found and valid JSON")
        except json.JSONDecodeError as e:
            failed(sec, f"{name} is not valid JSON: {e}")
        except Exception as e:
            failed(sec, f"{name} could not be read: {e}")

    # --- db_config.json key validation ---
    if "db_config.json" in configs:
        db = configs["db_config.json"]
        required = ("db_host", "db_name", "db_user", "psql", "python", "service")
        missing  = [k for k in required if not db.get(k)]
        if missing:
            failed("db_config.json", f"Missing required key(s): {', '.join(missing)}")
        else:
            passed("db_config.json", f"All required keys present: {', '.join(required)}")

    # --- mdp_config.json key validation ---
    if "mdp_config.json" in configs:
        mdp = configs["mdp_config.json"]
        sec = "mdp_config.json"

        if not mdp.get("heartbeat_metric_name"):
            failed(sec, "Missing key: heartbeat_metric_name")
        else:
            passed(sec, f"heartbeat_metric_name = {mdp['heartbeat_metric_name']}")

        if not isinstance(mdp.get("interval_seconds"), int) or mdp["interval_seconds"] <= 0:
            failed(sec, "Missing or invalid key: interval_seconds (must be a positive integer)")
        else:
            passed(sec, f"interval_seconds = {mdp['interval_seconds']}")

        log_cfg = mdp.get("logging")
        if not isinstance(log_cfg, dict):
            failed(sec, "Missing section: logging")
        else:
            valid_levels = ("DEBUG", "INFO", "WARNING", "ERROR")
            level = log_cfg.get("level", "")
            if level.upper() not in valid_levels:
                failed(sec, f"logging.level '{level}' is invalid. Must be one of: {', '.join(valid_levels)}")
            else:
                passed(sec, f"logging.level = {level}")

            for key in ("max_bytes", "backup_count"):
                if log_cfg.get(key) is None:
                    failed(sec, f"logging section missing key: {key}")
                else:
                    passed(sec, f"logging.{key} = {log_cfg[key]}")

        scripts = mdp.get("mdp_scripts")
        if not isinstance(scripts, list) or not scripts:
            failed(sec, "mdp_scripts list is missing or empty")
        else:
            passed(sec, f"mdp_scripts contains {len(scripts)} entries")
            for i, entry in enumerate(scripts):
                for field in ("script", "metric_name", "enabled"):
                    if field not in entry:
                        failed(sec, f"mdp_scripts entry {i} missing field '{field}'")
                if entry.get("enabled") not in ("y", "n"):
                    failed(sec, f"mdp_scripts entry {i} ('{entry.get('script')}') "
                                f"has invalid enabled value: '{entry.get('enabled')}'")

    # --- otel_config.json key validation ---
    if "otel_config.json" in configs:
        otel = configs["otel_config.json"]
        sec  = "otel_config.json"
        required = ("endpoint", "service_name", "export_interval_ms")
        missing  = [k for k in required if otel.get(k) is None]
        if missing:
            failed(sec, f"Missing required key(s): {', '.join(missing)}")
        else:
            passed(sec, f"All required keys present")
            info(sec, f"endpoint         = {otel['endpoint']}")
            info(sec, f"service_name     = {otel['service_name']}")
            info(sec, f"export_interval  = {otel['export_interval_ms']}ms")

    # --- env_config.json hostname check ---
    if "env_config.json" in configs:
        env_cfg  = configs["env_config.json"]
        sec      = "env_config.json"
        hostname = os.uname().nodename
        env_map  = env_cfg.get("env_map", [])

        if not isinstance(env_map, list) or not env_map:
            failed(sec, "env_map is missing or empty")
        else:
            passed(sec, f"env_map contains {len(env_map)} hostname entries")
            match = next((e for e in env_map if e.get("hostname") == hostname), None)
            if match:
                passed(sec, f"Current hostname '{hostname}' found → env = {match['env']}")
            else:
                warned(sec, f"Current hostname '{hostname}' not found in env_map — "
                            f"hostname will be used as env label")

    return configs


# ---------------------------------------------------------------------------
# Check 2 — Binaries and paths
# ---------------------------------------------------------------------------
def check_binaries(configs: dict) -> None:
    section_header("2. Binaries and Paths")
    sec = "binaries"

    db_cfg = configs.get("db_config.json", {})

    # psql
    psql = db_cfg.get("psql", "")
    if not psql:
        failed(sec, "psql path not available (db_config.json missing or invalid)")
    elif not os.path.exists(psql):
        failed(sec, f"psql not found: {psql}")
    elif not os.access(psql, os.X_OK):
        failed(sec, f"psql exists but is not executable: {psql}")
    else:
        try:
            ver = subprocess.check_output([psql, "--version"], text=True).strip()
            passed(sec, f"psql executable: {psql}  ({ver})")
        except Exception as e:
            warned(sec, f"psql found but version check failed: {e}")

    # python
    python = db_cfg.get("python", "")
    if not python:
        failed(sec, "python path not available (db_config.json missing or invalid)")
    elif not os.path.exists(python):
        failed(sec, f"python not found: {python}")
    elif not os.access(python, os.X_OK):
        failed(sec, f"python exists but is not executable: {python}")
    else:
        try:
            ver = subprocess.check_output([python, "--version"], text=True,
                                          stderr=subprocess.STDOUT).strip()
            passed(sec, f"python executable: {python}  ({ver})")
        except Exception as e:
            warned(sec, f"python found but version check failed: {e}")

    # otel wrapper (co-located)
    if not os.path.exists(WRAPPER_PATH):
        failed(sec, f"bm_otel_publish_metric.py not found: {WRAPPER_PATH}")
    else:
        passed(sec, f"bm_otel_publish_metric.py found: {WRAPPER_PATH}")

    # logs directory — writable or creatable
    if os.path.exists(LOG_DIR):
        if os.access(LOG_DIR, os.W_OK):
            passed(sec, f"logs/ directory exists and is writable: {LOG_DIR}")
        else:
            failed(sec, f"logs/ directory exists but is not writable: {LOG_DIR}")
    else:
        # Try to create it
        try:
            os.makedirs(LOG_DIR, exist_ok=True)
            passed(sec, f"logs/ directory created: {LOG_DIR}")
        except Exception as e:
            failed(sec, f"logs/ directory does not exist and could not be created: {e}")

    # pgpass
    pgpass = os.path.expanduser("~/.pgpass")
    if os.path.exists(pgpass):
        mode = oct(os.stat(pgpass).st_mode)[-3:]
        if mode == "600":
            passed(sec, f".pgpass found with correct permissions (600): {pgpass}")
        else:
            warned(sec, f".pgpass found but permissions are {mode} — should be 600: {pgpass}")
    else:
        warned(sec, f".pgpass not found at {pgpass} — DB connection may fail if password is required")


# ---------------------------------------------------------------------------
# Check 3 — Database connectivity
# ---------------------------------------------------------------------------
def check_database(configs: dict) -> None:
    section_header("3. Database Connectivity")
    sec = "database"

    db_cfg = configs.get("db_config.json", {})
    if not db_cfg:
        failed(sec, "Skipping — db_config.json not available")
        return

    db_host = db_cfg.get("db_host", "")
    db_name = db_cfg.get("db_name", "")
    db_user = db_cfg.get("db_user", "")
    psql    = db_cfg.get("psql", "")

    if not all([db_host, db_name, db_user, psql]):
        failed(sec, "Skipping — one or more required db_config.json values are missing")
        return

    info(sec, f"Connecting to host={db_host} db={db_name} user={db_user}")

    # TCP reachability first
    try:
        sock = socket.create_connection((db_host, 5432), timeout=5)
        sock.close()
        passed(sec, f"TCP connection to {db_host}:5432 succeeded")
    except Exception as e:
        failed(sec, f"TCP connection to {db_host}:5432 failed: {e}")
        return  # no point running psql if TCP is down

    # psql SELECT 1
    try:
        cmd = [psql, "-h", db_host, "-U", db_user, "-d", db_name,
               "-t", "-A", "-c", "SELECT 1"]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if result.returncode == 0 and result.stdout.strip() == "1":
            passed(sec, f"psql SELECT 1 succeeded — DB connection is working")
        else:
            stderr = result.stderr.strip().splitlines()[0] if result.stderr.strip() else "no detail"
            failed(sec, f"psql SELECT 1 failed (rc={result.returncode}): {stderr}")
    except subprocess.TimeoutExpired:
        failed(sec, "psql SELECT 1 timed out after 10s")
    except Exception as e:
        failed(sec, f"psql SELECT 1 raised an exception: {e}")

    # Quick DB version info
    try:
        cmd = [psql, "-h", db_host, "-U", db_user, "-d", db_name,
               "-t", "-A", "-c", "SELECT version()"]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            version_line = result.stdout.strip().splitlines()[0]
            info(sec, f"DB version: {version_line}")
    except Exception:
        pass  # version info is nice-to-have, not a check


# ---------------------------------------------------------------------------
# Check 4 — OTEL network reachability
# ---------------------------------------------------------------------------
def check_otel(configs: dict) -> None:
    section_header("4. OTEL Collector Reachability")
    sec = "otel"

    otel_cfg = configs.get("otel_config.json", {})
    if not otel_cfg:
        failed(sec, "Skipping — otel_config.json not available")
        return

    endpoint = otel_cfg.get("endpoint", "")
    if not endpoint:
        failed(sec, "Skipping — endpoint missing from otel_config.json")
        return

    # Parse host and port from endpoint URL
    match = re.match(r"https?://([^:/]+)(?::(\d+))?", endpoint)
    if not match:
        failed(sec, f"Could not parse host/port from endpoint: {endpoint}")
        return

    host = match.group(1)
    port = int(match.group(2)) if match.group(2) else 4317

    info(sec, f"Checking TCP reachability: {host}:{port}")

    try:
        sock = socket.create_connection((host, port), timeout=5)
        sock.close()
        passed(sec, f"TCP connection to {host}:{port} succeeded — collector is reachable")
    except socket.timeout:
        failed(sec, f"TCP connection to {host}:{port} timed out — collector may be down or firewalled")
    except ConnectionRefusedError:
        failed(sec, f"TCP connection to {host}:{port} refused — collector is not listening on this port")
    except Exception as e:
        failed(sec, f"TCP connection to {host}:{port} failed: {e}")


# ---------------------------------------------------------------------------
# Check 5 — MDP scripts
# ---------------------------------------------------------------------------
def check_mdp_scripts(configs: dict) -> None:
    section_header("5. MDP Scripts")
    sec = "mdp_scripts"

    mdp_cfg = configs.get("mdp_config.json", {})
    scripts = mdp_cfg.get("mdp_scripts", [])

    if not scripts:
        failed(sec, "Skipping — mdp_scripts not available")
        return

    if not os.path.isdir(MDP_DIR):
        failed(sec, f"mdp/ directory not found: {MDP_DIR}")
        return

    passed(sec, f"mdp/ directory found: {MDP_DIR}")

    enabled_count  = 0
    disabled_count = 0
    missing_count  = 0

    for entry in scripts:
        name    = entry.get("script", "")
        enabled = entry.get("enabled", "n")
        path    = os.path.join(MDP_DIR, name)

        if not os.path.exists(path):
            failed(sec, f"Script not found: {name}")
            missing_count += 1
        elif not os.access(path, os.R_OK):
            failed(sec, f"Script exists but is not readable: {name}")
            missing_count += 1
        else:
            status = "enabled" if enabled == "y" else "disabled"
            info(sec, f"{name:<45} [{status}]")
            if enabled == "y":
                enabled_count += 1
            else:
                disabled_count += 1

    passed(sec, f"{enabled_count} enabled, {disabled_count} disabled, {missing_count} missing")
    if missing_count:
        failed(sec, f"{missing_count} script(s) listed in mdp_config.json were not found in mdp/")


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
def print_summary() -> int:
    section_header("Summary")

    passes   = [(s, m) for (st, s, m) in _results if st == PASS]
    warnings = [(s, m) for (st, s, m) in _results if st == WARN]
    failures = [(s, m) for (st, s, m) in _results if st == FAIL]

    print(f"  {green(f'{len(passes)} passed')}  |  "
          f"{yellow(f'{len(warnings)} warnings')}  |  "
          f"{red(f'{len(failures)} failed')}")

    if failures:
        print(f"\n  {bold(red('FAILURES:'))}")
        for s, m in failures:
            print(f"    {red('✗')}  [{s}] {m}")

    if warnings:
        print(f"\n  {bold(yellow('WARNINGS:'))}")
        for s, m in warnings:
            print(f"    {yellow('!')}  [{s}] {m}")

    if not failures and not warnings:
        print(f"\n  {bold(green('All checks passed — ready to deploy.'))} ")
    elif not failures:
        print(f"\n  {bold(yellow('Checks passed with warnings — review before deploying.'))}")
    else:
        print(f"\n  {bold(red('One or more checks failed — do not start the service until resolved.'))}")

    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    _log_lines.append(f"\n[{ts}] SUMMARY: {len(passes)} passed, "
                      f"{len(warnings)} warnings, {len(failures)} failed")

    if failures:
        return 2
    if warnings:
        return 1
    return 0


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> int:
    print(bold(f"\nbm-transact-monitoring — Preflight Check"))
    print(f"  Host : {os.uname().nodename}")
    print(f"  User : {_current_user()}")
    print(f"  Dir  : {SCRIPT_DIR}")
    print(f"  Time : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    _log_lines.append(f"Host : {os.uname().nodename}")
    _log_lines.append(f"User : {_current_user()}")
    _log_lines.append(f"Dir  : {SCRIPT_DIR}")
    _log_lines.append(f"Time : {ts}")

    configs = check_config_files()
    pause()
    check_binaries(configs)
    pause()
    check_database(configs)
    pause()
    check_otel(configs)
    pause()
    check_mdp_scripts(configs)
    pause()

    rc = print_summary()
    write_log()

    return rc


if __name__ == "__main__":
    raise SystemExit(main())
