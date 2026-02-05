"""In-memory job queue for async analysis."""
from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import uuid4

from src.config.settings import settings
from src.fetcher.ghost_fetcher import is_ghost_url
from src.fetcher.html_fetcher import fetch_html
from src.geo.geo_checker import check_geo
from src.parser.content_parser import parse_content


@dataclass
class Job:
    """Analysis job."""

    id: str
    url: str
    status: Literal["pending", "processing", "completed", "failed"]
    created_at: datetime
    completed_at: datetime | None = None
    result: dict[str, Any] | None = None
    error: str | None = None


class JobQueue:
    """Simple in-memory job queue using ThreadPoolExecutor."""

    def __init__(self, max_workers: int | None = None):
        self.max_workers = max_workers or settings.api.job_max_workers
        self.jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        self._executor = ThreadPoolExecutor(max_workers=self.max_workers)
        self._cleanup_interval = 3600  # seconds
        self._last_cleanup = time.time()

    def submit(self, url: str) -> str:
        """Submit a new analysis job. Returns job_id."""
        job_id = uuid4().hex
        job = Job(
            id=job_id,
            url=url,
            status="pending",
            created_at=datetime.now(UTC),
        )

        with self._lock:
            self.jobs[job_id] = job
            self._maybe_cleanup()

        self._executor.submit(self._run_analysis, job_id)
        return job_id

    def get(self, job_id: str) -> Job | None:
        """Get job by ID."""
        with self._lock:
            return self.jobs.get(job_id)

    def _run_analysis(self, job_id: str) -> None:
        """Run the analysis (executed in thread pool)."""
        job = self.jobs.get(job_id)
        if not job:
            return

        job.status = "processing"

        try:
            # Fetch HTML
            draft_mode = is_ghost_url(job.url)
            html = fetch_html(job.url)

            # Parse content
            parsed = parse_content(html, job.url)

            # Run GEO analysis
            geo = check_geo(parsed, html, job.url, draft_mode=draft_mode)

            # Store result
            job.result = {
                "geo": geo,
                "stats": parsed.get("stats", {}),
                "readability": parsed.get("readability", {}),
                "schema_org": parsed.get("schema_org", {}),
            }
            job.status = "completed"

        except ValueError as e:
            job.error = str(e)
            job.status = "failed"

        except Exception as e:
            from src.fetcher.ghost_fetcher import GhostAPIError
            if isinstance(e, GhostAPIError):
                job.error = f"Ghost API: {str(e)}"
                job.status = "failed"
                return
            job.error = f"Analysis failed: {type(e).__name__}: {str(e)}"
            job.status = "failed"

        finally:
            job.completed_at = datetime.now(UTC)

    def _maybe_cleanup(self) -> None:
        """Clean up old jobs if needed (called with lock held)."""
        now = time.time()
        if now - self._last_cleanup < self._cleanup_interval:
            return

        retention_seconds = settings.api.job_retention_hours * 3600
        cutoff = datetime.now(UTC).timestamp() - retention_seconds

        # Find old jobs to remove
        to_remove = [
            job_id
            for job_id, job in self.jobs.items()
            if job.created_at.timestamp() < cutoff
        ]

        for job_id in to_remove:
            del self.jobs[job_id]

        self._last_cleanup = now

    def shutdown(self, wait: bool = True) -> None:
        """Shutdown the executor."""
        self._executor.shutdown(wait=wait)


# Global job queue instance
job_queue = JobQueue()
