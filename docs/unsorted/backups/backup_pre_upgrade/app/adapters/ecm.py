"""ECM Adapters implementing ECMAdapter interface (FakeECM and Nuxeo REST Adapter)."""

import json
from typing import Any, Dict, List, Optional
import httpx
from app.core.interfaces import ECMAdapter, ECMDocumentRecord
from app.models.db import DocumentModel, get_db_session


class DatabaseECMAdapter(ECMAdapter):
    """Postgres / SQLite backed ECM adapter implementing full document lifecycle."""

    def create_document(self, record: ECMDocumentRecord) -> ECMDocumentRecord:
        db = get_db_session()
        try:
            doc = db.query(DocumentModel).filter(DocumentModel.uid == record.uid).first()
            if not doc:
                doc = DocumentModel(
                    uid=record.uid,
                    sha256=record.sha256,
                    file_name=record.metadata.get("file_name", "document.pdf"),
                    file_size=record.metadata.get("file_size", 0),
                    mime_type=record.metadata.get("mime_type", "application/pdf"),
                    storage_path=record.metadata.get("storage_path", ""),
                    doc_type=record.doc_type,
                    confidence=record.confidence,
                    retention_class=record.retention_class,
                    acl=record.acl,
                    target_workflow=record.target_workflow,
                    review_status=record.review_status,
                    is_link=record.is_link,
                    linked_to_uid=record.linked_to_id,
                    batch_id=record.metadata.get("batch_id"),
                    extracted_fields_json=json.dumps(record.metadata.get("extracted_fields", {})),
                    human_verified_fields_json=json.dumps(record.human_verified_fields),
                    field_confidences_json=json.dumps(record.metadata.get("field_confidences", {})),
                    pii_detected=record.metadata.get("pii_detected", False),
                    pii_types_json=json.dumps(record.metadata.get("pii_types", [])),
                    ocr_engine=record.metadata.get("ocr_engine", "unknown"),
                    ocr_version=record.metadata.get("ocr_version", "1.0"),
                    classifier_model=record.metadata.get("classifier_model", "tfidf_logistic"),
                    classifier_version=record.metadata.get("classifier_version", "v1.0"),
                    decision_reason=record.metadata.get("decision_reason", ""),
                )
                db.add(doc)
            else:
                doc.doc_type = record.doc_type
                doc.confidence = record.confidence
                doc.retention_class = record.retention_class
                doc.acl = record.acl
                doc.target_workflow = record.target_workflow
                doc.review_status = record.review_status
                doc.decision_reason = record.metadata.get("decision_reason", "")
                if record.metadata.get("batch_id"):
                    doc.batch_id = record.metadata.get("batch_id")
                if record.metadata.get("user_id"):
                    doc.user_id = record.metadata.get("user_id")
                if record.metadata.get("extracted_fields"):
                    doc.extracted_fields_json = json.dumps(record.metadata.get("extracted_fields", {}))
                if record.metadata.get("field_confidences"):
                    doc.field_confidences_json = json.dumps(record.metadata.get("field_confidences", {}))
                if record.metadata.get("pii_detected") is not None:
                    doc.pii_detected = record.metadata.get("pii_detected")
                if record.metadata.get("pii_types"):
                    doc.pii_types_json = json.dumps(record.metadata.get("pii_types", []))
                if record.metadata.get("ocr_engine"):
                    doc.ocr_engine = record.metadata.get("ocr_engine")
                if record.metadata.get("ocr_version"):
                    doc.ocr_version = record.metadata.get("ocr_version")
                if record.metadata.get("classifier_model"):
                    doc.classifier_model = record.metadata.get("classifier_model")
                if record.metadata.get("classifier_version"):
                    doc.classifier_version = record.metadata.get("classifier_version")
            db.commit()
            record.ecm_id = str(doc.id)
            return record
        finally:
            db.close()

    def create_link(
        self,
        source_sha256: str,
        target_record: ECMDocumentRecord,
        batch_id: Optional[str] = None,
        source_uid: Optional[str] = None,
    ) -> ECMDocumentRecord:
        """Create lightweight link reference instead of copying duplicate asset."""
        import uuid
        db = get_db_session()
        try:
            link_uid = source_uid or f"link-{uuid.uuid4().hex[:12]}"
            target_uid = target_record.uid if hasattr(target_record, "uid") else target_record.get("uid", "")
            target_meta = target_record.metadata if hasattr(target_record, "metadata") else target_record.get("metadata", {})
            target_type = target_record.doc_type if hasattr(target_record, "doc_type") else target_record.get("doc_type", "unknown")
            target_conf = target_record.confidence if hasattr(target_record, "confidence") else target_record.get("confidence", 0.9)
            target_ret = target_record.retention_class if hasattr(target_record, "retention_class") else target_record.get("retention_class", "")
            target_acl = target_record.acl if hasattr(target_record, "acl") else target_record.get("acl", "CONFIDENTIAL_FINANCE")

            link_record = ECMDocumentRecord(
                ecm_id="",
                uid=link_uid,
                sha256=source_sha256,
                doc_type=target_type,
                confidence=target_conf,
                metadata={
                    "file_name": target_meta.get("file_name", "link.pdf"),
                    "link_created": True,
                    "target_uid": target_uid,
                    "batch_id": batch_id,
                },
                retention_class=target_ret,
                acl=target_acl,
                target_workflow="DEDUPE_LINK_REFERENCE",
                review_status="auto_accepted",
                is_link=True,
                linked_to_id=target_uid,
            )

            existing_doc = db.query(DocumentModel).filter(DocumentModel.uid == link_uid).first()
            canonical_doc = db.query(DocumentModel).filter(DocumentModel.uid == target_uid).first()
            
            c_fields = canonical_doc.extracted_fields_json if canonical_doc else "{}"
            c_confs = canonical_doc.field_confidences_json if canonical_doc else "{}"
            c_verified = canonical_doc.human_verified_fields_json if canonical_doc else "{}"
            c_ocr_eng = canonical_doc.ocr_engine if canonical_doc else "unknown"
            c_ocr_ver = canonical_doc.ocr_version if canonical_doc else "1.0"
            c_cls_mod = canonical_doc.classifier_model if canonical_doc else "unknown"
            c_cls_ver = canonical_doc.classifier_version if canonical_doc else "v1.0"
            c_pii = canonical_doc.pii_detected if canonical_doc else False
            c_pii_types = canonical_doc.pii_types_json if canonical_doc else "[]"

            if existing_doc:
                existing_doc.doc_type = target_type
                existing_doc.confidence = target_conf
                existing_doc.retention_class = target_ret
                existing_doc.acl = target_acl
                existing_doc.target_workflow = "DEDUPE_LINK_REFERENCE"
                existing_doc.review_status = "auto_accepted"
                existing_doc.is_link = True
                existing_doc.linked_to_uid = target_uid
                existing_doc.extracted_fields_json = c_fields
                existing_doc.field_confidences_json = c_confs
                existing_doc.human_verified_fields_json = c_verified
                existing_doc.ocr_engine = c_ocr_eng
                existing_doc.ocr_version = c_ocr_ver
                existing_doc.classifier_model = c_cls_mod
                existing_doc.classifier_version = c_cls_ver
                existing_doc.pii_detected = c_pii
                existing_doc.pii_types_json = c_pii_types
                existing_doc.decision_reason = f"Deduplicated reference to canonical asset {target_uid}"
                if batch_id:
                    existing_doc.batch_id = batch_id
                db.commit()
                link_record.ecm_id = str(existing_doc.id)
                return link_record

            link_doc = DocumentModel(
                uid=link_uid,
                sha256=source_sha256,
                file_name=link_record.metadata.get("file_name", "link.pdf"),
                storage_path=target_meta.get("storage_path", ""),
                doc_type=target_type,
                confidence=target_conf,
                retention_class=target_ret,
                acl=target_acl,
                target_workflow="DEDUPE_LINK_REFERENCE",
                review_status="auto_accepted",
                is_link=True,
                linked_to_uid=target_uid,
                extracted_fields_json=c_fields,
                field_confidences_json=c_confs,
                human_verified_fields_json=c_verified,
                ocr_engine=c_ocr_eng,
                ocr_version=c_ocr_ver,
                classifier_model=c_cls_mod,
                classifier_version=c_cls_ver,
                pii_detected=c_pii,
                pii_types_json=c_pii_types,
                batch_id=batch_id,
                decision_reason=f"Deduplicated reference to canonical asset {target_uid}",
            )
            db.add(link_doc)
            db.commit()
            link_record.ecm_id = str(link_doc.id)
            return link_record
        finally:
            db.close()

    def update_metadata(self, ecm_id: str, metadata: Dict[str, Any], human_verified: bool = False) -> ECMDocumentRecord:
        db = get_db_session()
        try:
            if str(ecm_id).isdigit():
                doc = db.query(DocumentModel).filter((DocumentModel.id == int(ecm_id)) | (DocumentModel.uid == str(ecm_id))).first()
            else:
                doc = db.query(DocumentModel).filter(DocumentModel.uid == str(ecm_id)).first()
            if not doc:
                raise ValueError(f"Document {ecm_id} not found in FakeECM")

            if human_verified:
                existing = json.loads(doc.human_verified_fields_json or "{}")
                existing.update(metadata)
                doc.human_verified_fields_json = json.dumps(existing)
                doc.review_status = "human_verified"
            else:
                existing_extracted = json.loads(doc.extracted_fields_json or "{}")
                existing_extracted.update(metadata)
                doc.extracted_fields_json = json.dumps(existing_extracted)

            db.commit()
            return self.get_document(str(doc.id))
        finally:
            db.close()

    def get_document(self, ecm_id: str) -> Optional[ECMDocumentRecord]:
        db = get_db_session()
        try:
            if str(ecm_id).isdigit():
                doc = db.query(DocumentModel).filter((DocumentModel.id == int(ecm_id)) | (DocumentModel.uid == str(ecm_id))).first()
            else:
                doc = db.query(DocumentModel).filter(DocumentModel.uid == str(ecm_id)).first()
            if not doc:
                return None
            return ECMDocumentRecord(
                ecm_id=str(doc.id),
                uid=doc.uid,
                sha256=doc.sha256,
                doc_type=doc.doc_type,
                confidence=doc.confidence,
                metadata={
                    "file_name": doc.file_name,
                    "storage_path": doc.storage_path,
                    "extracted_fields": json.loads(doc.extracted_fields_json or "{}"),
                    "pii_detected": doc.pii_detected,
                    "pii_types": json.loads(doc.pii_types_json or "[]"),
                    "ocr_engine": doc.ocr_engine,
                    "ocr_version": doc.ocr_version,
                    "classifier_model": doc.classifier_model,
                    "classifier_version": doc.classifier_version,
                    "decision_reason": doc.decision_reason,
                },
                retention_class=doc.retention_class,
                acl=doc.acl,
                target_workflow=doc.target_workflow,
                review_status=doc.review_status,
                is_link=doc.is_link,
                linked_to_id=doc.linked_to_uid,
                human_verified_fields=json.loads(doc.human_verified_fields_json or "{}"),
            )
        finally:
            db.close()

    def find_by_hash(self, sha256: str, exclude_uid: Optional[str] = None) -> Optional[ECMDocumentRecord]:
        db = get_db_session()
        try:
            q = db.query(DocumentModel).filter(
                DocumentModel.sha256 == sha256,
                DocumentModel.is_link == False,
                DocumentModel.review_status.in_(["auto_accepted", "approved", "pending_review", "human_verified"]),
            )
            if exclude_uid:
                q = q.filter(DocumentModel.uid != exclude_uid)
            doc = q.first()
            if not doc:
                return None
            return self.get_document(str(doc.id))
        finally:
            db.close()


class NuxeoAdapter(ECMAdapter):
    """Nuxeo REST API Adapter implementing the ECM contract with stubbed & live modes."""

    def __init__(self, base_url: str = "http://localhost:8080/nuxeo/site/api/v1", username: str = "Administrator", password: str = "Administrator", stub_mode: bool = True):
        self.base_url = base_url.rstrip("/")
        self.auth = (username, password)
        self.stub_mode = stub_mode
        self._stub_store: Dict[str, ECMDocumentRecord] = {}
        self._hash_index: Dict[str, str] = {}

    def create_document(self, record: ECMDocumentRecord) -> ECMDocumentRecord:
        if self.stub_mode:
            record.ecm_id = f"nuxeo-{record.uid[:12]}"
            self._stub_store[record.ecm_id] = record
            if not record.is_link:
                self._hash_index[record.sha256] = record.ecm_id
            return record

        payload = {
            "entity-type": "document",
            "type": "File",
            "name": record.uid,
            "properties": {
                "dc:title": record.metadata.get("file_name", "document.pdf"),
                "dc:description": f"Classified: {record.doc_type} (conf: {record.confidence})",
                "ecm:retentionClass": record.retention_class,
                "ecm:acl": record.acl,
                "ecm:targetWorkflow": record.target_workflow,
                "ecm:sha256": record.sha256,
            },
        }
        with httpx.Client(auth=self.auth, timeout=10.0) as client:
            resp = client.post(f"{self.base_url}/path/default-domain/workspaces", json=payload)
            if resp.status_code in [200, 201]:
                data = resp.json()
                record.ecm_id = data.get("uid", record.uid)
                return record
            else:
                # Fallback to stub record if Nuxeo server isn't reachable
                record.ecm_id = f"nuxeo-{record.uid[:12]}"
                return record

    def create_link(self, source_sha256: str, target_record: ECMDocumentRecord) -> ECMDocumentRecord:
        link_record = ECMDocumentRecord(
            ecm_id=f"nuxeo-link-{target_record.uid[:8]}",
            uid=f"link-{target_record.uid}",
            sha256=source_sha256,
            doc_type=target_record.doc_type,
            confidence=target_record.confidence,
            retention_class=target_record.retention_class,
            acl=target_record.acl,
            target_workflow="DEDUPE_LINK_REFERENCE",
            review_status="auto_accepted",
            is_link=True,
            linked_to_id=target_record.uid,
            metadata={"is_proxy_link": True, "target_uid": target_record.uid},
        )
        if self.stub_mode:
            self._stub_store[link_record.ecm_id] = link_record
            return link_record
        return link_record

    def update_metadata(self, ecm_id: str, metadata: Dict[str, Any], human_verified: bool = False) -> ECMDocumentRecord:
        if self.stub_mode:
            doc = self._stub_store.get(ecm_id)
            if not doc:
                raise ValueError(f"Document {ecm_id} not found in Nuxeo stub")
            if human_verified:
                doc.human_verified_fields.update(metadata)
                doc.review_status = "human_verified"
            else:
                doc.metadata.update(metadata)
            return doc

        payload = {"properties": metadata}
        with httpx.Client(auth=self.auth, timeout=10.0) as client:
            resp = client.put(f"{self.base_url}/id/{ecm_id}", json=payload)
            return self.get_document(ecm_id)

    def get_document(self, ecm_id: str) -> Optional[ECMDocumentRecord]:
        if self.stub_mode:
            return self._stub_store.get(ecm_id)
        with httpx.Client(auth=self.auth, timeout=10.0) as client:
            resp = client.get(f"{self.base_url}/id/{ecm_id}")
            if resp.status_code == 200:
                data = resp.json()
                props = data.get("properties", {})
                return ECMDocumentRecord(
                    ecm_id=data.get("uid"),
                    uid=props.get("dc:title", ecm_id),
                    sha256=props.get("ecm:sha256", ""),
                    doc_type=props.get("ecm:docType", "unknown"),
                    confidence=float(props.get("ecm:confidence", 0.0)),
                    retention_class=props.get("ecm:retentionClass", ""),
                    acl=props.get("ecm:acl", "RESTRICTED_REVIEW"),
                    target_workflow=props.get("ecm:targetWorkflow", ""),
                    review_status="auto_accepted",
                )
            return None

    def find_by_hash(self, sha256: str) -> Optional[ECMDocumentRecord]:
        if self.stub_mode:
            ecm_id = self._hash_index.get(sha256)
            if ecm_id:
                return self._stub_store.get(ecm_id)
            return None
        return None


# Alias for backwards compatibility
FakeECM = DatabaseECMAdapter

_global_ecm_adapter: Optional[ECMAdapter] = None


def get_ecm_adapter() -> ECMAdapter:
    """Factory returning configured ECM adapter."""
    global _global_ecm_adapter
    if _global_ecm_adapter is None:
        _global_ecm_adapter = DatabaseECMAdapter()
    return _global_ecm_adapter
