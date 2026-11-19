import type {
  DashboardStats,
  DocumentItem,
  DocumentAuditDetail,
  ReviewTaskSummary,
  ReviewTaskDetail,
  ReviewActionPayload,
  IngestResponse,
  ReprocessRequest,
  ReprocessResponse,
  ScannerTriggerResponse,
} from '../types';

const BASE_URL = '';

export const api = {
  // Observability & Dashboard
  async getDashboardStats(): Promise<DashboardStats> {
    const res = await fetch(`${BASE_URL}/api/stats/dashboard`);
    if (!res.ok) throw new Error('Failed to fetch dashboard stats');
    return res.json();
  },

  async getHealthStatus(): Promise<{ status: string; database?: string; queue?: string }> {
    const res = await fetch(`${BASE_URL}/health/ready`);
    if (!res.ok) {
      const liveRes = await fetch(`${BASE_URL}/health/live`);
      return liveRes.json();
    }
    return res.json();
  },

  // Document Exploration & Audit
  async listDocuments(params?: {
    doc_type?: string;
    review_status?: string;
    search?: string;
    limit?: number;
    offset?: number;
  }): Promise<{ total: number; items: DocumentItem[]; limit: number; offset: number }> {
    const query = new URLSearchParams();
    if (params?.doc_type) query.append('doc_type', params.doc_type);
    if (params?.review_status) query.append('review_status', params.review_status);
    if (params?.search) query.append('search', params.search);
    if (params?.limit !== undefined) query.append('limit', params.limit.toString());
    if (params?.offset !== undefined) query.append('offset', params.offset.toString());

    const res = await fetch(`${BASE_URL}/api/documents?${query.toString()}`);
    if (!res.ok) throw new Error('Failed to fetch documents');
    return res.json();
  },

  async getDocumentAudit(uid: string): Promise<DocumentAuditDetail> {
    const res = await fetch(`${BASE_URL}/audit/${uid}`);
    if (!res.ok) throw new Error('Failed to fetch document audit trail');
    return res.json();
  },

  // Ingestion
  async ingestSingleFile(file: File): Promise<IngestResponse> {
    const formData = new FormData();
    formData.append('file', file);

    const res = await fetch(`${BASE_URL}/ingest`, {
      method: 'POST',
      body: formData,
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: 'Ingest failed' }));
      throw new Error(err.detail || 'Ingest failed');
    }
    return res.json();
  },

  async ingestBulkFiles(files: File[]): Promise<IngestResponse[]> {
    const formData = new FormData();
    files.forEach((f) => formData.append('files', f));

    const res = await fetch(`${BASE_URL}/ingest/bulk`, {
      method: 'POST',
      body: formData,
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: 'Bulk ingest failed' }));
      throw new Error(err.detail || 'Bulk ingest failed');
    }
    return res.json();
  },

  async triggerScannerWatch(): Promise<ScannerTriggerResponse> {
    const res = await fetch(`${BASE_URL}/ingest/scanner_watch_trigger`, {
      method: 'POST',
    });
    if (!res.ok) throw new Error('Failed to trigger scanner directory');
    return res.json();
  },

  // Human Review
  async getReviewTasks(): Promise<ReviewTaskSummary[]> {
    const res = await fetch(`${BASE_URL}/review/api/tasks`);
    if (!res.ok) throw new Error('Failed to fetch review tasks');
    return res.json();
  },

  async getReviewTaskDetail(documentUid: string): Promise<ReviewTaskDetail> {
    const res = await fetch(`${BASE_URL}/review/api/task/${documentUid}`);
    if (!res.ok) throw new Error('Failed to fetch task detail');
    return res.json();
  },

  async submitReviewAction(
    documentUid: string,
    payload: ReviewActionPayload
  ): Promise<{ status: string; document_uid: string; action: string; review_status: string; final_type: string }> {
    const res = await fetch(`${BASE_URL}/review/api/task/${documentUid}/action`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: 'Action submission failed' }));
      throw new Error(err.detail || 'Action submission failed');
    }
    return res.json();
  },

  getTrainingDataExportUrl(): string {
    return `${BASE_URL}/review/export/training_data.jsonl`;
  },

  getPrometheusMetricsUrl(): string {
    return `${BASE_URL}/metrics`;
  },

  // Reprocessing
  async triggerReprocessing(payload: ReprocessRequest): Promise<ReprocessResponse> {
    const res = await fetch(`${BASE_URL}/reprocess`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: 'Reprocessing trigger failed' }));
      throw new Error(err.detail || 'Reprocessing trigger failed');
    }
    return res.json();
  },
};
