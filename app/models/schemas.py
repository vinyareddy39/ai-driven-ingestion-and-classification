"""Pydantic v2 schemas for document ingestion, field extraction, decision gates, and API payloads."""

from datetime import datetime
from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Per-Type Field Extraction Schemas with Strict Validation
# ---------------------------------------------------------------------------

class InvoiceFields(BaseModel):
    invoice_number: str = Field(description="Unique invoice number identifier")
    invoice_date: str = Field(description="Date invoice was issued (YYYY-MM-DD)")
    total_amount: float = Field(ge=0.0, description="Total payable amount")
    vendor_name: str = Field(min_length=1, description="Entity issuing the invoice")


class ContractFields(BaseModel):
    contract_id: str = Field(description="Contract reference code")
    effective_date: str = Field(description="Date contract becomes active (YYYY-MM-DD)")
    party_one: str = Field(min_length=1, description="First contracting party")
    party_two: str = Field(min_length=1, description="Second contracting party")


class KYCFormFields(BaseModel):
    full_name: str = Field(min_length=1, description="Full legal name of individual")
    id_number: str = Field(min_length=3, description="National ID or Passport number")
    date_of_birth: str = Field(description="Date of birth (YYYY-MM-DD)")
    nationality: str = Field(min_length=2, description="Country of citizenship")


class BankStatementFields(BaseModel):
    account_number: str = Field(description="Bank account identifier")
    statement_period: str = Field(description="Billing or statement period")
    opening_balance: float = Field(description="Account balance at start of cycle")
    closing_balance: float = Field(description="Account balance at close of cycle")


class MedicalReportFields(BaseModel):
    patient_id: str = Field(description="Unique patient identifier")
    diagnosis: str = Field(min_length=1, description="Clinical finding or diagnosis")
    doctor_name: str = Field(min_length=1, description="Attending physician")
    report_date: str = Field(description="Date of examination (YYYY-MM-DD)")


class PurchaseOrderFields(BaseModel):
    po_number: str = Field(description="Purchase order identification number")
    po_date: str = Field(description="Issue date (YYYY-MM-DD)")
    vendor_name: str = Field(min_length=1, description="Supplier or vendor name")
    order_total: float = Field(ge=0.0, description="Total authorized expenditure")


class LetterFields(BaseModel):
    sender: str = Field(min_length=1, description="Originating sender of correspondence")
    recipient: str = Field(min_length=1, description="Addressee recipient")
    letter_date: str = Field(description="Date of letter (YYYY-MM-DD)")
    subject: str = Field(min_length=1, description="Subject line or topic")


class ClaimFormFields(BaseModel):
    claim_id: str = Field(description="Insurance claim identifier")
    claimant_name: str = Field(min_length=1, description="Name of policyholder / claimant")
    incident_date: str = Field(description="Date of loss or incident (YYYY-MM-DD)")
    claim_amount: float = Field(ge=0.0, description="Total claimed damages")


class UnknownFields(BaseModel):
    """Empty or arbitrary fields for unknown document types."""
    pass


FIELD_SCHEMA_MAP = {
    "invoice": InvoiceFields,
    "contract": ContractFields,
    "kyc_form": KYCFormFields,
    "bank_statement": BankStatementFields,
    "medical_report": MedicalReportFields,
    "purchase_order": PurchaseOrderFields,
    "letter": LetterFields,
    "claim_form": ClaimFormFields,
    "unknown": UnknownFields,
}


# ---------------------------------------------------------------------------
# API Payloads
# ---------------------------------------------------------------------------

class IngestResponse(BaseModel):
    """Response returned upon successful document ingestion."""
    uid: str
    sha256: str
    file_name: str
    status: str
    queue: str
    message: str


class DecisionResult(BaseModel):
    """Output from the Decision Gate stage."""
    action: str  # AUTO_ACCEPT, ROUTE_TO_REVIEW, QUARANTINE
    predicted_type: str
    confidence: float
    retention_class: str
    acl: str
    target_workflow: str
    reason: str
    review_status: str


class ReviewActionRequest(BaseModel):
    """Reviewer confirmation or correction request."""
    reviewer_id: str
    action: str  # CONFIRM, CORRECT, REJECT
    corrected_type: Optional[str] = None
    corrected_fields: Optional[Dict[str, Any]] = None
    review_notes: Optional[str] = None


class ReprocessRequest(BaseModel):
    """Query payload for reprocess-by-query endpoint."""
    query: Optional[str] = None  # e.g. "classifierVersion < 2.0" or "confidence < 0.8"
    classifier_version_filter: Optional[str] = None
    min_confidence: Optional[float] = None
    target_types: Optional[List[str]] = None
    dry_run: bool = False


class ReprocessResponse(BaseModel):
    """Response from reprocess endpoint."""
    matched_count: int
    queued_count: int
    skipped_count: int
    dry_run: bool
    job_id: str
