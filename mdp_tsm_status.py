#!/usr/bin/env python3
"""mdp_tsm_status.py

MDP: TSM status
- Reads public."F_TSA_SERVICE" recid='TSM'
- Publishes a gauge metric (1=START, 0=STOP)

Env vars:
- BM_TSM_METRIC_NAME (default: bm_poc_tsm_status)

Requires:
- pgpass configured for DB access
- bm_otel_publish_metric.py available (BM_OTEL_WRAPPER)
"""

import sys
import subprocess

from bm_transact_lib import log, psql_scalar, build_base_labels, publish_gauge

SQL_TSM = """
SELECT CASE UPPER(COALESCE(NULLIF((xmlrecord::json)->>'6',''),'STOP'))
         WHEN 'START' THEN 'START'
         ELSE 'STOP'
       END
FROM public."F_TSA_SERVICE"
WHERE recid='TSM'
LIMIT 1;
""".strip()


def get_tsm_state() -> str:
    log("Querying TSM state from database")
    out = psql_scalar(SQL_TSM)
    log(f"Raw DB result (TSM): '{out}'")
    return "START" if out == "START" else "STOP"


def main() -> int:
    metric_name = __import__("os").environ.get("BM_TSM_METRIC_NAME", "bm_poc_tsm_status")

    try:
        tsm_state = get_tsm_state()
        tsm_value = 1 if tsm_state == "START" else 0

        log(f"Publishing TSM metric: {metric_name} value={tsm_value} status={tsm_state}")
        publish_gauge(
            metric_name,
            tsm_value,
            build_base_labels() + [
                "component=tsm",
                f"status={tsm_state}",
                'table=F_TSA_SERVICE',
                "recid=TSM",
            ],
        )
        log("TSM metric published successfully")
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

