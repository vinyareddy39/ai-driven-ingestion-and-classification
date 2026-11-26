"""Audit trail management ensuring 100% of assets carry model and compliance metadata."""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class AssetAuditMetadata(BaseModel):
    """Mandatory audit attributes persisted on 100% of ECM assets."""
    uid: str
    sha256: str
    ocrEngine: str
    ocrVersion: str
    classifierModel: str
    classifierVersion: str
    predictedType: str
    confidence: float
    fieldConfidences: Dict[str, float] = Field(default_factory=dict)
    piiDetected: bool = False
    piiTypes: List[str] = Field(default_factory=list)
    reviewStatus: str = "pending"  # auto_accepted, pending_review, human_verified, rejected, quarantined
    processedAt: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    humanVerifiedFields: Dict[str, Any] = Field(default_factory=dict)
    retentionClass: str = ""
    assignedAcl: str = ""
    targetWorkflow: str = ""
    decisionReason: str = ""
    reviewerId: Optional[str] = None
    reviewNotes: Optional[str] = None

    def validate_audit_completeness(self) -> bool:
        """Validate that all mandatory audit fields are populated."""
        required = [
            self.uid,
            self.sha256,
            self.ocrEngine,
            self.ocrVersion,
            self.classifierModel,
            self.classifierVersion,
            self.predictedType,
            self.reviewStatus,
            self.processedAt,
        ]
        return all(r is not None and str(r).strip() != "" for r in required)


class AuditEvent(BaseModel):
    """Event representing a state change or lifecycle action on a document."""
    event_id: str
    document_uid: str
    sha256: str
    event_type: str  # INGEST, STAGE_COMPLETE, DECISION_GATE, REVIEW_CONFIRM, REPROCESS, QUARANTINE
    stage_name: Optional[str] = None
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    payload: Dict[str, Any] = Field(default_factory=dict)
    status: str = "SUCCESS"  # SUCCESS, FAILURE, SKIPPED, RETRY
