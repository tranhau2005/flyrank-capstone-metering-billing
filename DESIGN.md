# Design: usage metering and billing

## Problem and scope

Track API calls and AI token quantities per tenant, enforce monthly plan quotas, calculate deterministic costs and mirror test-mode Stripe subscription status. The service models usage, not an LLM call or real invoicing. Proration, overages and real payments are non-goals.

## Data model

SQLite stores plans (limits), tenants (hashed API credential), subscriptions (plan, status and Stripe customer/subscription identifiers), immutable usage events, request idempotency records and processed Stripe event IDs. A database migration establishes constraints and indexes; timestamps and billing periods use UTC. Per-tenant authentication derives identity from a bearer credential, never from a user-supplied tenant ID.

## API and invariants

`POST /generate` accepts token quantities and an `Idempotency-Key`, charges one API call and the requested tokens; same tenant + key + same payload replays the original response, while a changed payload returns 409. Quota check and event insertion run in one SQLite `BEGIN IMMEDIATE` transaction, so concurrent requests cannot both spend the same remaining capacity. At exactly the limit usage is accepted; the next unit gets 429. Unpaid subscriptions return 402. `GET /usage` returns the current UTC month and limits. `POST /checkout` starts test-mode subscription checkout; `POST /webhooks/stripe` verifies signatures and deduplicates event IDs before updating subscription state. External payment status is authoritative; user-supplied plan changes never grant access.

## Pricing

All amounts are integer microdollars. Input tokens include cached tokens; output tokens include reasoning tokens. A request's charge is `(input - cached)*input_rate + cached*cached_rate + output*output_rate`; reasoning is not added a second time. Pinned microdollars per million tokens allow exact integer arithmetic and aggregated totals before rounding.

## Layers and non-goals

HTTP validation/authentication → service and transactions → SQLite migrations/repositories. Stripe verification is a separate boundary. A durable background task will handle a bounded reporting operation with retries and an observable failed state. No payment is executed outside Stripe test mode. SQLite is intentionally a single-host design; high-volume multi-instance deployment needs a server database and operational hardening.
