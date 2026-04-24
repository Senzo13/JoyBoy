"""Structured schemas for the SignalAtlas audit module."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


def _clean_mapping(values: Dict[str, Any]) -> Dict[str, Any]:
    cleaned: Dict[str, Any] = {}
    for key, value in values.items():
        if value is None:
            continue
        cleaned[key] = value
    return cleaned


@dataclass
class ModuleDescriptor:
    id: str
    name: str
    tagline: str
    description: str
    icon: str
    status: str
    entry_view: str
    capabilities: List[str] = field(default_factory=list)
    premium: bool = False
    available: bool = True
    locked_reason: str = ""
    featured: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return _clean_mapping(asdict(self))


@dataclass
class SignalAtlasTarget:
    raw: str
    normalized_url: str
    host: str
    mode: str = "public"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class PageSnapshot:
    url: str
    final_url: str
    status_code: int
    content_type: str
    title: str = ""
    meta_description: str = ""
    canonical: str = ""
    h1: str = ""
    heading_counts: Dict[str, int] = field(default_factory=dict)
    html_lang: str = ""
    canonical_in_head: bool = False
    canonical_relative: bool = False
    word_count: int = 0
    content_units: int = 0
    cjk_char_count: int = 0
    cjk_adjusted: bool = False
    text_hash: str = ""
    content_hash: str = ""
    robots_meta: str = ""
    noindex: bool = False
    nofollow: bool = False
    nosnippet: bool = False
    max_snippet: Optional[int] = None
    x_robots_tag: str = ""
    hreflang: List[Dict[str, str]] = field(default_factory=list)
    structured_data_count: int = 0
    structured_data_types: List[str] = field(default_factory=list)
    open_graph: Dict[str, str] = field(default_factory=dict)
    twitter_cards: Dict[str, str] = field(default_factory=dict)
    internal_links: List[str] = field(default_factory=list)
    external_link_count: int = 0
    image_total: int = 0
    image_missing_alt: int = 0
    image_empty_alt: int = 0
    shell_like: bool = False
    system_url: bool = False
    indexable_candidate: bool = False
    framework_signatures: List[str] = field(default_factory=list)
    render_signals: List[str] = field(default_factory=list)
    classification_reasons: List[str] = field(default_factory=list)
    template_signature: str = ""
    has_blog_signals: bool = False
    crawl_depth: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class CrawlSnapshot:
    started_at: str
    finished_at: str
    entry_url: str
    pages: List[PageSnapshot] = field(default_factory=list)
    crawled_urls: List[str] = field(default_factory=list)
    discovered_urls: List[str] = field(default_factory=list)
    broken_urls: List[str] = field(default_factory=list)
    robots: Dict[str, Any] = field(default_factory=dict)
    sitemaps: Dict[str, Any] = field(default_factory=dict)
    framework_detection: Dict[str, Any] = field(default_factory=dict)
    render_detection: Dict[str, Any] = field(default_factory=dict)
    visibility_signals: Dict[str, Any] = field(default_factory=dict)
    template_clusters: List[Dict[str, Any]] = field(default_factory=list)
    page_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["pages"] = [page.to_dict() for page in self.pages]
        return payload


@dataclass
class Finding:
    id: str
    title: str
    url: str
    scope: str
    category: str
    bucket: str
    severity: str
    confidence: str
    expected_impact: str
    evidence: List[str]
    diagnostic: str
    probable_cause: str
    recommended_fix: str
    acceptance_criteria: str
    dev_prompt: str
    content_prompt: str
    seo_prompt: str
    root_cause: bool = False
    derived_from: List[str] = field(default_factory=list)
    validation_state: str = "confirmed"
    evidence_mode: str = "public_crawl"
    relationship_summary: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ScoreBreakdown:
    id: str
    label: str
    score: float
    weight: float
    coverage: float
    confidence: str
    issues_count: int
    summary: str
    finding_ids: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class RemediationItem:
    finding_id: str
    url: str
    category: str
    severity: str
    confidence: str
    expected_impact: str
    diagnostic: str
    probable_cause: str
    recommended_fix: str
    acceptance_criteria: str
    dev_prompt: str
    content_prompt: str
    seo_prompt: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class InterpretationRun:
    id: str
    created_at: str
    model: str
    preset: str
    level: str
    mode: str
    content: str
    summary: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ExportArtifact:
    format: str
    created_at: str
    label: str
    path: str = ""
    size_bytes: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return _clean_mapping(asdict(self))


@dataclass
class SignalAtlasAuditRun:
    id: str
    target: SignalAtlasTarget
    title: str
    status: str
    created_at: str
    updated_at: str
    options: Dict[str, Any] = field(default_factory=dict)
    summary: Dict[str, Any] = field(default_factory=dict)
    snapshot: Dict[str, Any] = field(default_factory=dict)
    findings: List[Finding] = field(default_factory=list)
    scores: List[ScoreBreakdown] = field(default_factory=list)
    interpretations: List[InterpretationRun] = field(default_factory=list)
    remediation_items: List[RemediationItem] = field(default_factory=list)
    exports: List[ExportArtifact] = field(default_factory=list)
    owner_context: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["target"] = self.target.to_dict()
        payload["findings"] = [item.to_dict() for item in self.findings]
        payload["scores"] = [item.to_dict() for item in self.scores]
        payload["interpretations"] = [item.to_dict() for item in self.interpretations]
        payload["remediation_items"] = [item.to_dict() for item in self.remediation_items]
        payload["exports"] = [item.to_dict() for item in self.exports]
        return payload
