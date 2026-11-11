# Evidence

Run `python -m unittest discover -s tests -v`. The local test suite exercises:

- `test_concurrent_retries_record_once`: eight concurrent calls with one key return the same response and create one event.
- `test_quota_boundary_and_invalid_requests`: exactly 1,100 tokens and one call are allowed at the configured test limits, the next request returns 429, malformed subsets return 422 and an unpaid subscription returns 402.
- `test_replay_price_and_isolation`: repeated keys do not duplicate charges, changed payloads return 409, another tenant sees zero usage, and 1,000 input (200 cached) plus 100 output (50 reasoning) costs 2,250 microdollars including one call.
- `test_bad_signature_and_replay`: a locally signed synthetic webhook proves signature rejection and replay deduplication. The Stripe subscription retrieval is substituted in this test; it is not evidence of a live Stripe checkout.
- `test_report_is_background_and_tenant_scoped` and `test_retry_and_failed_state`: pending-to-done behavior, isolation, bounded retries and an error log after final failure.

Still required before claiming full completion: run a Stripe test Checkout with real test credentials and CLI, capture the signed event/replay proof, and verify a clean-machine setup. See README for configuration. Tests verify local behavior, not deployment or payment processing.
