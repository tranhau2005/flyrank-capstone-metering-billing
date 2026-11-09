"""Atomic quota checks, idempotent recording and integer cost rollups."""
import hashlib
import json
from datetime import datetime, timezone
from app.db import connect

# Microdollars per million tokens. API calls cost 1,000 microdollars each.
INPUT_RATE = 1_000_000
CACHED_INPUT_RATE = 250_000
OUTPUT_RATE = 4_000_000
CALL_MICRODOLLARS = 1_000
SCALE = 1_000_000


def current_month():
    return datetime.now(timezone.utc).strftime("%Y-%m")


def summary(db, tenant_id, month):
    plan = db.execute("SELECT p.name, p.monthly_calls, p.monthly_tokens, s.status FROM subscriptions s JOIN plans p ON p.name=s.plan WHERE s.tenant_id=?", (tenant_id,)).fetchone()
    totals = db.execute("SELECT COALESCE(SUM(calls),0) calls, COALESCE(SUM(input_tokens + output_tokens),0) tokens, COALESCE(SUM(cost_numerator),0) cost FROM usage_events WHERE tenant_id=? AND month=?", (tenant_id, month)).fetchone()
    return {"month": month, "plan": plan["name"], "status": plan["status"], "calls_used": totals["calls"], "calls_limit": plan["monthly_calls"], "tokens_used": totals["tokens"], "tokens_limit": plan["monthly_tokens"], "cost_microdollars": (totals["cost"] + SCALE // 2) // SCALE}


def usage(tenant_id, month=None):
    with connect() as db:
        return summary(db, tenant_id, month or current_month())


def record(tenant_id, key, payload):
    normalized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(normalized.encode()).hexdigest()
    now = datetime.now(timezone.utc)
    month = now.strftime("%Y-%m")
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        previous = db.execute("SELECT payload_hash, response_json FROM idempotency_keys WHERE tenant_id=? AND request_key=?", (tenant_id, key)).fetchone()
        if previous:
            if previous["payload_hash"] != digest:
                db.rollback()
                return 409, {"error": "Idempotency key already used with a different request"}
            result = json.loads(previous["response_json"])
            db.commit()
            return 200, result
        current = summary(db, tenant_id, month)
        if current["status"] not in ("active", "trialing"):
            db.rollback()
            return 402, {"error": "Subscription payment or upgrade required"}
        tokens = payload["input_tokens"] + payload["output_tokens"]
        if current["calls_used"] + 1 > current["calls_limit"] or current["tokens_used"] + tokens > current["tokens_limit"]:
            db.rollback()
            return 429, {"error": "Monthly usage quota exceeded"}
        cost = ((payload["input_tokens"] - payload["cached_input_tokens"]) * INPUT_RATE + payload["cached_input_tokens"] * CACHED_INPUT_RATE + payload["output_tokens"] * OUTPUT_RATE + CALL_MICRODOLLARS * SCALE)
        cursor = db.execute("INSERT INTO usage_events(tenant_id,request_key,month,calls,input_tokens,cached_input_tokens,output_tokens,reasoning_tokens,cost_numerator,created_at) VALUES (?,?,?,?,?,?,?,?,?,?)", (tenant_id, key, month, 1, payload["input_tokens"], payload["cached_input_tokens"], payload["output_tokens"], payload["reasoning_tokens"], cost, now.isoformat()))
        result = {"event_id": cursor.lastrowid, "usage": summary(db, tenant_id, month)}
        db.execute("INSERT INTO idempotency_keys VALUES (?,?,?,?)", (tenant_id, key, digest, json.dumps(result, sort_keys=True)))
        db.commit()
        return 200, result
