"""Transparent score rollups for PerfAtlas."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple


CATEGORY_DEFS: List[Tuple[str, str, float]] = [
    ("field_readiness", "Core Web Vitals & Field Readiness", 0.18),
    ("lab_startup", "Lab Rendering & Startup", 0.16),
    ("interactivity", "Interactivity & Main-thread Pressure", 0.16),
    ("network_delivery", "Network & Server Delivery", 0.16),
    ("asset_efficiency", "Asset Efficiency", 0.14),
    ("cache_transport", "Caching, Compression & Transport", 0.10),
    ("ux_resilience", "UX Resilience & Platform Fit", 0.10),
]

SEVERITY_PENALTIES = {
    "critical": 24,
    "high": 14,
    "medium": 8,
    "low": 4,
    "info": 0,
}

CONFIDENCE_ORDER = {
    "Confirmed": 4,
    "Strong signal": 3,
    "Estimated": 2,
    "Unknown": 1,
}

SEVERITY_ORDER = {
    "critical": 5,
    "high": 4,
    "medium": 3,
    "low": 2,
    "info": 1,
}


def _confidence_label(findings: List[Dict[str, Any]]) -> str:
    if not findings:
        return "Unknown"
    best = max((CONFIDENCE_ORDER.get(item.get("confidence", "Unknown"), 1) for item in findings), default=1)
    for label, rank in CONFIDENCE_ORDER.items():
        if rank == best:
            return label
    return "Unknown"


def _bounded_score(value: Any) -> Optional[float]:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if numeric < 0 or numeric > 100:
        return None
    return numeric


def _cap_bucket(
    buckets: Dict[str, Dict[str, Any]],
    bucket_id: str,
    cap: float,
    reason: str,
    guardrails: List[Dict[str, Any]],
) -> None:
    bucket = buckets.get(bucket_id)
    if not bucket:
        return
    current = float(bucket["score"])
    if current <= cap:
        return
    bucket["score"] = max(0.0, min(100.0, cap))
    bucket.setdefault("guardrails", []).append(reason)
    guardrails.append({
        "bucket": bucket_id,
        "cap": round(float(cap), 1),
        "reason": reason,
    })


def score_findings(
    findings: List[Dict[str, Any]],
    *,
    pages_analyzed: int,
    page_budget: int,
    lab_score: Any = None,
    lab_available: Optional[bool] = None,
    field_available: Optional[bool] = None,
) -> Dict[str, Any]:
    buckets: Dict[str, Dict[str, Any]] = {
        category_id: {
            "id": category_id,
            "label": label,
            "weight": weight,
            "score": 100.0,
            "issues": [],
            "guardrails": [],
        }
        for category_id, label, weight in CATEGORY_DEFS
    }

    for finding in findings:
        bucket_id = str(finding.get("bucket") or "ux_resilience")
        bucket = buckets.get(bucket_id)
        if not bucket:
            continue
        penalty = SEVERITY_PENALTIES.get(str(finding.get("severity", "low")).lower(), 4)
        bucket["score"] = max(0.0, float(bucket["score"]) - penalty)
        bucket["issues"].append(finding)

    finding_ids = {str(item.get("id") or "") for item in findings}
    if lab_available is None:
        lab_available = "lab-runtime-unavailable" not in finding_ids
    if field_available is None:
        field_available = "field-data-unavailable" not in finding_ids
    normalized_lab_score = _bounded_score(lab_score)

    guardrails: List[Dict[str, Any]] = []
    if not lab_available:
        _cap_bucket(buckets, "lab_startup", 50.0, "Lab runtime unavailable; startup score capped until Lighthouse or PSI data is available.", guardrails)
        _cap_bucket(buckets, "interactivity", 55.0, "Lab runtime unavailable; interactivity score capped until TBT/INP-style lab evidence is available.", guardrails)
        _cap_bucket(buckets, "asset_efficiency", 70.0, "Lab runtime unavailable; asset efficiency score capped because payload opportunities could not be measured.", guardrails)
        _cap_bucket(buckets, "ux_resilience", 80.0, "Lab runtime unavailable; confidence is degraded for the pass.", guardrails)
    elif normalized_lab_score is not None:
        _cap_bucket(buckets, "lab_startup", min(100.0, normalized_lab_score + 12.0), "Anchored to the representative Lighthouse/PSI performance score.", guardrails)
        _cap_bucket(buckets, "interactivity", min(100.0, normalized_lab_score + 18.0), "Anchored to the representative Lighthouse/PSI performance score.", guardrails)
        _cap_bucket(buckets, "asset_efficiency", min(100.0, normalized_lab_score + 35.0), "Anchored to the representative Lighthouse/PSI performance score.", guardrails)

    if not field_available:
        _cap_bucket(buckets, "field_readiness", 75.0, "CrUX field data unavailable; field readiness is capped until real-user data is confirmed.", guardrails)

    coverage = 0.0
    if page_budget > 0:
        coverage = min(1.0, float(pages_analyzed) / float(page_budget))

    weighted_total = 0.0
    total_weight = 0.0
    score_rows: List[Dict[str, Any]] = []
    for category_id, label, weight in CATEGORY_DEFS:
        bucket = buckets[category_id]
        issues = bucket["issues"]
        category_guardrails = bucket.get("guardrails") or []
        weighted_total += bucket["score"] * weight
        total_weight += weight
        confidence = _confidence_label(issues)
        if category_guardrails and confidence == "Unknown":
            confidence = "Estimated"
        if issues:
            summary = f"{len(issues)} issue(s) contribute to this category."
            if category_guardrails:
                summary += f" {category_guardrails[0]}"
        elif category_guardrails:
            summary = category_guardrails[0]
        else:
            summary = "No blocking issues detected in the sampled coverage."
        score_rows.append(
            {
                "id": category_id,
                "label": label,
                "score": round(float(bucket["score"]), 1),
                "weight": weight,
                "coverage": round(coverage, 2),
                "confidence": confidence,
                "issues_count": len(issues),
                "summary": summary,
                "finding_ids": [item.get("id") for item in issues if item.get("id")],
            }
        )

    raw_global_score = weighted_total / total_weight if total_weight else 0.0
    global_cap: Optional[float] = None
    global_cap_reason = ""
    if normalized_lab_score is not None:
        lab_weighted_score = (raw_global_score * 0.55) + (normalized_lab_score * 0.45)
        global_cap = min(lab_weighted_score, normalized_lab_score + 28.0, 100.0)
        global_cap_reason = "Global score anchored to the representative Lighthouse/PSI performance score."
    elif not lab_available and not field_available:
        global_cap = 65.0
        global_cap_reason = "Global score capped because both lab and field evidence are unavailable."
    elif not lab_available:
        global_cap = 72.0
        global_cap_reason = "Global score capped because lab evidence is unavailable."
    elif not field_available:
        global_cap = 88.0
        global_cap_reason = "Global score capped because field evidence is unavailable."

    if global_cap is not None and raw_global_score > global_cap:
        guardrails.append({
            "bucket": "global",
            "cap": round(float(global_cap), 1),
            "reason": global_cap_reason,
        })
        raw_global_score = global_cap
    global_score = round(raw_global_score, 1)
    ranked = sorted(
        findings,
        key=lambda item: (
            SEVERITY_ORDER.get(str(item.get("severity", "")).lower(), 0),
            CONFIDENCE_ORDER.get(item.get("confidence", "Unknown"), 1),
        ),
        reverse=True,
    )
    primary = ranked[0] if ranked else {}
    blocking_risk = {
        "level": "Low",
        "summary": "No blocking performance risk was detected in the sampled baseline.",
        "primary_finding_id": "",
        "finding_ids": [],
    }
    if primary:
        severity = str(primary.get("severity", "")).lower()
        if severity == "critical":
            level = "Critical"
        elif severity == "high":
            level = "High"
        elif severity == "medium":
            level = "Medium"
        else:
            level = "Low"
        blocking_risk = {
            "level": level,
            "summary": primary.get("relationship_summary") or primary.get("diagnostic") or "A high-priority performance risk was detected.",
            "primary_finding_id": primary.get("id", ""),
            "finding_ids": [item.get("id") for item in ranked if item.get("id")],
        }
    return {
        "global_score": global_score,
        "categories": score_rows,
        "coverage": {
            "pages_analyzed": pages_analyzed,
            "page_budget": page_budget,
            "ratio": round(coverage, 2),
        },
        "blocking_risk": blocking_risk,
        "guardrails": guardrails,
    }
