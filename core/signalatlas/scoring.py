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
    root_causes = [item for item in findings if item.get("root_cause")]
    blocking_candidates = root_causes or [
        item for item in findings if SEVERITY_ORDER.get(str(item.get("severity", "")).lower(), 0) >= SEVERITY_ORDER["high"]
    ]
    blocking_risk = {
        "level": "Low",
        "summary": "No blocking root cause was detected in the sampled baseline.",
        "primary_finding_id": "",
        "finding_ids": [],
    }
    if blocking_candidates:
        ranked = sorted(
            blocking_candidates,
            key=lambda item: (
                1 if item.get("root_cause") else 0,
                SEVERITY_ORDER.get(str(item.get("severity", "")).lower(), 0),
                CONFIDENCE_ORDER.get(item.get("confidence", "Unknown"), 1),
            ),
            reverse=True,
        )
        primary = ranked[0]
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
            "summary": (
                primary.get("relationship_summary")
                or primary.get("diagnostic")
                or "A high-priority issue blocks trustworthy SEO interpretation."
            ),
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
