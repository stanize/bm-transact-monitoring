#!/usr/bin/env python3
"""mdp_cob_progress.py

MDP: COB progress
- Calculates overall COB completion percentage from public."F_BATCH"
- Field 1 = batch job ID (prefix indicates stage: A, S, R, D, O)
- Field 3 = '2' means processed
- Publishes overall pct_completed as a gauge metric (0.00 - 100.00)

Requires:
  - pgpass configured for DB access
  - bm_otel_publish_metric.py available (BM_OTEL_WRAPPER)

Manual test:
  python3 mdp_cob_progress.py
"""

import os
import sys
import subprocess

from bm_transact_lib import log, psql_scalar, build_base_labels, publish_gauge, get_metric_name

SQL_COB_PROGRESS = """
WITH stage_map AS (
    SELECT 'A' AS prefix UNION ALL
    SELECT 'S'           UNION ALL
    SELECT 'R'           UNION ALL
    SELECT 'D'           UNION ALL
    SELECT 'O'
),
stage_counts AS (
    SELECT
        (SELECT COUNT(*) FROM public."F_BATCH" fb
          WHERE COALESCE((fb.xmlrecord::json)->>'1', '') LIKE sm.prefix || '%') AS total,
        (SELECT COUNT(*) FROM public."F_BATCH" fb
          WHERE COALESCE((fb.xmlrecord::json)->>'1', '') LIKE sm.prefix || '%'
            AND COALESCE((fb.xmlrecord::json)->>'3', '') = '2') AS processed
    FROM stage_map sm
)
SELECT CASE
    WHEN SUM(total) = 0 THEN 0
    ELSE ROUND((SUM(processed)::numeric / SUM(total)::numeric) * 100, 2)
END
FROM stage_counts;
""".strip()

SCRIPT_NAME = os.path.basename(__file__)


def get_cob_progress() -> float:
    out = psql_scalar(SQL_COB_PROGRESS)
    try:
        return float(out)
    except ValueError:
        raise RuntimeError(f"Unexpected COB progress output: '{out}'")


def main() -> int:
    metric_name = get_metric_name(__file__)

    try:
        pct = get_cob_progress()
        publish_gauge(
            metric_name,
            pct,
            build_base_labels() + [
                "component=cob",
                "table=F_BATCH",
                "company_id=LU0010001",
            ],
        )
        log(f"{metric_name} = {pct} [{SCRIPT_NAME}]")
        return 0

    except subprocess.CalledProcessError as e:
        log(f"ERROR [{SCRIPT_NAME}]: command failed: {e}")
        return 2
    except Exception as e:
        log(f"ERROR [{SCRIPT_NAME}]: {e}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
