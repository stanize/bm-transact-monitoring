#!/usr/bin/env python3
"""bm_transact_lib.py

Shared helpers for Transact monitoring MDP scripts.

All configuration is loaded exclusively from JSON files under config/.
There are no environment variable fallbacks and no hard-coded defaults —
if a required config file is missing, unreadable, or incomplete the
process exits with rc=2 immediately.

  config/db_config.json   — DB connectivity, tool paths, service identity
  config/mdp_config.json  — MDP script registry, schedule, logging, heartbeat
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
import logging
import logging.handlers
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
LOG_DIR         = os.path.join(SCRIPT_DIR, "logs")
LOG_PATH        = os.path.join(LOG_DIR, "bm-transact-monitoring.log")

# ---------------------------------------------------------------------------
# AUDIT level — sits above CRITICAL (50), can never be filtered out
# ---------------------------------------------------------------------------
AUDIT_LEVEL = 60
logging.addLevelName(AUDIT_LEVEL, "AUDIT")

_logger = logging.getLogger("bm_transact")


def audit(msg: str) -> None:
    """Log at AUDIT level — always written regardless of configured log level."""
    _logger.log(AUDIT_LEVEL, msg)


# ---------------------------------------------------------------------------
# Logging setup — called once by the service at startup
# ---------------------------------------------------------------------------
def setup_logging(level_name: str, max_bytes: int, backup_count: int) -> None:
    """
    Initialise logging to both a rotating file and stdout.
    Called once at service startup after config is loaded.
    """
    os.makedirs(LOG_DIR, exist_ok=True)

    level = getattr(logging, level_name.upper(), logging.INFO)

    formatter = logging.Formatter(
        fmt="[%(asctime)s] [%(levelname)-7s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Rotating file handler
    file_handler = logging.handlers.RotatingFileHandler(
        LOG_PATH,
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.DEBUG)  # file always gets everything

    # Stdout handler — respects configured level
    stdout_handler = logging.StreamHandler()
    stdout_handler.setFormatter(formatter)
    stdout_handler.setLevel(level)

    root = logging.getLogger("bm_transact")
    root.setLevel(logging.DEBUG)  # let handlers decide what to filter
    root.addHandler(file_handler)
    root.addHandler(stdout_handler)


# ---------------------------------------------------------------------------
# Logging helpers
#
# MDP scripts run as child processes — setup_logging() is never called in
# their process, so _logger has no handlers. In that case we fall back to
# print() with plain text only (no timestamp, no level prefix) so the
# parent service can capture it and log it through its own formatter
# without double-wrapping.
# ---------------------------------------------------------------------------
def _has_handlers() -> bool:
    """Return True if setup_logging() has been called in this process."""
    return bool(logging.getLogger("bm_transact").handlers)


def log(msg: str, prefix: str = "MDP") -> None:
    if _has_handlers():
        _logger.info("[%s] %s", prefix, msg)
    else:
        # Child process — when run standalone, include script name for context.
        # When captured by the service, the service adds [MDP] [script_name] itself.
        print(f"[{prefix}] {msg}")
      

def log_warning(msg: str, prefix: str = "MDP") -> None:
    if _has_handlers():
        _logger.warning("[%s] %s", prefix, msg)
    else:
        print(f"[WARNING] [{prefix}] {msg}")


def log_error(msg: str, prefix: str = "MDP") -> None:
    if _has_handlers():
        _logger.error("[%s] %s", prefix, msg)
    else:
        print(f"[ERROR] [{prefix}] {msg}")


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
        print(f"ERROR: db_config.json not found: {DB_CONFIG_PATH}")
        raise SystemExit(2)

    try:
        with open(DB_CONFIG_PATH, "r") as f:
            cfg = json.load(f)
    except Exception as e:
        print(f"ERROR: Failed to parse db_config.json: {e}")
        raise SystemExit(2)

    missing = [k for k in _DB_REQUIRED_KEYS if not cfg.get(k)]
    if missing:
        print(f"ERROR: db_config.json is missing required key(s): {', '.join(missing)}")
        raise SystemExit(2)

    return cfg


def _load_mdp_config() -> Dict:
    """
    Load and validate config/mdp_config.json.
    Raises SystemExit(2) if the file is missing, unreadable, corrupt,
    or if any required key is absent or invalid.
    """
    if not os.path.exists(MDP_CONFIG_PATH):
        print(f"ERROR: mdp_config.json not found: {MDP_CONFIG_PATH}")
        raise SystemExit(2)

    try:
        with open(MDP_CONFIG_PATH, "r") as f:
            config = json.load(f)
    except Exception as e:
        print(f"ERROR: Failed to parse mdp_config.json: {e}")
        raise SystemExit(2)

    # heartbeat_metric_name
    if not config.get("heartbeat_metric_name"):
        print("ERROR: mdp_config.json is missing required key: heartbeat_metric_name")
        raise SystemExit(2)

    # interval_seconds
    if not isinstance(config.get("interval_seconds"), int) or config["interval_seconds"] <= 0:
        print("ERROR: mdp_config.json is missing or invalid key: interval_seconds (must be a positive integer)")
        raise SystemExit(2)

    # logging section
    log_cfg = config.get("logging")
    if not isinstance(log_cfg, dict):
        print("ERROR: mdp_config.json is missing required section: logging")
        raise SystemExit(2)
    for key in ("level", "max_bytes", "backup_count"):
        if log_cfg.get(key) is None:
            print(f"ERROR: mdp_config.json logging section is missing required key: {key}")
            raise SystemExit(2)
    valid_levels = ("DEBUG", "INFO", "WARNING", "ERROR")
    if log_cfg["level"].upper() not in valid_levels:
        print(f"ERROR: mdp_config.json logging.level must be one of: {', '.join(valid_levels)}")
        raise SystemExit(2)

    # mdp_scripts
    scripts = config.get("mdp_scripts")
    if not isinstance(scripts, list) or not scripts:
        print("ERROR: 'mdp_scripts' key missing or empty in mdp_config.json")
        raise SystemExit(2)

    for i, entry in enumerate(scripts):
        for field in ("script", "metric_name", "enabled"):
            if field not in entry:
                print(f"ERROR: mdp_scripts entry {i} is missing field '{field}'")
                raise SystemExit(2)
        if entry["enabled"] not in ("y", "n"):
            print(f"ERROR: mdp_scripts entry {i} ('{entry['script']}') has invalid "
                  f"'enabled' value: '{entry['enabled']}'. Must be 'y' or 'n'.")
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
        print(f"ERROR: env_config.json not found: {ENV_CONFIG_PATH}")
        raise SystemExit(2)

    try:
        with open(ENV_CONFIG_PATH, "r") as f:
            config = json.load(f)
    except Exception as e:
        print(f"ERROR: Failed to parse env_config.json: {e}")
        raise SystemExit(2)

    for entry in config.get("env_map", []):
        if entry.get("hostname") == hostname:
            return entry["env"]

    # Hostname not in map — use hostname as the env label (intentional fallback)
    print(f"WARNING: hostname '{hostname}' not found in env_config.json env_map — using hostname as env label")
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

    log_error(f"Script '{script_name}' not found in mdp_config.json")
    raise SystemExit(2)


def get_heartbeat_metric_name() -> str:
    """
    Return the heartbeat metric name from mdp_config.json.
    Raises SystemExit(2) if the config is missing or the key is absent.
    """
    return _load_mdp_config()["heartbeat_metric_name"]


def get_service_config() -> Dict:
    """
    Return the service-level config values from mdp_config.json:
    interval_seconds, logging, heartbeat_metric_name.
    """
    cfg = _load_mdp_config()
    return {
        "interval_seconds":      cfg["interval_seconds"],
        "logging":               cfg["logging"],
        "heartbeat_metric_name": cfg["heartbeat_metric_name"],
    }


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
