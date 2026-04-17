"""Runtime routes: jobs, conversations and orchestration state."""

from __future__ import annotations

from flask import Blueprint, jsonify, request

runtime_bp = Blueprint("runtime", __name__)


def _bridge_runtime_cancel_to_generation_flags(app_module, job_id: str) -> bool:
    """Mark only the matching legacy generation as cancelled.

    Runtime jobs are job-scoped. The legacy ``generation_cancelled`` flag is
    global and is still used by /cancel-all, so setting it from a single job
    cancel can accidentally stop an unrelated active image generation.
    """
    with app_module.generations_lock:
        if job_id in app_module.active_generations:
            app_module.active_generations[job_id]["cancelled"] = True
            return True
    return False


def _query_int(name: str, default: int, *, minimum: int = 1, maximum: int = 500) -> int:
    try:
        value = int(request.args.get(name, default))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(value, maximum))


@runtime_bp.route("/api/runtime/status", methods=["GET"])
def runtime_status():
    from core.runtime import get_job_manager, get_conversation_store, get_resource_scheduler

    jobs = get_job_manager().list(limit=200)
    active = [job for job in jobs if job.get("status") not in {"done", "error", "cancelled"}]
    model_status = {}
    try:
        from core.model_manager import ModelManager
        model_status = ModelManager.get().get_status()
    except Exception as exc:
        model_status = {"error": str(exc)}
    return jsonify({
        "success": True,
        "jobs": {
            "active": len(active),
            "total_recent": len(jobs),
        },
        "conversations": {
            "total_recent": len(get_conversation_store().list(limit=500)),
        },
        "resources": get_resource_scheduler().state(model_status),
        "model_status": model_status,
    })


@runtime_bp.route("/api/runtime/jobs", methods=["GET", "POST"])
def runtime_jobs():
    from core.runtime import get_job_manager

    manager = get_job_manager()
    if request.method == "POST":
        data = request.json or {}
        job = manager.create(
            data.get("kind", "task"),
            job_id=data.get("id") or data.get("job_id"),
            conversation_id=data.get("conversation_id") or data.get("chatId"),
            prompt=data.get("prompt", ""),
            model=data.get("model", ""),
            metadata=data.get("metadata") or {},
        )
        return jsonify({"success": True, "job": job})

    conversation_id = request.args.get("conversation_id") or request.args.get("chatId")
    status = request.args.get("status")
    limit = _query_int("limit", 100)
    return jsonify({
        "success": True,
        "jobs": manager.list(conversation_id=conversation_id, status=status, limit=limit),
    })


@runtime_bp.route("/api/runtime/jobs/<job_id>", methods=["GET"])
def runtime_job(job_id):
    from core.runtime import get_job_manager

    job = get_job_manager().get(job_id)
    if not job:
        return jsonify({"success": False, "error": "Job introuvable"}), 404
    return jsonify({"success": True, "job": job})


@runtime_bp.route("/api/runtime/jobs/<job_id>/cancel", methods=["POST"])
def runtime_cancel_job(job_id):
    from core.runtime import get_job_manager

    manager = get_job_manager()
    data = request.json or {}
    force = bool(data.get("force"))
    current_job = manager.get(job_id)
    if force or (current_job and current_job.get("kind") == "terminal"):
        # Terminal calls can be blocked inside a non-streaming Ollama request;
        # waiting for cooperative cancellation leaves sidebar cards stuck in
        # "cancelling". Mark terminal jobs final immediately and let stale
        # callbacks be ignored by JobManager.update().
        job = manager.cancel(job_id, "Job cancelled" if force else "Terminal request cancelled")
    else:
        job = manager.request_cancel(job_id)
    if not job:
        return jsonify({"success": False, "error": "Job introuvable"}), 404

    # Bridge with legacy per-generation flags while routes migrate to the
    # runtime job manager. Do not set the global generation_cancelled flag here:
    # cancelling one runtime card must not stop unrelated active generations.
    try:
        import web.app as app_module
        _bridge_runtime_cancel_to_generation_flags(app_module, job_id)
    except Exception:
        pass

    return jsonify({"success": True, "job": job})


@runtime_bp.route("/api/runtime/conversations/<conversation_id>/cancel-jobs", methods=["POST"])
def runtime_cancel_conversation_jobs(conversation_id):
    from core.runtime import get_job_manager

    jobs = get_job_manager().cancel_conversation(
        conversation_id,
        "Conversation supprimée: jobs arrêtés",
    )
    return jsonify({"success": True, "jobs": jobs})


@runtime_bp.route("/api/runtime/conversations", methods=["GET", "POST"])
def runtime_conversations():
    from core.runtime import get_conversation_store

    store = get_conversation_store()
    if request.method == "POST":
        data = request.json or {}
        conv = store.create(
            conversation_id=data.get("id") or data.get("conversation_id"),
            title=data.get("title"),
            metadata=data.get("metadata") or {},
        )
        return jsonify({"success": True, "conversation": conv})

    return jsonify({
        "success": True,
        "conversations": store.list(
            include_archived=str(request.args.get("archived", "")).lower() in {"1", "true", "yes"},
            limit=_query_int("limit", 100),
        ),
    })


@runtime_bp.route("/api/runtime/conversations/<conversation_id>", methods=["GET"])
def runtime_conversation(conversation_id):
    from core.runtime import get_conversation_store, get_job_manager

    conv = get_conversation_store().get(conversation_id)
    if not conv:
        return jsonify({"success": False, "error": "Conversation introuvable"}), 404
    jobs = get_job_manager().list(conversation_id=conversation_id, limit=200)
    return jsonify({"success": True, "conversation": conv, "jobs": jobs})


@runtime_bp.route("/api/runtime/conversations/<conversation_id>/messages", methods=["POST"])
def runtime_append_message(conversation_id):
    from core.runtime import get_conversation_store

    data = request.json or {}
    message = get_conversation_store().append_message(
        conversation_id,
        data.get("role", "user"),
        data.get("content", ""),
        message_id=data.get("id") or data.get("message_id"),
        job_id=data.get("job_id"),
        metadata=data.get("metadata") or {},
    )
    return jsonify({"success": True, "message": message})
