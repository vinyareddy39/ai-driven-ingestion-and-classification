"""Explicit Pydantic v2 Schemas for Patient Prescription & Timetable API Contract."""

from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Auth Schemas
# ---------------------------------------------------------------------------

class UserSignupRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(..., pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$", description="Valid email address")
    password: str = Field(..., min_length=8, description="User password (min 8 characters)")
    role: str = Field(default="patient", description="Default role is 'patient'")


class UserLoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(..., pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = 1800  # 30 minutes


class RefreshTokenRequest(BaseModel):
    refresh_token: str


class AuthUserResponse(BaseModel):
    user_id: str
    email: str
    role: str
    created_at: Optional[datetime] = None


# ---------------------------------------------------------------------------
# Prescription Schemas
# ---------------------------------------------------------------------------

class PrescriptionJobResponse(BaseModel):
    job_id: str
    prescription_id: str
    status: str = Field(default="QUEUED", description="Initial status: QUEUED")
    message: str = "Prescription uploaded successfully and queued for OCR processing."


class PrescriptionStatusResponse(BaseModel):
    prescription_id: str
    status: str  # QUEUED, PROCESSING, NEEDS_REVIEW, CONFIRMED, FAILED
    created_at: datetime
    error_message: Optional[str] = None


class ExtractedMedicationItem(BaseModel):
    item_id: str
    drug_name: str
    strength: str
    dose: str
    frequency: str
    timing: str
    duration_days: Optional[int] = None
    schedule_rule: str
    confidence: Dict[str, float]
    verified_by_user: bool = False
    verified_at: Optional[datetime] = None
    low_confidence_flags: List[str] = Field(default_factory=list)


class PrescriptionDetailResponse(BaseModel):
    prescription_id: str
    status: str
    file_key: str
    model_version: str
    ocr_engine: str
    pii_detected: bool
    created_at: datetime
    items: List[ExtractedMedicationItem]
    requires_user_confirmation: bool = True


class ItemCorrectionRequest(BaseModel):
    drug_name: Optional[str] = None
    strength: Optional[str] = None
    dose: Optional[str] = None
    frequency: Optional[str] = None
    timing: Optional[str] = None
    duration_days: Optional[int] = None
    schedule_rule: Optional[str] = None
    verified_by_user: bool = True


# ---------------------------------------------------------------------------
# Timetable & Reminder Schemas
# ---------------------------------------------------------------------------

class TimetableSlotResponse(BaseModel):
    slot_id: str
    prescription_id: str
    extracted_item_id: str
    drug_name: str
    dose: str
    instruction: str
    scheduled_at: datetime
    status: str  # pending, taken, skipped
    status_changed_at: Optional[datetime] = None


class TimetableResponse(BaseModel):
    slots: List[TimetableSlotResponse]
    disclaimer: str = (
        "NOTICE: This medication timetable is an AI-assisted scheduling reference for personal adherence only. "
        "It does NOT constitute medical advice. Never adjust doses or medication regimens without consulting your licensed physician."
    )


class SlotStatusUpdateRequest(BaseModel):
    status: str = Field(..., pattern="^(pending|taken|skipped)$")


class ReminderPreferenceRequest(BaseModel):
    channel: str = Field(default="email", pattern="^(email|sms|push)$")
    advance_minutes: int = Field(default=15, ge=0, le=120)
    enabled: bool = True


class ReminderPreferenceResponse(BaseModel):
    user_id: str
    channel: str
    advance_minutes: int
    enabled: bool
