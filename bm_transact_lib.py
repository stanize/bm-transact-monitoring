#!/usr/bin/env python3
"""bm_transact_lib.py

Shared helpers for Transact monitoring MDP scripts.

All configuration is loaded exclusively from JSON files under config/.
There are no environment variable fallbacks and no hard-coded defaults —
if a required config file is missing, unreadable, or incomplete the
process exits with rc=2 immediately.

  config/db_config.json   — DB connectivity, tool paths, service identity
  config/mdp_config.json  — MDP script registry and heartbeat metric name
  config/env_config.json  — hostname → ENV label map

db_config.json required keys:
  db_host     PostgreSQL hostname
  db_name     PostgreSQL database name
  db_user     PostgreSQL user  (pgpass supplies the password)
  psql        Absolute path to psql binary
  python      Absolute path to python3 binary
  service     Service label reported in metrics

Runtime-derived (not config values):
  vm          Taken from os.uname().nodename — always the current machine
  wrapper     Always co-located: <script_dir>/bm_otel_publish_metric.py

Each MDP script should:
  - call get_metric_name(__file__) to resolve its metric name from the config
  - call build_base_labels()
  - call publish_gauge(...)

No OTEL logic lives here (it delegates to bm_otel_publish_metric.py).
"""

import json
import os
import subprocess
from datetime import datetime
from typing import Dict, List

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
SCRIPT_DIR      = os.path.dirname(os.path.abspath(__file__))
DB_CONFIG_PATH  = os.path.join(SCRIPT_DIR, "config", "db_config.json")
MDP_CONFIG_PATH = os.path.join(SCRIPT_DIR, "config", "mdp_config.json")
ENV_CONFIG_PATH = os.path.join(SCRIPT_DIR, "config", "env_config.json")


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
def log(msg: str, prefix: str = "MDP") -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] [{prefix}] {msg}")


# ---------------------------------------------------------------------------
# Config loaders — all raise SystemExit(2) on any failure
# ---------------------------------------------------------------------------
_DB_REQUIRED_KEYS = ("db_host", "db_name", "db_user", "psql", "python", "service")


def _load_db_config() -> Dict[str, str]:
    """
    Load and validate config/db_config.json.
    Raises SystemExit(2) if the file is missing, unreadable, corrupt,
    or if any required key is absent or blank.
    """
    if not os.path.exists(DB_CONFIG_PATH):
        log(f"ERROR: db_config.json not found: {DB_CONFIG_PATH}")
        raise SystemExit(2)

    try:
        with open(DB_CONFIG_PATH, "r") as f:
            cfg = json.load(f)
    except Exception as e:
        log(f"ERROR: Failed to parse db_config.json: {e}")
        raise SystemExit(2)

    missing = [k for k in _DB_REQUIRED_KEYS if not cfg.get(k)]
    if missing:
        log(f"ERROR: db_config.json is missing required key(s): {', '.join(missing)}")
        raise SystemExit(2)

    return cfg


def _load_mdp_config() -> Dict:
    """
    Load and validate config/mdp_config.json.
    Raises SystemExit(2) if the file is missing, unreadable, corrupt,
    or if the mdp_scripts list is absent/empty/malformed.
    """
    if not os.path.exists(MDP_CONFIG_PATH):
        log(f"ERROR: mdp_config.json not found: {MDP_CONFIG_PATH}")
        raise SystemExit(2)

    try:
        with open(MDP_CONFIG_PATH, "r") as f:
            config = json.load(f)
    except Exception as e:
        log(f"ERROR: Failed to parse mdp_config.json: {e}")
        raise SystemExit(2)

    if not config.get("heartbeat_metric_name"):
        log("ERROR: mdp_config.json is missing required key: heartbeat_metric_name")
        raise SystemExit(2)

    scripts = config.get("mdp_scripts")
    if not isinstance(scripts, list) or not scripts:
        log(f"ERROR: 'mdp_scripts' key missing or empty in mdp_config.json")
        raise SystemExit(2)

    for i, entry in enumerate(scripts):
        for field in ("script", "metric_name", "enabled"):
            if field not in entry:
                log(f"ERROR: mdp_scripts entry {i} is missing field '{field}'")
                raise SystemExit(2)
        if entry["enabled"] not in ("y", "n"):
            log(f"ERROR: mdp_scripts entry {i} ('{entry['script']}') has invalid 'enabled' value: "
                f"'{entry['enabled']}'. Must be 'y' or 'n'.")
            raise SystemExit(2)

    return config


# ---------------------------------------------------------------------------
# Module-level config — loaded once at import time, fail-fast on any error
# ---------------------------------------------------------------------------
_db_cfg = _load_db_config()

DB_HOST = _db_cfg["db_host"]
DB_NAME = _db_cfg["db_name"]
DB_USER = _db_cfg["db_user"]
PSQL    = _db_cfg["psql"]
PYTHON  = _db_cfg["python"]
SERVICE = _db_cfg["service"]
VM      = os.uname().nodename                                     # always the current machine — not a config value
WRAPPER = os.path.join(SCRIPT_DIR, "bm_otel_publish_metric.py")  # always co-located — not a config value


# ---------------------------------------------------------------------------
# ENV resolution (env_config.json)
# ---------------------------------------------------------------------------
def _resolve_env() -> str:
    """
    Resolve the ENV label from env_config.json by matching the current hostname.

    Raises SystemExit(2) if the file is missing or unreadable.
    Falls back to the raw hostname only when the hostname is simply not listed
    in the map (not a config error — just an unmapped host).
    """
    hostname = os.uname().nodename

    if not os.path.exists(ENV_CONFIG_PATH):
        log(f"ERROR: env_config.json not found: {ENV_CONFIG_PATH}")
        raise SystemExit(2)

    try:
        with open(ENV_CONFIG_PATH, "r") as f:
            config = json.load(f)
    except Exception as e:
        log(f"ERROR: Failed to parse env_config.json: {e}")
        raise SystemExit(2)

    for entry in config.get("env_map", []):
        if entry.get("hostname") == hostname:
            return entry["env"]

    # Hostname not in map — use hostname as the env label (intentional fallback)
    log(f"WARNING: hostname '{hostname}' not found in env_config.json env_map — using hostname as env label")
    return hostname


ENV = _resolve_env()


# ---------------------------------------------------------------------------
# Public config accessors
# ---------------------------------------------------------------------------
def _load_config() -> List[Dict]:
    """Return the validated mdp_scripts list from mdp_config.json."""
    return _load_mdp_config()["mdp_scripts"]


def get_metric_name(caller_file: str) -> str:
    """
    Resolve the metric name for the calling MDP script from mdp_config.json.

    Usage in any MDP script:
        metric_name = get_metric_name(__file__)

    Raises SystemExit(2) if the config is unreadable or the script is not listed.
    """
    script_name = os.path.basename(caller_file)

    for entry in _load_config():
        if entry["script"] == script_name:
            return entry["metric_name"]

    log(f"ERROR: Script '{script_name}' not found in mdp_config.json")
    raise SystemExit(2)


def get_heartbeat_metric_name() -> str:
    """
    Return the heartbeat metric name from mdp_config.json.
    Raises SystemExit(2) if the config is missing or the key is absent.
    """
    return _load_mdp_config()["heartbeat_metric_name"]


# ---------------------------------------------------------------------------
# psql helper
# ---------------------------------------------------------------------------
def psql_scalar(sql: str) -> str:
    """Run SQL and return a trimmed scalar result."""
    cmd = [
        PSQL,
        "-h", DB_HOST,
        "-U", DB_USER,
        "-d", DB_NAME,
        "-t", "-A",
        "-c", sql,
    ]
    return subprocess.check_output(cmd, text=True, stderr=subprocess.STDOUT).strip()


# ---------------------------------------------------------------------------
# Label / publish helpers
# ---------------------------------------------------------------------------
def build_base_labels(*, source: str = "postgres") -> List[str]:
    """Return base label list (key=value strings)."""
    return [
        f"service={SERVICE}",
        f"env={ENV}",
        f"vm={VM}",
        f"source={source}",
        f"db={DB_NAME}",
    ]


def publish_gauge(metric_name: str, value: float, labels: List[str]) -> None:
    """Publish gauge via the OTEL wrapper."""
    cmd = [PYTHON, WRAPPER, "gauge", metric_name, str(value)] + labels
    subprocess.check_call(cmd)
