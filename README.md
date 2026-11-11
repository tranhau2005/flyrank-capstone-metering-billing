# Usage Metering & Billing Engine

A small FastAPI/SQLite service for tenant-scoped usage, quota enforcement, cost rollups, and Stripe **test-mode** subscription synchronization. An asynchronous report worker persists report state and records a failure after three attempts.

```text
Client -- bearer + idempotency key --> API --> metering transaction --> SQLite
Stripe test Checkout --> signed webhook --> current Stripe subscription --> SQLite
Client --> report request --> SQLite queue --> worker --> report status
```

## Setup

Python 3.10+ is required. Create a virtual environment, install `requirements.txt`, and provide configuration as environment variables using your preferred secret manager. No credentials are committed. The `TENANT_API_KEY` must be at least 24 characters and should be generated with a cryptographically secure generator. Do not use a real customer credential for the demonstration.

```sh
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
# Set TENANT_API_KEY in your shell through your secret manager first.
python -m app.seed
./run.sh
```

Run `python -m unittest discover -s tests -v` in another terminal. The service binds to `127.0.0.1:8000`; Swagger is at `/docs`. `DATABASE_PATH` and `PORT` can override the database file and port. `TENANT_ID` defaults to `demo`. `python -m app.seed` is idempotent for an existing tenant; it does not rotate its key.

| Variable | Purpose |
| --- | --- |
| `TENANT_API_KEY` | Demo tenant bearer credential, supplied only at seed time and by the caller |
| `DATABASE_PATH` | SQLite database path (default `billing.db`) |
| `TENANT_ID` | Tenant identifier for seeding (default `demo`) |
| `STRIPE_SECRET_KEY` | Stripe test-mode secret or restricted key |
| `STRIPE_WEBHOOK_SECRET` | Stripe CLI test webhook signing secret |
| `STRIPE_PRO_PRICE_ID` | Test-mode recurring Pro Price ID |
| `CHECKOUT_SUCCESS_URL`, `CHECKOUT_CANCEL_URL` | Checkout redirect URLs |

Call `/generate` with a bearer key, an `Idempotency-Key` header and JSON containing integer `input_tokens`, `cached_input_tokens`, `output_tokens`, and `reasoning_tokens`. Cached input is a subset of input and reasoning is a subset of output. An identical replay returns the original response; reuse for a different payload returns 409. `/usage` returns the tenant's UTC-month total. Free limits are 1,000 calls and 100,000 tokens/month; Pro limits are 100,000 calls and 10,000,000 tokens/month. The exact boundary is allowed; the next unit returns 429. Unpaid or inactive subscription statuses return 402. `POST /reports` returns a job ID and `GET /reports/{id}` reports status, scoped to the authenticated tenant.

Rates in `app/metering.py` are pinned illustrative prices: 1,000 microdollars per API call; 1,000,000, 250,000 and 4,000,000 microdollars per million fresh input, cached input and output tokens respectively. Reasoning is included in output, not billed twice. Integer arithmetic is rounded once at monthly rollup.

For Stripe, create a recurring test-mode Pro Price, set the Stripe variables, run `stripe listen --forward-to localhost:8000/webhooks/stripe`, and create a session with `POST /checkout`. Stripe is authoritative: signed events are deduplicated and the current subscription is retrieved before updating the tenant. Live keys and live events are refused. Never store keys in Git or logs.

## Limitations

This is a portfolio demonstration, not a production billing system. SQLite serializes writes and is intended for a single host; worker logs require an external log monitor for alert delivery. Multiple concurrent subscription checkouts for one tenant are not prevented. Authentication uses static tenant API keys and requires a separate provisioning and rotation policy. Stripe test Checkout and a signed webhook have been verified; a real Stripe event replay and clean-machine setup remain unverified. See `EVIDENCE.md`. The assignment requests `.env.example`; this workspace's instruction prohibits committing dotenv files, so the table above documents the variables instead.
