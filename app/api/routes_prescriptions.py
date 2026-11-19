"""Patient Prescription & Timetable API Routes with Strict Per-User Data Isolation."""

import hashlib
import json
import os
import uuid
from datetime import datetime, timezone
from typing import List, Optional
from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Query, Response, UploadFile, status
from app.adapters.storage import get_storage_adapter
from app.adapters.virus import MockVirusScanner
from app.core.auth import get_current_user
from app.models.api_schemas import UserSessionResponse
from app.models.db import (
    AuditEventModel,
    ExtractedItemModel,
    PrescriptionModel,
    ReminderModel,
    TimetableSlotModel,
    get_db_session,
)
from app.models.prescription_schemas import (
    ExtractedMedicationItem,
    ItemCorrectionRequest,
    PrescriptionDetailResponse,
    PrescriptionJobResponse,
    PrescriptionStatusResponse,
    ReminderPreferenceRequest,
    ReminderPreferenceResponse,
    ReprocessFilterRequest,
    ReprocessItemDiff,
    ReprocessPrescriptionResult,
    ReprocessResponse,
    SlotStatusUpdateRequest,
    TimetableResponse,
    TimetableSlotResponse,
)
from app.workers.medication_extractor import MedicationExtractor
from app.workers.prescription_worker import process_prescription_job

router = APIRouter(prefix="/api/v1", tags=["Prescriptions & Timetable"])

STAFF_ROLES = {"reviewer", "admin", "compliance"}
ALLOWED_MIME_TYPES = {"image/jpeg", "image/png", "image/jpg", "application/pdf"}
MAX_UPLOAD_SIZE = 10 * 1024 * 1024  # 10MB


def _get_user_prescription(db, prescription_id: str, current_user: UserSessionResponse) -> PrescriptionModel:
    """Fetch prescription ensuring strict per-user isolation or audited staff access."""
    if current_user.role in STAFF_ROLES:
        rx = db.query(PrescriptionModel).filter(PrescriptionModel.id == prescription_id).first()
        if not rx:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Prescription not found")
        # Audit staff access to patient health data
        audit_ev = AuditEventModel(
            event_id=f"audit-staff-{uuid.uuid4().hex[:12]}",
            document_uid=prescription_id,
            sha256="",
            event_type="STAFF_PATIENT_ACCESS",
            stage_name="prescription_review",
            status="AUDITED",
            payload_json=json.dumps({
                "staff_user_id": current_user.user_id,
                "staff_role": current_user.role,
                "prescription_id": prescription_id,
                "patient_user_id": rx.user_id,
            }),
            created_at=datetime.now(timezone.utc),
        )
        db.add(audit_ev)
        db.commit()
        return rx

    # Standard patient role: strict user_id filtering (returns 404 to avoid leaking existence)
    rx = db.query(PrescriptionModel).filter(
        PrescriptionModel.id == prescription_id,
        PrescriptionModel.user_id == current_user.user_id,
    ).first()
    if not rx:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Prescription not found")
    return rx


# ---------------------------------------------------------------------------
# Prescription Endpoints
# ---------------------------------------------------------------------------

@router.post("/prescriptions", response_model=PrescriptionJobResponse, status_code=status.HTTP_201_CREATED)
async def upload_prescription(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    current_user: UserSessionResponse = Depends(get_current_user),
):
    """Upload prescription photo/scan. Saves file, enqueues OCR job bound to authenticated user."""
    # Check mime type
    content_type = file.content_type or "application/octet-stream"
    ext = "pdf"
    if "jpeg" in content_type or "jpg" in content_type or (file.filename and file.filename.lower().endswith((".jpg", ".jpeg"))):
        ext = "jpg"
    elif "png" in content_type or (file.filename and file.filename.lower().endswith(".png")):
        ext = "png"
    elif "pdf" in content_type or (file.filename and file.filename.lower().endswith(".pdf")):
        ext = "pdf"
    else:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Unsupported file type '{content_type}'. Supported: image/jpeg, image/png, application/pdf.",
        )

    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Uploaded file is empty.")

    if len(file_bytes) > MAX_UPLOAD_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="File size exceeds maximum allowed 10MB limit.",
        )

    # Virus scan verification
    scanner = MockVirusScanner()
    is_clean, virus_name = scanner.scan(file_bytes)
    if not is_clean:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Quarantined: malicious content detected ({virus_name}).",
        )

    # Compute SHA-256 for duplicate detection
    file_hash = hashlib.sha256(file_bytes).hexdigest()

    db = get_db_session()
    try:
        # Check duplicate per user
        existing_rx = db.query(PrescriptionModel).filter(
            PrescriptionModel.user_id == current_user.user_id,
            PrescriptionModel.sha256 == file_hash,
        ).first()

        if existing_rx:
            return PrescriptionJobResponse(
                job_id=f"job-dup-{existing_rx.id}",
                prescription_id=existing_rx.id,
                status=existing_rx.status,
                message="Duplicate upload detected; returning existing prescription record.",
            )

        rx_id = f"rx-{uuid.uuid4().hex[:12]}"
        job_id = f"job-rx-{uuid.uuid4().hex[:12]}"
        file_key = f"prescriptions/{current_user.user_id}/{rx_id}.{ext}"

        # Save to storage adapter
        storage = get_storage_adapter()
        storage.save(file_key, file_bytes, content_type)

        rx = PrescriptionModel(
            id=rx_id,
            user_id=current_user.user_id,
            file_key=file_key,
            sha256=file_hash,
            status="QUEUED",
            model_version="v1.0",
            ocr_engine="HybridPyMuPDF-Tesseract",
            pii_detected=False,
            created_at=datetime.now(timezone.utc),
        )
        db.add(rx)
        db.commit()

        # Enqueue background processing worker
        background_tasks.add_task(process_prescription_job, rx_id)

        return PrescriptionJobResponse(
            job_id=job_id,
            prescription_id=rx_id,
            status="QUEUED",
            message="Prescription uploaded successfully and queued for OCR processing.",
        )
    finally:
        db.close()


@router.get("/prescriptions/{prescription_id}/status", response_model=PrescriptionStatusResponse)
def get_prescription_status(
    prescription_id: str,
    current_user: UserSessionResponse = Depends(get_current_user),
):
    """Check asynchronous OCR & extraction job processing status."""
    db = get_db_session()
    try:
        rx = _get_user_prescription(db, prescription_id, current_user)
        return PrescriptionStatusResponse(
            prescription_id=rx.id,
            status=rx.status,
            created_at=rx.created_at,
            error_message=rx.error_message,
        )
    finally:
        db.close()


@router.get("/prescriptions/{prescription_id}", response_model=PrescriptionDetailResponse)
def get_prescription_detail(
    prescription_id: str,
    current_user: UserSessionResponse = Depends(get_current_user),
):
    """Retrieve extracted medication items, field confidences, model version, and verification flags."""
    db = get_db_session()
    try:
        rx = _get_user_prescription(db, prescription_id, current_user)
        items_db = db.query(ExtractedItemModel).filter(ExtractedItemModel.prescription_id == rx.id).all()

        items = []
        for it in items_db:
            conf_dict = json.loads(it.confidence_json or "{}")
            low_flags = [k for k, v in conf_dict.items() if v < 0.85]
            items.append(
                ExtractedMedicationItem(
                    item_id=it.id,
                    drug_name=it.drug_name,
                    strength=it.strength or "",
                    dose=it.dose or "",
                    frequency=it.frequency or "",
                    timing=it.timing or "",
                    duration_days=it.duration_days,
                    schedule_rule=it.schedule_rule or "",
                    confidence=conf_dict,
                    verified_by_user=it.verified_by_user,
                    verified_at=it.verified_at,
                    low_confidence_flags=low_flags,
                )
            )

        return PrescriptionDetailResponse(
            prescription_id=rx.id,
            status=rx.status,
            file_key=rx.file_key,
            sha256=rx.sha256,
            raw_text=rx.raw_text,
            error_message=rx.error_message,
            model_version=rx.model_version or "v1.0",
            ocr_engine=rx.ocr_engine or "HybridPyMuPDF-Tesseract",
            pii_detected=rx.pii_detected,
            created_at=rx.created_at,
            items=items,
            requires_user_confirmation=True,
        )
    finally:
        db.close()


@router.get("/prescriptions/{prescription_id}/image")
def get_prescription_image(
    prescription_id: str,
    page: int = Query(default=1, ge=1),
    width: Optional[int] = Query(default=None, ge=16, le=4096),
    current_user: UserSessionResponse = Depends(get_current_user),
):
    """Render authenticated prescription page image. Strictly accessible only to resource owner."""
    db = get_db_session()
    try:
        rx = _get_user_prescription(db, prescription_id, current_user)
        storage = get_storage_adapter()
        file_bytes: Optional[bytes] = None
        if storage.exists(rx.file_key):
            file_bytes = storage.get(rx.file_key)
        else:
            local_fallback = os.path.join(os.getcwd(), "data", "storage", rx.file_key)
            if os.path.exists(local_fallback):
                with open(local_fallback, "rb") as f:
                    file_bytes = f.read()

        if not file_bytes:
            # 1x1 transparent PNG fallback if file is stubbed
            png_1x1 = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4\x00\x00\x00\nIDATx\x9cc`\x00\x00\x00\x02\x00\x01H\xaf\xa4q\x00\x00\x00\x00IEND\xaeB`\x82"
            return Response(content=png_1x1, media_type="image/png")

        if rx.file_key.endswith(".pdf"):
            import fitz
            doc = fitz.open(stream=file_bytes, filetype="pdf")
            if page < 1 or page > len(doc):
                doc.close()
                raise HTTPException(status_code=400, detail="Page number out of range")
            p = doc.load_page(page - 1)
            if width is not None:
                zoom = width / p.rect.width
                mat = fitz.Matrix(zoom, zoom)
                pix = p.get_pixmap(matrix=mat)
            else:
                pix = p.get_pixmap(dpi=150)
            img_bytes = pix.tobytes("png")
            doc.close()
            return Response(content=img_bytes, media_type="image/png")
        else:
            if width is not None:
                import cv2
                import numpy as np
                nparr = np.frombuffer(file_bytes, np.uint8)
                img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
                if img is not None:
                    h, w = img.shape[:2]
                    new_h = int(h * (width / float(w)))
                    resized = cv2.resize(img, (width, new_h), interpolation=cv2.INTER_AREA)
                    return Response(content=cv2.imencode(".png", resized)[1].tobytes(), media_type="image/png")
            return Response(content=file_bytes, media_type="image/png")
    finally:
        db.close()


@router.patch("/prescriptions/{prescription_id}/items/{item_id}", response_model=ExtractedMedicationItem)
def update_prescription_item(
    prescription_id: str,
    item_id: str,
    req: ItemCorrectionRequest,
    current_user: UserSessionResponse = Depends(get_current_user),
):
    """Submit user confirmation or manual correction for a specific extracted medication item."""
    db = get_db_session()
    try:
        rx = _get_user_prescription(db, prescription_id, current_user)
        item = db.query(ExtractedItemModel).filter(
            ExtractedItemModel.id == item_id,
            ExtractedItemModel.prescription_id == rx.id,
        ).first()
        if not item:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Medication item not found")

        prev_data = {
            "drug_name": item.drug_name,
            "strength": item.strength,
            "dose": item.dose,
            "frequency": item.frequency,
            "timing": item.timing,
            "duration_days": item.duration_days,
            "schedule_rule": item.schedule_rule,
        }

        if req.drug_name is not None: item.drug_name = req.drug_name
        if req.strength is not None: item.strength = req.strength
        if req.dose is not None: item.dose = req.dose
        if req.frequency is not None: item.frequency = req.frequency
        if req.timing is not None: item.timing = req.timing
        if req.duration_days is not None: item.duration_days = req.duration_days
        if req.schedule_rule is not None: item.schedule_rule = req.schedule_rule

        item.verified_by_user = req.verified_by_user
        now = datetime.now(timezone.utc)
        item.verified_at = now

        # Append human review correction pair to offline active learning file data/prescription_corrections.jsonl
        # STRICT SAFETY: Do NOT log patient identity or PII
        os.makedirs("data", exist_ok=True)
        corrected_data = {
            "drug_name": item.drug_name,
            "strength": item.strength,
            "dose": item.dose,
            "frequency": item.frequency,
            "timing": item.timing,
            "duration_days": item.duration_days,
            "schedule_rule": item.schedule_rule,
        }
        correction_entry = {
            "timestamp": now.isoformat(),
            "prescription_id": rx.id,
            "item_id": item.id,
            "source_span": item.raw_text,
            "original_fields": prev_data,
            "corrected_fields": corrected_data,
            "verified_by_user": item.verified_by_user,
        }
        with open(os.path.join("data", "prescription_corrections.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps(correction_entry) + "\n")

        audit_ev = AuditEventModel(
            event_id=f"audit-item-{uuid.uuid4().hex[:12]}",
            document_uid=rx.id,
            sha256=rx.sha256 or "",
            event_type="ITEM_CORRECTED" if prev_data != corrected_data else "ITEM_VERIFIED",
            stage_name="human_review",
            status="SUCCESS",
            payload_json=json.dumps({
                "item_id": item.id,
                "drug_name": item.drug_name,
                "verified_by_user": item.verified_by_user,
            }),
            created_at=now,
        )
        db.add(audit_ev)
        db.commit()

        conf_dict = json.loads(item.confidence_json or "{}")
        return ExtractedMedicationItem(
            item_id=item.id,
            drug_name=item.drug_name,
            strength=item.strength or "",
            dose=item.dose or "",
            frequency=item.frequency or "",
            timing=item.timing or "",
            duration_days=item.duration_days,
            schedule_rule=item.schedule_rule or "",
            confidence=conf_dict,
            verified_by_user=item.verified_by_user,
            verified_at=item.verified_at,
            low_confidence_flags=[],
        )
    finally:
        db.close()


@router.post("/prescriptions/{prescription_id}/confirm", response_model=TimetableResponse)
def confirm_prescription(
    prescription_id: str,
    current_user: UserSessionResponse = Depends(get_current_user),
):
    """Confirm prescription and generate timetable slots. Fails with 409 if any item is unverified."""
    db = get_db_session()
    try:
        rx = _get_user_prescription(db, prescription_id, current_user)
        items = db.query(ExtractedItemModel).filter(ExtractedItemModel.prescription_id == rx.id).all()
        if not items:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Prescription has no extracted medication items.",
            )

        unverified = [it.drug_name for it in items if not it.verified_by_user]
        if unverified:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Clinical safety restriction: All medication items must be verified by user. Unverified: {unverified}",
            )

        # Generate slots for each verified item using deterministic parser
        from app.workers.timetable import DeterministicScheduleParser
        parser = DeterministicScheduleParser()

        # Clean any previous slots for this rx to ensure idempotency
        db.query(TimetableSlotModel).filter(TimetableSlotModel.prescription_id == rx.id).delete()

        created_slots = []
        for item in items:
            parse_res = parser.parse_rule(
                drug_name=item.drug_name,
                dose=item.dose,
                frequency=item.frequency,
                timing=item.timing,
                duration_days=item.duration_days,
            )
            for sl in parse_res.slots:
                slot_id = f"slot-{uuid.uuid4().hex[:12]}"
                slot_row = TimetableSlotModel(
                    id=slot_id,
                    user_id=current_user.user_id,
                    prescription_id=rx.id,
                    extracted_item_id=item.id,
                    scheduled_at=sl["scheduled_at"],
                    instruction=sl["instruction"],
                    status="pending",
                )
                db.add(slot_row)
                created_slots.append((slot_row, item))

        rx.status = "CONFIRMED"

        # Log audit event
        audit_ev = AuditEventModel(
            event_id=f"audit-confirm-{uuid.uuid4().hex[:12]}",
            document_uid=rx.id,
            sha256="",
            event_type="PRESCRIPTION_CONFIRMED",
            stage_name="timetable_generation",
            status="SUCCESS",
            payload_json=json.dumps({
                "prescription_id": rx.id,
                "user_id": current_user.user_id,
                "items_count": len(items),
                "slots_count": len(created_slots),
            }),
            created_at=datetime.now(timezone.utc),
        )
        db.add(audit_ev)
        db.commit()

        slot_responses = [
            TimetableSlotResponse(
                slot_id=s.id,
                prescription_id=s.prescription_id,
                extracted_item_id=s.extracted_item_id,
                drug_name=it.drug_name,
                dose=it.dose,
                instruction=s.instruction or "",
                scheduled_at=s.scheduled_at,
                status=s.status,
                status_changed_at=s.status_changed_at,
            )
            for s, it in created_slots
        ]
        return TimetableResponse(slots=slot_responses)
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Timetable & Reminder Endpoints
# ---------------------------------------------------------------------------

@router.get("/timetable", response_model=TimetableResponse)
def get_medication_timetable(
    from_date: Optional[datetime] = Query(default=None, alias="from"),
    to_date: Optional[datetime] = Query(default=None, alias="to"),
    current_user: UserSessionResponse = Depends(get_current_user),
):
    """Retrieve patient's scheduled medication timetable slots across date window."""
    db = get_db_session()
    try:
        q = db.query(TimetableSlotModel).filter(TimetableSlotModel.user_id == current_user.user_id)
        if from_date:
            q = q.filter(TimetableSlotModel.scheduled_at >= from_date)
        if to_date:
            q = q.filter(TimetableSlotModel.scheduled_at <= to_date)
        slots_db = q.order_by(TimetableSlotModel.scheduled_at.asc()).all()

        slot_responses = []
        for s in slots_db:
            item = db.query(ExtractedItemModel).filter(ExtractedItemModel.id == s.extracted_item_id).first()
            drug_name = item.drug_name if item else "Medication"
            dose = item.dose if item else ""
            slot_responses.append(
                TimetableSlotResponse(
                    slot_id=s.id,
                    prescription_id=s.prescription_id,
                    extracted_item_id=s.extracted_item_id,
                    drug_name=drug_name,
                    dose=dose,
                    instruction=s.instruction or "",
                    scheduled_at=s.scheduled_at,
                    status=s.status,
                    status_changed_at=s.status_changed_at,
                )
            )
        return TimetableResponse(slots=slot_responses)
    finally:
        db.close()


@router.patch("/timetable/slots/{slot_id}", response_model=TimetableSlotResponse)
def update_slot_status(
    slot_id: str,
    req: SlotStatusUpdateRequest,
    current_user: UserSessionResponse = Depends(get_current_user),
):
    """Update adherence status of a specific medication slot (pending, taken, skipped)."""
    db = get_db_session()
    try:
        slot = db.query(TimetableSlotModel).filter(
            TimetableSlotModel.id == slot_id,
            TimetableSlotModel.user_id == current_user.user_id,
        ).first()
        if not slot:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Timetable slot not found")

        slot.status = req.status
        now = datetime.now(timezone.utc)
        slot.status_changed_at = now

        # Record adherence audit event
        audit_ev = AuditEventModel(
            event_id=f"audit-slot-{uuid.uuid4().hex[:12]}",
            document_uid=slot.prescription_id,
            sha256="",
            event_type="SLOT_STATUS_UPDATED",
            stage_name="adherence_tracking",
            status="SUCCESS",
            payload_json=json.dumps({
                "slot_id": slot.id,
                "user_id": current_user.user_id,
                "new_status": req.status,
            }),
            created_at=now,
        )
        db.add(audit_ev)
        db.commit()

        item = db.query(ExtractedItemModel).filter(ExtractedItemModel.id == slot.extracted_item_id).first()
        return TimetableSlotResponse(
            slot_id=slot.id,
            prescription_id=slot.prescription_id,
            extracted_item_id=slot.extracted_item_id,
            drug_name=item.drug_name if item else "Medication",
            dose=item.dose if item else "",
            instruction=slot.instruction or "",
            scheduled_at=slot.scheduled_at,
            status=slot.status,
            status_changed_at=slot.status_changed_at,
        )
    finally:
        db.close()


@router.get("/reminders/preferences", response_model=ReminderPreferenceResponse)
def get_reminder_preferences(current_user: UserSessionResponse = Depends(get_current_user)):
    """Retrieve patient's medication reminder notification preferences."""
    return ReminderPreferenceResponse(
        user_id=current_user.user_id,
        channel="email",
        advance_minutes=15,
        enabled=True,
    )


@router.put("/reminders/preferences", response_model=ReminderPreferenceResponse)
def update_reminder_preferences(
    req: ReminderPreferenceRequest,
    current_user: UserSessionResponse = Depends(get_current_user),
):
    """Update patient's medication reminder notification preferences."""
    return ReminderPreferenceResponse(
        user_id=current_user.user_id,
        channel=req.channel,
        advance_minutes=req.advance_minutes,
        enabled=req.enabled,
    )


@router.post("/prescriptions/reprocess", response_model=ReprocessResponse)
def reprocess_prescriptions(
    req: ReprocessFilterRequest,
    current_user: UserSessionResponse = Depends(get_current_user),
):
    """Batch reprocess unconfirmed prescription extractions with updated models.
    
    CRITICAL SAFETY INVARIANT:
    - Extracted items that have been verified or corrected by a user (verified_by_user == True)
      are PROTECTED and will NEVER be overwritten or deleted during reprocessing.
    - Dry-run mode allows auditing what would change before writing to DB.
    """
    db = get_db_session()
    try:
        query = db.query(PrescriptionModel)
        if current_user.role not in STAFF_ROLES:
            query = query.filter(PrescriptionModel.user_id == current_user.user_id)

        if req.prescription_ids:
            query = query.filter(PrescriptionModel.id.in_(req.prescription_ids))
        if req.model_version:
            query = query.filter(PrescriptionModel.model_version == req.model_version)

        # Do not alter confirmed or archived prescriptions
        query = query.filter(PrescriptionModel.status.in_(["NEEDS_REVIEW", "PROCESSING", "QUEUED"]))
        rxs = query.all()

        extractor = MedicationExtractor()
        results: List[ReprocessPrescriptionResult] = []
        total_reprocessed = 0

        for rx in rxs:
            existing_items = db.query(ExtractedItemModel).filter(
                ExtractedItemModel.prescription_id == rx.id
            ).all()

            preserved_items = [it for it in existing_items if it.verified_by_user]
            unverified_items = [it for it in existing_items if not it.verified_by_user]

            diffs: List[ReprocessItemDiff] = []

            for p_it in preserved_items:
                diffs.append(ReprocessItemDiff(
                    item_id=p_it.id,
                    action="preserved",
                    drug_name=p_it.drug_name,
                    details={"reason": "User-verified item protected from automated overwrite", "dose": p_it.dose},
                ))

            # Re-extract from stored raw text
            new_candidates = extractor.extract(rx.raw_text or "")
            preserved_drug_names = {p.drug_name.lower() for p in preserved_items}

            # Filter out candidates that duplicate preserved items
            actionable_candidates = [
                c for c in new_candidates if c.drug_name.lower() not in preserved_drug_names
            ]

            for old_unv in unverified_items:
                diffs.append(ReprocessItemDiff(
                    item_id=old_unv.id,
                    action="replaced",
                    drug_name=old_unv.drug_name,
                    details={"reason": "Unverified item replaced by latest model extraction"},
                ))

            for new_c in actionable_candidates:
                diffs.append(ReprocessItemDiff(
                    item_id=f"new-reprocess-{uuid.uuid4().hex[:8]}",
                    action="added",
                    drug_name=new_c.drug_name,
                    details={
                        "strength": new_c.strength,
                        "dose": new_c.dose,
                        "frequency": new_c.frequency,
                        "timing": new_c.timing,
                        "duration_days": new_c.duration_days,
                    },
                ))

            if not req.dry_run:
                # Delete unverified items
                db.query(ExtractedItemModel).filter(
                    ExtractedItemModel.prescription_id == rx.id,
                    ExtractedItemModel.verified_by_user == False,
                ).delete()

                # Insert new candidates
                for cand in actionable_candidates:
                    new_item_row = ExtractedItemModel(
                        id=str(uuid.uuid4()),
                        prescription_id=rx.id,
                        raw_text=cand.source_span,
                        drug_name=cand.drug_name,
                        strength=cand.strength,
                        dose=cand.dose,
                        frequency=cand.frequency,
                        timing=cand.timing,
                        duration_days=cand.duration_days,
                        schedule_rule=cand.schedule_rule,
                        confidence_json=json.dumps(cand.confidence),
                        verified_by_user=False,
                    )
                    db.add(new_item_row)

                rx.model_version = "v2.0-batch-reprocessed"

                now = datetime.now(timezone.utc)
                audit_ev = AuditEventModel(
                    event_id=f"audit-reprocess-{uuid.uuid4().hex[:12]}",
                    document_uid=rx.id,
                    sha256=rx.sha256 or "",
                    event_type="PRESCRIPTION_REPROCESSED",
                    stage_name="batch_reprocessing",
                    status="SUCCESS",
                    payload_json=json.dumps({
                        "prescription_id": rx.id,
                        "preserved_count": len(preserved_items),
                        "reprocessed_count": len(actionable_candidates),
                        "model_version": rx.model_version,
                    }),
                    created_at=now,
                )
                db.add(audit_ev)
                total_reprocessed += 1

            results.append(ReprocessPrescriptionResult(
                prescription_id=rx.id,
                status="DRY_RUN_PREVIEW" if req.dry_run else "REPROCESSED",
                items_reprocessed=len(actionable_candidates),
                items_preserved=len(preserved_items),
                diffs=diffs,
            ))

        if not req.dry_run:
            db.commit()

        return ReprocessResponse(
            total_scanned=len(rxs),
            total_reprocessed=total_reprocessed if not req.dry_run else len(rxs),
            dry_run=req.dry_run,
            results=results,
        )
    finally:
        db.close()


@router.post("/reminders/dispatch")
def trigger_reminder_dispatch(
    window_minutes: int = Query(60, ge=1, le=1440),
    current_user: UserSessionResponse = Depends(get_current_user),
):
    """Trigger dispatch of upcoming medication reminders."""
    db = get_db_session()
    try:
        from app.workers.reminders import dispatch_due_reminders
        dispatched = dispatch_due_reminders(db, window_minutes=window_minutes)
        return {
            "dispatched_count": len(dispatched),
            "dispatched": dispatched,
        }
    finally:
        db.close()

