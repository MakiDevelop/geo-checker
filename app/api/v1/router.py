"""API v1 router aggregation."""
from __future__ import annotations

from fastapi import APIRouter

from app.api.v1.endpoints import analyze, compare, health, jobs

router = APIRouter()

router.include_router(analyze.router)
router.include_router(compare.router)
router.include_router(jobs.router)
router.include_router(health.router)
