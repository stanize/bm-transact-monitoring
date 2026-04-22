#!/usr/bin/env python3
"""mdp_license_expiry_days.py

MDP: License expiry days remaining
- Reads license expiry date (yyyymmdd) from F_SPF SYSTEM field 37
- Publishes days remaining as a gauge metric

Requires:
  - pgpass configured for DB access
  - bm_otel_publish_metric.py available (BM_OTEL_WRAPPER)

Manual test:
  python3 mdp_license_expiry_days.py
"""

import os
import sys
from datetime import datetime, date

from bm_transact_lib import log, psql_scalar, publish_gauge, build_base_labels, get_metric_name

SQL_LICENSE = """
SELECT (xmlrecord::json)->>'37'
FROM public."F_SPF"
WHERE recid = 'SYSTEM';
"""

SCRIPT_NAME = os.path.basename(__file__)


def main() -> int:
    metric_name = get_metric_name(__file__)

    try:
        expiry_raw = psql_scalar(SQL_LICENSE).strip()

        if not expiry_raw:
            log(f"ERROR [{SCRIPT_NAME}]: license expiry field is empty")
            return 1

        expiry_date = datetime.strptime(expiry_raw, "%Y%m%d").date()
        days_left = (expiry_date - date.today()).days

        labels = build_base_labels(source="postgres")
        labels.append("component=transact_monitoring_service")
        labels.append(f"expiry_date={expiry_date}")

        publish_gauge(metric_name, days_left, labels)
        log(f"{metric_name} = {days_left} [{SCRIPT_NAME}]")
        return 0

    except Exception as e:
        log(f"ERROR [{SCRIPT_NAME}]: {e}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
