# Security Policy

## Supported versions

| Version | Supported |
| --- | --- |
| 0.1.x | yes |

## Reporting a vulnerability

Please do **not** open a public issue for security problems.

Report privately through
[GitHub Security Advisories](https://github.com/saizul/sslcommerz-py/security/advisories/new). Include the
affected version, a description, steps to reproduce and the impact you expect. You should receive a reply within
7 days. Once a fix is released, the advisory is published with credit to the reporter unless you prefer otherwise.

Do not include real SSLCommerz store passwords, card data or customer details in reports. If a store password has
been exposed, ask SSLCommerz to rotate it first.

## Scope

In scope: anything in this repository that could lead to accepting an unpaid or tampered payment (hash, status,
amount, currency or tran_id checks), duplicate refunds, or leaking the store password.

Out of scope: vulnerabilities in the SSLCommerz platform itself (report those to SSLCommerz), and issues that need an attacker
who already controls your server or credentials.

## Recommendations for users

- Keep credentials on the server and in a secret manager, never in source control.
- Accept payments only through `verify_ipn()` with the expected amount and currency from your database.
- Make fulfilment idempotent per `tran_id`; IPNs and redirects can arrive more than once.
