"""AI interpretation layer for CyberAtlas."""

from __future__ import annotations

import uuid
from typing import Any, Dict

from core.ai.text_model_router import call_text_model
from core.runtime.storage import utc_now_iso


AI_LEVEL_PROMPTS = {
    "basic_summary": "Summarize the security audit for a founder or product owner. Stay clear, defensive, and practical.",
    "full_expert_analysis": "Produce an expert defensive security interpretation grouped by exposure, browser hardening, API surface, session risk, and remediation order.",
    "ai_remediation_pack": "Transform the CyberAtlas audit into a remediation pack with concrete tickets, acceptance criteria, validation steps, and safe rollout order.",
}


def _audit_excerpt(audit: Dict[str, Any]) -> Dict[str, Any]:
    snapshot = audit.get("snapshot") or {}
    return {
        "summary": audit.get("summary") or {},
        "top_findings": (audit.get("findings") or [])[:12],
        "scores": audit.get("scores") or [],
        "tls": snapshot.get("tls") or {},
        "security_headers": snapshot.get("security_headers") or {},
        "exposure_probes": (snapshot.get("exposure_probes") or [])[:18],
        "openapi": snapshot.get("openapi") or {},
        "api_inventory": snapshot.get("api_inventory") or {},
        "coverage": audit.get("coverage") or snapshot.get("coverage") or {},
        "owner_verification_plan": (audit.get("owner_verification_plan") or snapshot.get("owner_verification_plan") or [])[:10],
        "attack_paths": (audit.get("attack_paths") or snapshot.get("attack_paths") or [])[:8],
        "standard_map": [
            item for item in (audit.get("standard_map") or snapshot.get("standard_map") or [])
            if item.get("status") != "clear"
        ][:12],
        "security_tickets": (audit.get("security_tickets") or snapshot.get("security_tickets") or [])[:12],
        "evidence_graph": {
            "nodes": ((audit.get("evidence_graph") or snapshot.get("evidence_graph") or {}).get("nodes") or [])[:18],
            "edges": ((audit.get("evidence_graph") or snapshot.get("evidence_graph") or {}).get("edges") or [])[:24],
        },
        "action_plan": (audit.get("action_plan") or [])[:10],
        "forms": (snapshot.get("forms") or [])[:10],
        "pages": (snapshot.get("pages") or [])[:6],
    }


def _preset_note(preset: str) -> str:
    clean = str(preset or "").strip().lower()
    if clean == "fast":
        return "Keep only the highest-risk confirmed findings and the first fixes to ship."
    if clean == "expert":
        return "Be precise, nuanced, and defensive. Separate confirmed evidence from risk signals."
    if clean == "local_private":
        return "Keep output compact and privacy-conscious. Do not ask for secrets or credentials."
    return "Balance depth, clarity, and implementation usefulness."


def _generation_budget(level: str, excerpt: Dict[str, Any]) -> Dict[str, int]:
    finding_count = len(excerpt.get("top_findings") or [])
    if str(level or "").strip().lower() == "basic_summary":
        return {"num_predict": 650, "timeout": 60}
    if finding_count <= 6:
        return {"num_predict": 900, "timeout": 70}
    return {"num_predict": 1300, "timeout": 100}


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
        "You are CyberAtlas AI inside JoyBoy. This is a defensive, authorized audit assistant. "
        "The deterministic audit is the source of truth. Do not invent vulnerabilities, CVEs, "
        "credentials, exploit chains, or unmeasured network access. Do not provide offensive exploit payloads. "
        "Focus on risk explanation, safe remediation, validation, and rollout order."
    )
    user_message = (
        f"Task: {prompt_goal}\n"
        f"Preset: {preset}\n"
        f"Model note: {_preset_note(preset)}\n"
        "Return markdown with sections: Executive summary, Confirmed risks, Standards map, Risk paths, Owner verification plan, Security tickets, Validation checklist, Prompt for implementation.\n"
        "Keep the output directly usable by another AI or developer fixing the site.\n\n"
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
            "CyberAtlas could not obtain an AI interpretation from the selected model. "
            "The deterministic security report remains valid and can still be exported.\n\n"
            "## Next step\n"
            "Retry with another JoyBoy model or export the remediation pack."
        )
    return {
        "id": str(uuid.uuid4()),
        "created_at": utc_now_iso(),
        "model": model,
        "preset": preset,
        "level": clean_level,
        "mode": mode,
        "summary": (excerpt.get("summary") or {}).get("target", ""),
        "content": content,
        "metadata": {
            "finding_count": len(excerpt.get("top_findings") or []),
            "score_count": len(excerpt.get("scores") or []),
        },
    }
