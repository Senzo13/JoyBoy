"""Transparent risk scoring for CyberAtlas."""

from __future__ import annotations

from typing import Any, Dict, List, Tuple


CATEGORY_DEFS: List[Tuple[str, str, float]] = [
    ("transport_tls", "Transport & TLS", 0.18),
    ("browser_hardening", "Browser Hardening Headers", 0.20),
    ("app_exposure", "Application Exposure", 0.22),
    ("api_surface", "API & Documentation Surface", 0.14),
    ("session_privacy", "Session & Privacy Controls", 0.14),
    ("operational_resilience", "Operational Resilience", 0.12),
]

SEVERITY_PENALTIES = {
    "critical": 28,
    "high": 18,
    "medium": 10,
    "low": 4,
    "info": 0,
}

SEVERITY_ORDER = {
    "critical": 5,
    "high": 4,
    "medium": 3,
    "low": 2,
    "info": 1,
}

CONFIDENCE_ORDER = {
    "Confirmed": 4,
    "Strong signal": 3,
    "Estimated": 2,
    "Unknown": 1,
}

CONFIDENCE_MULTIPLIERS = {
    "Confirmed": 1.0,
    "Strong signal": 0.85,
    "Estimated": 0.65,
    "Unknown": 0.45,
}


def _confidence_label(findings: List[Dict[str, Any]]) -> str:
    if not findings:
        return "Unknown"
    best = max((CONFIDENCE_ORDER.get(item.get("confidence", "Unknown"), 1) for item in findings), default=1)
    for label, rank in CONFIDENCE_ORDER.items():
        if rank == best:
            return label
    return "Unknown"


def score_findings(
    findings: List[Dict[str, Any]],
    *,
    pages_analyzed: int,
    page_budget: int,
    endpoint_count: int = 0,
) -> Dict[str, Any]:
    buckets: Dict[str, Dict[str, Any]] = {
        category_id: {
            "id": category_id,
            "label": label,
            "weight": weight,
            "score": 100.0,
            "issues": [],
        }
        for category_id, label, weight in CATEGORY_DEFS
    }

    for finding in findings:
        bucket_id = str(finding.get("bucket") or "app_exposure")
        bucket = buckets.get(bucket_id)
        if not bucket:
            continue
        severity = str(finding.get("severity") or "low").lower()
        confidence = str(finding.get("confidence") or "Unknown")
        penalty = SEVERITY_PENALTIES.get(severity, 4) * CONFIDENCE_MULTIPLIERS.get(confidence, 0.55)
        if finding.get("root_cause"):
            penalty = max(penalty, SEVERITY_PENALTIES.get(severity, 4) * 0.9)
        bucket["score"] = max(0.0, float(bucket["score"]) - penalty)
        bucket["issues"].append(finding)

    if endpoint_count > 50:
        bucket = buckets["api_surface"]
        bucket["score"] = min(float(bucket["score"]), 78.0)

    coverage = min(1.0, float(pages_analyzed) / float(page_budget)) if page_budget else 0.0
    weighted_total = 0.0
    total_weight = 0.0
    score_rows: List[Dict[str, Any]] = []
    for category_id, label, weight in CATEGORY_DEFS:
        bucket = buckets[category_id]
        issues = bucket["issues"]
        weighted_total += float(bucket["score"]) * weight
        total_weight += weight
        score_rows.append({
            "id": category_id,
            "label": label,
            "score": round(float(bucket["score"]), 1),
            "weight": weight,
            "coverage": round(coverage, 2),
            "confidence": _confidence_label(issues),
            "issues_count": len(issues),
            "summary": (
                f"{len(issues)} risk signal(s) affect this category."
                if issues
                else "No blocking risk detected in the sampled evidence."
            ),
            "finding_ids": [item.get("id") for item in issues if item.get("id")],
        })

    global_score = round(weighted_total / total_weight, 1) if total_weight else 0.0
    ranked = sorted(
        findings,
        key=lambda item: (
            SEVERITY_ORDER.get(str(item.get("severity") or "").lower(), 0),
            CONFIDENCE_ORDER.get(item.get("confidence", "Unknown"), 1),
        ),
        reverse=True,
    )
    primary = ranked[0] if ranked else {}
    blocking_risk = {
        "level": "Low",
        "summary": "No blocking cyber exposure was detected in the sampled evidence.",
        "primary_finding_id": "",
        "finding_ids": [],
    }
    if primary:
        severity = str(primary.get("severity") or "").lower()
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
            "summary": primary.get("relationship_summary") or primary.get("diagnostic") or "A priority security risk was detected.",
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
    }
