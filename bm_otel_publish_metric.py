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

Env vars:
  OTEL_EXPORTER_OTLP_ENDPOINT (default: http://172.29.2.8:4317)
  OTEL_SERVICE_NAME           (default: bm-metrics-publisher)
  BM_EXPORT_INTERVAL_MS       (default: 1000)
"""

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


DEFAULT_OTEL_ENDPOINT = "http://172.29.2.8:4317"
DEFAULT_OTEL_SERVICE_NAME = "bm-metrics-publisher"

EXPORT_INTERVAL_MS = int(os.environ.get("BM_EXPORT_INTERVAL_MS", "1000"))

REQUIRED_STABLE = ("service", "component", "env", "vm")
OPTIONAL_STABLE = ("status",)
EXTENSIBLE_LABEL = "details"


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


def setup_provider() -> MeterProvider:
    endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", DEFAULT_OTEL_ENDPOINT)
    otel_service_name = os.environ.get("OTEL_SERVICE_NAME", DEFAULT_OTEL_SERVICE_NAME)
    hostname = os.uname().nodename

    resource = Resource.create({
        "service.name": otel_service_name,
        "host.name": hostname,
    })

    exporter = OTLPMetricExporter(endpoint=endpoint, insecure=True)
    reader = PeriodicExportingMetricReader(exporter, export_interval_millis=EXPORT_INTERVAL_MS)

    provider = MeterProvider(resource=resource, metric_readers=[reader])
    metrics.set_meter_provider(provider)
    return provider


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
