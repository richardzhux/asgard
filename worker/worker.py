"""
Render worker that polls Supabase for queued lit-review jobs and runs the pipeline.
Requires env vars:
  SUPABASE_URL
  SUPABASE_SERVICE_ROLE_KEY
Optional:
  JOBS_POLL_INTERVAL (seconds, default 10)
  JOBS_BATCH_LIMIT (default 1)
"""

from __future__ import annotations

import os
import sys
import time
import traceback
from dataclasses import fields
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from supabase import Client, create_client

from pipelines.litrev_pipeline import LitReviewConfig, LitReviewPipeline

POLL_INTERVAL = int(os.getenv("JOBS_POLL_INTERVAL", "10"))
BATCH_LIMIT = int(os.getenv("JOBS_BATCH_LIMIT", "1"))


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _to_path(val: Optional[str]) -> Optional[Path]:
    if not val:
        return None
    return Path(val).expanduser().resolve()


def _build_config(job: Dict[str, Any]) -> LitReviewConfig:
    cfg = job.get("config") or {}
    research_focus = cfg.get("research_focus") or job.get("research_focus") or "Research focus not provided."
    pdf_dir = cfg.get("pdf_dir") or job.get("input_uri")
    if not pdf_dir:
        raise ValueError("Job missing pdf_dir / input_uri in config.")

    kwargs: Dict[str, Any] = {"pdf_dir": _to_path(pdf_dir), "research_focus": research_focus}
    path_fields = {
        "pdf_dir",
        "output_dir",
        "media_output_dir",
        "lit_review_output_path",
        "lit_review_outline_path",
        "lit_review_cache_path",
    }
    for field in fields(LitReviewConfig):
        name = field.name
        if name in {"pdf_dir", "research_focus"}:
            continue
        if name in cfg:
            val = cfg[name]
            if name in path_fields and val is not None:
                kwargs[name] = _to_path(val)
            else:
                kwargs[name] = val
    return LitReviewConfig(**kwargs)


def _post_event(sb: Client, job_id: str, event_type: str, message: str, data: Optional[Dict[str, Any]] = None) -> None:
    try:
        sb.table("job_events").insert(
            {"job_id": job_id, "event_type": event_type, "message": message, "data": data or {}, "created_at": _utcnow().isoformat()}
        ).execute()
    except Exception:
        traceback.print_exc()


def _update_job(sb: Client, job_id: str, payload: Dict[str, Any]) -> None:
    payload["updated_at"] = _utcnow().isoformat()
    sb.table("jobs").update(payload).eq("id", job_id).execute()


def _claim_next_job(sb: Client) -> Optional[Dict[str, Any]]:
    res = sb.table("jobs").select("*").eq("status", "queued").order("created_at", desc=False).limit(BATCH_LIMIT).execute()
    jobs = res.data or []
    for job in jobs:
        job_id = job["id"]
        updated = sb.table("jobs").update({"status": "running", "started_at": _utcnow().isoformat()}).eq("id", job_id).eq(
            "status", "queued"
        ).execute()
        if updated.data:
            return job
    return None


def run_job(sb: Client, job: Dict[str, Any]) -> None:
    job_id = job["id"]
    title = job.get("title") or "lit-review job"
    _post_event(sb, job_id, "status", f"Starting {title}")
    try:
        config = _build_config(job)
        pipeline = LitReviewPipeline(config)
        pipeline.run()
        _update_job(
            sb,
            job_id,
            {"status": "completed", "finished_at": _utcnow().isoformat(), "error": None},
        )
        _post_event(sb, job_id, "status", f"Completed {title}")
    except Exception as exc:
        err_text = f"{type(exc).__name__}: {exc}"
        _post_event(sb, job_id, "log", f"Job failed: {err_text}", {"traceback": traceback.format_exc()})
        _update_job(sb, job_id, {"status": "failed", "finished_at": _utcnow().isoformat(), "error": err_text})


def main() -> None:
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        print("Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY", file=sys.stderr)
        sys.exit(1)

    sb = create_client(url, key)
    print("Worker started; polling for jobs...", flush=True)
    while True:
        job = _claim_next_job(sb)
        if not job:
            time.sleep(POLL_INTERVAL)
            continue
        run_job(sb, job)


if __name__ == "__main__":
    main()
