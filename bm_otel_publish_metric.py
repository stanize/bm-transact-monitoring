#!/usr/bin/env python3
"""
bm_otel_publish_metric.py

Static wrapper to publish ONE metric sample to OTEL Collector via OTLP/gRPC.

Usage:
  ./bm_otel_publish_metric.py <type> <metric_name> <value> key=value ...

Types:
  gauge | counter | updowncounter | histogram

Label contract:
  Required: service, component, env, vm
  Optional: status
  Extensible: details="k=v;k=v"
    - If details is NOT provided, it is auto-built from any remaining key=value pairs.

Configuration:
  All settings are loaded exclusively from config/otel_config.json.
  The process exits with rc=2 if the file is missing, unreadable, or incomplete.

  otel_config.json required keys:
    endpoint              OTLP/gRPC collector endpoint  (e.g. http://172.29.2.8:4317)
    service_name          OTEL service.name resource attribute
    export_interval_ms    Export interval in milliseconds (integer)
"""

import json
import os
import sys
import time
from typing import Dict

from opentelemetry import metrics
from opentelemetry.metrics import Observation
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter


# ---------------------------------------------------------------------------
# Config loader — fail-fast, no env var fallbacks
# ---------------------------------------------------------------------------
_OTEL_CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config", "otel_config.json")
_OTEL_REQUIRED_KEYS = ("endpoint", "service_name", "export_interval_ms")


def _load_otel_config() -> Dict:
    """
    Load and validate config/otel_config.json.
    Prints an error and exits with rc=2 on any failure.
    """
    if not os.path.exists(_OTEL_CONFIG_PATH):
        print(f"ERROR: otel_config.json not found: {_OTEL_CONFIG_PATH}", file=sys.stderr)
        raise SystemExit(2)

    try:
        with open(_OTEL_CONFIG_PATH, "r") as f:
            cfg = json.load(f)
    except Exception as e:
        print(f"ERROR: Failed to parse otel_config.json: {e}", file=sys.stderr)
        raise SystemExit(2)

    missing = [k for k in _OTEL_REQUIRED_KEYS if cfg.get(k) is None]
    if missing:
        print(f"ERROR: otel_config.json is missing required key(s): {', '.join(missing)}", file=sys.stderr)
        raise SystemExit(2)

    return cfg


_otel_cfg = _load_otel_config()

OTEL_ENDPOINT    = _otel_cfg["endpoint"]
OTEL_SERVICE_NAME = _otel_cfg["service_name"]
EXPORT_INTERVAL_MS = int(_otel_cfg["export_interval_ms"])

REQUIRED_STABLE  = ("service", "component", "env", "vm")
OPTIONAL_STABLE  = ("status",)
EXTENSIBLE_LABEL = "details"


# ---------------------------------------------------------------------------
# Label helpers
# ---------------------------------------------------------------------------
def parse_kv(args) -> Dict[str, str]:
    attrs: Dict[str, str] = {}
    for a in args:
        if "=" not in a:
            raise ValueError(f"Invalid attribute '{a}'. Use key=value.")
        k, v = a.split("=", 1)
        k, v = k.strip(), v.strip()
        if not k:
            raise ValueError(f"Invalid attribute '{a}': empty key.")
        attrs[k] = v
    return attrs


def normalize_labels(attrs_in: Dict[str, str]) -> Dict[str, str]:
    missing = [k for k in REQUIRED_STABLE if k not in attrs_in]
    if missing:
        raise ValueError(f"Missing required labels: {', '.join(missing)}")

    out = {k: attrs_in[k] for k in REQUIRED_STABLE}
    for k in OPTIONAL_STABLE:
        if k in attrs_in:
            out[k] = attrs_in[k]

    # Explicit details wins
    if EXTENSIBLE_LABEL in attrs_in and attrs_in[EXTENSIBLE_LABEL]:
        out[EXTENSIBLE_LABEL] = attrs_in[EXTENSIBLE_LABEL]
        return out

    # Auto-build details from extras
    extras = {
        k: v for k, v in attrs_in.items()
        if k not in REQUIRED_STABLE and k not in OPTIONAL_STABLE and k != EXTENSIBLE_LABEL
    }
    if extras:
        out[EXTENSIBLE_LABEL] = ";".join([f"{k}={extras[k]}" for k in sorted(extras.keys())])

    return out


# ---------------------------------------------------------------------------
# OTEL provider setup
# ---------------------------------------------------------------------------
def setup_provider() -> MeterProvider:
    resource = Resource.create({
        "service.name": OTEL_SERVICE_NAME,
        "host.name": os.uname().nodename,
    })

    exporter = OTLPMetricExporter(endpoint=OTEL_ENDPOINT, insecure=True)
    reader = PeriodicExportingMetricReader(exporter, export_interval_millis=EXPORT_INTERVAL_MS)

    provider = MeterProvider(resource=resource, metric_readers=[reader])
    metrics.set_meter_provider(provider)
    return provider


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def usage() -> int:
    print(__doc__.strip())
    return 2


def main() -> int:
    if len(sys.argv) < 4:
        return usage()

    mtype = sys.argv[1].strip().lower()
    metric_name = sys.argv[2].strip()
    raw_value = sys.argv[3].strip()

    if mtype not in ("gauge", "counter", "updowncounter", "histogram"):
        print(f"Invalid type: {mtype}", file=sys.stderr)
        return usage()

    if not metric_name:
        print("metric_name must not be empty", file=sys.stderr)
        return 2

    try:
        value = float(raw_value)
    except ValueError:
        print(f"value must be numeric. Got: {raw_value}", file=sys.stderr)
        return 2

    try:
        attrs_in = parse_kv(sys.argv[4:])
        labels = normalize_labels(attrs_in)
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 2

    provider = setup_provider()
    meter = metrics.get_meter("bm.publisher")

    if mtype == "gauge":
        # In Python OTEL SDK, a Gauge is callback-based (observable).
        # For a one-shot wrapper, we register a callback returning a single observation
        # and wait for one export cycle.
        sample = {"value": value, "labels": labels}

        def observe(_options=None):
            return [Observation(sample["value"], sample["labels"])]

        meter.create_observable_gauge(
            name=metric_name,
            callbacks=[observe],
            description="BM gauge metric (one-shot wrapper)",
            unit="1",
        )

        # wait for at least one collection/export
        time.sleep((EXPORT_INTERVAL_MS / 1000.0) + 0.2)

    elif mtype == "counter":
        if value < 0:
            print("counter cannot add negative values; use updowncounter", file=sys.stderr)
            provider.shutdown()
            return 2
        c = meter.create_counter(
            name=metric_name,
            description="BM counter metric (one-shot wrapper)",
            unit="1",
        )
        c.add(value, labels)

    elif mtype == "updowncounter":
        udc = meter.create_up_down_counter(
            name=metric_name,
            description="BM updowncounter metric (one-shot wrapper)",
            unit="1",
        )
        udc.add(value, labels)

    elif mtype == "histogram":
        h = meter.create_histogram(
            name=metric_name,
            description="BM histogram metric (one-shot wrapper)",
            unit="1",
        )
        h.record(value, labels)

    # Flush and exit cleanly
    try:
        provider.force_flush()
    except Exception:
        pass
    provider.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
