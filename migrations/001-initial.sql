CREATE TABLE IF NOT EXISTS plans (
  name TEXT PRIMARY KEY,
  monthly_calls INTEGER NOT NULL CHECK(monthly_calls >= 0),
  monthly_tokens INTEGER NOT NULL CHECK(monthly_tokens >= 0)
);
CREATE TABLE IF NOT EXISTS tenants (
  id TEXT PRIMARY KEY,
  api_key_hash TEXT NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS subscriptions (
  tenant_id TEXT PRIMARY KEY REFERENCES tenants(id),
  plan TEXT NOT NULL REFERENCES plans(name),
  status TEXT NOT NULL,
  stripe_customer_id TEXT UNIQUE,
  stripe_subscription_id TEXT UNIQUE,
  last_event_created INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS usage_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  tenant_id TEXT NOT NULL REFERENCES tenants(id),
  request_key TEXT NOT NULL,
  month TEXT NOT NULL,
  calls INTEGER NOT NULL,
  input_tokens INTEGER NOT NULL,
  cached_input_tokens INTEGER NOT NULL,
  output_tokens INTEGER NOT NULL,
  reasoning_tokens INTEGER NOT NULL,
  cost_numerator INTEGER NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE(tenant_id, request_key)
);
CREATE INDEX IF NOT EXISTS usage_by_tenant_month ON usage_events(tenant_id, month);
CREATE TABLE IF NOT EXISTS idempotency_keys (
  tenant_id TEXT NOT NULL REFERENCES tenants(id),
  request_key TEXT NOT NULL,
  payload_hash TEXT NOT NULL,
  response_json TEXT NOT NULL,
  PRIMARY KEY (tenant_id, request_key)
);
CREATE TABLE IF NOT EXISTS stripe_events (
  event_id TEXT PRIMARY KEY,
  received_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS report_jobs (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id),
  month TEXT NOT NULL,
  state TEXT NOT NULL CHECK(state IN ('pending','running','done','failed')),
  attempts INTEGER NOT NULL DEFAULT 0,
  result_json TEXT,
  last_error TEXT,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS report_jobs_pending ON report_jobs(state, updated_at);
INSERT OR IGNORE INTO plans VALUES ('free',1000,100000),('pro',100000,10000000);
