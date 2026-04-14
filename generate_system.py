#!/usr/bin/env python3
import argparse

from common import (
    HOSTS,
    ORGANIZATION_NAME,
    add_common_args,
    bulk_index,
    init_rng,
    isoformat_utc,
    new_trace_id,
    parse_start_time,
    print_summary,
    random_internal_ip,
    random_timestamp,
    weighted_choice,
)

INDEX = "lab-system"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate synthetic system telemetry events")
    return add_common_args(parser, default_count=2000)


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def generate_docs(count: int, seed: int, start_time: str, hours: int):
    rng = init_rng(seed)
    start = parse_start_time(start_time, hours)

    degraded_host = "app-02"
    processes = ["nginx", "python-app", "java-worker", "elastic-agent", "postgres"]

    docs = []
    for _ in range(max(0, count)):
        host = weighted_choice(rng, HOSTS["system"], [20, 18, 18, 16, 16, 12])
        spike = rng.random() < 0.03
        is_degraded = host == degraded_host and rng.random() < 0.25

        cpu = _clamp(rng.gauss(0.35, 0.12), 0.03, 0.95)
        mem = _clamp(rng.gauss(0.52, 0.14), 0.08, 0.96)
        disk = _clamp(rng.gauss(0.58, 0.10), 0.12, 0.97)
        load1 = _clamp(rng.gauss(1.2, 0.6), 0.01, 12.0)

        if spike:
            cpu = _clamp(rng.uniform(0.82, 0.99), 0.0, 1.0)
            mem = _clamp(max(mem, rng.uniform(0.76, 0.97)), 0.0, 1.0)
            load1 = _clamp(rng.uniform(5.0, 12.0), 0.0, 12.0)

        if is_degraded:
            cpu = _clamp(max(cpu, rng.uniform(0.68, 0.9)), 0.0, 1.0)
            mem = _clamp(max(mem, rng.uniform(0.74, 0.93)), 0.0, 1.0)
            disk = _clamp(max(disk, rng.uniform(0.78, 0.95)), 0.0, 1.0)
            load1 = _clamp(max(load1, rng.uniform(3.0, 7.5)), 0.0, 12.0)

        severity = 2
        message = "Host healthy"
        if cpu > 0.85 or mem > 0.88 or disk > 0.9:
            severity = 5
            message = "Resource pressure detected"
        elif cpu > 0.7 or mem > 0.75:
            severity = 3
            message = "Resource usage above baseline"

        docs.append(
            {
                "@timestamp": isoformat_utc(random_timestamp(rng, start, hours)),
                "event": {
                    "dataset": "system",
                    "action": "metric",
                    "outcome": "success" if severity <= 3 else "warning",
                    "severity": severity,
                },
                "organization": {"name": ORGANIZATION_NAME},
                "host": {"name": host},
                "cpu": {"usage": round(cpu, 4)},
                "memory": {"used": {"pct": round(mem, 4)}},
                "disk": {"used": {"pct": round(disk, 4)}},
                "load": {"1": round(load1, 3)},
                "process": {"name": weighted_choice(rng, processes, [26, 29, 16, 19, 10])},
                "message": message,
                "source": {"ip": random_internal_ip(rng)},
                "trace": {"id": new_trace_id()},
                "service": {"name": "elastic-agent"},
            }
        )

    return docs


def main():
    args = build_parser().parse_args()
    docs = generate_docs(args.count, args.seed, args.start_time, args.hours)

    if args.dry_run:
        print_summary(INDEX, len(docs), 0, 0, True)
        return

    indexed, failures, errors = bulk_index(
        args.es_url,
        INDEX,
        docs,
        username=args.username,
        password=args.password,
    )
    print_summary(INDEX, len(docs), indexed, failures, False, errors)


if __name__ == "__main__":
    main()
