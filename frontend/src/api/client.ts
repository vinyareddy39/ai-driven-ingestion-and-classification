/** API client for frontend. */

const API_BASE = '/api';

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
  value: string;
  orig?: string;
  conf?: number;
  src?: string;
  page?: number;
  bbox?: number[] | null;
  is_sensitive?: boolean;
}

export interface FileItem {
  id: string;
  name: string;
  type: string;
  cond: string;
  dup?: string;
  status: string;
  stage: string;
  error?: string;
  fields: FieldItem[];
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

  getPageImageUrl(fileId: string, pageNum: number = 1): string {
    const token = localStorage.getItem('token') || '';
    return `${API_BASE}/files/${fileId}/page/${pageNum}?token=${encodeURIComponent(token)}`;
  },

  getDownloadUrl(batchId: string): string {
    const token = localStorage.getItem('token') || '';
    return `${API_BASE}/batches/${batchId}/download?token=${encodeURIComponent(token)}`;
  },
};
