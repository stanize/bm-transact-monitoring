#!/usr/bin/env python3
import os
import subprocess
import sys
from datetime import datetime

# --- DB config (pgpass will provide password) ---
DB_HOST = os.environ.get("DB_HOST", "T24-DB")
DB_NAME = os.environ.get("DB_NAME", "BANCA")
DB_USER = os.environ.get("DB_USER", "t24")

PSQL = os.environ.get("BM_PSQL", "/bin/psql")
PYTHON = os.environ.get("BM_PYTHON", "/bin/python3")

SQL_TSM = """
SELECT CASE UPPER(COALESCE(NULLIF((xmlrecord::json)->>'6',''),'STOP'))
         WHEN 'START' THEN 'START'
         ELSE 'STOP'
       END
FROM public."F_TSA_SERVICE"
WHERE recid='TSM'
LIMIT 1;
""".strip()

SQL_USERS = 'SELECT COUNT(*) FROM public."F_OS_TOKEN";'

# --- Wrapper config ---
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
WRAPPER = os.environ.get("BM_OTEL_WRAPPER", os.path.join(SCRIPT_DIR, "bm_otel_publish_metric.py"))

# --- Stable labels ---
ENV = os.environ.get("BM_ENV", "LOCALACN")
VM = os.environ.get("BM_VM", os.uname().nodename)
SERVICE = os.environ.get("BM_SERVICE", "transact")

# --- Metric names ---
METRIC_TSM = os.environ.get("BM_TSM_METRIC_NAME", "bm_poc_tsm_status")
METRIC_USERS = os.environ.get("BM_USERS_METRIC_NAME", "bm_poc_concurrent_users")


def log(msg: str):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}")


def psql_scalar(sql: str) -> str:
    cmd = [
        PSQL,
        "-h", DB_HOST,
        "-U", DB_USER,
        "-d", DB_NAME,
        "-t", "-A",
        "-c", sql
    ]
    return subprocess.check_output(cmd, text=True, stderr=subprocess.STDOUT).strip()


def get_tsm_state() -> str:
    log("Querying TSM state from database")
    out = psql_scalar(SQL_TSM)
    log(f"Raw DB result (TSM): '{out}'")
    return "START" if out == "START" else "STOP"


def get_concurrent_users() -> int:
    log('Querying concurrent users from public."F_OS_TOKEN"')
    out = psql_scalar(SQL_USERS)
    log(f"Raw DB result (users): '{out}'")
    try:
        return int(out)
    except ValueError:
        raise RuntimeError(f"Unexpected COUNT(*) output: '{out}'")


def publish_gauge(metric_name: str, value: int, labels: list[str]) -> None:
    cmd = [PYTHON, WRAPPER, "gauge", metric_name, str(value)] + labels
    subprocess.check_call(cmd)


def main() -> int:
    log("Combined health check started")

    base_labels = [
        f"service={SERVICE}",
        f"env={ENV}",
        f"vm={VM}",
        "source=postgres",
        f"db={DB_NAME}",
    ]

    try:
        # --- 1) TSM ---
        tsm_state = get_tsm_state()
        tsm_value = 1 if tsm_state == "START" else 0
        log(f"Publishing TSM metric: {METRIC_TSM} value={tsm_value} status={tsm_state}")
        publish_gauge(
            METRIC_TSM,
            tsm_value,
            base_labels + [
                "component=tsm",
                f"status={tsm_state}",
                'table=F_TSA_SERVICE',
                "recid=TSM",
            ],
        )
        log("TSM metric published successfully")

        # --- 2) Concurrent users ---
        users = get_concurrent_users()
        log(f"Publishing users metric: {METRIC_USERS} value={users}")
        publish_gauge(
            METRIC_USERS,
            users,
            base_labels + [
                "component=auth",
                "metric=concurrent_users",
                'table=F_OS_TOKEN',
            ],
        )
        log("Concurrent users metric published successfully")

        log("Combined health check completed OK")
        return 0

    except subprocess.CalledProcessError as e:
        log(f"ERROR executing command: {e}")
        print(f"ERROR: command failed: {e}", file=sys.stderr)
        return 2
    except Exception as e:
        log(f"ERROR: {e}")
        print(f"ERROR: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

