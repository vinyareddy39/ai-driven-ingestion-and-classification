/** API client for frontend. */

const rawApiUrl = (import.meta as any).env?.VITE_API_URL || (import.meta as any).env?.VITE_API_BASE_URL;
const API_BASE = rawApiUrl
  ? (rawApiUrl.endsWith('/api') ? rawApiUrl : `${rawApiUrl}/api`)
  : '/api';

function getAuthHeader(): Record<string, string> {
  const token = localStorage.getItem('token');
  return token ? { Authorization: `Bearer ${token}` } : {};
}

export interface User {
  id: string;
  name: string;
  email: string;
}

export interface FieldItem {
  id?: string;
  label: string;
  orig_label?: string;
  value: string;
  orig?: string;
  conf?: number;
  val_conf?: number;
  lbl_conf?: number;
  structure_type?: string;
  structure_group?: string;
  structure_confidence?: number;
  region_id?: string;
  reason?: string;
  suggested_label?: string;
  alternatives?: string[];
  hint?: string;
  grounding_span?: any;
  split_suggestion?: any;
  in_more_details?: boolean;
  is_promoted?: boolean;
  src?: string;
  page?: number;
  bbox?: number[] | null;
  is_sensitive?: boolean;
  detector_tag?: string | null;
  masked_value?: string;
  is_unlabelled?: boolean;
  is_edited?: boolean;
}

export interface RegionItem {
  region_id: string;
  structure_type: string;
  confidence: number;
  bbox: number[];
  reading_order: number;
  page_number: number;
  text?: string;
  column_index?: number;
  metadata?: Record<string, any>;
}

export interface TableArithmeticCheck {
  type: string;
  row_index?: number;
  column?: string;
  status: 'verified' | 'mismatch';
  message: string;
  computed?: number;
  expected?: number;
}

export interface TableItem {
  id?: string;
  page?: number;
  headers: string[];
  rows: Array<Record<string, string>>;
  bbox?: number[] | null;
  arithmetic_checks?: TableArithmeticCheck[];
}

export interface FileItem {
  id: string;
  name: string;
  relative_path?: string;
  type: string;
  cond: string;
  dup?: string;
  status: string;
  stage: string;
  error?: string;
  check_reasons?: string | null;
  document_summary?: string;
  tags?: string[];
  raw_text?: string;
  raw_text_by_page?: Record<string, string>;
  layout_blocks?: any[];
  fields: FieldItem[];
  tables?: TableItem[];
  regions?: RegionItem[];
}

export interface BatchItem {
  id: string;
  name: string;
  created_at?: string;
  file_count: number;
  done_count: number;
  failed_count: number;
  progress_pct: number;
  corrections_count: number;
  files: FileItem[];
}

export const api = {
  async register(name: string, email: string, pw: string) {
    const res = await fetch(`${API_BASE}/register`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, email, password: pw }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'Registration failed');
    return data;
  },

  async login(email: string, pw: string) {
    const res = await fetch(`${API_BASE}/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password: pw }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'Login failed');
    if (data.token) localStorage.setItem('token', data.token);
    return data;
  },

  async logout() {
    try {
      await fetch(`${API_BASE}/logout`, { method: 'POST', headers: getAuthHeader() });
    } finally {
      localStorage.removeItem('token');
    }
  },

  async getMe(): Promise<User | null> {
    const token = localStorage.getItem('token');
    if (!token) return null;
    const res = await fetch(`${API_BASE}/me`, { headers: getAuthHeader() });
    if (!res.ok) {
      localStorage.removeItem('token');
      return null;
    }
    return res.json();
  },

  async initBatch(batchName?: string): Promise<{ id: string; name: string }> {
    const formData = new FormData();
    if (batchName) formData.append('batch_name', batchName);
    const res = await fetch(`${API_BASE}/batches`, {
      method: 'POST',
      headers: getAuthHeader(),
      body: formData,
    });
    if (!res.ok) throw new Error('Failed to create batch');
    return res.json();
  },

  async appendBatchFiles(
    batchId: string,
    files: File[],
    relativePaths: string[]
  ): Promise<{ batch_id: string; added_count: number; total_count: number }> {
    const formData = new FormData();
    files.forEach((f) => formData.append('files', f));
    formData.append('relative_paths', JSON.stringify(relativePaths));

    let retries = 3;
    while (retries > 0) {
      try {
        const res = await fetch(`${API_BASE}/batches/${batchId}/files`, {
          method: 'POST',
          headers: getAuthHeader(),
          body: formData,
        });
        if (!res.ok) {
          const errText = await res.text();
          throw new Error(errText || `Failed to append files (${res.status})`);
        }
        return await res.json();
      } catch (err: any) {
        retries--;
        if (retries === 0) throw err;
        await new Promise((r) => setTimeout(r, 1000));
      }
    }
    throw new Error('Upload failed after retries');
  },

  async startBatch(batchId: string): Promise<any> {
    const res = await fetch(`${API_BASE}/batches/${batchId}/start`, {
      method: 'POST',
      headers: getAuthHeader(),
    });
    if (!res.ok) throw new Error('Failed to start batch reading');
    return res.json();
  },

  async uploadBatch(files: File[]): Promise<{ id: string; name: string }> {
    const formData = new FormData();
    files.forEach((f) => formData.append('files', f));
    const res = await fetch(`${API_BASE}/batches`, {
      method: 'POST',
      headers: getAuthHeader(),
      body: formData,
    });
    if (!res.ok) {
      if (res.status === 401) {
        localStorage.removeItem('token');
        throw new Error('Your session expired. Please sign in again.');
      }
      const text = await res.text();
      let msg = `Upload failed (${res.status})`;
      try {
        const j = JSON.parse(text);
        if (j.detail) msg = j.detail;
      } catch {
        if (res.status === 413) msg = 'Files too large for proxy. Please upload fewer files at once.';
        else if (res.status >= 500) msg = 'Server connection error. Please try again.';
      }
      throw new Error(msg);
    }
    return res.json();
  },

  async listBatches(): Promise<any[]> {
    const res = await fetch(`${API_BASE}/batches`, { headers: getAuthHeader() });
    if (!res.ok) throw new Error('Failed to load past batches');
    return res.json();
  },

  async getBatch(id: string): Promise<BatchItem> {
    const res = await fetch(`${API_BASE}/batches/${id}`, { headers: getAuthHeader() });
    if (res.status === 404) {
      const err: any = new Error('Batch not found (404)');
      err.status = 404;
      throw err;
    }
    if (!res.ok) throw new Error(`Failed to fetch batch (${res.status})`);
    return res.json();
  },

  async deleteBatch(id: string) {
    const res = await fetch(`${API_BASE}/batches/${id}`, {
      method: 'DELETE',
      headers: getAuthHeader(),
    });
    if (!res.ok) throw new Error('Failed to delete batch');
    return res.json();
  },

  async clearAllBatches() {
    const res = await fetch(`${API_BASE}/batches`, {
      method: 'DELETE',
      headers: getAuthHeader(),
    });
    if (!res.ok) throw new Error('Failed to clear batches');
    return res.json();
  },

  async updateFields(fileId: string, fields: FieldItem[]) {
    const res = await fetch(`${API_BASE}/files/${fileId}/fields`, {
      method: 'PUT',
      headers: {
        'Content-Type': 'application/json',
        ...getAuthHeader(),
      },
      body: JSON.stringify({ fields }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'Failed to save fields');
    return data;
  },

  async updateTables(fileId: string, tables: TableItem[]) {
    const res = await fetch(`${API_BASE}/files/${fileId}/tables`, {
      method: 'PUT',
      headers: {
        'Content-Type': 'application/json',
        ...getAuthHeader(),
      },
      body: JSON.stringify({ tables }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'Failed to save tables');
    return data;
  },

  async getLabelSuggestions(docType?: string): Promise<string[]> {
    const query = docType ? `?doc_type=${encodeURIComponent(docType)}` : '';
    const res = await fetch(`${API_BASE}/label-suggestions${query}`, {
      headers: getAuthHeader(),
    });
    if (!res.ok) return [];
    const data = await res.json();
    return data.suggestions || [];
  },

  async retryFile(fileId: string) {
    const res = await fetch(`${API_BASE}/files/${fileId}/retry`, {
      method: 'POST',
      headers: getAuthHeader(),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'Failed to retry file');
    return data;
  },

  async unlockFile(fileId: string, password: string) {
    const res = await fetch(`${API_BASE}/files/${fileId}/unlock`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...getAuthHeader(),
      },
      body: JSON.stringify({ password }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'Failed to unlock file');
    return data;
  },

  async retryBatchRateLimited(batchId: string) {
    const res = await fetch(`${API_BASE}/batches/${batchId}/retry-rate-limited`, {
      method: 'POST',
      headers: getAuthHeader(),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'Failed to retry rate-limited files');
    return data;
  },

  async reclassifyRegion(fileId: string, regionId: string, newStructureType: string) {
    const res = await fetch(`${API_BASE}/files/${fileId}/regions/${regionId}/reclassify`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...getAuthHeader(),
      },
      body: JSON.stringify({ new_structure_type: newStructureType }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'Failed to reclassify region');
    return data;
  },

  getPageImageUrl(fileId: string, pageNum: number = 1): string {
    const token = localStorage.getItem('token') || '';
    return `${API_BASE}/files/${fileId}/page/${pageNum}?token=${encodeURIComponent(token)}`;
  },

  getDownloadUrl(batchId: string): string {
    const token = localStorage.getItem('token') || '';
    return `${API_BASE}/batches/${batchId}/download?token=${encodeURIComponent(token)}`;
  },

  getCorrectionsExportUrl(format: 'json' | 'csv' = 'csv'): string {
    const token = localStorage.getItem('token') || '';
    return `${API_BASE}/corrections/export?format=${format}&token=${encodeURIComponent(token)}`;
  },

  async exportCorrections(format: 'json' | 'csv' = 'json') {
    const res = await fetch(`${API_BASE}/corrections/export?format=${format}`, {
      headers: getAuthHeader(),
    });
    if (!res.ok) throw new Error('Failed to export corrections');
    return format === 'json' ? await res.json() : await res.text();
  },
  async acceptAllSuggestions(fileId: string) {
    const res = await fetch(`${API_BASE}/files/${fileId}/accept-all`, {
      method: 'POST',
      headers: getAuthHeader(),
    });
    if (!res.ok) throw new Error('Failed to accept suggestions');
    return await res.json();
  },

  async promoteDetail(fileId: string, fieldId: string) {
    const res = await fetch(`${API_BASE}/files/${fileId}/promote-detail`, {
      method: 'POST',
      headers: { ...getAuthHeader(), 'Content-Type': 'application/json' },
      body: JSON.stringify({ field_id: fieldId }),
    });
    if (!res.ok) throw new Error('Failed to promote detail');
    return await res.json();
  },

  async acceptSplit(fileId: string, fieldId: string) {
    const res = await fetch(`${API_BASE}/files/${fileId}/accept-split`, {
      method: 'POST',
      headers: { ...getAuthHeader(), 'Content-Type': 'application/json' },
      body: JSON.stringify({ field_id: fieldId }),
    });
    if (!res.ok) throw new Error('Failed to accept split');
    return await res.json();
  },

  async bulkVerifyClean(batchId: string) {
    const res = await fetch(`${API_BASE}/batches/${batchId}/bulk-verify-clean`, {
      method: 'POST',
      headers: getAuthHeader(),
    });
    if (!res.ok) throw new Error('Failed to bulk verify clean documents');
    return await res.json();
  },

  async getWorkerHealth(): Promise<{ status: string; workers: any; database: any }> {
    const res = await fetch(`${API_BASE}/health/workers`);
    if (!res.ok) throw new Error('Failed to fetch worker health');
    return await res.json();
  },

  async exportAccountData(): Promise<Blob> {
    const res = await fetch(`${API_BASE}/account/export`, {
      headers: getAuthHeader(),
    });
    if (!res.ok) throw new Error('Failed to export account data');
    return await res.blob();
  },
};

export async function pingBackendWithColdStartRetry(
  onWakingUp?: (isWaking: boolean, elapsedSec: number) => void,
  maxWaitSec: number = 65
): Promise<boolean> {
  const startTime = Date.now();

  while ((Date.now() - startTime) < maxWaitSec * 1000) {
    try {
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 6000);
      const res = await fetch(`${API_BASE}/health/workers`, { signal: controller.signal });
      clearTimeout(timeoutId);
      if (res.ok) {
        if (onWakingUp) onWakingUp(false, Math.round((Date.now() - startTime) / 1000));
        return true;
      }
    } catch {
      // Backend may be sleeping / booting up
    }

    const elapsed = Math.round((Date.now() - startTime) / 1000);
    if (elapsed >= 2 && onWakingUp) {
      onWakingUp(true, elapsed);
    }
    await new Promise((resolve) => setTimeout(resolve, 2500));
  }

  if (onWakingUp) onWakingUp(false, Math.round((Date.now() - startTime) / 1000));
  return false;
}
