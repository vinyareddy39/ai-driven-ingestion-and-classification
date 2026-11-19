export interface DashboardStats {
  total_documents: number;
  auto_accepted: number;
  pending_review: number;
  quarantined: number;
  human_verified: number;
  duplicates_linked: number;
  stp_rate: number;
  error_rate: number;
  queue_depths: {
    live: number;
    bulk: number;
    dlq: number;
  };
  stage_latencies: Record<string, { p50: number; p95: number }>;
  type_breakdown: Array<{ type: string; count: number }>;
  status_breakdown: Array<{ status: string; count: number }>;
  recent_documents: DocumentItem[];
}

export interface DocumentItem {
  uid: string;
  sha256?: string;
  file_name: string;
  doc_type: string;
  confidence: number;
  review_status: string;
  retention_class?: string;
  acl?: string;
  pii_detected?: boolean;
  is_link?: boolean;
  linked_to_uid?: string | null;
  decision_reason?: string;
  created_at: string | null;
}

export interface AuditEvent {
  event_id: string;
  event_type: string;
  stage: string | null;
  timestamp: string | null;
}

export interface DocumentAuditDetail {
  uid: string;
  sha256: string;
  file_name: string;
  predictedType: string;
  confidence: number;
  ocrEngine: string;
  ocrVersion: string;
  classifierModel: string;
  classifierVersion: string;
  reviewStatus: string;
  retentionClass: string;
  assignedAcl: string;
  targetWorkflow: string;
  decisionReason: string;
  reviewerId: string | null;
  reviewNotes: string | null;
  piiDetected: boolean;
  piiTypes: string[];
  extractedFields: Record<string, any>;
  humanVerifiedFields: Record<string, any>;
  processedAt: string | null;
  auditTrail: AuditEvent[];
}

export interface ReviewTaskSummary {
  task_id: string;
  document_uid: string;
  file_name: string;
  predicted_type: string;
  confidence: number;
  pii_detected: boolean;
  pii_types: string[];
  decision_reason: string;
  created_at: string | null;
  status: string;
}

export interface ReviewTaskDetail {
  document_uid: string;
  task_id: string | null;
  file_name: string;
  sha256: string;
  doc_type: string;
  confidence: number;
  review_status: string;
  retention_class: string;
  acl: string;
  decision_reason: string;
  pii_detected: boolean;
  pii_types: string[];
  pii_entities: Array<{ type: string; text?: string; score?: number }>;
  extracted_fields: Record<string, any>;
  field_confidences: Record<string, number>;
  evidence_text: string;
  created_at: string | null;
}

export interface ReviewActionPayload {
  reviewer_id: string;
  action: 'CONFIRM' | 'CORRECT' | 'REJECT';
  corrected_type?: string;
  corrected_fields?: Record<string, any>;
  review_notes?: string;
  [key: string]: unknown;
}

export interface IngestResponse {
  uid: string;
  sha256: string;
  file_name: string;
  status: string;
  queue: string;
  message: string;
  is_link?: boolean;
  linked_to_uid?: string | null;
}

export interface ReprocessRequest {
  query?: string;
  classifier_version_filter?: string;
  min_confidence?: number;
  target_types?: string[];
  dry_run: boolean;
}

export interface ReprocessResponse {
  matched_count: number;
  queued_count: number;
  skipped_count: number;
  dry_run: boolean;
  job_id: string;
}

export interface ScannerTriggerResponse {
  ingested_count: number;
  message: string;
}
