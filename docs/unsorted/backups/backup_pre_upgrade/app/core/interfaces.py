"""Core interfaces defining contracts for all external dependencies.

Every external service (OCR, Classifier, PII Detector, ECM Adapter,
Storage, Queue, Search, Virus Scanner) implements one of these interfaces.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Tuple
from pydantic import BaseModel, Field


class BoundingBox(BaseModel):
    """Bounding box coordinates for recognized text token."""
    text: str
    x0: float
    y0: float
    x1: float
    y1: float
    page: int
    confidence: float = 1.0


class OCRResult(BaseModel):
    """Standardized result from an OCR engine."""
    full_text: str
    pages_count: int
    bounding_boxes: List[BoundingBox] = Field(default_factory=list)
    searchable_pdf_bytes: Optional[bytes] = None
    engine_name: str
    engine_version: str
    page_methods: List[str] = Field(default_factory=list)


class PIIEntity(BaseModel):
    """Detected PII entity with type, text, score, and position."""
    entity_type: str
    text: str
    start: int
    end: int
    score: float
    sensitivity: str = "medium"  # low, medium, high


class ClassificationResult(BaseModel):
    """Classification prediction with confidence and per-class distribution."""
    predicted_class: str
    confidence: float
    probabilities: Dict[str, float] = Field(default_factory=dict)
    model_name: str
    model_version: str


class ECMDocumentRecord(BaseModel):
    """ECM Document metadata record."""
    ecm_id: str
    uid: str
    sha256: str
    doc_type: str
    confidence: float
    metadata: Dict[str, Any] = Field(default_factory=dict)
    retention_class: str
    acl: str
    target_workflow: str
    review_status: str
    is_link: bool = False
    linked_to_id: Optional[str] = None
    human_verified_fields: Dict[str, Any] = Field(default_factory=dict)


class Storage(ABC):
    """Abstract interface for raw asset storage (S3 / MinIO / Local)."""

    @abstractmethod
    def save(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
        """Store bytes under key and return storage path / URI."""
        pass

    def save_file(self, key: str, file_path: str, content_type: str = "application/octet-stream") -> str:
        """Store a file from filesystem under key without loading into memory."""
        with open(file_path, "rb") as f:
            return self.save(key, f.read(), content_type=content_type)

    @abstractmethod
    def get(self, key: str) -> bytes:
        """Retrieve bytes stored under key."""
        pass

    @abstractmethod
    def exists(self, key: str) -> bool:
        """Check if asset exists in storage."""
        pass

    @abstractmethod
    def delete(self, key: str) -> bool:
        """Delete asset stored under key."""
        pass


class Queue(ABC):
    """Abstract interface for message queue / streaming operations."""

    @abstractmethod
    def push(self, queue_name: str, message: Dict[str, Any]) -> str:
        """Push a message to the specified queue/stream."""
        pass

    @abstractmethod
    def pop(self, queue_name: str, consumer_group: str = "default", timeout_ms: int = 1000) -> Optional[Tuple[str, Dict[str, Any]]]:
        """Pop a message from queue, returning (message_id, payload)."""
        pass

    @abstractmethod
    def ack(self, queue_name: str, consumer_group: str, message_id: str) -> bool:
        """Acknowledge completed processing of a message."""
        pass

    @abstractmethod
    def length(self, queue_name: str) -> int:
        """Return the current depth of the queue."""
        pass


class OCREngine(ABC):
    """Abstract interface for Optical Character Recognition engines."""

    @abstractmethod
    def extract_text(self, file_bytes: bytes, file_type: str) -> OCRResult:
        """Extract plain text, page count, and tokens."""
        pass

    @abstractmethod
    def extract_bounding_boxes(self, file_bytes: bytes, file_type: str) -> List[BoundingBox]:
        """Extract token-level bounding boxes."""
        pass

    @abstractmethod
    def generate_searchable_pdf(self, file_bytes: bytes, file_type: str) -> bytes:
        """Render a searchable PDF containing OCR text layer."""
        pass


class Classifier(ABC):
    """Abstract interface for document type classification."""

    @abstractmethod
    def predict(self, text: str) -> ClassificationResult:
        """Predict document type and confidence from text content."""
        pass

    @abstractmethod
    def predict_proba(self, text: str) -> Dict[str, float]:
        """Return probability distribution over all supported classes."""
        pass

    @abstractmethod
    def get_model_info(self) -> Dict[str, str]:
        """Return model metadata (name, version, training date, parameters)."""
        pass


class PIIDetector(ABC):
    """Abstract interface for PII detection and redaction."""

    @abstractmethod
    def detect(self, text: str) -> List[PIIEntity]:
        """Analyze text and return detected PII entities."""
        pass

    @abstractmethod
    def mask(self, text: str, entities: Optional[List[PIIEntity]] = None) -> str:
        """Mask detected PII entities within text for audit and logging."""
        pass


class ECMAdapter(ABC):
    """Abstract interface for Enterprise Content Management platforms."""

    @abstractmethod
    def create_document(self, record: ECMDocumentRecord) -> ECMDocumentRecord:
        """Create a new document asset with metadata, retention, and ACL."""
        pass

    @abstractmethod
    def create_link(
        self,
        source_sha256: str,
        target_record: ECMDocumentRecord,
        batch_id: Optional[str] = None,
        source_uid: Optional[str] = None,
    ) -> ECMDocumentRecord:
        """Create a lightweight deduplicated reference linking to an existing asset."""
        pass

    @abstractmethod
    def update_metadata(self, ecm_id: str, metadata: Dict[str, Any], human_verified: bool = False) -> ECMDocumentRecord:
        """Update metadata on an existing ECM document."""
        pass

    @abstractmethod
    def get_document(self, ecm_id: str) -> Optional[ECMDocumentRecord]:
        """Retrieve document record by ECM ID."""
        pass

    @abstractmethod
    def find_by_hash(self, sha256: str, exclude_uid: Optional[str] = None) -> Optional[ECMDocumentRecord]:
        """Find existing document asset by raw file SHA-256 hash."""
        pass


class SearchIndex(ABC):
    """Abstract interface for full-text search indexing (OpenSearch / Memory)."""

    @abstractmethod
    def index_document(self, doc_id: str, payload: Dict[str, Any]) -> bool:
        """Index or update a document in the search cluster."""
        pass

    @abstractmethod
    def search(self, query: Dict[str, Any], limit: int = 50) -> List[Dict[str, Any]]:
        """Execute a search query and return matching documents."""
        pass

    @abstractmethod
    def delete(self, doc_id: str) -> bool:
        """Remove a document from the search index."""
        pass


class VirusScanner(ABC):
    """Abstract interface for antivirus scanning (ClamAV / Mock)."""

    @abstractmethod
    def scan(self, data: bytes) -> Tuple[bool, Optional[str]]:
        """Scan raw bytes for virus/malware signatures. Returns (is_clean, virus_name)."""
        pass
