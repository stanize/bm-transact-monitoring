#!/usr/bin/env python3
"""bm_transact_lib.py

Shared helpers for Transact monitoring MDP scripts.

Keeps the same env var contract as the original combined script:
- DB_HOST, DB_NAME, DB_USER, BM_PSQL
- BM_PYTHON, BM_OTEL_WRAPPER
- BM_VM, BM_SERVICE

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
from typing import Dict, List, Optional

# --- DB config (pgpass will provide password) ---
DB_HOST = os.environ.get("DB_HOST", "T24-DB")
DB_NAME = os.environ.get("DB_NAME", "BANCA")
DB_USER = os.environ.get("DB_USER", "t24")

PSQL = os.environ.get("BM_PSQL", "/bin/psql")
PYTHON = os.environ.get("BM_PYTHON", "/bin/python3")

# --- Wrapper config ---
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
WRAPPER = os.environ.get("BM_OTEL_WRAPPER", os.path.join(SCRIPT_DIR, "bm_otel_publish_metric.py"))
MDP_CONFIG_PATH = os.path.join(SCRIPT_DIR, "config", "mdp_config.json")
ENV_CONFIG_PATH = os.path.join(SCRIPT_DIR, "config", "env_config.json")

# --- Stable labels ---
VM = os.environ.get("BM_VM", os.uname().nodename)
SERVICE = os.environ.get("BM_SERVICE", "transact")


def log(msg: str, prefix: str = "MDP") -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] [{prefix}] {msg}")


def _resolve_env() -> str:
    """
    Resolve ENV label from env_config.json by matching current hostname.
    If hostname not found in map, uses hostname as env label.
    """
    hostname = os.uname().nodename

    if os.path.exists(ENV_CONFIG_PATH):
        try:
            with open(ENV_CONFIG_PATH, "r") as f:
                config = json.load(f)
            for entry in config.get("env_map", []):
                if entry.get("hostname") == hostname:
                    return entry["env"]
        except Exception as e:
            log(f"WARNING: Failed to read env_config.json: {e} — using hostname as env label")

    # Not found in map — use hostname as env label
    return hostname


ENV = _resolve_env()


def _load_config() -> List[Dict]:
    """Load and return the mdp_scripts list from mdp_config.json. Raises SystemExit on any failure."""
    if not os.path.exists(MDP_CONFIG_PATH):
        log(f"ERROR: MDP config file not found: {MDP_CONFIG_PATH}")
        raise SystemExit(2)

    try:
        with open(MDP_CONFIG_PATH, "r") as f:
            config = json.load(f)
    except Exception as e:
        log(f"ERROR: Failed to read MDP config file: {MDP_CONFIG_PATH}: {e}")
        raise SystemExit(2)

    scripts = config.get("mdp_scripts")
    if not isinstance(scripts, list) or not scripts:
        log(f"ERROR: 'mdp_scripts' key missing or empty in {MDP_CONFIG_PATH}")
        raise SystemExit(2)

    for i, entry in enumerate(scripts):
        for field in ("script", "metric_name", "enabled"):
            if field not in entry:
                log(f"ERROR: Entry {i} in config is missing field '{field}'")
                raise SystemExit(2)
        if entry["enabled"] not in ("y", "n"):
            log(f"ERROR: Entry {i} ('{entry['script']}') has invalid 'enabled' value: '{entry['enabled']}'. Must be 'y' or 'n'.")
            raise SystemExit(2)

    return scripts


def get_metric_name(caller_file: str) -> str:
    """
    Resolve the metric name for the calling MDP script from mdp_config.json.

    Usage in any MDP script:
        metric_name = get_metric_name(__file__)

    Raises SystemExit if the config is unreadable or the script is not listed.
    """
    script_name = os.path.basename(caller_file)
    entries = _load_config()

    for entry in entries:
        if entry["script"] == script_name:
            return entry["metric_name"]

    log(f"ERROR: Script '{script_name}' not found in {MDP_CONFIG_PATH}")
    raise SystemExit(2)


def psql_scalar(sql: str) -> str:
    """Run SQL and return a trimmed scalar result."""
    cmd = [
        PSQL,
        "-h",
        DB_HOST,
        "-U",
        DB_USER,
        "-d",
        DB_NAME,
        "-t",
        "-A",
        "-c",
        sql,
    ]
    return subprocess.check_output(cmd, text=True, stderr=subprocess.STDOUT).strip()


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


