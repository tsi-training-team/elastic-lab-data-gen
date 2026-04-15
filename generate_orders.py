#!/usr/bin/env python3
import argparse
import uuid

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
    random_internal_ip,
    random_timestamp,
    iteration_seed,
    sleep_between_iterations,
    weighted_choice,
)

INDEX = "lab-orders"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate synthetic ecommerce order events")
    return add_common_args(parser, default_count=1200)


def generate_docs(count: int, seed: int, start_time: str, hours: int):
    rng = init_rng(seed)
    start = parse_start_time(start_time, hours)

    categories = ["electronics", "home", "fashion", "books", "beauty", "grocery"]
    payment_methods = ["card", "paypal", "apple_pay", "bank_transfer"]
    regions = ["NA", "EMEA", "APAC", "LATAM"]

    vip_users = {u["id"] for u in rng.sample(USERS, k=8)}

    docs = []
    for _ in range(max(0, count)):
        user = weighted_choice(rng, USERS, [2 if u["id"] in vip_users else 1 for u in USERS])
        is_vip = user["id"] in vip_users

        status = weighted_choice(rng, ["completed", "failed_payment", "refunded"], [91, 5, 4])
        items_count = weighted_choice(rng, [1, 2, 3, 4, 5, 6], [30, 27, 20, 12, 7, 4])
        base_total = max(8.0, rng.gauss(85.0, 45.0))

        if is_vip and rng.random() < 0.3:
            base_total *= rng.uniform(1.3, 2.4)

        high_value = rng.random() < 0.02
        if high_value:
            base_total = max(base_total, rng.uniform(600.0, 2200.0))

        fraud_score = int(max(1, min(99, rng.gauss(14, 8))))
        if status != "completed" or high_value:
            fraud_score = int(max(fraud_score, min(99, rng.gauss(62, 18))))

        event_outcome = "success" if status == "completed" else "failure"
        order_total = round(base_total * max(1, items_count / 2), 2)

        docs.append(
            {
                "@timestamp": isoformat_utc(random_timestamp(rng, start, hours)),
                "event": {
                    "dataset": "commerce.orders",
                    "action": "order",
                    "outcome": event_outcome,
                },
                "organization": {"name": ORGANIZATION_NAME},
                "order": {
                    "id": "ord-" + uuid.uuid4().hex[:12],
                    "total": order_total,
                    "status": status,
                },
                "customer": {
                    "id": user["id"],
                    "tier": "vip" if is_vip else weighted_choice(rng, ["standard", "gold"], [85, 15]),
                },
                "product": {"category": weighted_choice(rng, categories, [23, 18, 21, 13, 11, 14])},
                "payment": {"method": weighted_choice(rng, payment_methods, [71, 16, 8, 5])},
                "shipping": {"region": weighted_choice(rng, regions, [50, 24, 20, 6])},
                "items_count": items_count,
                "fraud": {"score": fraud_score},
                "user": {"id": user["id"], "name": user["name"]},
                "source": {"ip": random_internal_ip(rng)},
                "session": {"id": new_session_id()},
                "trace": {"id": new_trace_id()},
                "service": {"name": "checkout"},
            }
        )

    return docs


def main():
    args = build_parser().parse_args()
    iteration = 0
    try:
        while True:
            docs = generate_docs(
                args.count,
                iteration_seed(args.seed, iteration),
                args.start_time,
                args.hours,
            )

            if args.dry_run:
                print_summary(INDEX, len(docs), 0, 0, True)
            else:
                indexed, failures, errors = bulk_index(
                    args.es_url,
                    INDEX,
                    docs,
                    username=args.username,
                    password=args.password,
                )
                print_summary(INDEX, len(docs), indexed, failures, False, errors)

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
