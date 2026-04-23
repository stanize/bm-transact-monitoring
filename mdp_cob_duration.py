#!/usr/bin/env python3
"""mdp_cob_duration.py

MDP: COB duration
- Reads F_TSA_SERVICE recid='COB' fields 15 (date), 16 (started), 17 (stopped), 18 (elapsed)
- Finds the first entry where both started and stopped are non-blank
- Converts elapsed HH:MM:SS to total seconds and publishes as a gauge metric
- Publishes cob_date and raw elapsed string as labels

Requires:
  - pgpass configured for DB access
  - bm_otel_publish_metric.py available (BM_OTEL_WRAPPER)

Manual test:
  python3 mdp_cob_duration.py
"""

import json
import os
import sys
import subprocess

from bm_transact_lib import log, psql_scalar, build_base_labels, publish_gauge, get_metric_name

SQL_COB_DURATION = """
SELECT xmlrecord
FROM public."F_TSA_SERVICE"
WHERE recid='COB'
LIMIT 1;
""".strip()

SCRIPT_NAME = os.path.basename(__file__)


def elapsed_to_seconds(elapsed: str) -> int:
    """Convert HH:MM:SS to total seconds."""
    parts = elapsed.strip().split(":")
    if len(parts) != 3:
        raise RuntimeError(f"Unexpected elapsed format: '{elapsed}'")
    h, m, s = int(parts[0]), int(parts[1]), int(parts[2])
    return h * 3600 + m * 60 + s


def get_cob_duration() -> tuple[int, str, str]:
    """
    Returns (duration_seconds, cob_date, elapsed_raw).
    Finds first index where both field 16 (started) and field 17 (stopped) are non-blank.
    """
    raw = psql_scalar(SQL_COB_DURATION)
    if not raw:
        raise RuntimeError("No COB record found in F_TSA_SERVICE")

    record = json.loads(raw)

    dates    = record.get("15", [])
    started  = record.get("16", [])
    stopped  = record.get("17", [])
    elapsed  = record.get("18", [])

    # Normalize to lists
    if isinstance(dates,   str): dates   = [dates]
    if isinstance(started, str): started = [started]
    if isinstance(stopped, str): stopped = [stopped]
    if isinstance(elapsed, str): elapsed = [elapsed]

    for i in range(len(started)):
        s = started[i].strip() if i < len(started) else ""
        e = stopped[i].strip() if i < len(stopped) else ""
        if s and e:
            cob_date    = dates[i].strip()   if i < len(dates)   else "unknown"
            elapsed_raw = elapsed[i].strip() if i < len(elapsed) else ""
            if not elapsed_raw:
                raise RuntimeError(f"Elapsed is blank at index {i}")
            return elapsed_to_seconds(elapsed_raw), cob_date, elapsed_raw

    raise RuntimeError("No completed COB run found (no entry with both started and stopped)")


def main() -> int:
    metric_name = get_metric_name(__file__)

    try:
        duration_seconds, cob_date, elapsed_raw = get_cob_duration()

        publish_gauge(
            metric_name,
            duration_seconds,
            build_base_labels() + [
                "component=cob",
                "table=F_TSA_SERVICE",
                "recid=COB",
                f"cob_date={cob_date}",
                f"elapsed={elapsed_raw}",
            ],
        )
        log(f"{metric_name} = {duration_seconds} [{SCRIPT_NAME}]")
        return 0

    except subprocess.CalledProcessError as e:
        log(f"ERROR [{SCRIPT_NAME}]: command failed: {e}")
        return 2
    except Exception as e:
        log(f"ERROR [{SCRIPT_NAME}]: {e}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
