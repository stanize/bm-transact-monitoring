#!/usr/bin/env python3
"""bm_transact_lib.py

Shared helpers for Transact monitoring MDP scripts.

Keeps the same env var contract as the original combined script:
- DB_HOST, DB_NAME, DB_USER, BM_PSQL
- BM_PYTHON, BM_OTEL_WRAPPER
- BM_ENV, BM_VM, BM_SERVICE

Each MDP script should:
- call build_base_labels()
- call publish_gauge(...)

No OTEL logic lives here (it delegates to bm_otel_publish_metric.py).
"""

import os
import subprocess
from datetime import datetime
from typing import List

# --- DB config (pgpass will provide password) ---
DB_HOST = os.environ.get("DB_HOST", "T24-DB")
DB_NAME = os.environ.get("DB_NAME", "BANCA")
DB_USER = os.environ.get("DB_USER", "t24")

PSQL = os.environ.get("BM_PSQL", "/bin/psql")
PYTHON = os.environ.get("BM_PYTHON", "/bin/python3")

# --- Wrapper config ---
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
WRAPPER = os.environ.get("BM_OTEL_WRAPPER", os.path.join(SCRIPT_DIR, "bm_otel_publish_metric.py"))

# --- Stable labels ---
ENV = os.environ.get("BM_ENV", "LOCALACN")
VM = os.environ.get("BM_VM", os.uname().nodename)
SERVICE = os.environ.get("BM_SERVICE", "transact")


def log(msg: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}")


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

