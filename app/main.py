"""HTTP boundary for the metering service."""
import hashlib
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app import db, metering


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.migrate()
    yield


app = FastAPI(title="Usage Metering & Billing", lifespan=lifespan)
bearer = HTTPBearer(auto_error=False)


def tenant(credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]):
    if not credentials or credentials.scheme.lower() != "bearer":
        raise HTTPException(401, "Tenant credential required")
    digest = hashlib.sha256(credentials.credentials.encode()).hexdigest()
    with db.connect() as connection:
        row = connection.execute("SELECT id FROM tenants WHERE api_key_hash=?", (digest,)).fetchone()
    if row is None:
        raise HTTPException(401, "Invalid tenant credential")
    return row["id"]


class GenerateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    input_tokens: int = Field(ge=0, le=10_000_000)
    cached_input_tokens: int = Field(ge=0, le=10_000_000)
    output_tokens: int = Field(ge=0, le=10_000_000)
    reasoning_tokens: int = Field(ge=0, le=10_000_000)

    @model_validator(mode="after")
    def check_subsets(self):
        if self.cached_input_tokens > self.input_tokens or self.reasoning_tokens > self.output_tokens:
            raise ValueError("Cached tokens must be a subset of input; reasoning tokens a subset of output")
        return self


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/usage")
def get_usage(tenant_id: Annotated[str, Depends(tenant)]):
    return metering.usage(tenant_id)


@app.post("/generate")
def generate(payload: GenerateRequest, tenant_id: Annotated[str, Depends(tenant)], idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=128)]):
    status, result = metering.record(tenant_id, idempotency_key, payload.model_dump())
    headers = {"Retry-After": "86400"} if status == 429 else None
    return JSONResponse(status_code=status, content=result, headers=headers)


@app.post("/checkout")
def checkout(tenant_id: Annotated[str, Depends(tenant)]):
    from app import billing
    try:
        return {"checkout_url": billing.create_checkout(tenant_id)}
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc


@app.post("/webhooks/stripe")
async def stripe_webhook(request: Request, stripe_signature: Annotated[str | None, Header(alias="Stripe-Signature")] = None):
    import stripe
    from app import billing
    if not stripe_signature:
        raise HTTPException(400, "Missing Stripe signature")
    try:
        event = billing.verify_event(await request.body(), stripe_signature)
        processed = billing.process_event(event)
    except (ValueError, stripe.error.SignatureVerificationError) as exc:
        raise HTTPException(400, "Invalid Stripe event") from exc
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc
    return {"received": True, "processed": processed}


@app.post("/reports", status_code=202)
def request_report(tenant_id: Annotated[str, Depends(tenant)]):
    import uuid
    from datetime import datetime, timezone
    job_id = uuid.uuid4().hex
    with db.connect() as connection:
        connection.execute("INSERT INTO report_jobs(id, tenant_id, month, state, updated_at) VALUES (?, ?, ?, 'pending', ?)", (job_id, tenant_id, metering.current_month(), datetime.now(timezone.utc).isoformat()))
    return {"id": job_id, "status": "pending"}


@app.get("/reports/{job_id}")
def get_report(job_id: str, tenant_id: Annotated[str, Depends(tenant)]):
    import json
    with db.connect() as connection:
        job = connection.execute("SELECT id, state, attempts, result_json FROM report_jobs WHERE id=? AND tenant_id=?", (job_id, tenant_id)).fetchone()
    if job is None:
        raise HTTPException(404, "Report not found")
    return {"id": job["id"], "status": job["state"], "attempts": job["attempts"], "result": json.loads(job["result_json"]) if job["result_json"] else None}
