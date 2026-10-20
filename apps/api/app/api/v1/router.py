"""Collects every v1 route. main.py mounts this under /api/v1 (D-01)."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1 import alerts, claims, documents, eligibility, grievances, health, household, jobs, local_files, members, policies

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(household.router)
api_router.include_router(members.router)
api_router.include_router(documents.router)
api_router.include_router(jobs.router)
api_router.include_router(policies.router)
api_router.include_router(claims.router)
api_router.include_router(eligibility.router)
api_router.include_router(grievances.router)
api_router.include_router(alerts.router)
api_router.include_router(local_files.router)
