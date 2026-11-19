/**
 * API client module using types auto-generated from /openapi.json.
 * Handles active role stub, query building, error decoding, and loading states.
 */

import type { components, paths } from './schema';

export type SystemInfoResponse = components['schemas']['SystemInfoResponse'];
export type UserSessionResponse = components['schemas']['UserSessionResponse'];
export type ReviewQueueResponse = components['schemas']['ReviewQueueResponse'];
export type ReviewQueueItem = components['schemas']['ReviewQueueItem'];
export type ReviewDetailResponse = components['schemas']['ReviewDetailResponse'];
export type ReviewActionRequest = components['schemas']['ReviewActionRequest'];
export type ReviewActionResponse = components['schemas']['ReviewActionResponse'];
export type DocumentListResponse = components['schemas']['DocumentListResponse'];
export type DocumentSummaryItem = components['schemas']['DocumentSummaryItem'];
export type DocumentStatusResponse = components['schemas']['DocumentStatusResponse'];
export type DocumentComplianceDetailResponse = components['schemas']['DocumentComplianceDetailResponse'];
export type AuditTrailResponse = components['schemas']['AuditTrailResponse'];
export type AuditEventItem = components['schemas']['AuditEventItem'];
export type ReprocessPreviewRequest = components['schemas']['ReprocessPreviewRequest'];
export type ReprocessPreviewResponse = components['schemas']['ReprocessPreviewResponse'];
export type ReprocessResponse = components['schemas']['ReprocessResponse'];
export type DashboardMetricsResponse = components['schemas']['DashboardMetricsResponse'];
export type ClassThresholdConfig = components['schemas']['ClassThresholdConfig'];
export type AdminConfigResponse = components['schemas']['AdminConfigResponse'];
export type AdminConfigUpdateRequest = components['schemas']['AdminConfigUpdateRequest'];
export type AdminConfigUpdateResponse = components['schemas']['AdminConfigUpdateResponse'];
export type ConfigHistoryResponse = components['schemas']['ConfigHistoryResponse'];
export type IngestResponse = components['schemas']['IngestResponse'];

const API_BASE = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000';

let currentRole = localStorage.getItem('ecm_user_role') || import.meta.env.VITE_DEFAULT_ROLE || 'admin';

export function getActiveRole(): string {
  return currentRole;
}

export function setActiveRole(role: string): void {
  currentRole = role;
  localStorage.setItem('ecm_user_role', role);
}

export class ApiError extends Error {
  status: number;
  detail: string;

  constructor(status: number, detail: string) {
    super(detail);
    this.name = 'ApiError';
    this.status = status;
    this.detail = detail;
  }
}

async function apiFetch<T>(endpoint: string, options: RequestInit = {}): Promise<T> {
  const url = `${API_BASE}${endpoint}`;
  const headers = new Headers(options.headers || {});
  
  headers.set('X-User-Role', currentRole);
  if (!headers.has('Content-Type') && !(options.body instanceof FormData)) {
    headers.set('Content-Type', 'application/json');
  }

  const response = await fetch(url, {
    ...options,
    headers,
  });

  if (!response.ok) {
    let errorDetail = `HTTP ${response.status} ${response.statusText}`;
    try {
      const errorJson = await response.json();
      if (errorJson && errorJson.detail) {
        errorDetail = typeof errorJson.detail === 'string' ? errorJson.detail : JSON.stringify(errorJson.detail);
      }
    } catch {
      // Body not JSON
    }
    throw new ApiError(response.status, errorDetail);
  }

  // Handle empty responses
  if (response.status === 204 || response.headers.get('content-length') === '0') {
    return {} as T;
  }

  return response.json();
}

export const api = {
  // Shell & Auth
  getSystemInfo: () => apiFetch<SystemInfoResponse>('/api/v1/system/info'),
  getAuthMe: () => apiFetch<UserSessionResponse>('/api/v1/auth/me'),

  // Review Queue
  getReviewQueue: (params: {
    page?: number;
    page_size?: number;
    sort_by?: 'risk' | 'confidence' | 'age';
    doc_type?: string;
    risk_level?: string;
    pii_sensitivity?: string;
  }) => {
    const q = new URLSearchParams();
    if (params.page) q.set('page', String(params.page));
    if (params.page_size) q.set('page_size', String(params.page_size));
    if (params.sort_by) q.set('sort_by', params.sort_by);
    if (params.doc_type) q.set('doc_type', params.doc_type);
    if (params.risk_level) q.set('risk_level', params.risk_level);
    if (params.pii_sensitivity) q.set('pii_sensitivity', params.pii_sensitivity);
    return apiFetch<ReviewQueueResponse>(`/api/v1/review/queue?${q.toString()}`);
  },

  // Review Detail & Actions
  getReviewDetail: (documentUid: string) =>
    apiFetch<ReviewDetailResponse>(`/api/v1/review/${encodeURIComponent(documentUid)}`),

  submitReviewAction: (documentUid: string, actionReq: ReviewActionRequest) =>
    apiFetch<ReviewActionResponse>(`/api/v1/review/${encodeURIComponent(documentUid)}/action`, {
      method: 'POST',
      body: JSON.stringify(actionReq),
    }),

  // Page Image
  getPageImageUrl: (documentUid: string, pageNum: number = 1) =>
    `${API_BASE}/api/v1/documents/${encodeURIComponent(documentUid)}/pages/${pageNum}/image`,

  // Ingestion
  uploadSingleFile: async (file: File): Promise<IngestResponse> => {
    const formData = new FormData();
    formData.append('file', file);
    return apiFetch<IngestResponse>('/ingest', {
      method: 'POST',
      body: formData,
    });
  },

  uploadBulkFiles: async (files: File[]): Promise<IngestResponse[]> => {
    const formData = new FormData();
    files.forEach((f) => formData.append('files', f));
    return apiFetch<IngestResponse[]>('/ingest/bulk', {
      method: 'POST',
      body: formData,
    });
  },

  getDocumentStatus: (documentUid: string) =>
    apiFetch<DocumentStatusResponse>(`/api/v1/documents/${encodeURIComponent(documentUid)}/status`),

  // Documents List & Search
  getDocuments: (params: {
    page?: number;
    page_size?: number;
    q?: string;
    doc_type?: string;
    min_confidence?: number;
    max_confidence?: number;
    model_version?: string;
    review_status?: string;
    pii_type?: string;
  }) => {
    const q = new URLSearchParams();
    if (params.page) q.set('page', String(params.page));
    if (params.page_size) q.set('page_size', String(params.page_size));
    if (params.q) q.set('q', params.q);
    if (params.doc_type) q.set('doc_type', params.doc_type);
    if (params.min_confidence !== undefined) q.set('min_confidence', String(params.min_confidence));
    if (params.max_confidence !== undefined) q.set('max_confidence', String(params.max_confidence));
    if (params.model_version) q.set('model_version', params.model_version);
    if (params.review_status) q.set('review_status', params.review_status);
    if (params.pii_type) q.set('pii_type', params.pii_type);
    return apiFetch<DocumentListResponse>(`/api/v1/documents?${q.toString()}`);
  },

  // Document Compliance & Audit
  getDocumentCompliance: (documentUid: string) =>
    apiFetch<DocumentComplianceDetailResponse>(`/api/v1/documents/${encodeURIComponent(documentUid)}`),

  getDocumentAudit: (documentUid: string) =>
    apiFetch<AuditTrailResponse>(`/api/v1/documents/${encodeURIComponent(documentUid)}/audit`),

  // Reprocessing
  previewReprocess: (req: ReprocessPreviewRequest) =>
    apiFetch<ReprocessPreviewResponse>('/api/v1/reprocess/preview', {
      method: 'POST',
      body: JSON.stringify(req),
    }),

  executeReprocess: (queryStr: string) =>
    apiFetch<ReprocessResponse>('/reprocess', {
      method: 'POST',
      body: JSON.stringify({ query: queryStr }),
    }),

  // Dashboard Metrics
  getDashboardMetrics: () => apiFetch<DashboardMetricsResponse>('/api/v1/dashboard/metrics'),

  // Admin Configuration
  getAdminConfig: () => apiFetch<AdminConfigResponse>('/api/v1/admin/config'),

  updateAdminConfig: (req: AdminConfigUpdateRequest) =>
    apiFetch<AdminConfigUpdateResponse>('/api/v1/admin/config', {
      method: 'POST',
      body: JSON.stringify(req),
    }),

  getConfigHistory: () => apiFetch<ConfigHistoryResponse>('/api/v1/admin/config/history'),
};
