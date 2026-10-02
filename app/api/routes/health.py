"""Liveness check for Railway — public, reveals nothing about the data."""

from fastapi import APIRouter

router = APIRouter(tags=["system"], include_in_schema=False)


@router.get("/health")
def health() -> dict:
    return {"status": "ok"}
