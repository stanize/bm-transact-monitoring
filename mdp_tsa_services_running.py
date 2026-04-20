#!/usr/bin/env python3
"""mdp_tsa_services_running.py

MDP: TSA services running count
- Counts records in public."F_TSA_SERVICE" where SERVICE.CONTROL (JSON field 6)
  is START or AUTO (case-insensitive)
- Publishes a gauge metric with that count

Requires:
  - pgpass configured for DB access
  - bm_otel_publish_metric.py available (BM_OTEL_WRAPPER)

Manual test:
  python3 mdp_tsa_services_running.py
"""

import sys
import subprocess

from bm_transact_lib import log, psql_scalar, build_base_labels, publish_gauge, get_metric_name

SQL_TSA_SERVICES_RUNNING = """
SELECT COUNT(*)
FROM public."F_TSA_SERVICE"
WHERE UPPER((xmlrecord::json)->>'6') IN ('START', 'AUTO');
""".strip()


def get_tsa_services_running() -> int:
    log('Querying F_TSA_SERVICE count where SERVICE.CONTROL IN (START, AUTO)')
    out = psql_scalar(SQL_TSA_SERVICES_RUNNING)
    log(f"Raw DB result (tsa_services_running): '{out}'")
    try:
        return int(out)
    except ValueError:
        raise RuntimeError(f"Unexpected COUNT(*) output: '{out}'")


def main() -> int:
    metric_name = get_metric_name(__file__)

    try:
        count = get_tsa_services_running()
        log(f"Publishing metric: {metric_name} value={count}")
        publish_gauge(
            metric_name,
            count,
            build_base_labels() + [
                "component=tsm",
                "table=F_TSA_SERVICE",
                "filter=SERVICE_CONTROL_START_AUTO",
            ],
        )
        log("TSA services running metric published successfully")
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
