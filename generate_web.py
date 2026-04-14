#!/usr/bin/env python3
import argparse

from common import (
    HOSTS,
    ORGANIZATION_NAME,
    add_common_args,
    bulk_index,
    choose_user,
    init_rng,
    isoformat_utc,
    new_session_id,
    new_trace_id,
    parse_start_time,
    print_summary,
    random_attack_ip,
    random_internal_ip,
    random_timestamp,
    weighted_choice,
)

INDEX = "lab-web-access"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate synthetic web access events")
    return add_common_args(parser, default_count=3000)


def generate_docs(count: int, seed: int, start_time: str, hours: int):
    rng = init_rng(seed)
    start = parse_start_time(start_time, hours)

    methods = ["GET", "GET", "GET", "POST", "PUT"]
    paths = ["/", "/products", "/cart", "/login", "/checkout"]
    user_agents = [
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5)",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Mozilla/5.0 (X11; Linux x86_64)",
        "curl/8.7.1",
        "python-requests/2.32.0",
    ]
    referrers = [
        "https://search.example.com",
        "https://ads.example.com",
        "https://acme-retail.example/",
        "",
    ]

    docs = []
    for _ in range(max(0, count)):
        user = choose_user(rng)
        is_bot = rng.random() < 0.01
        anomaly = rng.random() < 0.03

        base_path = weighted_choice(rng, paths, [26, 34, 10, 14, 16])
        if base_path == "/products" and rng.random() < 0.7:
            base_path = f"/products/{rng.randint(1000, 1099)}"

        status = weighted_choice(rng, [200, 404, 500], [96.5, 2.8, 0.7])
        duration_ms = int(max(5, rng.gauss(120, 45)))
        if anomaly or status == 500:
            duration_ms = int(max(duration_ms, rng.uniform(1200, 6000)))

        ua = weighted_choice(rng, user_agents, [35, 35, 22, 4, 4])
        source_ip = random_internal_ip(rng)
        if is_bot:
            ua = weighted_choice(rng, ["curl/8.7.1", "python-requests/2.32.0"], [1, 1])
            source_ip = random_attack_ip(rng)

        event_outcome = "success" if status < 400 else "failure"
        method = weighted_choice(rng, methods, [65, 20, 10, 4, 1])

        docs.append(
            {
                "@timestamp": isoformat_utc(random_timestamp(rng, start, hours)),
                "event": {
                    "dataset": "web.access",
                    "action": "http_request",
                    "outcome": event_outcome,
                    "duration": duration_ms * 1_000_000,
                },
                "organization": {"name": ORGANIZATION_NAME},
                "url": {"path": base_path},
                "http": {
                    "request": {"method": method},
                    "response": {"status_code": status},
                },
                "user_agent": {"original": ua},
                "source": {"ip": source_ip},
                "user": {"id": user["id"], "name": user["name"]},
                "session": {"id": new_session_id()},
                "trace": {"id": new_trace_id()},
                "host": {"name": weighted_choice(rng, HOSTS["web"], [1, 1])},
                "bytes": max(250, int(rng.gauss(5400, 1300))),
                "referrer": weighted_choice(rng, referrers, [30, 8, 50, 12]),
                "service": {"name": "storefront"},
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
