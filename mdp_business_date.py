#!/usr/bin/env python3
"""mdp_business_date.py

MDP: Business date
- Reads field 1 (yyyymmdd) from public."F_DATES" where recid='LU0010001'
- Publishes the raw yyyymmdd value as an integer gauge metric

Requires:
  - pgpass configured for DB access
  - bm_otel_publish_metric.py available (BM_OTEL_WRAPPER)

Manual test:
  python3 mdp_business_date.py
"""

import sys
import subprocess

from bm_transact_lib import log, psql_scalar, build_base_labels, publish_gauge, get_metric_name

SQL_BUSINESS_DATE = """
SELECT (xmlrecord::json)->>'1'
FROM public."F_DATES"
WHERE recid='LU0010001'
LIMIT 1;
""".strip()


def get_business_date() -> int:
    log("Querying business date from F_DATES recid=LU0010001")
    raw = psql_scalar(SQL_BUSINESS_DATE).strip()
    log(f"Raw DB result (business_date): '{raw}'")

    if not raw:
        raise RuntimeError("Business date field is empty")

    try:
        return int(raw)
    except ValueError as e:
        raise RuntimeError(f"ERROR parsing business date '{raw}': {e}")


def main() -> int:
    metric_name = get_metric_name(__file__)

    try:
        value = get_business_date()
        log(f"Publishing metric: {metric_name} value={value}")
        publish_gauge(
            metric_name,
            value,
            build_base_labels() + [
                "component=dates",
                "table=F_DATES",
                "recid=LU0010001",
            ],
        )
        log("Business date metric published successfully")
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
