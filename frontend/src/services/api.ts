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
const DEFAULT_LOCAL_TOKEN = '7v0xX3WljSa89vceTyNKmhDpPO4_NIJ63jIC3mkAKbo';

function getHeaders(extra?: Record<string, string>): Record<string, string> {
  return {
    Authorization: `Bearer ${DEFAULT_LOCAL_TOKEN}`,
    'X-User-Role': 'admin',
    ...extra,
  };
}

export const api = {
  // Observability & Dashboard
  async getDashboardStats(): Promise<DashboardStats> {
    const res = await fetch(`${BASE_URL}/api/stats/dashboard`, {
      headers: getHeaders(),
    });
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

    const res = await fetch(`${BASE_URL}/api/documents?${query.toString()}`, {
      headers: getHeaders(),
    });
    if (!res.ok) throw new Error('Failed to fetch documents');
    return res.json();
  },

  async getDocumentAudit(uid: string): Promise<DocumentAuditDetail> {
    const res = await fetch(`${BASE_URL}/audit/${uid}`, {
      headers: getHeaders(),
    });
    if (!res.ok) throw new Error('Failed to fetch document audit trail');
    return res.json();
  },

  // Ingestion
  async ingestSingleFile(file: File): Promise<IngestResponse> {
    const formData = new FormData();
    formData.append('file', file);

    const res = await fetch(`${BASE_URL}/ingest`, {
      method: 'POST',
      headers: getHeaders(),
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
      headers: getHeaders(),
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
      headers: getHeaders(),
    });
    if (!res.ok) throw new Error('Failed to trigger scanner directory');
    return res.json();
  },

  // Human Review
  async getReviewQueue(params?: {
    page?: number;
    page_size?: number;
    sort_by?: string;
    doc_type?: string;
    risk_level?: string;
    pii_sensitivity?: string;
  }): Promise<{ items: any[]; total: number; page: number; page_size: number; total_pages: number }> {
    const query = new URLSearchParams();
    if (params?.page) query.append('page', params.page.toString());
    if (params?.page_size) query.append('page_size', params.page_size.toString());
    if (params?.sort_by) query.append('sort_by', params.sort_by);
    if (params?.doc_type) query.append('doc_type', params.doc_type);
    if (params?.risk_level) query.append('risk_level', params.risk_level);
    if (params?.pii_sensitivity) query.append('pii_sensitivity', params.pii_sensitivity);

    const res = await fetch(`${BASE_URL}/api/v1/review/queue?${query.toString()}`, {
      headers: getHeaders(),
    });
    if (!res.ok) throw new Error('Failed to fetch review queue');
    return res.json();
  },

  async getReviewTasks(): Promise<ReviewTaskSummary[]> {
    const res = await fetch(`${BASE_URL}/review/api/tasks`, {
      headers: getHeaders(),
    });
    if (!res.ok) throw new Error('Failed to fetch review tasks');
    return res.json();
  },

  async getReviewTaskDetail(documentUid: string): Promise<ReviewTaskDetail> {
    const res = await fetch(`${BASE_URL}/review/api/task/${documentUid}`, {
      headers: getHeaders(),
    });
    if (!res.ok) throw new Error('Failed to fetch task detail');
    return res.json();
  },

  async submitReviewAction(
    documentUid: string,
    payload: ReviewActionPayload
  ): Promise<{ status: string; document_uid: string; action: string; review_status: string; final_type: string }> {
    const res = await fetch(`${BASE_URL}/review/api/task/${documentUid}/action`, {
      method: 'POST',
      headers: getHeaders({
        'Content-Type': 'application/json',
      }),
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
      headers: getHeaders({
        'Content-Type': 'application/json',
      }),
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: 'Reprocessing trigger failed' }));
      throw new Error(err.detail || 'Reprocessing trigger failed');
    }
    return res.json();
  },

  async getSystemInfo(): Promise<any> {
    const res = await fetch(`${BASE_URL}/api/v1/system/info`, {
      headers: getHeaders(),
    });
    if (!res.ok) return { mode: 'LOCAL MODE', max_upload_mb: 200, allowed_file_types: [] };
    return res.json();
  },

  async getDocuments(params?: any): Promise<any> {
    return this.listDocuments(params);
  },

  async previewReprocess(payload: any): Promise<any> {
    return this.triggerReprocessing(payload);
  },

  async executeReprocess(payload: any): Promise<any> {
    return this.triggerReprocessing(payload);
  },

  async getReviewDetail(uid: string): Promise<any> {
    return this.getReviewTaskDetail(uid);
  },

  async getDocumentStatus(uid: string): Promise<any> {
    const res = await fetch(`${BASE_URL}/api/v1/documents/${uid}/status`, {
      headers: getHeaders(),
    });
    return res.json();
  },

  async uploadSingleFile(file: File): Promise<any> {
    return this.ingestSingleFile(file);
  },

  async getAdminConfig(): Promise<any> {
    const res = await fetch(`${BASE_URL}/api/v1/admin/config`, {
      headers: getHeaders(),
    });
    return res.json();
  },

  async getConfigHistory(): Promise<any> {
    const res = await fetch(`${BASE_URL}/api/v1/admin/config/history`, {
      headers: getHeaders(),
    });
    return res.json();
  },

  async updateAdminConfig(payload: any): Promise<any> {
    const res = await fetch(`${BASE_URL}/api/v1/admin/config`, {
      method: 'PUT',
      headers: getHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify(payload),
    });
    return res.json();
  },

  async getDashboardMetrics(): Promise<any> {
    const res = await fetch(`${BASE_URL}/api/v1/dashboard/metrics`, {
      headers: getHeaders(),
    });
    return res.json();
  },

  async getDocumentCompliance(uid: string): Promise<any> {
    const res = await fetch(`${BASE_URL}/api/v1/documents/${uid}/compliance`, {
      headers: getHeaders(),
    });
    return res.json();
  },

  async listDownloads(params?: { page?: number; page_size?: number }): Promise<any> {
    const query = new URLSearchParams();
    if (params?.page) query.append('page', params.page.toString());
    if (params?.page_size) query.append('page_size', params.page_size.toString());
    const res = await fetch(`${BASE_URL}/api/v1/downloads?${query.toString()}`, {
      headers: getHeaders(),
    });
    if (!res.ok) throw new Error('Failed to fetch downloads');
    return res.json();
  },

  async requestBatchDownload(batchId: string): Promise<any> {
    const res = await fetch(`${BASE_URL}/api/v1/batches/${encodeURIComponent(batchId)}/downloads`, {
      method: 'POST',
      headers: getHeaders({ 'Content-Type': 'application/json' }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: 'Failed to request download' }));
      throw new Error(err.detail || 'Failed to request download');
    }
    return res.json();
  },
};
