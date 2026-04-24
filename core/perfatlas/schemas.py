"""Structured schemas for the PerfAtlas audit module."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class PerfAtlasTarget:
    raw: str
    normalized_url: str
    host: str
    mode: str = "public"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class PerfPageSnapshot:
    url: str
    final_url: str
    status_code: int
    content_type: str
    title: str = ""
    html_lang: str = ""
    template_signature: str = ""
    content_length: int = 0
    transfer_size_bytes: int = 0
    html_bytes: int = 0
    ttfb_ms: float = 0.0
    request_duration_ms: float = 0.0
    script_count: int = 0
    stylesheet_count: int = 0
    image_count: int = 0
    lazy_image_count: int = 0
    preload_count: int = 0
    preconnect_count: int = 0
    font_host_count: int = 0
    third_party_host_count: int = 0
    render_blocking_hints: List[str] = field(default_factory=list)
    resource_hints: Dict[str, int] = field(default_factory=dict)
    redirected: bool = False
    redirect_count: int = 0
    headers: Dict[str, str] = field(default_factory=dict)
    internal_links: List[str] = field(default_factory=list)
    external_hosts: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)
    system_url: bool = False
    crawl_depth: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class LabRunSnapshot:
    url: str
    runner: str
    strategy: str
    runs_attempted: int
    runs_completed: int
    score: Optional[float] = None
    first_contentful_paint_ms: Optional[float] = None
    largest_contentful_paint_ms: Optional[float] = None
    cumulative_layout_shift: Optional[float] = None
    total_blocking_time_ms: Optional[float] = None
    speed_index_ms: Optional[float] = None
    interactive_ms: Optional[float] = None
    server_response_time_ms: Optional[float] = None
    total_byte_weight: Optional[int] = None
    request_count: Optional[int] = None
    diagnostics: Dict[str, Any] = field(default_factory=dict)
    opportunities: List[Dict[str, Any]] = field(default_factory=list)
    note: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class FieldMetricsSnapshot:
    scope: str
    source: str
    form_factor: str
    lcp_ms: Optional[float] = None
    inp_ms: Optional[float] = None
    cls: Optional[float] = None
    fcp_ms: Optional[float] = None
    ttfb_ms: Optional[float] = None
    collection_period: Dict[str, Any] = field(default_factory=dict)
    note: str = ""
    history: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class PerformanceFinding:
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
    validation_state: str = "confirmed"
    evidence_mode: str = "measured"
    relationship_summary: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class PerformanceScoreBreakdown:
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
class PerfRemediationItem:
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

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class PerfInterpretationRun:
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
class PerfExportArtifact:
    format: str
    created_at: str
    label: str
    path: str = ""
    size_bytes: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        return {key: value for key, value in payload.items() if value not in (None, "", [], {})}


@dataclass
class PerfAtlasAuditRun:
    id: str
    target: PerfAtlasTarget
    title: str
    status: str
    created_at: str
    updated_at: str
    options: Dict[str, Any] = field(default_factory=dict)
    summary: Dict[str, Any] = field(default_factory=dict)
    snapshot: Dict[str, Any] = field(default_factory=dict)
    findings: List[PerformanceFinding] = field(default_factory=list)
    scores: List[PerformanceScoreBreakdown] = field(default_factory=list)
    interpretations: List[PerfInterpretationRun] = field(default_factory=list)
    remediation_items: List[PerfRemediationItem] = field(default_factory=list)
    exports: List[PerfExportArtifact] = field(default_factory=list)
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
