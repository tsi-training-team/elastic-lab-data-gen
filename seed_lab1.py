#!/usr/bin/env python3
import argparse
import uuid
from collections import defaultdict
from datetime import timedelta
from typing import Dict, List, Optional

from common import (
    HOSTS,
    ORGANIZATION_NAME,
    USERS,
    bulk_index,
    init_rng,
    isoformat_utc,
    new_session_id,
    new_trace_id,
    parse_start_time,
    print_summary,
    random_internal_ip,
    random_timestamp,
    weighted_choice,
)

WEB_INDEX = "lab-web-access"
AUTH_INDEX = "lab-auth"
ORDERS_INDEX = "lab-orders"
SYSTEM_INDEX = "lab-system"

IP_PRIMARY = "185.220.101.21"
IP_SECONDARY = "91.92.109.77"
IP_TERTIARY = "198.51.100.23"
IP_SINGLE_FAILURE = "203.0.113.10"

KEY_USERS = {
    "user-010",
    "user-020",
    "user-030",
    "user-050",
    "user-075",
    "user-090",
    "user-100",
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Seed guaranteed Lab 1 ES|QL training scenarios across all lab indices"
    )
    parser.add_argument("--es-url", default="", help="Elasticsearch URL (example: http://localhost:9200)")
    parser.add_argument("--username", default="", help="Elasticsearch username")
    parser.add_argument("--password", default="", help="Elasticsearch password")
    parser.add_argument("--count", type=int, default=1000, help="Approximate number of documents to generate")
    parser.add_argument("--dry-run", action="store_true", help="Generate data without indexing")
    parser.add_argument("--seed", type=int, default=None, help="Deterministic random seed")
    parser.add_argument(
        "--start-time",
        default="",
        help="Start timestamp in ISO8601 (default: now-<hours>)",
    )
    parser.add_argument("--hours", type=int, default=24, help="Time window span in hours")
    return parser


def _user_map() -> Dict[str, dict]:
    return {u["id"]: u for u in USERS}


def _web_doc(ts, user, source_ip, path, method, status, duration_ms, host, ua, referrer, session_id, trace_id):
    return {
        "@timestamp": isoformat_utc(ts),
        "event": {
            "dataset": "web.access",
            "action": "http_request",
            "outcome": "success" if status < 400 else "failure",
            "duration": duration_ms * 1_000_000,
        },
        "organization": {"name": ORGANIZATION_NAME},
        "url": {"path": path},
        "http": {"request": {"method": method}, "response": {"status_code": status}},
        "user_agent": {"original": ua},
        "source": {"ip": source_ip},
        "user": {"id": user["id"], "name": user["name"]},
        "session": {"id": session_id},
        "trace": {"id": trace_id},
        "host": {"name": host},
        "bytes": 4200,
        "referrer": referrer,
        "service": {"name": "storefront"},
    }


def _auth_doc(ts, user, source_ip, outcome, method, host, reason, risk, session_id, trace_id):
    return {
        "@timestamp": isoformat_utc(ts),
        "event": {"dataset": "auth", "action": "login", "outcome": outcome},
        "organization": {"name": ORGANIZATION_NAME},
        "user": {"id": user["id"], "name": user["name"]},
        "source": {"ip": source_ip},
        "host": {"name": host},
        "authentication": {"method": method},
        "failure_reason": reason,
        "risk_score": risk,
        "session": {"id": session_id},
        "trace": {"id": trace_id},
        "service": {"name": "auth-service"},
    }


def _orders_doc(ts, user, source_ip, total, status, fraud_score, category, payment_method, shipping_region, session_id, trace_id):
    return {
        "@timestamp": isoformat_utc(ts),
        "event": {
            "dataset": "commerce.orders",
            "action": "order",
            "outcome": "success" if status == "completed" else "failure",
        },
        "organization": {"name": ORGANIZATION_NAME},
        "order": {"id": "ord-" + uuid.uuid4().hex[:12], "total": round(total, 2), "status": status},
        "customer": {"id": user["id"], "tier": "standard"},
        "product": {"category": category},
        "payment": {"method": payment_method},
        "shipping": {"region": shipping_region},
        "items_count": 2,
        "fraud": {"score": fraud_score},
        "user": {"id": user["id"], "name": user["name"]},
        "source": {"ip": source_ip},
        "session": {"id": session_id},
        "trace": {"id": trace_id},
        "service": {"name": "checkout"},
    }


def _system_doc(ts, host, cpu, mem, disk, load1, severity, message, source_ip, process_name, trace_id):
    return {
        "@timestamp": isoformat_utc(ts),
        "event": {
            "dataset": "system",
            "action": "metric",
            "outcome": "warning" if severity >= 4 else "success",
            "severity": severity,
        },
        "organization": {"name": ORGANIZATION_NAME},
        "host": {"name": host},
        "cpu": {"usage": round(cpu, 4)},
        "memory": {"used": {"pct": round(mem, 4)}},
        "disk": {"used": {"pct": round(disk, 4)}},
        "load": {"1": round(load1, 3)},
        "process": {"name": process_name},
        "message": message,
        "source": {"ip": source_ip},
        "trace": {"id": trace_id},
        "service": {"name": "elastic-agent"},
    }


def _mandatory_scenarios(docs: Dict[str, List[dict]], users: Dict[str, dict], t_base) -> None:
    # Fixed principal identities for cross-index timeline queries.
    u010 = users["user-010"]
    u020 = users["user-020"]
    u030 = users["user-030"]
    u050 = users["user-050"]
    u075 = users["user-075"]
    u090 = users["user-090"]
    u100 = users["user-100"]

    trace_050 = new_trace_id()
    sess_050 = new_session_id()

    # Auth: spray + thresholds + per-user patterns.
    spray_targets = [users[f"user-{i:03d}"] for i in range(1, 13)]
    for i in range(24):
        target = spray_targets[i % len(spray_targets)]
        ts = t_base + timedelta(seconds=i * 15)
        docs[AUTH_INDEX].append(
            _auth_doc(ts, target, IP_PRIMARY, "failure", "password", "auth-01", "invalid_password", 88, new_session_id(), new_trace_id())
        )

    for i in range(8):
        ts = t_base + timedelta(minutes=6, seconds=i * 18)
        docs[AUTH_INDEX].append(
            _auth_doc(ts, u050, IP_PRIMARY, "failure", "password", "auth-01", "invalid_password", 92, new_session_id(), trace_050)
        )

    docs[AUTH_INDEX].append(
        _auth_doc(
            t_base + timedelta(minutes=9),
            u050,
            IP_PRIMARY,
            "success",
            "password",
            "auth-02",
            "",
            72,
            sess_050,
            trace_050,
        )
    )

    for i in range(12):
        ts = t_base + timedelta(minutes=11, seconds=i * 13)
        docs[AUTH_INDEX].append(
            _auth_doc(ts, u075, IP_SECONDARY, "failure", "password", "auth-01", "invalid_password", 86, new_session_id(), new_trace_id())
        )

    for i in range(6):
        ts = t_base + timedelta(minutes=13, seconds=i * 21)
        docs[AUTH_INDEX].append(
            _auth_doc(ts, u010, IP_SECONDARY, "failure", "password", "auth-01", "invalid_password", 84, new_session_id(), new_trace_id())
        )

    docs[AUTH_INDEX].append(
        _auth_doc(
            t_base + timedelta(minutes=16),
            u010,
            IP_SECONDARY,
            "success",
            "password",
            "auth-02",
            "",
            48,
            new_session_id(),
            new_trace_id(),
        )
    )

    for i in range(11):
        ts = t_base + timedelta(minutes=17, seconds=i * 17)
        docs[AUTH_INDEX].append(
            _auth_doc(ts, users[f"user-{(20 + i) % 120 + 1:03d}"], IP_TERTIARY, "failure", "password", "auth-01", "invalid_password", 80, new_session_id(), new_trace_id())
        )

    docs[AUTH_INDEX].append(
        _auth_doc(
            t_base + timedelta(minutes=22),
            users["user-099"],
            IP_SINGLE_FAILURE,
            "failure",
            "password",
            "auth-01",
            "invalid_password",
            70,
            new_session_id(),
            new_trace_id(),
        )
    )

    # Add auth presence for user IDs called out in labs.
    docs[AUTH_INDEX].append(_auth_doc(t_base + timedelta(minutes=24), u020, IP_PRIMARY, "success", "sso", "auth-02", "", 35, new_session_id(), new_trace_id()))
    docs[AUTH_INDEX].append(_auth_doc(t_base + timedelta(minutes=25), u030, IP_PRIMARY, "success", "password", "auth-02", "", 36, new_session_id(), new_trace_id()))
    docs[AUTH_INDEX].append(_auth_doc(t_base + timedelta(minutes=26), u090, IP_TERTIARY, "success", "password", "auth-02", "", 42, new_session_id(), new_trace_id()))
    docs[AUTH_INDEX].append(_auth_doc(t_base + timedelta(minutes=27), u100, IP_PRIMARY, "failure", "password", "auth-01", "invalid_password", 76, new_session_id(), new_trace_id()))
    docs[AUTH_INDEX].append(_auth_doc(t_base + timedelta(minutes=28), u100, IP_PRIMARY, "success", "password", "auth-02", "", 55, new_session_id(), new_trace_id()))

    # Web: exact paths + status slices + cross-index correlation.
    def add_web_series(user, source_ip, path, total, status_cycle, host, base_minute):
        for i in range(total):
            ts = t_base + timedelta(minutes=base_minute, seconds=i * 11)
            status = status_cycle[i % len(status_cycle)]
            duration = 120 if path == "/products" else 240
            if status >= 500:
                duration = 3200
            elif path == "/checkout":
                duration = 850
            docs[WEB_INDEX].append(
                _web_doc(
                    ts,
                    user,
                    source_ip,
                    path,
                    "POST" if path in {"/login", "/checkout"} else "GET",
                    status,
                    duration,
                    host,
                    "Mozilla/5.0",
                    "https://search.example.com",
                    new_session_id(),
                    new_trace_id(),
                )
            )

    add_web_series(u050, IP_PRIMARY, "/cart", 25, [200, 200, 404, 500], "web-01", 30)
    add_web_series(u050, IP_PRIMARY, "/login", 25, [200, 200, 404], "web-01", 36)
    add_web_series(u050, IP_PRIMARY, "/checkout", 25, [200, 500, 404], "web-02", 42)
    add_web_series(u050, IP_PRIMARY, "/products", 25, [200, 200, 200, 404], "web-02", 48)

    # Ensure >=20 hard 500s for LIMIT queries.
    for i in range(22):
        ts = t_base + timedelta(minutes=54, seconds=i * 9)
        docs[WEB_INDEX].append(
            _web_doc(ts, users[f"user-{(i % 12) + 1:03d}"], IP_PRIMARY, "/checkout", "GET", 500, 4500, "web-01", "curl/8.7.1", "", new_session_id(), new_trace_id())
        )

    # Specific user/IP timeline coverage.
    timeline_rows = [
        (u010, IP_SECONDARY, "/login", 200),
        (u010, IP_SECONDARY, "/checkout", 200),
        (u075, IP_SECONDARY, "/cart", 404),
        (u100, IP_PRIMARY, "/products", 200),
        (u100, IP_PRIMARY, "/checkout", 500),
        (u090, IP_TERTIARY, "/login", 200),
    ]
    for i, (user, ip, path, status) in enumerate(timeline_rows):
        docs[WEB_INDEX].append(
            _web_doc(
                t_base + timedelta(minutes=58, seconds=i * 20),
                user,
                ip,
                path,
                "POST" if path in {"/login", "/checkout"} else "GET",
                status,
                2600 if status >= 500 else 400,
                weighted_choice(init_rng(i), HOSTS["web"], [1, 1]),
                "python-requests/2.32.0",
                "",
                new_session_id(),
                new_trace_id(),
            )
        )

    # Orders: ensure all requested users and high-value user-050 order.
    docs[ORDERS_INDEX].append(_orders_doc(t_base + timedelta(minutes=61), u050, IP_PRIMARY, 1680.0, "completed", 92, "electronics", "card", "NA", sess_050, trace_050))
    docs[ORDERS_INDEX].append(_orders_doc(t_base + timedelta(minutes=62), u050, IP_PRIMARY, 95.0, "completed", 28, "books", "paypal", "NA", new_session_id(), new_trace_id()))
    docs[ORDERS_INDEX].append(_orders_doc(t_base + timedelta(minutes=63), u010, IP_SECONDARY, 120.0, "completed", 24, "fashion", "card", "EMEA", new_session_id(), new_trace_id()))
    docs[ORDERS_INDEX].append(_orders_doc(t_base + timedelta(minutes=64), u020, IP_PRIMARY, 82.0, "failed_payment", 64, "home", "card", "NA", new_session_id(), new_trace_id()))
    docs[ORDERS_INDEX].append(_orders_doc(t_base + timedelta(minutes=65), u030, IP_PRIMARY, 56.0, "refunded", 50, "beauty", "paypal", "APAC", new_session_id(), new_trace_id()))
    docs[ORDERS_INDEX].append(_orders_doc(t_base + timedelta(minutes=65, seconds=30), u075, IP_SECONDARY, 118.0, "completed", 34, "home", "card", "EMEA", new_session_id(), new_trace_id()))
    docs[ORDERS_INDEX].append(_orders_doc(t_base + timedelta(minutes=66), u090, IP_TERTIARY, 210.0, "completed", 30, "grocery", "apple_pay", "LATAM", new_session_id(), new_trace_id()))
    docs[ORDERS_INDEX].append(_orders_doc(t_base + timedelta(minutes=67), u100, IP_PRIMARY, 1340.0, "completed", 88, "electronics", "card", "NA", new_session_id(), new_trace_id()))

    # System baseline and pressure samples.
    for i in range(20):
        spike = i % 6 == 0
        docs[SYSTEM_INDEX].append(
            _system_doc(
                t_base + timedelta(minutes=70, seconds=i * 30),
                weighted_choice(init_rng(i + 10), HOSTS["system"], [20, 18, 18, 16, 16, 12]),
                0.88 if spike else 0.36,
                0.84 if spike else 0.54,
                0.82 if spike else 0.62,
                6.5 if spike else 1.2,
                5 if spike else 2,
                "Resource pressure detected" if spike else "Host healthy",
                random_internal_ip(init_rng(i + 20)),
                "python-app" if spike else "elastic-agent",
                new_trace_id(),
            )
        )


def _fill_to_target(docs: Dict[str, List[dict]], users: Dict[str, dict], rng, start, hours, target_total: int) -> None:
    # Keep mandatory rows and add realistic filler so `--count` scales volume.
    current = sum(len(v) for v in docs.values())
    if current >= target_total:
        return

    target_by_index = {
        WEB_INDEX: int(target_total * 0.42),
        AUTH_INDEX: int(target_total * 0.31),
        ORDERS_INDEX: int(target_total * 0.16),
        SYSTEM_INDEX: target_total - int(target_total * 0.42) - int(target_total * 0.31) - int(target_total * 0.16),
    }

    while len(docs[WEB_INDEX]) < target_by_index[WEB_INDEX]:
        user = rng.choice(USERS)
        status = weighted_choice(rng, [200, 404, 500], [93, 5, 2])
        path = weighted_choice(rng, ["/", "/products", "/cart", "/login", "/checkout"], [22, 28, 15, 15, 20])
        docs[WEB_INDEX].append(
            _web_doc(
                random_timestamp(rng, start, hours),
                user,
                weighted_choice(rng, [IP_PRIMARY, IP_SECONDARY, IP_TERTIARY, random_internal_ip(rng)], [15, 10, 8, 67]),
                path,
                weighted_choice(rng, ["GET", "POST"], [74, 26]),
                status,
                130 if status == 200 else 2900,
                weighted_choice(rng, HOSTS["web"], [1, 1]),
                weighted_choice(rng, ["Mozilla/5.0", "curl/8.7.1"], [94, 6]),
                "",
                new_session_id(),
                new_trace_id(),
            )
        )

    while len(docs[AUTH_INDEX]) < target_by_index[AUTH_INDEX]:
        user = rng.choice(USERS)
        outcome = weighted_choice(rng, ["success", "failure"], [88, 12])
        docs[AUTH_INDEX].append(
            _auth_doc(
                random_timestamp(rng, start, hours),
                user,
                weighted_choice(rng, [IP_PRIMARY, IP_SECONDARY, IP_TERTIARY, random_internal_ip(rng)], [14, 10, 8, 68]),
                outcome,
                weighted_choice(rng, ["password", "sso", "mfa"], [80, 12, 8]),
                weighted_choice(rng, HOSTS["auth"], [1, 1]),
                "" if outcome == "success" else "invalid_password",
                weighted_choice(rng, [22, 35, 67, 82], [40, 30, 20, 10]),
                new_session_id(),
                new_trace_id(),
            )
        )

    key_user_ids = sorted(KEY_USERS)
    while len(docs[ORDERS_INDEX]) < target_by_index[ORDERS_INDEX]:
        user = users[weighted_choice(rng, key_user_ids, [1, 1, 1, 2, 1, 1, 1])]
        status = weighted_choice(rng, ["completed", "failed_payment", "refunded"], [88, 7, 5])
        total = weighted_choice(rng, [58.0, 120.0, 210.0, 1450.0], [45, 30, 20, 5])
        docs[ORDERS_INDEX].append(
            _orders_doc(
                random_timestamp(rng, start, hours),
                user,
                weighted_choice(rng, [IP_PRIMARY, IP_SECONDARY, IP_TERTIARY, random_internal_ip(rng)], [20, 12, 10, 58]),
                total,
                status,
                26 if status == "completed" else 66,
                weighted_choice(rng, ["electronics", "home", "fashion", "books"], [24, 24, 28, 24]),
                weighted_choice(rng, ["card", "paypal", "apple_pay"], [72, 16, 12]),
                weighted_choice(rng, ["NA", "EMEA", "APAC", "LATAM"], [54, 24, 16, 6]),
                new_session_id(),
                new_trace_id(),
            )
        )

    while len(docs[SYSTEM_INDEX]) < target_by_index[SYSTEM_INDEX]:
        docs[SYSTEM_INDEX].append(
            _system_doc(
                random_timestamp(rng, start, hours),
                weighted_choice(rng, HOSTS["system"], [20, 18, 18, 16, 16, 12]),
                weighted_choice(rng, [0.32, 0.44, 0.86], [70, 25, 5]),
                weighted_choice(rng, [0.48, 0.62, 0.9], [70, 25, 5]),
                weighted_choice(rng, [0.55, 0.7, 0.92], [70, 25, 5]),
                weighted_choice(rng, [1.1, 2.0, 6.3], [70, 25, 5]),
                weighted_choice(rng, [2, 3, 5], [80, 15, 5]),
                weighted_choice(rng, ["Host healthy", "Resource usage above baseline", "Resource pressure detected"], [80, 15, 5]),
                random_internal_ip(rng),
                weighted_choice(rng, ["nginx", "python-app", "elastic-agent", "postgres"], [28, 32, 24, 16]),
                new_trace_id(),
            )
        )


def build_lab1_seed_docs(count: int, seed: Optional[int], start_time: str, hours: int) -> Dict[str, List[dict]]:
    rng = init_rng(seed)
    users = _user_map()
    start = parse_start_time(start_time, hours)
    t_base = random_timestamp(rng, start, hours)

    docs: Dict[str, List[dict]] = defaultdict(list)
    _mandatory_scenarios(docs, users, t_base)

    # The mandatory contract set is intentionally large to guarantee every query in the lab.
    mandatory_total = sum(len(v) for v in docs.values())
    target_total = max(count, mandatory_total)
    _fill_to_target(docs, users, rng, start, hours, target_total)
    return docs


def main() -> None:
    args = build_parser().parse_args()
    docs_by_index = build_lab1_seed_docs(args.count, args.seed, args.start_time, args.hours)

    for index in [WEB_INDEX, AUTH_INDEX, ORDERS_INDEX, SYSTEM_INDEX]:
        docs = docs_by_index[index]
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


if __name__ == "__main__":
    main()
