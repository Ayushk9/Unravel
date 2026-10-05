"""Liveness check. Public: no token required (API_DECISIONS D-24)."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter

from app.schemas.base import ApiModel

router = APIRouter()


class HealthStatus(ApiModel):
    status: Literal["ok"]


@router.get("/health")
async def health() -> HealthStatus:
    return HealthStatus(status="ok")
