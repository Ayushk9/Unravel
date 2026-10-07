"""Shared FastAPI dependencies that hand routes the app's long-lived objects."""

from __future__ import annotations

from fastapi import Request

from app.jobs.runner import JobRunner
from app.storage.base import DocumentStorage


def get_storage(request: Request) -> DocumentStorage:
    return request.app.state.storage


def get_runner(request: Request) -> JobRunner:
    return request.app.state.runner
