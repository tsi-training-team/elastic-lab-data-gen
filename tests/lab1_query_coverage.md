# Lab 1 Query Coverage Checklist

This checklist maps the Confluence Lab 1 ES|QL queries to guaranteed conditions from `seed_lab1.py`.

## Auth Query Guarantees

- `FROM lab-auth | WHERE event.outcome == "failure" | STATS ... BY user.id`
  - guaranteed heavy-failure users, including `user-050`, `user-075`, `user-010`.
- `... WHERE failures > 5`, `> 10`, `== 1`
  - `user-050` and `user-075` satisfy `> 5`/`> 10`.
  - at least one user has exactly one failure (`user-099`).
- `STATS attempts BY source.ip`, `attempts > 10`, `> 20`, `== 1`
  - `185.220.101.21` has >20 failures.
  - `91.92.109.77` has >10 failures.
  - `203.0.113.10` has exactly 1 failure.
- `STATS failures, users_targeted BY source.ip` with `users_targeted > 5` and `> 10`
  - `185.220.101.21` targets >10 unique users.
- failures/successes mixed and split checks:
  - `user-075` has failures and no successes.
  - `user-050` has failures and successes.

## Web Query Guarantees

- Status filters: `== 200`, `== 404`, `== 500`, `>= 400`, `>= 500`
  - all guaranteed with minimum 500 population >= 20.
- Path filters: `/cart`, `/login`, `/checkout`, `/products`
  - each guaranteed with at least 20 events.
- Duration aggregation by `host.name` and `url.path`
  - varied `event.duration` and mixed hosts guaranteed.

## Cross-Index Query Guarantees

- `lab-auth, lab-web-access` for users `user-010`, `user-050`, `user-075`
  - guaranteed auth + web events for each.
- `lab-auth, lab-orders` for users `user-010`, `user-020`, `user-030`, `user-050`, `user-090`
  - guaranteed auth + order events for each.
- `lab-auth, lab-web-access, lab-orders` for `user-100`, `user-075`, and `user-050`
  - guaranteed events in all three datasets.
- source-ip timeline queries for `185.220.101.21`, `91.92.109.77`, `198.51.100.23`
  - guaranteed presence in required datasets.

## Orders Query Guarantees

- `user-050` has at least one high-value order (`order.total > 1000`).
- mix of `completed`, `failed_payment`, `refunded` exists for timeline analysis.
