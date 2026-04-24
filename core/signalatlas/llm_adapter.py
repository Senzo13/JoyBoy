"""AI interpretation layer for SignalAtlas."""

from __future__ import annotations

import uuid
from typing import Any, Dict, List

from core.ai.text_model_router import call_text_model
from core.runtime.storage import utc_now_iso


AI_LEVEL_PROMPTS = {
    "basic_summary": "Summarize the audit clearly for a non-specialist founder. Stay concise and action-oriented.",
    "full_expert_analysis": "Produce an expert interpretation grouped by root cause, business impact, and implementation priority.",
    "ai_remediation_pack": "Transform the audit into a remediation pack with actionable tickets for dev, SEO, and content owners.",
}


def _audit_excerpt(audit: Dict[str, Any]) -> Dict[str, Any]:
    summary = audit.get("summary") or {}
    findings = audit.get("findings") or []
    scores = audit.get("scores") or []
    snapshot = audit.get("snapshot") or {}
    pages = snapshot.get("pages") or []
    render_detection = snapshot.get("render_detection") or {}
    return {
        "summary": summary,
        "top_findings": findings[:10],
        "root_causes": [
            {
                "id": item.get("id"),
                "title": item.get("title"),
                "severity": item.get("severity"),
                "confidence": item.get("confidence"),
                "validation_state": item.get("validation_state"),
                "relationship_summary": item.get("relationship_summary"),
            }
            for item in findings
            if item.get("root_cause")
        ],
        "derived_symptoms": [
            {
                "id": item.get("id"),
                "title": item.get("title"),
                "severity": item.get("severity"),
                "confidence": item.get("confidence"),
                "validation_state": item.get("validation_state"),
                "derived_from": item.get("derived_from"),
            }
            for item in findings
            if item.get("derived_from")
        ],
        "scores": scores,
        "render_detection": {
            "render_js_requested": render_detection.get("render_js_requested"),
            "render_js_executed": render_detection.get("render_js_executed"),
            "note": render_detection.get("note"),
        },
        "visibility_signals": snapshot.get("visibility_signals") or {},
        "template_clusters": (snapshot.get("template_clusters") or [])[:6],
        "sample_pages": [
            {
                "url": page.get("final_url") or page.get("url"),
                "status_code": page.get("status_code"),
                "title": page.get("title"),
                "html_lang": page.get("html_lang"),
                "word_count": page.get("word_count"),
                "content_units": page.get("content_units"),
                "cjk_char_count": page.get("cjk_char_count"),
                "image_missing_alt": page.get("image_missing_alt"),
                "image_empty_alt": page.get("image_empty_alt"),
                "shell_like": page.get("shell_like"),
                "framework_signatures": page.get("framework_signatures"),
            }
            for page in pages[:6]
        ],
    }


def _preset_note(preset: str) -> str:
    preset = str(preset or "").strip().lower()
    if preset == "fast":
        return "Favor concise output and only the highest-impact issues."
    if preset == "expert":
        return "Be exhaustive, nuanced, and precise. Highlight tradeoffs and confidence levels."
    if preset == "local_private":
        return "Assume privacy is prioritized over verbosity. Avoid fluff and keep reasoning local-friendly."
    return "Balance clarity, precision, and depth."


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
    system_message = (
        "You are SignalAtlas AI inside JoyBoy. The deterministic audit is the source of truth. "
        "Never invent crawl data, indexing facts, or unsupported metrics. "
        "Use the provided confidence labels exactly as given. "
        "Separate root causes from downstream symptoms. "
        "When render_js_requested is true but render_js_executed is false, explicitly say that some heading, "
        "content-depth, duplicate, or internal-linking findings may be baseline-only symptoms of the initial HTML response."
    )
    user_message = (
        f"Task: {prompt_goal}\n"
        f"Preset: {preset}\n"
        f"Model note: {_preset_note(preset)}\n"
        "Return markdown with sections: Executive summary, Root causes, Prioritized roadmap, "
        "Prompts for action. Include confidence and source transparency.\n"
        "Call out what is confirmed, what is baseline-only, and what needs rendered-browser validation.\n\n"
        f"AUDIT EXCERPT:\n{excerpt}"
    )
    content = call_text_model(
        [
            {"role": "system", "content": system_message},
            {"role": "user", "content": user_message},
        ],
        purpose="utility",
        model=model,
        num_predict=1200 if clean_level != "basic_summary" else 700,
        temperature=0.2,
        timeout=90,
    )
    if not content:
        content = (
            "## Executive summary\n"
            "SignalAtlas could not obtain an AI interpretation from the selected model. "
            "The deterministic audit remains valid and can still be exported.\n\n"
            "## Next step\n"
            "Retry with another JoyBoy model or use the remediation prompts from the technical findings."
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
