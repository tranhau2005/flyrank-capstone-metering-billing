import hashlib
import hmac
import json
import os
import tempfile
import time
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from app import db
from app.main import app


class WebhookTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        db.DB_PATH = os.path.join(self.tmp.name, "test.db")
        db.migrate()
        db.seed("a", "a" * 32)
        self.env = patch.dict(os.environ, {"STRIPE_WEBHOOK_SECRET": "whsec_test_only", "STRIPE_SECRET_KEY": "sk_test_placeholder", "STRIPE_PRO_PRICE_ID": "price_test"})
        self.env.start()
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        self.env.stop()
        self.tmp.cleanup()

    def signed(self, event, secret="whsec_test_only"):
        body = json.dumps(event, separators=(",", ":")).encode()
        timestamp = str(int(time.time()))
        signature = hmac.new(secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()
        return self.client.post("/webhooks/stripe", content=body, headers={"Stripe-Signature": f"t={timestamp},v1={signature}", "Content-Type": "application/json"})

    def test_bad_signature_and_replay(self):
        event = {"id": "evt_test", "type": "checkout.session.completed", "livemode": False, "data": {"object": {"subscription": "sub_test"}}}
        self.assertEqual(self.signed(event, "wrong").status_code, 400)
        subscription = {"id": "sub_test", "metadata": {"tenant_id": "a"}, "customer": "cus_test", "status": "active", "items": {"data": [{"price": {"id": "price_test"}}]}}
        with patch("app.billing.stripe.Subscription.retrieve", return_value=subscription) as retrieve:
            self.assertEqual(self.signed(event).json(), {"received": True, "processed": True})
            self.assertEqual(self.signed(event).json(), {"received": True, "processed": False})
            self.assertEqual(retrieve.call_count, 1)
        with db.connect() as connection:
            self.assertEqual(connection.execute("SELECT plan FROM subscriptions WHERE tenant_id='a'").fetchone()[0], "pro")
            self.assertEqual(connection.execute("SELECT count(*) FROM stripe_events").fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()
