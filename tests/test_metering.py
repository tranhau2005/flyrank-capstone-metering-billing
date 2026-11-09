import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient
from app import db, metering
from app.main import app

KEY_A = "a" * 32
KEY_B = "b" * 32
PAYLOAD = {"input_tokens": 1000, "cached_input_tokens": 200, "output_tokens": 100, "reasoning_tokens": 50}


class MeteringTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        db.DB_PATH = os.path.join(self.tmp.name, "test.db")
        db.migrate()
        db.seed("a", KEY_A)
        db.seed("b", KEY_B)
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        self.tmp.cleanup()

    def post(self, key, payload=PAYLOAD, tenant_key=KEY_A):
        return self.client.post("/generate", json=payload, headers={"Authorization": f"Bearer {tenant_key}", "Idempotency-Key": key})

    def test_replay_price_and_isolation(self):
        first = self.post("request-1")
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json(), self.post("request-1").json())
        self.assertEqual(first.json()["usage"]["cost_microdollars"], 2250)
        self.assertEqual(self.post("request-1", {**PAYLOAD, "output_tokens": 101}).status_code, 409)
        self.assertEqual(self.client.get("/usage", headers={"Authorization": f"Bearer {KEY_B}"}).json()["calls_used"], 0)
        with db.connect() as connection:
            self.assertEqual(connection.execute("SELECT count(*) FROM usage_events").fetchone()[0], 1)

    def test_quota_boundary_and_invalid_requests(self):
        with db.connect() as connection:
            connection.execute("UPDATE plans SET monthly_calls=1, monthly_tokens=1100 WHERE name='free'")
        self.assertEqual(self.post("one").status_code, 200)
        self.assertEqual(self.post("two").status_code, 429)
        self.assertEqual(self.post("bad", {**PAYLOAD, "cached_input_tokens": 1001}).status_code, 422)
        self.assertEqual(self.client.get("/usage").status_code, 401)
        with db.connect() as connection:
            connection.execute("UPDATE subscriptions SET status='unpaid' WHERE tenant_id='b'")
        self.assertEqual(self.post("unpaid", tenant_key=KEY_B).status_code, 402)

    def test_concurrent_retries_record_once(self):
        with ThreadPoolExecutor(max_workers=8) as pool:
            responses = list(pool.map(lambda _: metering.record("a", "same-key", PAYLOAD), range(8)))
        self.assertTrue(all(status == 200 and body == responses[0][1] for status, body in responses))
        with db.connect() as connection:
            self.assertEqual(connection.execute("SELECT count(*) FROM usage_events").fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()
