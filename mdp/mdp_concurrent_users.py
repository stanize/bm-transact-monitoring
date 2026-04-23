#!/usr/bin/env python3
"""mdp_concurrent_users.py

MDP: Concurrent users
- Reads COUNT(*) from public."F_OS_TOKEN"
- Publishes a gauge metric with that count

Requires:
  - pgpass configured for DB access
  - bm_otel_publish_metric.py available (BM_OTEL_WRAPPER)

Manual test:
  python3 mdp_concurrent_users.py
"""

import os
import sys
import subprocess

from bm_transact_lib import log, psql_scalar, build_base_labels, publish_gauge, get_metric_name

SQL_USERS = 'SELECT COUNT(*) FROM public."F_OS_TOKEN";'

SCRIPT_NAME = os.path.basename(__file__)


def get_concurrent_users() -> int:
    out = psql_scalar(SQL_USERS)
    try:
        return int(out)
    except ValueError:
        raise RuntimeError(f"Unexpected COUNT(*) output: '{out}'")


def main() -> int:
    metric_name = get_metric_name(__file__)

    try:
        users = get_concurrent_users()
        publish_gauge(
            metric_name,
            users,
            build_base_labels() + [
                "component=auth",
                "metric=concurrent_users",
                "table=F_OS_TOKEN",
            ],
        )
        log(f"{metric_name} = {users} [{SCRIPT_NAME}]")
        return 0

    except subprocess.CalledProcessError as e:
        log(f"ERROR [{SCRIPT_NAME}]: command failed: {e}")
        return 2
    except Exception as e:
        log(f"ERROR [{SCRIPT_NAME}]: {e}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
