"""SQLite connection and schema management."""
import hashlib
import os
import sqlite3
from pathlib import Path

DB_PATH = os.getenv("DATABASE_PATH", "billing.db")
SCHEMA = Path(__file__).resolve().parent.parent / "migrations" / "001-initial.sql"


def connect():
    db = sqlite3.connect(DB_PATH, timeout=10, isolation_level=None)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("PRAGMA busy_timeout=10000")
    return db


def migrate():
    with connect() as db:
        db.executescript(SCHEMA.read_text())


def seed(tenant_id, api_key):
    if not tenant_id or len(api_key) < 24:
        raise ValueError("Tenant ID required; API key must contain at least 24 characters")
    digest = hashlib.sha256(api_key.encode()).hexdigest()
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        db.execute("INSERT OR IGNORE INTO tenants(id, api_key_hash) VALUES (?,?)", (tenant_id, digest))
        db.execute("INSERT OR IGNORE INTO subscriptions(tenant_id, plan, status) VALUES (?, 'free', 'active')", (tenant_id,))
        db.commit()
