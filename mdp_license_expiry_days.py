#!/usr/bin/env python3

import os
from datetime import datetime, date
from bm_transact_lib import log, psql_scalar, publish_gauge, build_base_labels


def main() -> int:

    metric_name = os.getenv(
        "BM_LICENSE_METRIC_NAME",
        "bm_poc_license_days_remaining"
    )

    log('Querying license expiry date from F_SPF (SYSTEM field 37)')

    sql = """
    SELECT (xmlrecord::json)->>'37'
    FROM public."F_SPF"
    WHERE recid = 'SYSTEM';
    """

    expiry_raw = psql_scalar(sql).strip()

    log(f"Raw license expiry value: '{expiry_raw}'")

    if not expiry_raw:
        log("ERROR: License expiry field is empty")
        return 1

    try:
        expiry_date = datetime.strptime(expiry_raw, "%Y%m%d").date()
        today = date.today()
        days_left = (expiry_date - today).days
    except Exception as e:
        log(f"ERROR parsing expiry date: {e}")
        return 1

    log(f"License expiry date : {expiry_date}")
    log(f"Days remaining      : {days_left}")

    labels = build_base_labels(source="postgres")
    labels.append("component=transact_monitoring_service")
    labels.append(f"expiry_date={expiry_date}")

    publish_gauge(metric_name, days_left, labels)

    log("License expiry metric published successfully")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
