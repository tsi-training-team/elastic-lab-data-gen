import argparse
import base64
import json
import random
import uuid
from datetime import datetime, timedelta, timezone
from typing import Dict, Iterable, List, Optional, Sequence, Tuple
from urllib import error, request

ORGANIZATION_NAME = "Acme Retail"

USERS = [
    {"id": f"user-{i:03d}", "name": f"acme_user_{i:03d}"}
    for i in range(1, 121)
]
HOSTS = {
    "web": ["web-01", "web-02"],
    "app": ["app-01", "app-02"],
    "auth": ["auth-01", "auth-02"],
    "system": ["web-01", "web-02", "app-01", "app-02", "db-01", "kibana-01"],
}
SERVICES = ["storefront", "checkout", "auth-service", "orders-api"]

INTERNAL_IP_RANGES = ["10.10.1.", "10.10.2.", "10.20.1.", "172.16.10."]
EXTERNAL_ATTACK_IPS = ["185.220.101.21", "91.92.109.77", "198.51.100.23"]


def add_common_args(parser: argparse.ArgumentParser, default_count: int) -> argparse.ArgumentParser:
    parser.add_argument("--es-url", default="", help="Elasticsearch URL (example: http://localhost:9200)")
    parser.add_argument("--username", default="", help="Elasticsearch username")
    parser.add_argument("--password", default="", help="Elasticsearch password")
    parser.add_argument("--count", type=int, default=default_count, help="Number of documents to generate")
    parser.add_argument("--dry-run", action="store_true", help="Generate data without indexing")
    parser.add_argument("--seed", type=int, default=None, help="Deterministic random seed")
    parser.add_argument(
        "--start-time",
        default="",
        help="Start timestamp in ISO8601 (default: now-<hours>)",
    )
    parser.add_argument("--hours", type=int, default=24, help="Time window span in hours")
    return parser


def init_rng(seed: Optional[int]) -> random.Random:
    return random.Random(seed)


def parse_start_time(start_time: str, hours: int) -> datetime:
    now = datetime.now(timezone.utc)
    if start_time:
        ts = start_time.strip()
        if ts.endswith("Z"):
            ts = ts[:-1] + "+00:00"
        parsed = datetime.fromisoformat(ts)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    return now - timedelta(hours=hours)


def random_timestamp(rng: random.Random, start: datetime, hours: int) -> datetime:
    seconds = max(1, int(hours * 3600))
    return start + timedelta(seconds=rng.randint(0, seconds))


def isoformat_utc(ts: datetime) -> str:
    return ts.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def weighted_choice(rng: random.Random, items: Sequence, weights: Sequence[float]):
    return rng.choices(items, weights=weights, k=1)[0]


def choose_user(rng: random.Random) -> Dict[str, str]:
    return rng.choice(USERS)


def random_internal_ip(rng: random.Random) -> str:
    prefix = rng.choice(INTERNAL_IP_RANGES)
    return f"{prefix}{rng.randint(2, 254)}"


def random_attack_ip(rng: random.Random) -> str:
    return rng.choice(EXTERNAL_ATTACK_IPS)


def new_session_id() -> str:
    return "sess-" + uuid.uuid4().hex[:16]


def new_trace_id() -> str:
    return "trace-" + uuid.uuid4().hex[:16]


def chunked(items: Sequence[dict], size: int) -> Iterable[Sequence[dict]]:
    for i in range(0, len(items), size):
        yield items[i : i + size]


def _bulk_payload(index: str, docs: Sequence[dict]) -> str:
    lines: List[str] = []
    for doc in docs:
        lines.append(json.dumps({"index": {"_index": index}}, separators=(",", ":")))
        lines.append(json.dumps(doc, separators=(",", ":")))
    return "\n".join(lines) + "\n"


def bulk_index(
    es_url: str,
    index: str,
    docs: Sequence[dict],
    username: str = "",
    password: str = "",
    batch_size: int = 500,
    timeout: int = 15,
) -> Tuple[int, int, List[str]]:
    if not es_url:
        return 0, len(docs), ["--es-url not provided"]

    endpoint = es_url.rstrip("/") + "/_bulk"
    indexed = 0
    failures = 0
    errors: List[str] = []

    for batch in chunked(list(docs), max(1, batch_size)):
        payload = _bulk_payload(index, batch).encode("utf-8")
        headers = {"Content-Type": "application/x-ndjson"}
        if username:
            token = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
            headers["Authorization"] = f"Basic {token}"

        req = request.Request(endpoint, data=payload, headers=headers, method="POST")
        try:
            with request.urlopen(req, timeout=timeout) as response:
                status_code = response.getcode()
                response_text = response.read().decode("utf-8", errors="replace")
        except error.HTTPError as exc:
            failures += len(batch)
            body = exc.read().decode("utf-8", errors="replace")
            errors.append(f"HTTP {exc.code}: {body[:240]}")
            continue
        except error.URLError as exc:
            failures += len(batch)
            errors.append(f"request error: {exc.reason}")
            continue
        except TimeoutError:
            failures += len(batch)
            errors.append("request error: timeout")
            continue

        if status_code >= 300:
            failures += len(batch)
            errors.append(f"HTTP {status_code}: {response_text[:240]}")
            continue

        try:
            result = json.loads(response_text)
        except ValueError:
            failures += len(batch)
            errors.append("bulk response was not valid JSON")
            continue

        items = result.get("items", [])
        if not items:
            failures += len(batch)
            errors.append("bulk response missing items")
            continue

        for item in items:
            status = item.get("index", {}).get("status", 500)
            if 200 <= status < 300:
                indexed += 1
            else:
                failures += 1
                err = item.get("index", {}).get("error")
                if err and len(errors) < 8:
                    errors.append(str(err))

    return indexed, failures, errors


def print_summary(index: str, generated: int, indexed: int, failures: int, dry_run: bool, errors: Optional[Sequence[str]] = None) -> None:
    mode = "dry-run" if dry_run else "index"
    print(f"[{mode}] target_index={index} generated={generated} indexed={indexed} failures={failures}")
    if errors:
        for err in list(errors)[:5]:
            print(f"  error: {err}")
