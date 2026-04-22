#!/usr/bin/env python3
"""mdp_tsm_status.py

MDP: TSM status
- Reads public."F_TSA_SERVICE" recid='TSM'
- Publishes a gauge metric (1=START, 0=STOP)

Requires:
  - pgpass configured for DB access
  - bm_otel_publish_metric.py available (BM_OTEL_WRAPPER)

Manual test:
  python3 mdp_tsm_status.py
"""

import os
import sys
import subprocess

from bm_transact_lib import log, psql_scalar, build_base_labels, publish_gauge, get_metric_name

SQL_TSM = """
SELECT CASE UPPER(COALESCE(NULLIF((xmlrecord::json)->>'6',''),'STOP'))
         WHEN 'START' THEN 'START'
         ELSE 'STOP'
       END
FROM public."F_TSA_SERVICE"
WHERE recid='TSM'
LIMIT 1;
""".strip()

SCRIPT_NAME = os.path.basename(__file__)


def get_tsm_state() -> str:
    out = psql_scalar(SQL_TSM)
    return "START" if out == "START" else "STOP"


def main() -> int:
    metric_name = get_metric_name(__file__)

    try:
        tsm_state = get_tsm_state()
        tsm_value = 1 if tsm_state == "START" else 0

        publish_gauge(
            metric_name,
            tsm_value,
            build_base_labels() + [
                "component=tsm",
                f"status={tsm_state}",
                "table=F_TSA_SERVICE",
                "recid=TSM",
            ],
        )
        log(f"{metric_name} = {tsm_value} [{SCRIPT_NAME}]")
        return 0

    except subprocess.CalledProcessError as e:
        log(f"ERROR [{SCRIPT_NAME}]: command failed: {e}")
        return 2
    except Exception as e:
        log(f"ERROR [{SCRIPT_NAME}]: {e}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
