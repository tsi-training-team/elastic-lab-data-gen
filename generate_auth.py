#!/usr/bin/env python3
import argparse

from common import (
    HOSTS,
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
    random_internal_ip,
    random_timestamp,
    iteration_seed,
    sleep_between_iterations,
    weighted_choice,
)

INDEX = "lab-auth"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate synthetic authentication events")
    return add_common_args(parser, default_count=2000)


def generate_docs(count: int, seed: int, start_time: str, hours: int):
    rng = init_rng(seed)
    start = parse_start_time(start_time, hours)

    suspicious_users = rng.sample(USERS, k=4)
    methods = ["password", "sso", "mfa"]
    docs = []

    for _ in range(max(0, count)):
        user = weighted_choice(rng, USERS, [3 if u in suspicious_users else 1 for u in USERS])
        is_suspicious_user = user in suspicious_users
        attackish = is_suspicious_user and rng.random() < 0.35

        success = rng.random() < (0.75 if attackish else 0.96)
        if attackish and rng.random() < 0.8:
            success = False

        failure_reason = ""
        risk_score = int(max(1, min(99, rng.gauss(18, 9))))
        source_ip = random_internal_ip(rng)

        if not success:
            failure_reason = weighted_choice(
                rng,
                ["invalid_password", "account_locked", "mfa_failed"],
                [75, 15, 10],
            )
            risk_score = int(max(30, min(99, rng.gauss(70, 12))))
            if attackish:
                source_ip = random_attack_ip(rng)

        docs.append(
            {
                "@timestamp": isoformat_utc(random_timestamp(rng, start, hours)),
                "event": {
                    "dataset": "auth",
                    "action": "login",
                    "outcome": "success" if success else "failure",
                },
                "organization": {"name": ORGANIZATION_NAME},
                "user": {"id": user["id"], "name": user["name"]},
                "source": {"ip": source_ip},
                "host": {"name": weighted_choice(rng, HOSTS["auth"], [1, 1])},
                "authentication": {"method": weighted_choice(rng, methods, [82, 12, 6])},
                "failure_reason": failure_reason,
                "risk_score": risk_score,
                "session": {"id": new_session_id()},
                "trace": {"id": new_trace_id()},
                "service": {"name": "auth-service"},
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
