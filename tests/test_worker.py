import os
import tempfile
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from app import db, worker
from app.main import app


class WorkerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        db.DB_PATH = os.path.join(self.tmp.name, "test.db")
        db.migrate()
        db.seed("a", "a" * 32)
        db.seed("b", "b" * 32)
        self.client = TestClient(app)
        self.headers = {"Authorization": "Bearer " + "a" * 32}

    def tearDown(self):
        self.client.close()
        self.tmp.cleanup()

    def test_report_is_background_and_tenant_scoped(self):
        response = self.client.post("/reports", headers=self.headers)
        self.assertEqual(response.status_code, 202)
        path = "/reports/" + response.json()["id"]
        self.assertEqual(self.client.get(path, headers=self.headers).json()["status"], "pending")
        self.assertEqual(self.client.get(path, headers={"Authorization": "Bearer " + "b" * 32}).status_code, 404)
        self.assertTrue(worker.run_once())
        self.assertEqual(self.client.get(path, headers=self.headers).json()["status"], "done")

    def test_retry_and_failed_state(self):
        job = self.client.post("/reports", headers=self.headers).json()["id"]
        with patch("app.worker.usage", side_effect=RuntimeError("failure")):
            with self.assertLogs("billing.worker", level="WARNING") as logs:
                for _ in range(3):
                    worker.run_once()
        result = self.client.get("/reports/" + job, headers=self.headers).json()
        self.assertEqual((result["status"], result["attempts"]), ("failed", 3))
        self.assertIn("failed after 3 attempts", " ".join(logs.output))


if __name__ == "__main__":
    unittest.main()
