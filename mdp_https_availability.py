#!/usr/bin/env python3
"""mdp_https_availability.py

MDP: HTTPS availability
- Builds URL from hostname: https://<hostname -s>.bancamarch.es:8443
- Checks TCP+SSL connectivity via curl -vk
- Publishes gauge metric (1=connected, 0=failed)
- Extracts cert subject and publishes as a label

Requires:
  - curl available on the system
  - bm_otel_publish_metric.py available (BM_OTEL_WRAPPER)

Manual test:
  python3 mdp_https_availability.py
"""

import os
import re
import subprocess

from bm_transact_lib import log, build_base_labels, publish_gauge, get_metric_name

SCRIPT_NAME = os.path.basename(__file__)


def get_hostname_short() -> str:
    result = subprocess.run(["hostname", "-s"], text=True, capture_output=True)
    return result.stdout.strip()


def check_https(url: str) -> tuple[int, str]:
    """
    Returns (value, cert_subject).
    value: 1 if connected, 0 if failed.
    cert_subject: extracted from curl output or 'unknown'.
    """
    try:
        result = subprocess.run(
            ["curl", "-vk", "--max-time", "10", url],
            text=True,
            capture_output=True,
        )
        output = result.stderr + result.stdout

        connected = 1 if "Connected" in output else 0

        subject_match = re.search(r"subject:\s*(.+)", output)
        cert_subject = subject_match.group(1).strip() if subject_match else "unknown"

        return connected, cert_subject

    except Exception as e:
        raise RuntimeError(f"curl execution failed: {e}")


def main() -> int:
    metric_name = get_metric_name(__file__)

    try:
        hostname = get_hostname_short()
        url = f"https://{hostname}.bancamarch.es:8443"

        value, cert_subject = check_https(url)

        labels = build_base_labels(source="network")
        labels.append("component=https")
        labels.append(f"url={url}")
        labels.append(f"cert_subject={cert_subject}")

        publish_gauge(metric_name, value, labels)
        log(f"{metric_name} = {value} [{SCRIPT_NAME}]")
        return 0

    except Exception as e:
        log(f"ERROR [{SCRIPT_NAME}]: {e}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
