#!/usr/bin/env python3
"""mdp_transact_release.py

MDP: Transact release version
- Reads field 8 (Transact Release) from public."F_SPF" where recid='SYSTEM'
- Strips leading non-numeric characters (e.g. R24 -> 24)
- Publishes the numeric part as a gauge metric, with the raw string as a label

Requires:
  - pgpass configured for DB access
  - bm_otel_publish_metric.py available (BM_OTEL_WRAPPER)

Manual test:
  python3 mdp_transact_release.py
"""

import os
import re
import sys
import subprocess

from bm_transact_lib import log, psql_scalar, build_base_labels, publish_gauge, get_metric_name

SQL_TRANSACT_RELEASE = """
SELECT (xmlrecord::json)->>'8'
FROM public."F_SPF"
WHERE recid='SYSTEM'
LIMIT 1;
""".strip()

SCRIPT_NAME = os.path.basename(__file__)


def get_transact_release() -> tuple[str, int]:
    raw = psql_scalar(SQL_TRANSACT_RELEASE).strip()
    if not raw:
        raise RuntimeError("Transact release field is empty")
    match = re.search(r"\d+", raw)
    if not match:
        raise RuntimeError(f"No numeric part found in release value: '{raw}'")
    return raw, int(match.group())


def main() -> int:
    metric_name = get_metric_name(__file__)

    try:
        raw, value = get_transact_release()
        publish_gauge(
            metric_name,
            value,
            build_base_labels(source="postgres") + [
                "component=transact_monitoring_service",
                "table=F_SPF",
                "recid=SYSTEM",
                f"release={raw}",
            ],
        )
        log(f"{metric_name} = {value} [{SCRIPT_NAME}]")
        return 0

    except subprocess.CalledProcessError as e:
        log(f"ERROR [{SCRIPT_NAME}]: command failed: {e}")
        return 2
    except Exception as e:
        log(f"ERROR [{SCRIPT_NAME}]: {e}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
