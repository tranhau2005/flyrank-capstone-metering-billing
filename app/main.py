"""HTTP boundary for the metering service."""
import hashlib
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException
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
