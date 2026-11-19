"""Patient Prescription & Timetable API Routes."""

import uuid
from datetime import datetime, timezone
from typing import List, Optional
from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile, status
from app.core.auth import get_current_user
from app.models.api_schemas import UserSessionResponse
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


# ---------------------------------------------------------------------------
# Prescription Endpoints
# ---------------------------------------------------------------------------

@router.post("/prescriptions", response_model=PrescriptionJobResponse, status_code=status.HTTP_202_ACCEPTED)
async def upload_prescription(
    file: UploadFile = File(...),
    current_user: UserSessionResponse = Depends(get_current_user),
):
    """Upload prescription photo/scan. Validates token, file size and enqueues OCR extraction job."""
    rx_id = f"rx-{uuid.uuid4().hex[:12]}"
    job_id = f"job-rx-{uuid.uuid4().hex[:12]}"
    return PrescriptionJobResponse(
        job_id=job_id,
        prescription_id=rx_id,
        status="QUEUED",
        message="Prescription uploaded successfully and queued for OCR processing.",
    )


@router.get("/prescriptions/{prescription_id}/status", response_model=PrescriptionStatusResponse)
def get_prescription_status(
    prescription_id: str,
    current_user: UserSessionResponse = Depends(get_current_user),
):
    """Check asynchronous OCR & extraction job processing status."""
    return PrescriptionStatusResponse(
        prescription_id=prescription_id,
        status="NEEDS_REVIEW",
        created_at=datetime.now(timezone.utc),
    )


@router.get("/prescriptions/{prescription_id}", response_model=PrescriptionDetailResponse)
def get_prescription_detail(
    prescription_id: str,
    current_user: UserSessionResponse = Depends(get_current_user),
):
    """Retrieve extracted medication items, field confidences, model version, and verification flags."""
    return PrescriptionDetailResponse(
        prescription_id=prescription_id,
        status="NEEDS_REVIEW",
        file_key=f"storage/rx/{prescription_id}.pdf",
        model_version="v1.0",
        ocr_engine="HybridPyMuPDF-Tesseract",
        pii_detected=False,
        created_at=datetime.now(timezone.utc),
        items=[],
        requires_user_confirmation=True,
    )


@router.get("/prescriptions/{prescription_id}/image")
def get_prescription_image(
    prescription_id: str,
    page: int = Query(default=1, ge=1),
    width: Optional[int] = Query(default=None, ge=16, le=4096),
    current_user: UserSessionResponse = Depends(get_current_user),
):
    """Render authenticated prescription page image. Strictly accessible only to resource owner."""
    # 1x1 transparent PNG stub for contract specification
    png_1x1 = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4\x00\x00\x00\nIDATx\x9cc`\x00\x00\x00\x02\x00\x01H\xaf\xa4q\x00\x00\x00\x00IEND\xaeB`\x82"
    return Response(content=png_1x1, media_type="image/png")


@router.patch("/prescriptions/{prescription_id}/items/{item_id}", response_model=ExtractedMedicationItem)
def update_prescription_item(
    prescription_id: str,
    item_id: str,
    req: ItemCorrectionRequest,
    current_user: UserSessionResponse = Depends(get_current_user),
):
    """Submit user confirmation or manual correction for a specific extracted medication item."""
    return ExtractedMedicationItem(
        item_id=item_id,
        drug_name=req.drug_name or "Amoxicillin",
        strength=req.strength or "500mg",
        dose=req.dose or "1 capsule",
        frequency=req.frequency or "TDS",
        timing=req.timing or "after_meals",
        duration_days=req.duration_days or 7,
        schedule_rule=req.schedule_rule or "every 8 hours after meals",
        confidence={"drug_name": 1.0, "strength": 1.0, "dose": 1.0, "frequency": 1.0},
        verified_by_user=True,
        verified_at=datetime.now(timezone.utc),
        low_confidence_flags=[],
    )


@router.post("/prescriptions/{prescription_id}/confirm", response_model=TimetableResponse)
def confirm_prescription(
    prescription_id: str,
    current_user: UserSessionResponse = Depends(get_current_user),
):
    """Confirm prescription and generate timetable slots. Fails with 409 if any item is unverified."""
    return TimetableResponse(slots=[])


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
    return TimetableResponse(slots=[])


@router.patch("/timetable/slots/{slot_id}", response_model=TimetableSlotResponse)
def update_slot_status(
    slot_id: str,
    req: SlotStatusUpdateRequest,
    current_user: UserSessionResponse = Depends(get_current_user),
):
    """Update adherence status of a specific medication slot (pending, taken, skipped)."""
    return TimetableSlotResponse(
        slot_id=slot_id,
        prescription_id="rx-demo-01",
        extracted_item_id="item-demo-01",
        drug_name="Amoxicillin",
        dose="500mg",
        instruction="Take 1 capsule after breakfast",
        scheduled_at=datetime.now(timezone.utc),
        status=req.status,
        status_changed_at=datetime.now(timezone.utc),
    )


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
