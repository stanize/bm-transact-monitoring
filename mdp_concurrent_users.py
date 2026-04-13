#!/usr/bin/env python3
"""mdp_concurrent_users.py

MDP: Concurrent users
- Reads COUNT(*) from public."F_OS_TOKEN"
- Publishes a gauge metric with that count

Env vars:
- BM_USERS_METRIC_NAME (default: bm_poc_concurrent_users)

Requires:
- pgpass configured for DB access
- bm_otel_publish_metric.py available (BM_OTEL_WRAPPER)
"""

import os
import sys
import subprocess

from bm_transact_lib import log, psql_scalar, build_base_labels, publish_gauge

SQL_USERS = 'SELECT COUNT(*) FROM public."F_OS_TOKEN";'


def get_concurrent_users() -> int:
    log('Querying concurrent users from public."F_OS_TOKEN"')
    out = psql_scalar(SQL_USERS)
    log(f"Raw DB result (users): '{out}'")
    try:
        return int(out)
    except ValueError:
        raise RuntimeError(f"Unexpected COUNT(*) output: '{out}'")


def main() -> int:
    metric_name = os.environ.get("BM_USERS_METRIC_NAME", "bm_poc_concurrent_users")

    try:
        users = get_concurrent_users()
        log(f"Publishing users metric: {metric_name} value={users}")
        publish_gauge(
            metric_name,
            users,
            build_base_labels() + [
                "component=auth",
                "metric=concurrent_users",
                'table=F_OS_TOKEN',
            ],
        )
        log("Concurrent users metric published successfully")
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

