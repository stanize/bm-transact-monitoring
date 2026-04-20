#!/usr/bin/env python3
"""mdp_business_date.py

MDP: Business date
- Reads field 1 (yyyymmdd) from public."F_DATES" where recid='LU0010001'
- Converts to a Unix timestamp and publishes as a gauge metric

Env vars:
  BM_BUSINESS_DATE_METRIC_NAME  (default: bm_poc_business_date)

Requires:
  - pgpass configured for DB access
  - bm_otel_publish_metric.py available (BM_OTEL_WRAPPER)

Manual test:
  python3 mdp_business_date.py
"""

import os
import sys
import subprocess
from datetime import datetime, timezone

from bm_transact_lib import log, psql_scalar, build_base_labels, publish_gauge

SQL_BUSINESS_DATE = """
SELECT (xmlrecord::json)->>'1'
FROM public."F_DATES"
WHERE recid='LU0010001'
LIMIT 1;
""".strip()


def get_business_date() -> tuple[str, float]:
    """Returns (raw_date_str, unix_timestamp)."""
    log("Querying business date from F_DATES recid=LU0010001")
    raw = psql_scalar(SQL_BUSINESS_DATE).strip()
    log(f"Raw DB result (business_date): '{raw}'")

    if not raw:
        raise RuntimeError("Business date field is empty")

    try:
        dt = datetime.strptime(raw, "%Y%m%d").replace(tzinfo=timezone.utc)
        return raw, dt.timestamp()
    except ValueError as e:
        raise RuntimeError(f"ERROR parsing business date '{raw}': {e}")


def main() -> int:
    metric_name = os.environ.get("BM_BUSINESS_DATE_METRIC_NAME", "bm_poc_business_date")

    try:
        raw_date, ts = get_business_date()
        log(f"Business date: {raw_date} -> unix timestamp: {ts}")
        log(f"Publishing metric: {metric_name} value={ts}")
        publish_gauge(
            metric_name,
            ts,
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
