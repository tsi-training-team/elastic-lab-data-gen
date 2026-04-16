# Elastic Lab Data Generators

Lightweight synthetic data generators for an Elastic training lab using a fictional ecommerce company, **Acme Retail**.

The scripts generate small, realistic datasets for:
- filtering and sorting
- aggregations and time-based analysis
- cross-source correlation
- security investigations and troubleshooting

## Prerequisites

- Python 3.10+
- Elasticsearch (local or remote)

## Install

```bash
python3 -m venv .venv
source .venv/bin/activate
```

No third-party packages are required.

## Generated Indices

- `lab-web-access`
- `lab-auth`
- `lab-orders`
- `lab-system`

`inject_attack.py` writes correlated suspicious events into existing indices above.

## Common CLI Flags

Every script supports:

- `--es-url`
- `--username`
- `--password`
- `--count`
- `--dry-run`
- `--seed`
- `--start-time`
- `--hours`
- `--continuous`
- `--interval-seconds`
- `--max-iterations`

Behavior:
- `--dry-run`: generate only, no indexing requests.
- no `--dry-run` + valid `--es-url`: index with Elasticsearch `_bulk`.
- no credentials provided: requests are sent unauthenticated.
- `--continuous`: keep generating/indexing batches until interrupted (or `--max-iterations` is reached).

## Usage Examples

Dry run examples:

```bash
python generate_web.py --dry-run --count 3000 --seed 42
python generate_auth.py --dry-run --count 1800 --seed 42
python generate_orders.py --dry-run --count 1200 --seed 42
python generate_system.py --dry-run --count 2200 --seed 42
python inject_attack.py --dry-run --count 200 --seed 42
python seed_lab1.py --dry-run --count 700 --seed 42
```

Continuous examples for alert labs:

```bash
python generate_auth.py --es-url http://localhost:9200 --username elastic --password YOUR_PASSWORD --continuous --interval-seconds 10 --count 200
python generate_web.py --es-url http://localhost:9200 --username elastic --password YOUR_PASSWORD --continuous --interval-seconds 10 --count 300
```

Bounded continuous runs (useful for testing):

```bash
python generate_system.py --dry-run --continuous --max-iterations 3 --interval-seconds 1 --count 100 --seed 42
```

## systemd (non-blocking background)

For Terraform/user-data setups where generation should run in the background, use the ready-made units in `systemd/`.

Quick start:

```bash
sudo cp systemd/elastic-lab-data-gen.env.example /etc/elastic-lab-data-gen.env
sudo vi /etc/elastic-lab-data-gen.env
sudo bash systemd/install_services.sh
```

See `systemd/README.md` for full details.

Indexing examples:

```bash
python generate_web.py --es-url http://localhost:9200 --username elastic --password YOUR_PASSWORD
python generate_auth.py --es-url http://localhost:9200 --username elastic --password YOUR_PASSWORD
python generate_orders.py --es-url http://localhost:9200 --username elastic --password YOUR_PASSWORD
python generate_system.py --es-url http://localhost:9200 --username elastic --password YOUR_PASSWORD
python inject_attack.py --es-url http://localhost:9200 --username elastic --password YOUR_PASSWORD --count 180
python seed_lab1.py --es-url http://localhost:9200 --username elastic --password YOUR_PASSWORD --count 700 --seed 42
```

Generate narrower windows:

```bash
python generate_web.py --es-url http://localhost:9200 --hours 6 --count 2000
python generate_system.py --es-url http://localhost:9200 --start-time 2026-04-14T08:00:00Z --hours 4 --count 1200
```

## Script Overview

- `generate_web.py`
- writes `web.access` events into `lab-web-access`
- mostly normal traffic (`200`), small `404` slice, very few `500`, plus occasional bot-like requests and slow responses

- `generate_auth.py`
- writes login events into `lab-auth`
- mostly successful logins, occasional failures, repeated failures for a small suspicious subset

- `generate_orders.py`
- writes order events into `lab-orders`
- mostly completed orders, some failed payments/refunds, sparse high-value orders, VIP users

- `generate_system.py`
- writes host telemetry into `lab-system`
- mostly healthy hosts with occasional CPU/memory bursts and one mildly degraded host profile

- `inject_attack.py`
- injects an investigation scenario across auth/web (+optional order)
- includes password spraying from one source IP, one successful login, and follow-on activity linked by user/session/trace

- `seed_lab1.py`
- one-time guaranteed seed for Lab 1 ES|QL exercises across all indices
- ensures baseline scenarios like endpoint counts, 500s/slow web requests, failed logins by user/IP, one-IP-many-users spray, success after failures, and cross-index user/IP timeline events
- exact scenario contract is documented in `tests/seed_lab1_contract.json`
- query-to-scenario mapping is documented in `tests/lab1_query_coverage.md`

## Reset / Cleanup

Delete all generated lab indices:

```bash
curl -u elastic:YOUR_PASSWORD -X DELETE "http://localhost:9200/lab-*"
```

If local Elasticsearch allows anonymous access:

```bash
curl -X DELETE "http://localhost:9200/lab-*"
```

## Example Kibana / ES|QL Questions

1. Which source IPs have the highest failed login counts in the last 24 hours?
2. Do failed logins correlate with web requests from the same `source.ip` and `user.id`?
3. Which sessions show auth success followed by checkout activity and a high fraud score?
4. Which hosts had high `cpu.usage` spikes before `500` web responses?
5. Which users have repeated auth failures and then successful high-value orders?

Example ES|QL query ideas:

```text
FROM lab-auth
| WHERE event.action == "login" AND event.outcome == "failure"
| STATS failed_logins = COUNT() BY source.ip, user.id
| SORT failed_logins DESC
```

```text
FROM lab-web-access
| WHERE http.response.status_code >= 500
| STATS errors = COUNT() BY host.name
| SORT errors DESC
```

```text
FROM lab-orders
| WHERE fraud.score >= 75
| KEEP @timestamp, user.id, order.id, order.total, source.ip, trace.id
| SORT @timestamp DESC
```
