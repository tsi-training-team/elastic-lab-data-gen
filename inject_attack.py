#!/usr/bin/env python3
import argparse
import uuid
from collections import defaultdict
from datetime import timedelta

from common import (
    ORGANIZATION_NAME,
    USERS,
    add_common_args,
    bulk_index,
    init_rng,
    isoformat_utc,
    new_session_id,
    new_trace_id,
    parse_start_time,
    print_summary,
    random_attack_ip,
    iteration_seed,
    sleep_between_iterations,
)

AUTH_INDEX = "lab-auth"
WEB_INDEX = "lab-web-access"
ORDERS_INDEX = "lab-orders"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Inject a correlated suspicious scenario")
    return add_common_args(parser, default_count=200)


def _build_attack_docs(count: int, seed: int, start_time: str, hours: int):
    rng = init_rng(seed)
    start = parse_start_time(start_time, hours)

    docs_by_index = defaultdict(list)

    attacker_ip = random_attack_ip(rng)
    spray_targets = rng.sample(USERS, k=min(20, max(8, count // 12)))
    compromised_user = spray_targets[-1]
    compromised_session = new_session_id()
    shared_trace = new_trace_id()

    auth_count = max(12, int(count * 0.62))
    web_count = max(8, int(count * 0.33))
    order_count = 1 if count >= 120 else 0

    base_ts = start + timedelta(minutes=rng.randint(0, max(1, hours * 60 - 40)))

    for i in range(auth_count - 1):
        user = spray_targets[i % len(spray_targets)]
        ts = base_ts + timedelta(seconds=i * rng.randint(8, 20))
        docs_by_index[AUTH_INDEX].append(
            {
                "@timestamp": isoformat_utc(ts),
                "event": {"dataset": "auth", "action": "login", "outcome": "failure"},
                "organization": {"name": ORGANIZATION_NAME},
                "user": {"id": user["id"], "name": user["name"]},
                "source": {"ip": attacker_ip},
                "host": {"name": "auth-01"},
                "authentication": {"method": "password"},
                "failure_reason": "invalid_password",
                "risk_score": rng.randint(78, 95),
                "session": {"id": new_session_id()},
                "trace": {"id": shared_trace},
                "service": {"name": "auth-service"},
            }
        )

    success_ts = base_ts + timedelta(minutes=18)
    docs_by_index[AUTH_INDEX].append(
        {
            "@timestamp": isoformat_utc(success_ts),
            "event": {"dataset": "auth", "action": "login", "outcome": "success"},
            "organization": {"name": ORGANIZATION_NAME},
            "user": {"id": compromised_user["id"], "name": compromised_user["name"]},
            "source": {"ip": attacker_ip},
            "host": {"name": "auth-02"},
            "authentication": {"method": "password"},
            "failure_reason": "",
            "risk_score": rng.randint(65, 88),
            "session": {"id": compromised_session},
            "trace": {"id": shared_trace},
            "service": {"name": "auth-service"},
        }
    )

    suspicious_paths = ["/login", "/account", "/cart", "/checkout", f"/products/{rng.randint(1000, 1099)}"]
    for i in range(web_count):
        ts = success_ts + timedelta(minutes=1, seconds=i * rng.randint(12, 30))
        path = suspicious_paths[i % len(suspicious_paths)]
        status = 200 if i < web_count - 2 else 404
        docs_by_index[WEB_INDEX].append(
            {
                "@timestamp": isoformat_utc(ts),
                "event": {
                    "dataset": "web.access",
                    "action": "http_request",
                    "outcome": "success" if status == 200 else "failure",
                    "duration": int(rng.uniform(1200, 5500) * 1_000_000),
                },
                "organization": {"name": ORGANIZATION_NAME},
                "url": {"path": path},
                "http": {"request": {"method": "POST" if path in {"/login", "/checkout"} else "GET"}, "response": {"status_code": status}},
                "user_agent": {"original": "python-requests/2.32.0"},
                "source": {"ip": attacker_ip},
                "user": {"id": compromised_user["id"], "name": compromised_user["name"]},
                "session": {"id": compromised_session},
                "trace": {"id": shared_trace},
                "host": {"name": "web-01"},
                "bytes": int(rng.uniform(4500, 14000)),
                "referrer": "",
                "service": {"name": "storefront"},
            }
        )

    if order_count:
        order_ts = success_ts + timedelta(minutes=8)
        docs_by_index[ORDERS_INDEX].append(
            {
                "@timestamp": isoformat_utc(order_ts),
                "event": {"dataset": "commerce.orders", "action": "order", "outcome": "success"},
                "organization": {"name": ORGANIZATION_NAME},
                "order": {
                    "id": "ord-" + uuid.uuid4().hex[:12],
                    "total": round(rng.uniform(1450.0, 2900.0), 2),
                    "status": "completed",
                },
                "customer": {"id": compromised_user["id"], "tier": "standard"},
                "product": {"category": "electronics"},
                "payment": {"method": "card"},
                "shipping": {"region": "NA"},
                "items_count": rng.randint(2, 5),
                "fraud": {"score": rng.randint(78, 96)},
                "user": {"id": compromised_user["id"], "name": compromised_user["name"]},
                "source": {"ip": attacker_ip},
                "session": {"id": compromised_session},
                "trace": {"id": shared_trace},
                "service": {"name": "checkout"},
            }
        )

    return docs_by_index


def main():
    args = build_parser().parse_args()
    iteration = 0
    try:
        while True:
            docs_by_index = _build_attack_docs(
                args.count,
                iteration_seed(args.seed, iteration),
                args.start_time,
                args.hours,
            )

            for index, docs in docs_by_index.items():
                if args.dry_run:
                    print_summary(index, len(docs), 0, 0, True)
                    continue

                indexed, failures, errors = bulk_index(
                    args.es_url,
                    index,
                    docs,
                    username=args.username,
                    password=args.password,
                )
                print_summary(index, len(docs), indexed, failures, False, errors)

            iteration += 1
            if not args.continuous:
                break
            if args.max_iterations > 0 and iteration >= args.max_iterations:
                break
            sleep_between_iterations(args.interval_seconds)
    except KeyboardInterrupt:
        print("Interrupted; exiting.")


if __name__ == "__main__":
    main()
