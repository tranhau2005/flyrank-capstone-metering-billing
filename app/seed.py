"""Seed a local tenant using a credential supplied via the environment."""
import os
from app.db import migrate, seed

if __name__ == "__main__":
    migrate()
    seed(os.getenv("TENANT_ID", "demo"), os.environ["TENANT_API_KEY"])
    print("Tenant is ready. API key was not printed.")
