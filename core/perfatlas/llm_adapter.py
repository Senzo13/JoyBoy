"""AI interpretation layer for PerfAtlas."""

from __future__ import annotations

import uuid
from typing import Any, Dict

from core.ai.text_model_router import call_text_model
from core.runtime.storage import utc_now_iso


AI_LEVEL_PROMPTS = {
    "basic_summary": "Summarize the performance audit clearly for a non-specialist founder. Stay concise and action-oriented.",
    "full_expert_analysis": "Produce an expert performance interpretation grouped by field data, lab bottlenecks, delivery risks, and implementation priority.",
    "ai_remediation_pack": "Transform the performance audit into a remediation pack with concrete tickets for developers, platform owners, and delivery teams.",
}


def _audit_excerpt(audit: Dict[str, Any]) -> Dict[str, Any]:
    summary = audit.get("summary") or {}
    findings = audit.get("findings") or []
    scores = audit.get("scores") or []
    snapshot = audit.get("snapshot") or {}
    return {
        "summary": summary,
        "top_findings": findings[:10],
        "scores": scores,
        "runtime": snapshot.get("runtime") or {},
        "field_data": (snapshot.get("field_data") or [])[:3],
        "lab_runs": (snapshot.get("lab_runs") or [])[:5],
        "asset_samples": (snapshot.get("asset_samples") or [])[:8],
        "template_clusters": (snapshot.get("template_clusters") or [])[:6],
        "owner_context": audit.get("owner_context") or {},
    }


def _preset_note(preset: str) -> str:
    preset = str(preset or "").strip().lower()
    if preset == "fast":
        return "Favor concise output and only the highest-impact performance blockers."
    if preset == "expert":
        return "Be exhaustive, nuanced, and precise. Highlight tradeoffs, confidence levels, and rollout order."
    if preset == "local_private":
        return "Assume privacy is prioritized over verbosity. Avoid fluff and keep reasoning local-friendly."
    return "Balance clarity, precision, and depth."


def _generation_budget(level: str, excerpt: Dict[str, Any]) -> Dict[str, int]:
    summary = excerpt.get("summary") or {}
    pages_crawled = int(summary.get("pages_crawled") or 0)
    lab_runs = len(excerpt.get("lab_runs") or [])
    finding_count = len(excerpt.get("top_findings") or [])
    small_audit = pages_crawled <= 8 and lab_runs <= 2 and finding_count <= 8
    if str(level or "").strip().lower() == "basic_summary":
        return {"num_predict": 500 if small_audit else 700, "timeout": 45 if small_audit else 70}
    if small_audit:
        return {"num_predict": 850, "timeout": 60}
    return {"num_predict": 1200, "timeout": 90}


def generate_interpretation(
    audit: Dict[str, Any],
    *,
    model: str,
    level: str,
    preset: str,
    mode: str = "rerun",
) -> Dict[str, Any]:
    clean_level = str(level or "basic_summary").strip().lower()
    prompt_goal = AI_LEVEL_PROMPTS.get(clean_level, AI_LEVEL_PROMPTS["basic_summary"])
    excerpt = _audit_excerpt(audit)
    budget = _generation_budget(clean_level, excerpt)
    system_message = (
        "You are PerfAtlas AI inside JoyBoy. The deterministic audit is the source of truth. "
        "Never invent field data, Lighthouse results, provider integrations, or measured timings. "
        "Separate confirmed measurements from estimated structural risks. "
        "If the runtime is degraded or field data is missing, say so explicitly before making recommendations."
    )
    user_message = (
        f"Task: {prompt_goal}\n"
        f"Preset: {preset}\n"
        f"Model note: {_preset_note(preset)}\n"
        "Return markdown with sections: Executive summary, Field vs lab truth, Root causes, Prioritized roadmap, Prompts for action.\n"
        "Prioritize the work so another AI or developer can implement the fixes.\n\n"
        f"AUDIT EXCERPT:\n{excerpt}"
    )
    content = call_text_model(
        [
            {"role": "system", "content": system_message},
            {"role": "user", "content": user_message},
        ],
        purpose="utility",
        model=model,
        num_predict=budget["num_predict"],
        temperature=0.2,
        timeout=budget["timeout"],
    )
    if not content:
        content = (
            "## Executive summary\n"
            "PerfAtlas could not obtain an AI interpretation from the selected model. "
            "The deterministic audit remains valid and can still be exported.\n\n"
            "## Next step\n"
            "Retry with another JoyBoy model or use the remediation prompts from the measured findings."
        )
    return {
        "id": str(uuid.uuid4()),
        "created_at": utc_now_iso(),
        "model": model,
        "preset": preset,
        "level": clean_level,
        "mode": mode,
        "summary": excerpt.get("summary", {}).get("target", ""),
        "content": content,
        "metadata": {
            "finding_count": len(excerpt.get("top_findings") or []),
            "score_count": len(excerpt.get("scores") or []),
        },
    }
