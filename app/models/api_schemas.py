"""Pydantic v2 schemas for Frontend REST API contracts."""

from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class SystemInfoResponse(BaseModel):
    """System metadata and operational mode indication."""
    mode: str = Field(description="Operational mode: LOCAL MODE or REAL SERVICES")
    version: str = Field(description="Pipeline application version")
    environment: str = Field(description="Deployment environment name")
    storage_backend: str = Field(description="Storage adapter: local or minio")
    queue_backend: str = Field(description="Queue adapter: memory or redis")
    search_backend: str = Field(description="Search adapter: memory or opensearch")
    ocr_engine: str = Field(description="Configured OCR engine")
    classifier_version: str = Field(description="Active document classifier model version")
    high_risk_floor: float = Field(default=0.92, description="Immutable threshold floor for high-risk classes")
    low_risk_floor: float = Field(default=0.85, description="Immutable threshold floor for low-risk classes")
    max_upload_mb: int = Field(default=10, description="Maximum upload size in MB")
    allowed_file_types: str = Field(default="image/jpeg,image/png,application/pdf", description="Allowed upload MIME types")
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class UserSessionResponse(BaseModel):
    """Stub user session representing role-gated access."""
    user_id: str
    username: str
    role: str = Field(description="Active role: reviewer, admin, compliance, or viewer")
    permissions: List[str]


class ReviewQueueItem(BaseModel):
    """Item displayed on the human review queue table."""
    task_id: str
    document_uid: str
    file_name: str
    predicted_type: str
    confidence: float
    risk_level: str = Field(description="HIGH or LOW risk tier")
    review_reason: str
    pii_sensitivity: str = Field(description="HIGH, MEDIUM, LOW, or NONE")
    age_seconds: int
    created_at: Optional[datetime] = None
    status: str
    thumbnail_url: Optional[str] = None


class ReviewQueueResponse(BaseModel):
    """Paginated review queue response."""
    items: List[ReviewQueueItem]
    total: int
    page: int
    page_size: int
    total_pages: int


class OCRWordBox(BaseModel):
    """Bounding box coordinates for an OCR detected word or token."""
    text: str
    x0: float
    y0: float
    x1: float
    y1: float
    page_num: int = 1


class ReviewDetailResponse(BaseModel):
    """Full review detail payload with page image, OCR text, and field confidences."""
    document_uid: str
    task_id: str
    file_name: str
    predicted_type: str
    confidence: float
    model_name: str
    model_version: str
    ocr_engine: str
    ocr_version: str
    decision_reason: str
    review_status: str
    assigned_reviewer: Optional[str] = None
    extracted_fields: Dict[str, Any] = Field(default_factory=dict)
    human_verified_fields: Dict[str, Any] = Field(default_factory=dict)
    field_confidences: Dict[str, float] = Field(default_factory=dict)
    pii_entities: List[Dict[str, Any]] = Field(default_factory=list)
    ocr_text: str = ""
    ocr_words: List[OCRWordBox] = Field(default_factory=list)
    page_count: int = 1
    page_image_url: str = ""
    created_at: Optional[datetime] = None


class ReviewActionRequest(BaseModel):
    """Review action payload submitted by reviewer."""
    reviewer_id: str
    action: str = Field(description="CONFIRM, CORRECT, or REJECT")
    corrected_type: Optional[str] = None
    corrected_fields: Optional[Dict[str, Any]] = None
    review_notes: Optional[str] = None


class ReviewActionResponse(BaseModel):
    """Result of human review decision."""
    success: bool
    document_uid: str
    review_status: str
    doc_type: str
    message: str
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class DocumentSummaryItem(BaseModel):
    """Summary item for documents list and search results."""
    uid: str
    file_name: str
    file_size: int
    mime_type: str
    doc_type: str
    confidence: float
    review_status: str
    pii_detected: bool
    pii_types: List[str] = Field(default_factory=list)
    classifier_version: str
    is_link: bool
    linked_to_uid: Optional[str] = None
    quarantine_reason: Optional[str] = None
    created_at: Optional[datetime] = None


class DocumentListResponse(BaseModel):
    """Paginated list of documents with metadata filters."""
    items: List[DocumentSummaryItem]
    total: int
    page: int
    page_size: int
    total_pages: int


class DocumentStatusResponse(BaseModel):
    """Lightweight document status polling payload."""
    uid: str
    file_name: str
    review_status: str
    doc_type: str
    confidence: float
    is_link: bool
    linked_to_uid: Optional[str] = None
    quarantine_reason: Optional[str] = None
    created_at: Optional[datetime] = None


class DocumentComplianceDetailResponse(BaseModel):
    """Detailed compliance view showing AIClassification record, retention rules, and ACL."""
    uid: str
    sha256: str
    file_name: str
    file_size: int
    doc_type: str
    confidence: float
    retention_class: Optional[str] = None
    acl: Optional[str] = None
    decision_rule: Optional[str] = None
    decision_reason: Optional[str] = None
    target_workflow: Optional[str] = None
    review_status: str
    classifier_model: Optional[str] = None
    classifier_version: Optional[str] = None
    ocr_engine: Optional[str] = None
    ocr_version: Optional[str] = None
    pii_detected: bool
    pii_entities: List[Dict[str, Any]] = Field(default_factory=list)
    pii_types: List[str] = Field(default_factory=list)
    extracted_fields: Dict[str, Any] = Field(default_factory=dict)
    human_verified_fields: Dict[str, Any] = Field(default_factory=dict)
    field_confidences: Dict[str, float] = Field(default_factory=dict)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class AuditEventItem(BaseModel):
    """Individual audit event in the document history timeline."""
    event_id: str
    document_uid: str
    event_type: str
    stage_name: Optional[str] = None
    status: str
    payload: Dict[str, Any] = Field(default_factory=dict)
    created_at: Optional[datetime] = None


class AuditTrailResponse(BaseModel):
    """Complete chronological audit trail for a document."""
    document_uid: str
    events: List[AuditEventItem]


class PIIRevealRequest(BaseModel):
    """Audit request to reveal a masked PII entity."""
    entity_type: str
    position: Optional[Dict[str, Any]] = None


class PIIRevealResponse(BaseModel):
    """Audit confirmation of PII reveal."""
    success: bool
    event_id: str
    entity_type: str
    message: str


class ReprocessExecutionRequest(BaseModel):
    """Execution request to reprocess documents matching criteria."""
    query: Optional[str] = None
    target_types: Optional[List[str]] = None
    min_confidence: Optional[float] = None
    classifier_version_filter: Optional[str] = None
    dry_run: bool = False


class ReprocessExecutionResponse(BaseModel):
    """Response from executing a reprocess run."""
    job_id: str
    status: str
    matched_count: int
    reprocessed_count: int
    conflicts_preserved_count: int


class ReprocessSampleItem(BaseModel):
    """Sample document matching reprocess criteria."""
    uid: str
    file_name: str
    current_doc_type: str
    current_confidence: float
    classifier_version: str
    has_human_verified_fields: bool
    human_verified_field_names: List[str] = Field(default_factory=list)


class ReprocessPreviewRequest(BaseModel):
    """Criteria to preview documents targeted for reprocessing."""
    query: Optional[str] = None
    classifier_version_filter: Optional[str] = None
    min_confidence: Optional[float] = None
    target_types: Optional[List[str]] = None


class ReprocessPreviewResponse(BaseModel):
    """Dry-run preview metrics for a proposed reprocess job."""
    matched_count: int
    human_verified_conflict_count: int
    sample_documents: List[ReprocessSampleItem]


class ReprocessJobStatusResponse(BaseModel):
    """Progress status of an active or completed reprocess job."""
    job_id: str
    status: str
    matched_count: int
    processed_count: int
    skipped_count: int
    error_count: int


class StageLatencyMetric(BaseModel):
    """Latency metrics for a specific pipeline stage."""
    stage: str
    count: int
    p50_ms: float
    p95_ms: float


class DashboardMetricsResponse(BaseModel):
    """High-level operational metrics dashboard."""
    has_data: bool
    total_ingested: int
    queue_depth: int
    review_queue_size: int
    stp_rate: Optional[float] = None
    error_rate: Optional[float] = None
    stage_latencies_ms: Dict[str, StageLatencyMetric] = Field(default_factory=dict)
    per_class_counts: Dict[str, int] = Field(default_factory=dict)
    dead_letter_count: int = 0


class ClassThresholdConfig(BaseModel):
    """Configuration and floor constraints for a single document class."""
    class_name: str
    risk: str
    current_threshold: float
    default_threshold: float
    floor_threshold: float
    retention_class: str
    acl: str
    target_workflow: str


class AdminConfigResponse(BaseModel):
    """Current threshold settings, floor limits, and PII sensitivity mapping."""
    classes: Dict[str, ClassThresholdConfig]
    routing_rules: Dict[str, str]
    pii_policy: Dict[str, Any]
    high_risk_floor: float = 0.92
    low_risk_floor: float = 0.85


class AdminConfigUpdateRequest(BaseModel):
    """Proposed updates to class thresholds with floor validation."""
    updated_by: str
    class_thresholds: Dict[str, float]
    pii_policy: Optional[Dict[str, Any]] = None


class AdminConfigUpdateResponse(BaseModel):
    """Result of configuration change application."""
    success: bool
    message: str
    effective_config: AdminConfigResponse


class ConfigHistoryItem(BaseModel):
    """Audit entry recording historical configuration changes."""
    change_id: str
    updated_by: str
    timestamp: datetime
    changes: Dict[str, Any]


class ConfigHistoryResponse(BaseModel):
    """Audit history of configuration adjustments."""
    history: List[ConfigHistoryItem]
