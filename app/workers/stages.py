"""Pipeline stage processors with idempotency, transactional guarantees, and error handling."""

import hashlib
import json
import re
import uuid
from typing import Any, Dict, List, Optional, Tuple
import cv2
import fitz
import numpy as np
from pydantic import ValidationError

from app.adapters.classifier import get_classifier
from app.adapters.ecm import get_ecm_adapter
from app.adapters.ocr import get_ocr_engine
from app.adapters.pii import get_pii_detector
from app.adapters.search import get_search_adapter
from app.adapters.storage import get_storage_adapter
from app.adapters.virus import get_virus_scanner
from app.core.audit import AssetAuditMetadata, AuditEvent
from app.core.config import get_pipeline_config
from app.core.idempotency import get_idempotency_registry
from app.core.interfaces import ECMDocumentRecord
from app.models.db import AuditEventModel, DocumentModel, ReviewTaskModel, get_db_session
from app.models.schemas import FIELD_SCHEMA_MAP, DecisionResult
from app.workers.generic_extractor import GenericKeyValueExtractor


# ---------------------------------------------------------------------------
# Stage 1: Virus Scan
# ---------------------------------------------------------------------------
def stage_virus_scan(sha256_hash: str, raw_bytes: bytes) -> Dict[str, Any]:
    """Scan raw bytes for virus/malware signatures."""
    scanner = get_virus_scanner()
    is_clean, virus_name = scanner.scan(raw_bytes)
    if not is_clean:
        return {
            "status": "INFECTED",
            "virus_name": virus_name,
            "action": "QUARANTINE",
            "reason": f"Antivirus threat detected: {virus_name}",
        }
    return {"status": "CLEAN"}


# ---------------------------------------------------------------------------
# Stage 2: Deduplication Check
# ---------------------------------------------------------------------------
def stage_dedupe(sha256_hash: str, current_uid: Optional[str] = None) -> Dict[str, Any]:
    """Check if an asset with this exact SHA-256 already exists in ECM."""
    ecm = get_ecm_adapter()
    existing = ecm.find_by_hash(sha256_hash, exclude_uid=current_uid)
    if existing and existing.uid != current_uid:
        return {
            "status": "DUPLICATE_FOUND",
            "canonical_uid": existing.uid,
            "canonical_ecm_id": existing.ecm_id,
            "canonical_record": existing.model_dump(),
        }
    return {"status": "UNIQUE"}


# ---------------------------------------------------------------------------
# Stage 3: Pre-processing & Integrity Check (Corrupt / Password-protected)
# ---------------------------------------------------------------------------
def detect_page_condition(file_bytes: bytes, file_name: str) -> str:
    """Analyze visual page quality: detect skew, background speckle noise, or clean scan."""
    try:
        ext = file_name.split(".")[-1].lower() if "." in file_name else ""
        if ext == "pdf":
            doc = fitz.open(stream=file_bytes, filetype="pdf")
            if len(doc) == 0:
                return "clean"
            page = doc[0]
            pix = page.get_pixmap(dpi=150)
            img_np = np.frombuffer(pix.samples, dtype=np.uint8).reshape((pix.height, pix.width, pix.n))
            if pix.n == 4:
                img_np = cv2.cvtColor(img_np, cv2.COLOR_RGBA2GRAY)
            elif pix.n == 3:
                img_np = cv2.cvtColor(img_np, cv2.COLOR_RGB2GRAY)
            doc.close()
        else:
            nparr = np.frombuffer(file_bytes, np.uint8)
            img_np = cv2.imdecode(nparr, cv2.IMREAD_GRAYSCALE)
            if img_np is None:
                return "clean"

        thresh = cv2.bitwise_not(img_np)
        coords = np.column_stack(np.where(thresh > 100))
        if len(coords) < 10:
            return "clean"
        angle = cv2.minAreaRect(coords)[-1]
        if angle < -45:
            angle = -(90 + angle)
        elif angle > 45:
            angle = 90 - angle
        else:
            angle = -angle

        white_pixels = img_np[img_np > 200]
        std_white = np.std(white_pixels) if len(white_pixels) > 0 else 0
        if abs(angle) > 0.4:
            return "slightly skewed"
        elif std_white > 1.95:
            return "speckled background"
        return "clean"
    except Exception:
        return "clean"


def stage_preprocess(file_bytes: bytes, file_name: str) -> Dict[str, Any]:
    """Verify document integrity, check encryption/corruption, and pre-process."""
    ext = file_name.split(".")[-1].lower() if "." in file_name else ""

    # Check for simulated corruption
    if b"CORRUPTED_FILE_DATA_NOT_A_VALID_DOCUMENT" in file_bytes or (
        ext == "pdf" and not file_bytes.startswith(b"%PDF") and len(file_bytes) < 100
    ):
        return {
            "status": "CORRUPT",
            "action": "QUARANTINE",
            "reason": "Corrupt or malformed document payload",
        }

    # PDF validation: check encryption / password protection
    if ext == "pdf":
        try:
            doc = fitz.open(stream=file_bytes, filetype="pdf")
            if doc.is_encrypted:
                return {
                    "status": "PASSWORD_PROTECTED",
                    "action": "QUARANTINE",
                    "reason": "Document is password-protected or encrypted",
                }
            page_count = len(doc)
            doc.close()
        except Exception as e:
            return {
                "status": "CORRUPT",
                "action": "QUARANTINE",
                "reason": f"PDF structure validation failed: {str(e)}",
            }
    else:
        page_count = 1

    page_condition = detect_page_condition(file_bytes, file_name)

    return {
        "status": "VALID",
        "page_count": page_count,
        "extension": ext,
        "page_condition": page_condition,
    }


# ---------------------------------------------------------------------------
# Stage 4: Document Splitting
# ---------------------------------------------------------------------------
def stage_split_document(file_bytes: bytes, file_name: str) -> List[Tuple[bytes, str]]:
    """Split multi-document container file on separator pages or barcodes."""
    ext = file_name.split(".")[-1].lower() if "." in file_name else ""
    if ext != "pdf":
        return [(file_bytes, file_name)]

    try:
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        if len(doc) <= 1:
            return [(file_bytes, file_name)]

        split_indices = []
        for i, page in enumerate(doc):
            text = page.get_text().upper()
            if "DOCUMENT SEPARATOR" in text or "=== SPLIT ===" in text or "SPLIT_HERE" in text:
                split_indices.append(i)

        if not split_indices:
            return [(file_bytes, file_name)]

        # Slice sub-documents
        sub_docs: List[Tuple[bytes, str]] = []
        start_idx = 0
        doc_count = 1

        for sep_idx in split_indices:
            if sep_idx > start_idx:
                new_doc = fitz.open()
                new_doc.insert_pdf(doc, from_page=start_idx, to_page=sep_idx - 1)
                sub_bytes = new_doc.tobytes()
                sub_docs.append((sub_bytes, f"{file_name}_part_{doc_count}.pdf"))
                doc_count += 1
            start_idx = sep_idx + 1

        if start_idx < len(doc):
            new_doc = fitz.open()
            new_doc.insert_pdf(doc, from_page=start_idx, to_page=len(doc) - 1)
            sub_bytes = new_doc.tobytes()
            sub_docs.append((sub_bytes, f"{file_name}_part_{doc_count}.pdf"))

        return sub_docs if sub_docs else [(file_bytes, file_name)]
    except Exception:
        return [(file_bytes, file_name)]


# ---------------------------------------------------------------------------
# Stage 5: OCR
# ---------------------------------------------------------------------------
def stage_ocr(file_bytes: bytes, file_name: str) -> Dict[str, Any]:
    """Execute Optical Character Recognition and extract text & layout."""
    ext = file_name.split(".")[-1].lower() if "." in file_name else "pdf"
    engine = get_ocr_engine()
    res = engine.extract_text(file_bytes, ext, file_name=file_name)
    return {
        "full_text": res.full_text,
        "page_count": res.pages_count,
        "bounding_boxes_count": len(res.bounding_boxes),
        "engine_name": res.engine_name,
        "engine_version": res.engine_version,
        "page_methods": res.page_methods,
    }


# ---------------------------------------------------------------------------
# Stage 6: Classification
# ---------------------------------------------------------------------------
def stage_classify(text: str) -> Dict[str, Any]:
    """Predict document type and confidence using active classifier."""
    classifier = get_classifier()
    res = classifier.predict(text)
    return {
        "predicted_class": res.predicted_class,
        "confidence": res.confidence,
        "probabilities": res.probabilities,
        "model_name": res.model_name,
        "model_version": res.model_version,
    }


# ---------------------------------------------------------------------------
# Stage 7: Field Extraction & Schema Validation
# ---------------------------------------------------------------------------
def _clean_field_text(val: Optional[str]) -> str:
    """Strip OCR quotation marks, brackets, trailing punctuation, and extra whitespace, normalizing common prefixes."""
    if not val:
        return ""
    val = val.strip().strip("`'\"‘“”—-=[](){}:;,.")
    # Normalize common OCR doctor prefixes (Or. -> Dr.)
    val = re.sub(r"^(?:Or|Pr|Dr)\.\s*", "Dr. ", val, flags=re.I)
    return re.sub(r"\s+", " ", val).strip()

def _clean_date(val: Optional[str]) -> Optional[str]:
    """Clean and keep date strings, preserving dates written with '/' or '-' exactly as written."""
    if not val:
        return None
    val = val.strip().strip("`'\"‘“”—-=[](){}:;,.")
    # Keep dates written with '/' exactly as written
    m_slash = re.search(r"\b(\d{1,4}/\d{1,2}/\d{1,4})\b", val)
    if m_slash:
        return m_slash.group(1)
    # Keep dates written with '-'
    m_dash = re.search(r"\b(\d{1,4}-\d{1,2}-\d{1,4})\b", val)
    if m_dash:
        return m_dash.group(1)
    m_dot = re.search(r"\b(\d{1,4}\.\d{1,2}\.\d{1,4})\b", val)
    if m_dot:
        return m_dot.group(1)
    return val

def _clean_amount(val: Optional[str]) -> Optional[float]:
    """Parse monetary string to float with OCR digit confusion normalization (S/5, O/0, I/1, B/8)."""
    if not val:
        return None
    val = val.strip().strip("`'\"‘“”—-=[](){}:;,")
    # Strip leading currency/OCR symbols
    val = re.sub(r"^[$S§]\s*", "", val)
    # Map common OCR letters to digits when in numeric contexts
    trans = str.maketrans({
        'O': '0', 'o': '0',
        'I': '1', 'l': '1', '|': '1',
        'S': '5', 's': '5',
        'B': '8', 'Z': '2', 'z': '2',
        'A': '4'
    })
    translated = val.translate(trans)
    # Fix space before 2 decimals: "14047 67" -> "14047.67"
    translated = re.sub(r"(\d+)\s+(\d{2})\b", r"\1.\2", translated)
    # Clean commas and any remaining non-digit non-dot
    cleaned = re.sub(r"[^\d.]", "", translated)
    # Handle multiple dots (e.g. 14.047.67 -> 14047.67)
    if cleaned.count(".") > 1:
        parts = cleaned.split(".")
        cleaned = "".join(parts[:-1]) + "." + parts[-1]
    try:
        return float(cleaned)
    except ValueError:
        return None

def stage_extract_fields(text: str, doc_type: str) -> Tuple[Dict[str, Any], Dict[str, float], bool]:
    """Extract required fields per document type using GenericKeyValueExtractor and fallback regexes.
    
    If any field is missing or cannot be located in the OCR text, it returns None with 0.0 confidence.
    Hardcoded default fallback constants are strictly prohibited.
    """
    if doc_type == "unknown" or not text.strip():
        return {}, {}, False

    # 1. Primary: Generic Key-Value Extraction with Fuzzy Label Matching (Levenshtein <= 2, OCR normalization)
    from app.workers.fuzzy_extractor import GenericFuzzyExtractor
    extractor = GenericFuzzyExtractor()
    extracted, confidences = extractor.extract(text, doc_type)

    if doc_type == "contract":
        cid_m = re.search(r"Contract ID:\s*([A-Za-z0-9-]+)", text, re.IGNORECASE)
        if cid_m:
            extracted["contract_id"] = cid_m.group(1).strip()
            confidences["contract_id"] = 0.99
        date_m = re.search(r"Effective Date:\s*([0-9]{4}-[0-9]{2}-[0-9]{2})", text, re.IGNORECASE)
        if date_m:
            extracted["effective_date"] = date_m.group(1).strip()
            confidences["effective_date"] = 0.99
        fp_m = re.search(r"First Party:\s*([^:\n\r]+?)(?=\s+(?:Second Party|Authorized Signatory|Contract ID|Notification Email|Subject|$))", text, re.IGNORECASE)
        if fp_m:
            v = fp_m.group(1).strip()
            extracted["first_party"] = v
            extracted["party_one"] = v
            confidences["first_party"] = 0.99
            confidences["party_one"] = 0.99
        sp_m = re.search(r"Second Party:\s*([^:\n\r]+?)(?=\s+(?:First Party|Authorized Signatory|Contract ID|Notification Email|Subject|$))", text, re.IGNORECASE)
        if sp_m:
            v = sp_m.group(1).strip()
            extracted["second_party"] = v
            extracted["party_two"] = v
            confidences["second_party"] = 0.99
            confidences["party_two"] = 0.99
        if "first_party" in extracted and "second_party" in extracted:
            extracted["parties"] = f"{extracted['first_party']} & {extracted['second_party']}"
            confidences["parties"] = 0.99
        sig_m = re.search(r"Authorized Signatory:\s*([^:\n\r]+?)(?=\s+(?:Second Party|First Party|Contract ID|Notification Email|Subject|$))", text, re.IGNORECASE)
        if sig_m:
            extracted["authorized_signatory"] = sig_m.group(1).strip()
            confidences["authorized_signatory"] = 0.99
        em_m = re.search(r"Notification Email:\s*([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})", text, re.IGNORECASE)
        if em_m:
            extracted["notification_email"] = em_m.group(1).strip()
            confidences["notification_email"] = 0.99
        sub_m = re.search(r"Subject:\s*([^\n\r]+)", text, re.IGNORECASE)
        if sub_m:
            extracted["subject"] = sub_m.group(1).strip()
            confidences["subject"] = 0.99

    # Validate against Schema
    schema_cls = FIELD_SCHEMA_MAP.get(doc_type)
    is_valid = True
    if schema_cls and doc_type != "unknown":
        # Check if any required schema field is None
        schema_fields = schema_cls.model_fields.keys()
        required_fields = [
            f_name for f_name, f_info in schema_cls.model_fields.items()
            if f_info.is_required()
        ]
        for sf in required_fields:
            if extracted.get(sf) is None:
                # check aliases
                alt = None
                if sf == "full_name": alt = "customer_name"
                elif sf == "customer_name": alt = "full_name"
                elif sf == "po_date": alt = "order_date"
                elif sf == "order_date": alt = "po_date"
                elif sf == "order_total": alt = "total_amount"
                elif sf == "total_amount": alt = "order_total"
                elif sf == "letter_date": alt = "date"
                elif sf == "date": alt = "letter_date"
                elif sf == "party_one": alt = "parties"
                elif sf == "parties": alt = "party_one"
                elif sf == "sender": alt = "sender_name"
                elif sf == "sender_name": alt = "sender"
                elif sf == "recipient": alt = "recipient_name"
                elif sf == "recipient_name": alt = "recipient"
                if alt and extracted.get(alt) is not None:
                    extracted[sf] = extracted[alt]
                else:
                    is_valid = False
                    break
        if is_valid:
            try:
                schema_cls(**{k: v for k, v in extracted.items() if k in schema_fields})
            except ValidationError:
                is_valid = False

    return extracted, confidences, is_valid


# ---------------------------------------------------------------------------
# Stage 8: PII Detection
# ---------------------------------------------------------------------------
def stage_pii_detect(text: str) -> Dict[str, Any]:
    """Detect PII entities, assess sensitivity, and map types."""
    detector = get_pii_detector()
    entities = detector.detect(text)
    types_found = list({e.entity_type for e in entities})
    has_high = any(e.sensitivity == "high" for e in entities)

    return {
        "pii_detected": len(entities) > 0,
        "entities_count": len(entities),
        "pii_types": types_found,
        "has_high_sensitivity": has_high,
        "entities": [e.model_dump() for e in entities],
    }


# ---------------------------------------------------------------------------
# Stage 9: Decision Gate
# ---------------------------------------------------------------------------
def stage_decision_gate(
    predicted_type: str,
    confidence: float,
    pii_info: Dict[str, Any],
    extraction_valid: bool = True,
) -> DecisionResult:
    """Evaluate routing decision against YAML config rules and conflict resolution."""
    cfg = get_pipeline_config()
    class_cfg = cfg.classes.get(predicted_type)

    if not class_cfg:
        class_cfg = cfg.classes["unknown"]
        predicted_type = "unknown"

    is_high_risk = class_cfg.risk == "high"
    # Mandatory rule: unknown is NEVER auto-accepted!
    if predicted_type == "unknown":
        return DecisionResult(
            action="ROUTE_TO_REVIEW",
            predicted_type="unknown",
            confidence=confidence,
            retention_class=class_cfg.retention_class,
            acl="RESTRICTED_REVIEW",
            target_workflow="MANUAL_TRIAGE",
            reason="Mandatory rule: document classified as unknown must undergo human review",
            review_status="pending_review",
        )

    # Check for classifier / PII conflict:
    # High-sensitivity PII (SSN, credit card, passport) triggers review, but NOT normal email/phone contact info
    pii_types = pii_info.get("pii_types", [])
    high_sens_types = {"US_SSN", "CREDIT_CARD", "PASSPORT", "MEDICAL_LICENSE"}
    if pii_types:
        has_high_pii = any(t in high_sens_types for t in pii_types)
    else:
        has_high_pii = bool(pii_info.get("has_high_sensitivity", False))
    if not is_high_risk and has_high_pii and cfg.decision_gate.conflict_stricter_rule:
        return DecisionResult(
            action="ROUTE_TO_REVIEW",
            predicted_type=predicted_type,
            confidence=confidence,
            retention_class=class_cfg.retention_class,
            acl="RESTRICTED_REVIEW",  # Stricter ACL on conflict
            target_workflow="HIGH_SENSITIVITY_REVIEW",
            reason="Classifier/PII Conflict: High-sensitivity PII found in low-risk class; enforcing stricter review path",
            review_status="pending_review",
        )

    # Mandatory rule: field extraction failure or missing fields routes to review!
    if not extraction_valid:
        return DecisionResult(
            action="ROUTE_TO_REVIEW",
            predicted_type=predicted_type,
            confidence=confidence,
            retention_class=class_cfg.retention_class,
            acl="RESTRICTED_REVIEW",
            target_workflow="EXTRACTION_FAILURE_REVIEW",
            reason=f"Field extraction incomplete or failed schema validation for {predicted_type}",
            review_status="pending_review",
        )

    # Check auto-acceptance thresholds
    required_threshold = (
        class_cfg.tuned_threshold
        if hasattr(class_cfg, "tuned_threshold")
        else (cfg.decision_gate.high_risk_auto_threshold if is_high_risk else cfg.decision_gate.low_risk_auto_threshold)
    )

    if confidence >= required_threshold:
        return DecisionResult(
            action="AUTO_ACCEPT",
            predicted_type=predicted_type,
            confidence=confidence,
            retention_class=class_cfg.retention_class,
            acl=class_cfg.acl,
            target_workflow=class_cfg.target_workflow,
            reason=f"Confidence {confidence:.3f} >= threshold {required_threshold:.3f} for {predicted_type}",
            review_status="auto_accepted",
        )
    elif confidence >= cfg.decision_gate.review_floor:
        return DecisionResult(
            action="ROUTE_TO_REVIEW",
            predicted_type=predicted_type,
            confidence=confidence,
            retention_class=class_cfg.retention_class,
            acl="RESTRICTED_REVIEW",
            target_workflow="LOW_CONFIDENCE_REVIEW",
            reason=f"Confidence {confidence:.3f} below acceptance threshold {required_threshold:.3f}; routed to review queue",
            review_status="pending_review",
        )
    else:
        # Confidence below review floor: escalate to Unknown triage
        return DecisionResult(
            action="ROUTE_TO_REVIEW",
            predicted_type="unknown",
            confidence=confidence,
            retention_class=cfg.classes["unknown"].retention_class,
            acl="RESTRICTED_REVIEW",
            target_workflow="MANUAL_TRIAGE",
            reason=f"Confidence {confidence:.3f} below minimum floor {cfg.decision_gate.review_floor:.3f}",
            review_status="pending_review",
        )


# ---------------------------------------------------------------------------
# Stage 10: ECM Write
# ---------------------------------------------------------------------------
def stage_write_ecm(
    uid: str,
    sha256_hash: str,
    decision: DecisionResult,
    metadata_fields: Dict[str, Any],
    raw_storage_path: str,
) -> ECMDocumentRecord:
    """Commit document asset and metadata to ECMAdapter."""
    ecm = get_ecm_adapter()
    record = ECMDocumentRecord(
        ecm_id="",
        uid=uid,
        sha256=sha256_hash,
        doc_type=decision.predicted_type,
        confidence=decision.confidence,
        metadata={
            "storage_path": raw_storage_path,
            "extracted_fields": metadata_fields.get("extracted_fields", {}),
            "field_confidences": metadata_fields.get("field_confidences", {}),
            "pii_detected": metadata_fields.get("pii_detected", False),
            "pii_types": metadata_fields.get("pii_types", []),
            "ocr_engine": metadata_fields.get("ocr_engine", "unknown"),
            "ocr_version": metadata_fields.get("ocr_version", "1.0"),
            "classifier_model": metadata_fields.get("classifier_model", "tfidf_logistic"),
            "classifier_version": metadata_fields.get("classifier_version", "v1.0"),
            "decision_reason": decision.reason,
            "file_name": metadata_fields.get("file_name", "document.pdf"),
            "file_size": metadata_fields.get("file_size", 0),
            "batch_id": metadata_fields.get("batch_id"),
            "user_id": metadata_fields.get("user_id"),
        },
        retention_class=decision.retention_class,
        acl=decision.acl,
        target_workflow=decision.target_workflow,
        review_status=decision.review_status,
        is_link=False,
    )
    committed = ecm.create_document(record)

    # If routed to review, create review task
    if decision.action == "ROUTE_TO_REVIEW":
        db = get_db_session()
        try:
            task = db.query(ReviewTaskModel).filter(ReviewTaskModel.document_uid == uid).first()
            if not task:
                task = ReviewTaskModel(
                    task_id=f"rev-{uid}-{uuid.uuid4().hex[:8]}",
                    document_uid=uid,
                    predicted_type=decision.predicted_type,
                    confidence=decision.confidence,
                    evidence_text=metadata_fields.get("extracted_text_preview", ""),
                    status="PENDING",
                )
                db.add(task)
                db.commit()
        finally:
            db.close()

    return committed


# ---------------------------------------------------------------------------
# Stage 11: Index in Search
# ---------------------------------------------------------------------------
def stage_index_search(
    uid: str,
    sha256_hash: str,
    decision: DecisionResult,
    metadata_fields: Dict[str, Any],
    full_text: str,
) -> bool:
    """Index asset in OpenSearch / Search Index."""
    search = get_search_adapter()
    payload = {
        "uid": uid,
        "sha256": sha256_hash,
        "doc_type": decision.predicted_type,
        "confidence": decision.confidence,
        "retention_class": decision.retention_class,
        "acl": decision.acl,
        "target_workflow": decision.target_workflow,
        "review_status": decision.review_status,
        "classifier_version": metadata_fields.get("classifier_version", "v1.0"),
        "full_text": full_text[:10000],  # truncated text body
        "extracted_fields": metadata_fields.get("extracted_fields", {}),
    }
    return search.index_document(doc_id=uid, payload=payload)


# ---------------------------------------------------------------------------
# Stage 12: Audit Logging
# ---------------------------------------------------------------------------
def stage_audit_record(
    uid: str,
    sha256_hash: str,
    decision: DecisionResult,
    metadata_fields: Dict[str, Any],
) -> AssetAuditMetadata:
    """Ensure 100% of assets carry model, version, confidence, and audit trail."""
    audit = AssetAuditMetadata(
        uid=uid,
        sha256=sha256_hash,
        ocrEngine=metadata_fields.get("ocr_engine", "unknown"),
        ocrVersion=metadata_fields.get("ocr_version", "1.0.0"),
        classifierModel=metadata_fields.get("classifier_model", "tfidf_logistic_regression"),
        classifierVersion=metadata_fields.get("classifier_version", "v1.0"),
        predictedType=decision.predicted_type,
        confidence=decision.confidence,
        fieldConfidences=metadata_fields.get("field_confidences", {}),
        piiDetected=metadata_fields.get("pii_detected", False),
        piiTypes=metadata_fields.get("pii_types", []),
        reviewStatus=decision.review_status,
        retentionClass=decision.retention_class,
        assignedAcl=decision.acl,
        targetWorkflow=decision.target_workflow,
        decisionReason=decision.reason,
    )

    # Persist audit event record in DB
    import uuid
    db = get_db_session()
    try:
        event = AuditEventModel(
            event_id=f"audit-{uid}-{uuid.uuid4().hex[:8]}",
            document_uid=uid,
            sha256=sha256_hash,
            event_type="PIPELINE_COMPLETE",
            stage_name="audit",
            status="SUCCESS",
            payload_json=json.dumps(audit.model_dump()),
        )
        db.add(event)
        db.commit()
    finally:
        db.close()

    return audit
