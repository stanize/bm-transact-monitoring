#!/usr/bin/env python3
"""mdp_eod_error_count.py

MDP: EOD error count
- Counts unresolved EOD errors in public."F_EB_EOD_ERROR"
- A record is considered unresolved when field 7 (resolution date) is missing,
  null, or an array containing null values
- Publishes the count as a gauge metric

Requires:
  - pgpass configured for DB access
  - bm_otel_publish_metric.py available (BM_OTEL_WRAPPER)

Manual test:
  python3 mdp_eod_error_count.py
"""

import os
import sys
import subprocess

from bm_transact_lib import log, psql_scalar, build_base_labels, publish_gauge, get_metric_name

SQL_EOD_ERROR_COUNT = """
SELECT COUNT(*)
FROM public."F_EB_EOD_ERROR"
WHERE NOT (xmlrecord::jsonb ? '7')
   OR (xmlrecord::jsonb->'7') = 'null'::jsonb
   OR (
       jsonb_typeof(xmlrecord::jsonb->'7') = 'array'
       AND EXISTS (
           SELECT 1
           FROM jsonb_array_elements(xmlrecord::jsonb->'7') AS e(val)
           WHERE val = 'null'::jsonb
       )
   );
""".strip()

SCRIPT_NAME = os.path.basename(__file__)


def get_eod_error_count() -> int:
    out = psql_scalar(SQL_EOD_ERROR_COUNT)
    try:
        return int(out)
    except ValueError:
        raise RuntimeError(f"Unexpected COUNT(*) output: '{out}'")


def main() -> int:
    metric_name = get_metric_name(__file__)

    try:
        count = get_eod_error_count()
        publish_gauge(
            metric_name,
            count,
            build_base_labels() + [
                "component=eod",
                "table=F_EB_EOD_ERROR",
                "filter=unresolved",
            ],
        )
        log(f"{metric_name} = {count} [{SCRIPT_NAME}]")
        return 0

    except subprocess.CalledProcessError as e:
        log(f"ERROR [{SCRIPT_NAME}]: command failed: {e}")
        return 2
    except Exception as e:
        log(f"ERROR [{SCRIPT_NAME}]: {e}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
