from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import __version__
from app.config import get_settings
from app.db import create_all, new_session
from app.routers import consent, public, staff
from app.seed import seed


def bootstrap() -> None:
    create_all()
    if get_settings().seed_reference_data:
        with new_session() as db:
            seed(db)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    bootstrap()
    yield


app = FastAPI(
    title="Privacy Request Portal",
    version=__version__,
    summary="Reference DSR portal: intake, risk-based verification, deadlines, deletion fan-out, audit.",
    lifespan=lifespan,
)
app.include_router(public.router)
app.include_router(staff.router)
app.include_router(consent.router)


@app.get("/healthz", tags=["ops"])
def healthz() -> dict:
    return {"ok": True}
