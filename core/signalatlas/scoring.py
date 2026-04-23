"""Transparent score rollups for SignalAtlas."""

from __future__ import annotations

from typing import Any, Dict, List, Tuple


CATEGORY_DEFS: List[Tuple[str, str, float]] = [
    ("crawl_discovery", "Crawl & Discovery", 0.16),
    ("indexability", "Indexability", 0.18),
    ("rendering_delivery", "Rendering & Delivery", 0.16),
    ("architecture_linking", "Architecture & Internal Linking", 0.15),
    ("metadata_semantics", "Metadata & Semantics", 0.12),
    ("content_depth_blog", "Content Depth & Blog", 0.11),
    ("visibility_readiness", "Visibility Readiness", 0.12),
]

SEVERITY_PENALTIES = {
    "critical": 22,
    "high": 12,
    "medium": 7,
    "low": 3,
    "info": 0,
}

CONFIDENCE_ORDER = {
    "Confirmed": 4,
    "Strong signal": 3,
    "Estimated": 2,
    "Unknown": 1,
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
        bucket_id = str(finding.get("bucket") or "visibility_readiness")
        bucket = buckets.get(bucket_id)
        if not bucket:
            continue
        penalty = SEVERITY_PENALTIES.get(str(finding.get("severity", "low")).lower(), 3)
        bucket["score"] = max(0.0, float(bucket["score"]) - penalty)
        bucket["issues"].append(finding)

    coverage = 0.0
    if page_budget > 0:
        coverage = min(1.0, float(pages_analyzed) / float(page_budget))

    score_rows: List[Dict[str, Any]] = []
    weighted_total = 0.0
    total_weight = 0.0
    for category_id, label, weight in CATEGORY_DEFS:
        bucket = buckets[category_id]
        issues = bucket["issues"]
        weighted_total += bucket["score"] * weight
        total_weight += weight
        summary = (
            f"{len(issues)} issue(s) contribute to this category."
            if issues
            else "No blocking issues detected in the sampled coverage."
        )
        score_rows.append(
            {
                "id": category_id,
                "label": label,
                "score": round(float(bucket["score"]), 1),
                "weight": weight,
                "coverage": round(coverage, 2),
                "confidence": _confidence_label(issues),
                "issues_count": len(issues),
                "summary": summary,
                "finding_ids": [item.get("id") for item in issues if item.get("id")],
            }
        )

    global_score = round(weighted_total / total_weight, 1) if total_weight else 0.0
    return {
        "global_score": global_score,
        "categories": score_rows,
        "coverage": {
            "pages_analyzed": pages_analyzed,
            "page_budget": page_budget,
            "ratio": round(coverage, 2),
        },
    }
