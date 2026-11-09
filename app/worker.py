"""Durable SQLite report worker with bounded retries and failure logging."""
import json
import logging
import time
from datetime import datetime, timedelta, timezone
from app.db import connect, migrate
from app.metering import usage

log = logging.getLogger("billing.worker")


def now():
    return datetime.now(timezone.utc).isoformat()


def run_once():
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=2)).isoformat()
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        db.execute("UPDATE report_jobs SET state='pending', updated_at=? WHERE state='running' AND updated_at<?", (now(), cutoff))
        job = db.execute("SELECT * FROM report_jobs WHERE state='pending' ORDER BY updated_at LIMIT 1").fetchone()
        if job is None:
            db.commit()
            return False
        db.execute("UPDATE report_jobs SET state='running', attempts=attempts+1, updated_at=? WHERE id=?", (now(), job['id']))
        db.commit()
    try:
        result = usage(job["tenant_id"], job["month"])
        with connect() as db:
            db.execute("UPDATE report_jobs SET state='done', result_json=?, last_error=NULL, updated_at=? WHERE id=?", (json.dumps(result), now(), job["id"]))
    except Exception as exc:
        attempts = job["attempts"] + 1
        state = "failed" if attempts >= 3 else "pending"
        with connect() as db:
            db.execute("UPDATE report_jobs SET state=?, last_error=?, updated_at=? WHERE id=?", (state, type(exc).__name__, now(), job["id"]))
        if state == "failed":
            log.error("Report job %s failed after %s attempts; investigate worker logs", job["id"], attempts)
        else:
            log.warning("Report job %s failed; retry %s of 3", job["id"], attempts)
    return True


def main():
    logging.basicConfig(level=logging.INFO)
    migrate()
    while True:
        if not run_once():
            time.sleep(2)


if __name__ == "__main__":
    main()
