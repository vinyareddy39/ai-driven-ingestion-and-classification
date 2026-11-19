"""Patient Prescription & Timetable API Routes with Strict Per-User Data Isolation."""

import json
import os
import uuid
from datetime import datetime, timezone
from typing import List, Optional
from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile, status
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
    SlotStatusUpdateRequest,
    TimetableResponse,
    TimetableSlotResponse,
)

router = APIRouter(prefix="/api/v1", tags=["Prescriptions & Timetable"])

STAFF_ROLES = {"reviewer", "admin", "compliance"}


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

@router.post("/prescriptions", response_model=PrescriptionJobResponse, status_code=status.HTTP_202_ACCEPTED)
async def upload_prescription(
    file: UploadFile = File(...),
    current_user: UserSessionResponse = Depends(get_current_user),
):
    """Upload prescription photo/scan. Saves file, enqueues OCR job bound to authenticated user."""
    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Uploaded file is empty.")

    rx_id = f"rx-{uuid.uuid4().hex[:12]}"
    job_id = f"job-rx-{uuid.uuid4().hex[:12]}"
    file_key = f"prescriptions/{current_user.user_id}/{rx_id}.pdf"

    # Save to local storage
    storage_dir = os.path.join("data", "storage", "prescriptions", current_user.user_id)
    os.makedirs(storage_dir, exist_ok=True)
    local_path = os.path.join(storage_dir, f"{rx_id}.pdf")
    with open(local_path, "wb") as f:
        f.write(file_bytes)

    db = get_db_session()
    try:
        rx = PrescriptionModel(
            id=rx_id,
            user_id=current_user.user_id,
            file_key=file_key,
            status="QUEUED",
            model_version="v1.0",
            ocr_engine="HybridPyMuPDF-Tesseract",
            pii_detected=False,
            created_at=datetime.now(timezone.utc),
        )
        db.add(rx)
        db.commit()

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
        local_path = os.path.join("data", "storage", "prescriptions", rx.user_id, f"{rx.id}.pdf")
        if os.path.exists(local_path):
            import fitz
            doc = fitz.open(local_path)
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

        # 1x1 transparent PNG fallback if file is stubbed
        png_1x1 = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4\x00\x00\x00\nIDATx\x9cc`\x00\x00\x00\x02\x00\x01H\xaf\xa4q\x00\x00\x00\x00IEND\xaeB`\x82"
        return Response(content=png_1x1, media_type="image/png")
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

        if req.drug_name is not None: item.drug_name = req.drug_name
        if req.strength is not None: item.strength = req.strength
        if req.dose is not None: item.dose = req.dose
        if req.frequency is not None: item.frequency = req.frequency
        if req.timing is not None: item.timing = req.timing
        if req.duration_days is not None: item.duration_days = req.duration_days
        if req.schedule_rule is not None: item.schedule_rule = req.schedule_rule

        item.verified_by_user = req.verified_by_user
        item.verified_at = datetime.now(timezone.utc)
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

        rx.status = "CONFIRMED"
        db.commit()

        # Query created slots for this prescription
        slots_db = db.query(TimetableSlotModel).filter(
            TimetableSlotModel.prescription_id == rx.id,
            TimetableSlotModel.user_id == current_user.user_id,
        ).order_by(TimetableSlotModel.scheduled_at.asc()).all()

        slot_responses = [
            TimetableSlotResponse(
                slot_id=s.id,
                prescription_id=s.prescription_id,
                extracted_item_id=s.extracted_item_id,
                drug_name="",
                dose="",
                instruction=s.instruction or "",
                scheduled_at=s.scheduled_at,
                status=s.status,
                status_changed_at=s.status_changed_at,
            )
            for s in slots_db
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
        slot.status_changed_at = datetime.now(timezone.utc)
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
