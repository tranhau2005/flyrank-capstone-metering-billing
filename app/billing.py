"""Stripe test-mode Checkout and signed webhook synchronization."""
import os
from datetime import datetime, timezone
import stripe
from app.db import connect


def setting(name):
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"{name} is not configured")
    return value


def configure_stripe():
    key = setting("STRIPE_SECRET_KEY")
    if not key.startswith(("sk_test_", "rk_test_")):
        raise RuntimeError("Only Stripe test-mode keys are permitted")
    stripe.api_key = key


def create_checkout(tenant_id):
    configure_stripe()
    price = setting("STRIPE_PRO_PRICE_ID")
    if not price.startswith("price_"):
        raise RuntimeError("STRIPE_PRO_PRICE_ID must be a Stripe Price ID")
    with connect() as db:
        customer = db.execute("SELECT stripe_customer_id FROM subscriptions WHERE tenant_id=?", (tenant_id,)).fetchone()[0]
    params = dict(mode="subscription", line_items=[{"price": price, "quantity": 1}],
                  client_reference_id=tenant_id, metadata={"tenant_id": tenant_id},
                  subscription_data={"metadata": {"tenant_id": tenant_id}},
                  success_url=setting("CHECKOUT_SUCCESS_URL"), cancel_url=setting("CHECKOUT_CANCEL_URL"))
    if customer:
        params["customer"] = customer
    return stripe.checkout.Session.create(**params).url


def verify_event(body, signature):
    return stripe.Webhook.construct_event(body, signature, setting("STRIPE_WEBHOOK_SECRET")).to_dict()


def process_event(event):
    """Process once. Fetch current subscription so out-of-order events cannot roll back state."""
    event_id = event["id"]
    event_type = event["type"]
    obj = event["data"]["object"]
    if event.get("livemode"):
        raise ValueError("Live-mode Stripe events are not accepted")
    with connect() as db:
        if db.execute("SELECT 1 FROM stripe_events WHERE event_id=?", (event_id,)).fetchone():
            return False
    if event_type not in ("checkout.session.completed", "customer.subscription.updated", "customer.subscription.deleted"):
        with connect() as db:
            db.execute("INSERT OR IGNORE INTO stripe_events VALUES (?,?)", (event_id, datetime.now(timezone.utc).isoformat()))
        return True
    subscription_id = obj.get("subscription") if event_type == "checkout.session.completed" else obj.get("id")
    if not subscription_id:
        raise ValueError("Event does not identify a subscription")
    configure_stripe()
    sub = stripe.Subscription.retrieve(subscription_id)
    if hasattr(sub, "to_dict"):
        sub = sub.to_dict()
    tenant_id = (sub.get("metadata") or {}).get("tenant_id")
    customer_id = sub.get("customer")
    status = sub.get("status")
    if not tenant_id or not customer_id or not status:
        raise ValueError("Subscription missing tenant, customer or status")
    items = (sub.get("items") or {}).get("data", [])
    pro_price = setting("STRIPE_PRO_PRICE_ID")
    has_pro = any((item.get("price") or {}).get("id") == pro_price for item in items)
    plan = "pro" if has_pro and status in ("active", "trialing") else "free"
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        if db.execute("SELECT 1 FROM stripe_events WHERE event_id=?", (event_id,)).fetchone():
            db.commit()
            return False
        existing = db.execute("SELECT stripe_customer_id FROM subscriptions WHERE tenant_id=?", (tenant_id,)).fetchone()
        if existing is None or (existing["stripe_customer_id"] and existing["stripe_customer_id"] != customer_id):
            db.rollback()
            raise ValueError("Subscription does not match a known tenant")
        db.execute("UPDATE subscriptions SET plan=?, status=?, stripe_customer_id=?, stripe_subscription_id=? WHERE tenant_id=?", (plan, status, customer_id, subscription_id, tenant_id))
        db.execute("INSERT INTO stripe_events VALUES (?,?)", (event_id, datetime.now(timezone.utc).isoformat()))
        db.commit()
    return True
