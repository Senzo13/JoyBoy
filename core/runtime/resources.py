"""Runtime resource scheduling for RAM/VRAM heavy tasks.

JoyBoy already knows which models are loaded through ``ModelManager.get_status``.
This scheduler does not duplicate that monitoring. It consumes the status,
decides which resource groups conflict, and records active leases so the UI and
future workers can answer: "what is running, what is warm, what must be freed?"
"""

from __future__ import annotations

import threading
import uuid
from copy import deepcopy
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Iterable, Optional, Set

from .storage import utc_now_iso


TASK_GROUPS = {
    "inpaint": "diffusion",
    "text2img": "diffusion",
    "inpaint_controlnet": "diffusion",
    "edit": "diffusion",
    "upscale": "diffusion",
    "expand": "diffusion",
    "fix_details": "diffusion",
    "video": "video",
    "chat": "chat",
    "terminal": "chat",
    "caption": "chat",
    "download": "io",
    "model_import": "io",
}

GROUP_CONFLICTS = {
    # Video generation is the greediest local workload. On low/mid VRAM it must
    # run alone, otherwise FramePack/Cog/SVD get stuck in CPU offload hell.
    "video": {"diffusion", "chat"},
    "diffusion": {"video"},
    "chat": set(),
    "io": set(),
}


@dataclass(frozen=True)
class ResourcePlan:
    task_type: str
    group: str
    loaded_groups: list[str]
    unload_groups: list[str]
    keep_groups: list[str]
    preserve_ollama: bool
    pressure: str
    reason: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ResourceLease:
    id: str
    task_type: str
    group: str
    job_id: Optional[str] = None
    model_name: str = ""
    plan: Dict[str, Any] = field(default_factory=dict)
    started_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class ResourceScheduler:
    """Small in-process scheduler that coordinates heavy runtime groups."""

    def __init__(self, max_recent_plans: int = 40):
        self.max_recent_plans = max_recent_plans
        self._lock = threading.RLock()
        self._active: Dict[str, ResourceLease] = {}
        self._recent_plans: list[Dict[str, Any]] = []

    def build_plan(
        self,
        task_type: str,
        *,
        requested_kwargs: Optional[Dict[str, Any]] = None,
        status_snapshot: Optional[Dict[str, Any]] = None,
    ) -> ResourcePlan:
        requested_kwargs = requested_kwargs or {}
        status_snapshot = status_snapshot or {}

        group = TASK_GROUPS.get(task_type, "other")
        loaded_groups = self._infer_loaded_groups(status_snapshot.get("models_loaded", []))
        preserve_ollama = bool(requested_kwargs.get("preserve_ollama", False))
        pressure = self._pressure(status_snapshot)
        conflicts = set(GROUP_CONFLICTS.get(group, set()))
        if group == "diffusion" and not preserve_ollama and self._is_low_vram(status_snapshot):
            # Ollama lives in another process, but on 8-10GB GPUs it still
            # consumes enough VRAM to starve SDXL/ControlNet. Treat chat as a
            # conflict here so plans match the real ModelManager behavior.
            conflicts.add("chat")
        if preserve_ollama:
            conflicts.discard("chat")

        unload_groups = sorted(conflicts.intersection(loaded_groups))
        keep_groups = sorted(set(loaded_groups).difference(unload_groups))
        reason = self._build_reason(group, unload_groups, keep_groups, pressure, preserve_ollama)

        return ResourcePlan(
            task_type=task_type,
            group=group,
            loaded_groups=sorted(loaded_groups),
            unload_groups=unload_groups,
            keep_groups=keep_groups,
            preserve_ollama=preserve_ollama,
            pressure=pressure,
            reason=reason,
        )

    def begin_task(
        self,
        task_type: str,
        *,
        job_id: Optional[str] = None,
        model_name: str = "",
        requested_kwargs: Optional[Dict[str, Any]] = None,
        status_snapshot: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        plan = self.build_plan(
            task_type,
            requested_kwargs=requested_kwargs,
            status_snapshot=status_snapshot,
        )
        lease = ResourceLease(
            id=str(uuid.uuid4()),
            task_type=task_type,
            group=plan.group,
            job_id=job_id,
            model_name=model_name or "",
            plan=plan.to_dict(),
        )
        with self._lock:
            self._active[lease.id] = lease
            self._recent_plans.append({
                "at": lease.started_at,
                "lease_id": lease.id,
                "job_id": job_id,
                "model_name": model_name or "",
                "plan": plan.to_dict(),
            })
            del self._recent_plans[:-self.max_recent_plans]
            return lease.to_dict()

    def end_task(self, lease_id: str) -> None:
        with self._lock:
            self._active.pop(str(lease_id), None)

    def end_task_by_job(self, job_id: str) -> int:
        """Release every active lease attached to a completed/cancelled job.

        Routes still release their own explicit lease IDs when they can. This
        job-level cleanup is the safety net for streaming paths such as the
        terminal: if the UI cancels or a route ends through a different branch,
        resources must not stay "reserved" forever in runtime status.
        """
        if not job_id:
            return 0
        removed = 0
        with self._lock:
            for lease_id, lease in list(self._active.items()):
                if lease.job_id == job_id:
                    self._active.pop(lease_id, None)
                    removed += 1
        return removed

    def state(self, status_snapshot: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        status_snapshot = status_snapshot or {}
        loaded_groups = sorted(self._infer_loaded_groups(status_snapshot.get("models_loaded", [])))
        with self._lock:
            active = [lease.to_dict() for lease in self._active.values()]
            recent = deepcopy(self._recent_plans)
        return {
            "active": active,
            "active_count": len(active),
            "loaded_groups": loaded_groups,
            "pressure": self._pressure(status_snapshot),
            "recent_plans": recent,
        }

    @staticmethod
    def _infer_loaded_groups(models_loaded: Iterable[str]) -> Set[str]:
        groups: Set[str] = set()
        for item in models_loaded or []:
            model = str(item).lower()
            if model.startswith("video:"):
                groups.add("video")
            elif model.startswith("ollama:"):
                groups.add("chat")
            elif (
                model.startswith("inpaint:")
                or model.startswith("gguf:")
                or model.startswith("outpaint")
                or model.startswith("upscale:")
                or model.startswith("controlnet:")
                or model.startswith("depth:")
                or model.startswith("ip-adapter:")
                or model.startswith("lora:")
                or model.startswith("segmentation:")
                or model.startswith("pose:")
            ):
                groups.add("diffusion")
            elif model.startswith("caption:"):
                groups.add("chat")
        return groups

    @staticmethod
    def _pressure(status_snapshot: Dict[str, Any]) -> str:
        try:
            total = float(status_snapshot.get("total_gb") or 0)
            used = float(status_snapshot.get("used_gb") or 0)
        except (TypeError, ValueError):
            return "unknown"
        if total <= 0:
            return "unknown"
        ratio = used / total
        if ratio >= 0.9:
            return "critical"
        if ratio >= 0.75:
            return "high"
        if ratio >= 0.5:
            return "medium"
        return "low"

    @staticmethod
    def _is_low_vram(status_snapshot: Dict[str, Any]) -> bool:
        try:
            total = float(status_snapshot.get("total_gb") or 0)
        except (TypeError, ValueError):
            return False
        return 0 < total <= 10

    @staticmethod
    def _build_reason(
        group: str,
        unload_groups: list[str],
        keep_groups: list[str],
        pressure: str,
        preserve_ollama: bool,
    ) -> str:
        if unload_groups:
            return (
                f"{group} needs exclusive resources; unload {', '.join(unload_groups)} "
                f"(pressure={pressure}, preserve_ollama={preserve_ollama})"
            )
        if keep_groups:
            return f"{group} can start while keeping {', '.join(keep_groups)} (pressure={pressure})"
        return f"{group} can start with no loaded resource conflicts (pressure={pressure})"


_RESOURCE_SCHEDULER: ResourceScheduler | None = None
_RESOURCE_LOCK = threading.Lock()


def get_resource_scheduler() -> ResourceScheduler:
    global _RESOURCE_SCHEDULER
    with _RESOURCE_LOCK:
        if _RESOURCE_SCHEDULER is None:
            _RESOURCE_SCHEDULER = ResourceScheduler()
        return _RESOURCE_SCHEDULER
