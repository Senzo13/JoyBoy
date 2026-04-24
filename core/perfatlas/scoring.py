"""Transparent score rollups for PerfAtlas."""

from __future__ import annotations

from typing import Any, Dict, List, Tuple


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


def score_findings(
    findings: List[Dict[str, Any]],
    *,
    pages_analyzed: int,
    page_budget: int,
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
        bucket_id = str(finding.get("bucket") or "ux_resilience")
        bucket = buckets.get(bucket_id)
        if not bucket:
            continue
        penalty = SEVERITY_PENALTIES.get(str(finding.get("severity", "low")).lower(), 4)
        bucket["score"] = max(0.0, float(bucket["score"]) - penalty)
        bucket["issues"].append(finding)

    coverage = 0.0
    if page_budget > 0:
        coverage = min(1.0, float(pages_analyzed) / float(page_budget))

    weighted_total = 0.0
    total_weight = 0.0
    score_rows: List[Dict[str, Any]] = []
    for category_id, label, weight in CATEGORY_DEFS:
        bucket = buckets[category_id]
        issues = bucket["issues"]
        weighted_total += bucket["score"] * weight
        total_weight += weight
        score_rows.append(
            {
                "id": category_id,
                "label": label,
                "score": round(float(bucket["score"]), 1),
                "weight": weight,
                "coverage": round(coverage, 2),
                "confidence": _confidence_label(issues),
                "issues_count": len(issues),
                "summary": (
                    f"{len(issues)} issue(s) contribute to this category."
                    if issues
                    else "No blocking issues detected in the sampled coverage."
                ),
                "finding_ids": [item.get("id") for item in issues if item.get("id")],
            }
        )

    global_score = round(weighted_total / total_weight, 1) if total_weight else 0.0
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
    }
