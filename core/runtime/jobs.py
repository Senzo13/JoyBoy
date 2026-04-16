"""Durable job tracking for generations, terminal tasks, downloads and setup."""

from __future__ import annotations

import json
import threading
import uuid
from copy import deepcopy
from pathlib import Path
from typing import Any

from .storage import get_runtime_root, utc_now_iso


TERMINAL_STATES = {"done", "error", "cancelled"}


class JobManager:
    """Thread-safe in-process job registry persisted to local JSON.

    The UI should persist stable job state, not DOM skeleton markup. A job keeps
    the current phase/progress and a compact event tail so switching
    conversations can reconstruct the active card cleanly.
    """

    def __init__(self, path: Path | None = None, max_events: int = 80):
        self.path = path or (get_runtime_root() / "jobs.json")
        self.max_events = max_events
        self._lock = threading.RLock()
        self._jobs: dict[str, dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                self._jobs = {
                    str(job_id): job
                    for job_id, job in data.get("jobs", {}).items()
                    if isinstance(job, dict)
                }
        except Exception as exc:
            print(f"[RUNTIME] Job store ignored ({exc})")
            self._jobs = {}

    def _save_locked(self) -> None:
        tmp = self.path.with_suffix(".tmp")
        payload = {
            "version": 1,
            "updated_at": utc_now_iso(),
            "jobs": self._jobs,
        }
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    @staticmethod
    def _release_resources_for_job(job_id: str) -> None:
        """Best-effort cleanup for ResourceScheduler leases tied to this job.

        The runtime intentionally keeps job tracking and resource scheduling
        decoupled, but terminal streams and cancellable generations can finish
        through several branches. Releasing by job ID here makes every terminal
        state a reliable cleanup point without duplicating route-specific code.
        """
        try:
            from .resources import get_resource_scheduler

            get_resource_scheduler().end_task_by_job(str(job_id))
        except Exception as exc:
            print(f"[RUNTIME] Resource lease cleanup skipped for {job_id}: {exc}")

    def create(
        self,
        kind: str,
        *,
        job_id: str | None = None,
        conversation_id: str | None = None,
        prompt: str = "",
        model: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        now = utc_now_iso()
        job_id = str(job_id or uuid.uuid4())
        job = {
            "id": job_id,
            "kind": str(kind or "task"),
            "conversation_id": conversation_id,
            "prompt": str(prompt or ""),
            "model": str(model or ""),
            "status": "queued",
            "phase": "queued",
            "progress": 0,
            "message": "",
            "cancel_requested": False,
            "metadata": metadata or {},
            "artifact": None,
            "events": [],
            "created_at": now,
            "updated_at": now,
            "started_at": None,
            "finished_at": None,
        }
        with self._lock:
            self._jobs[job_id] = job
            self._append_event_locked(job_id, "queued", message="Job queued")
            self._save_locked()
            return deepcopy(self._jobs[job_id])

    def update(
        self,
        job_id: str,
        *,
        status: str | None = None,
        phase: str | None = None,
        progress: float | int | None = None,
        message: str | None = None,
        metadata: dict[str, Any] | None = None,
        artifact: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        with self._lock:
            job = self._jobs.get(str(job_id))
            if not job:
                return None

            # Once a job reached a terminal state, stale async callbacks must
            # not resurrect it as "running". This is especially important for
            # terminal SSE streams: the user can cancel/delete the conversation
            # while Ollama is still unwinding in another thread.
            if job.get("status") in TERMINAL_STATES and status not in TERMINAL_STATES:
                return deepcopy(job)

            now = utc_now_iso()
            if status:
                job["status"] = status
                if status == "running" and not job.get("started_at"):
                    job["started_at"] = now
                if status in TERMINAL_STATES:
                    job["finished_at"] = now
            if phase:
                job["phase"] = phase
            if progress is not None:
                try:
                    job["progress"] = max(0, min(100, float(progress)))
                except Exception:
                    pass
            if message is not None:
                job["message"] = str(message)
            if metadata:
                job.setdefault("metadata", {}).update(metadata)
            if artifact is not None:
                job["artifact"] = artifact

            job["updated_at"] = now
            self._append_event_locked(
                str(job_id),
                phase or status or "update",
                message=message,
                progress=job.get("progress"),
            )
            self._save_locked()
            return deepcopy(job)

    def complete(self, job_id: str, *, artifact: dict[str, Any] | None = None, message: str = ""):
        job = self.update(
            job_id,
            status="done",
            phase="done",
            progress=100,
            message=message or "Job complete",
            artifact=artifact,
        )
        self._release_resources_for_job(str(job_id))
        return job

    def fail(self, job_id: str, error: str):
        job = self.update(
            job_id,
            status="error",
            phase="error",
            message=str(error or "Unknown error"),
            metadata={"error": str(error or "Unknown error")},
        )
        self._release_resources_for_job(str(job_id))
        return job

    def request_cancel(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            job = self._jobs.get(str(job_id))
            if not job:
                return None
            job["cancel_requested"] = True
            job["updated_at"] = utc_now_iso()
            if job.get("status") not in TERMINAL_STATES:
                job["status"] = "cancelling"
                job["phase"] = "cancelling"
            self._append_event_locked(str(job_id), "cancelling", message="Cancel requested")
            self._save_locked()
            return deepcopy(job)

    def cancel(self, job_id: str, message: str = "Job cancelled") -> dict[str, Any] | None:
        with self._lock:
            job = self._jobs.get(str(job_id))
            if not job:
                return None
            job["cancel_requested"] = True
        job = self.update(job_id, status="cancelled", phase="cancelled", message=message)
        self._release_resources_for_job(str(job_id))
        return job

    def cancel_conversation(self, conversation_id: str, message: str = "Conversation closed") -> list[dict[str, Any]]:
        """Cancel every non-terminal job attached to a conversation.

        Deleting a chat in the UI must not leave durable runtime cards or
        resource leases behind. This keeps the job store as the source of truth
        while letting the local conversation list stay lightweight.
        """
        conversation_id = str(conversation_id or "")
        if not conversation_id:
            return []
        with self._lock:
            job_ids = [
                job_id
                for job_id, job in self._jobs.items()
                if job.get("conversation_id") == conversation_id
                and job.get("status") not in TERMINAL_STATES
            ]
        cancelled = []
        for job_id in job_ids:
            job = self.cancel(job_id, message)
            if job:
                cancelled.append(job)
        return cancelled

    def is_cancel_requested(self, job_id: str) -> bool:
        with self._lock:
            job = self._jobs.get(str(job_id))
            return bool(job and job.get("cancel_requested"))

    def get(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            job = self._jobs.get(str(job_id))
            return deepcopy(job) if job else None

    def list(
        self,
        *,
        conversation_id: str | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        with self._lock:
            jobs = list(self._jobs.values())
        if conversation_id is not None:
            jobs = [job for job in jobs if job.get("conversation_id") == conversation_id]
        if status is not None:
            jobs = [job for job in jobs if job.get("status") == status]
        jobs.sort(key=lambda item: item.get("updated_at") or "", reverse=True)
        return deepcopy(jobs[: max(1, min(limit, 500))])

    def _append_event_locked(
        self,
        job_id: str,
        phase: str,
        *,
        message: str | None = None,
        progress: float | int | None = None,
    ) -> None:
        job = self._jobs.get(job_id)
        if not job:
            return
        event = {
            "at": utc_now_iso(),
            "phase": str(phase or "update"),
            "message": str(message or ""),
            "progress": progress,
        }
        events = job.setdefault("events", [])
        if events:
            last = events[-1]
            # Avoid persisting noisy duplicate ticks; current phase/progress are
            # already stored on the job itself.
            if (
                last.get("phase") == event["phase"]
                and last.get("message") == event["message"]
                and last.get("progress") == event["progress"]
            ):
                return
        events.append(event)
        del events[:-self.max_events]


_JOB_MANAGER: JobManager | None = None
_MANAGER_LOCK = threading.Lock()


def get_job_manager() -> JobManager:
    global _JOB_MANAGER
    with _MANAGER_LOCK:
        if _JOB_MANAGER is None:
            _JOB_MANAGER = JobManager()
        return _JOB_MANAGER
