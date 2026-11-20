import React, { useState, useEffect, useRef, useCallback } from 'react';
import {
  FileUp,
  Loader2,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  FileText,
  Trash2,
  ArrowRight,
  UploadCloud,
} from 'lucide-react';
import { BASE_URL, client, getAuthToken, getActiveRole } from '../api/client';
import { BatchResultView } from './BatchResultView';

// ─── Types ────────────────────────────────────────────────────────────────────

interface SystemInfo {
  max_upload_size_bytes: number;
  allowed_file_types: string[];
  allowed_extensions: string[];
}

export interface QueuedFileItem {
  id: string;
  file: File;
  name: string;
  size: number;
  error?: string | null;
  progress: number;
  status: 'idle' | 'uploading' | 'done' | 'error';
  uid?: string;
  sha256?: string;
}

interface UploadDeskProps {
  onNavigateBatch?: (batchId: string) => void;
  onNavigateTab?: (tab: string) => void;
}

function formatBytes(bytes: number): string {
  if (bytes === 0) return '0 B';
  const mb = bytes / (1024 * 1024);
  if (mb >= 1) return `${mb.toFixed(1)} MB`;
  const kb = bytes / 1024;
  return `${Math.round(kb)} KB`;
}

export const UploadDesk: React.FC<UploadDeskProps> = ({
  onNavigateBatch,
  onNavigateTab,
}) => {
  // System info
  const [systemInfo, setSystemInfo] = useState<SystemInfo | null>(null);
  const [systemInfoError, setSystemInfoError] = useState<string | null>(null);

  // Drag state
  const [isDragOver, setIsDragOver] = useState(false);

  // File Queue & Batch State
  const [queue, setQueue] = useState<QueuedFileItem[]>([]);
  const [isUploading, setIsUploading] = useState(false);
  const [activeBatchId, setActiveBatchId] = useState<string | null>(null);

  const fileInputRef = useRef<HTMLInputElement>(null);

  // ── Fetch system info on mount ────────────────────────────────────────────
  useEffect(() => {
    let cancelled = false;

    async function loadSystemInfo() {
      const { data, error } = await client.GET('/api/v1/system/info');
      if (cancelled) return;
      if (error || !data) {
        setSystemInfoError('Could not load upload limits — upload will still work.');
        return;
      }
      const rawTypes = (data as Record<string, unknown>).allowed_file_types;
      const allowedTypes = Array.isArray(rawTypes)
        ? (rawTypes as string[])
        : typeof rawTypes === 'string'
          ? (rawTypes as string).split(',').map((t) => t.trim().toLowerCase())
          : ['application/pdf', 'image/png', 'image/jpeg'];
      const rawExts = (data as Record<string, unknown>).allowed_extensions;
      const allowedExtensions = Array.isArray(rawExts)
        ? (rawExts as string[])
        : ['.pdf', '.png', '.jpg', '.jpeg', '.tiff', '.eml', '.docx'];

      const maxBytes =
        ((data as Record<string, unknown>).max_upload_size_bytes as number) ||
        (((data as Record<string, unknown>).max_upload_mb as number) || 200) * 1024 * 1024;

      setSystemInfo({
        max_upload_size_bytes: maxBytes,
        allowed_file_types: allowedTypes,
        allowed_extensions: allowedExtensions,
      });
    }

    void loadSystemInfo();
    return () => {
      cancelled = true;
    };
  }, []);

  // ── Plain Words File Validation ───────────────────────────────────────────
  function validateFile(file: File): string | null {
    const maxBytes = systemInfo?.max_upload_size_bytes ?? 200 * 1024 * 1024;
    if (file.size > maxBytes) {
      const fileMb = (file.size / (1024 * 1024)).toFixed(0);
      const limitMb = Math.round(maxBytes / (1024 * 1024));
      return `Too big (${fileMb} MB). Maximum allowed size is ${limitMb} MB.`;
    }

    if (systemInfo) {
      const mimeOk = systemInfo.allowed_file_types.includes(file.type);
      const ext = `.${file.name.split('.').pop()?.toLowerCase() ?? ''}`;
      const extOk = systemInfo.allowed_extensions.includes(ext);

      if (!mimeOk && !extOk) {
        return `Wrong file type. Accepted types: ${systemInfo.allowed_extensions.join(', ')}`;
      }
    }

    return null;
  }

  // ── Add Files to Queue ────────────────────────────────────────────────────
  function addFiles(files: FileList | File[]) {
    const newItems: QueuedFileItem[] = [];
    Array.from(files).forEach((f) => {
      const err = validateFile(f);
      newItems.push({
        id: `${f.name}-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
        file: f,
        name: f.name,
        size: f.size,
        error: err,
        progress: 0,
        status: err ? 'error' : 'idle',
      });
    });

    setQueue((prev) => [...prev, ...newItems]);
  }

  function removeQueueItem(id: string) {
    setQueue((prev) => prev.filter((item) => item.id !== id));
  }

  function clearQueue() {
    setQueue([]);
  }

  // ── Drag & Drop Handlers ──────────────────────────────────────────────────
  const onDragOver = useCallback((e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setIsDragOver(true);
  }, []);

  const onDragLeave = useCallback(() => {
    setIsDragOver(false);
  }, []);

  const onDrop = useCallback(
    (e: React.DragEvent<HTMLDivElement>) => {
      e.preventDefault();
      setIsDragOver(false);
      if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
        addFiles(e.dataTransfer.files);
      }
    },
    [systemInfo],
  );

  const onFileInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length > 0) {
      addFiles(e.target.files);
      e.target.value = '';
    }
  };

  // ── Per-File Upload Worker ────────────────────────────────────────────────
  async function uploadItem(item: QueuedFileItem, batchId: string): Promise<{ uid?: string; sha256?: string; error?: string }> {
    return new Promise((resolve) => {
      const formData = new FormData();
      formData.append('file', item.file);
      formData.append('batch_id', batchId);

      const xhr = new XMLHttpRequest();
      xhr.open('POST', `${BASE_URL}/api/v1/ingest`);

      const tok = getAuthToken();
      if (tok) {
        xhr.setRequestHeader('Authorization', `Bearer ${tok}`);
      } else {
        const r = getActiveRole() || 'admin';
        if (r) xhr.setRequestHeader('X-User-Role', r);
      }

      xhr.upload.onprogress = (evt) => {
        if (evt.lengthComputable) {
          const percent = Math.round((evt.loaded / evt.total) * 100);
          setQueue((prev) =>
            prev.map((i) => (i.id === item.id ? { ...i, progress: percent } : i)),
          );
        }
      };

      xhr.onload = () => {
        let json: Record<string, unknown> = {};
        try {
          json = JSON.parse(xhr.responseText);
        } catch {
          json = { detail: xhr.statusText };
        }

        if (xhr.status >= 200 && xhr.status < 300) {
          const uid = String(json.uid ?? '');
          const sha = String(json.sha256 ?? '');
          setQueue((prev) =>
            prev.map((i) =>
              i.id === item.id
                ? { ...i, progress: 100, status: 'done', uid, sha256: sha }
                : i,
            ),
          );
          resolve({ uid, sha256: sha });
        } else {
          const msg =
            typeof json.detail === 'string'
              ? json.detail
              : `Upload failed: ${xhr.status} ${xhr.statusText}`;
          setQueue((prev) =>
            prev.map((i) =>
              i.id === item.id ? { ...i, status: 'error', error: msg } : i,
            ),
          );
          resolve({ error: msg });
        }
      };

      xhr.onerror = () => {
        const msg = 'Network error during upload.';
        setQueue((prev) =>
          prev.map((i) =>
            i.id === item.id ? { ...i, status: 'error', error: msg } : i,
          ),
        );
        resolve({ error: msg });
      };

      xhr.send(formData);
    });
  }

  // ── Start Upload Batch ────────────────────────────────────────────────────
  async function startBatchUpload() {
    const validItems = queue.filter((i) => !i.error && i.status !== 'done');
    if (validItems.length === 0) return;

    setIsUploading(true);

    let batchId = `batch-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
    // 1. Create batch record in backend
    try {
      const headers: Record<string, string> = { 'Content-Type': 'application/json' };
      const tok = getAuthToken();
      if (tok) headers['Authorization'] = `Bearer ${tok}`;
      else headers['X-User-Role'] = 'admin';

      const res = await fetch(`${BASE_URL}/api/v1/batches`, {
        method: 'POST',
        headers,
        body: JSON.stringify({}),
      });
      if (res.ok) {
        const data = await res.json();
        if (data.batch_id) batchId = data.batch_id;
      }
    } catch {
      // Fallback to client-generated batchId
    }

    // 2. Mark valid items as uploading
    setQueue((prev) =>
      prev.map((i) =>
        !i.error && i.status !== 'done' ? { ...i, status: 'uploading', progress: 0 } : i,
      ),
    );

    // 3. Upload files
    await Promise.all(validItems.map((item) => uploadItem(item, batchId)));

    setIsUploading(false);

    // 4. Go straight to the batch page!
    if (onNavigateBatch) {
      onNavigateBatch(batchId);
    } else {
      setActiveBatchId(batchId);
    }
  }

  // If activeBatchId is set and we're showing results inline:
  if (activeBatchId) {
    return (
      <BatchResultView
        batchId={activeBatchId}
        onReset={() => {
          setActiveBatchId(null);
          clearQueue();
        }}
        onNavigateTab={onNavigateTab}
      />
    );
  }

  const validCount = queue.filter((i) => !i.error && i.status !== 'done').length;
  const maxMb = systemInfo ? Math.round(systemInfo.max_upload_size_bytes / (1024 * 1024)) : 200;

  return (
    <div className="space-y-6 max-w-4xl mx-auto">
      {/* Header */}
      <div className="pb-4 border-b border-slate-800">
        <h1 className="text-2xl font-bold text-white flex items-center space-x-2">
          <UploadCloud className="w-6 h-6 text-teal-400" />
          <span>Upload files</span>
        </h1>
        <p className="text-sm text-slate-400 mt-1">
          Select or drag documents here. We'll automatically sort them into categories and read the text.
        </p>
      </div>

      {systemInfoError && (
        <div className="px-4 py-3 rounded-xl bg-amber-500/10 border border-amber-500/30 text-amber-300 text-xs flex items-center space-x-2">
          <AlertTriangle className="w-4 h-4 flex-shrink-0" />
          <span>{systemInfoError}</span>
        </div>
      )}

      {/* ── One Big Drop Area ── */}
      <div
        onDragOver={onDragOver}
        onDragLeave={onDragLeave}
        onDrop={onDrop}
        onClick={() => fileInputRef.current?.click()}
        className={`relative flex flex-col items-center justify-center p-12 border-2 border-dashed rounded-3xl cursor-pointer transition-all text-center ${
          isDragOver
            ? 'border-teal-400 bg-teal-500/10 scale-[1.01]'
            : 'border-slate-700/80 bg-slate-900/50 hover:border-teal-500/50 hover:bg-slate-900/80'
        }`}
      >
        <input
          ref={fileInputRef}
          type="file"
          multiple
          className="hidden"
          onChange={onFileInputChange}
          accept={systemInfo?.allowed_extensions?.join(',') || '.pdf,.png,.jpg,.jpeg,.tiff,.eml,.docx'}
        />

        <div className="w-16 h-16 rounded-2xl bg-teal-500/10 border border-teal-500/30 flex items-center justify-center text-teal-400 mb-4 shadow-lg shadow-teal-500/10">
          <FileUp className="w-8 h-8" />
        </div>

        <h3 className="text-lg font-bold text-white mb-1">
          Drag files here or choose files
        </h3>
        <p className="text-xs text-slate-400 max-w-sm mb-3">
          Upload as many files as you like at once. PDF, images (PNG, JPG), TIFF, and Word docs supported up to {maxMb} MB per file.
        </p>

        <span className="px-4 py-2 rounded-xl text-xs font-semibold bg-teal-500/15 text-teal-300 border border-teal-500/30 shadow-sm hover:bg-teal-500/25 transition">
          Browse files on your computer
        </span>
      </div>

      {/* ── Selected Files List ── */}
      {queue.length > 0 && (
        <div className="rounded-2xl border border-slate-800 bg-slate-900/70 overflow-hidden shadow-sm space-y-4 p-5">
          <div className="flex items-center justify-between pb-3 border-b border-slate-800">
            <div className="flex items-center space-x-2">
              <span className="text-sm font-bold text-white">Selected files</span>
              <span className="px-2 py-0.5 rounded-full text-xs font-mono bg-slate-800 text-teal-300 border border-slate-700">
                {queue.length}
              </span>
            </div>
            {!isUploading && (
              <button
                onClick={clearQueue}
                className="text-xs text-slate-400 hover:text-rose-400 transition"
              >
                Clear all
              </button>
            )}
          </div>

          <div className="max-h-72 overflow-y-auto divide-y divide-slate-800/60 pr-1">
            {queue.map((item) => (
              <div key={item.id} className="py-2.5 flex items-center justify-between gap-3 text-xs">
                <div className="flex items-center space-x-3 min-w-0">
                  <FileText className="w-4 h-4 text-slate-400 flex-shrink-0" />
                  <div className="min-w-0">
                    <p className="font-medium text-slate-200 truncate">{item.name}</p>
                    <span className="text-[11px] text-slate-500">{formatBytes(item.size)}</span>
                  </div>
                </div>

                <div className="flex items-center space-x-3 flex-shrink-0">
                  {item.error ? (
                    <span className="text-xs text-rose-400 flex items-center space-x-1 font-medium">
                      <XCircle className="w-3.5 h-3.5" />
                      <span>{item.error}</span>
                    </span>
                  ) : item.status === 'uploading' ? (
                    <div className="flex items-center space-x-2">
                      <div className="w-20 h-1.5 rounded-full bg-slate-800 overflow-hidden">
                        <div
                          className="h-full bg-teal-400 rounded-full transition-all"
                          style={{ width: `${item.progress}%` }}
                        />
                      </div>
                      <span className="text-[11px] font-mono text-slate-400">{item.progress}%</span>
                    </div>
                  ) : item.status === 'done' ? (
                    <span className="text-xs text-emerald-400 flex items-center space-x-1">
                      <CheckCircle2 className="w-3.5 h-3.5" />
                      <span>Uploaded</span>
                    </span>
                  ) : (
                    <span className="text-xs text-slate-400">Ready</span>
                  )}

                  {!isUploading && (
                    <button
                      onClick={() => removeQueueItem(item.id)}
                      className="p-1 rounded text-slate-500 hover:text-rose-400 hover:bg-slate-800 transition"
                      aria-label="Remove file"
                    >
                      <Trash2 className="w-3.5 h-3.5" />
                    </button>
                  )}
                </div>
              </div>
            ))}
          </div>

          {/* Action Row */}
          <div className="pt-3 border-t border-slate-800 flex items-center justify-between">
            <span className="text-xs text-slate-400">
              {validCount} {validCount === 1 ? 'file' : 'files'} ready to sort
            </span>

            <button
              onClick={startBatchUpload}
              disabled={validCount === 0 || isUploading}
              className="flex items-center space-x-2 px-6 py-2.5 text-sm font-bold bg-teal-500 hover:bg-teal-400 text-slate-950 rounded-xl shadow-lg shadow-teal-500/25 transition disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {isUploading ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin text-slate-950" />
                  <span>Uploading files...</span>
                </>
              ) : (
                <>
                  <span>Upload {validCount > 0 ? `${validCount} files` : ''}</span>
                  <ArrowRight className="w-4 h-4" />
                </>
              )}
            </button>
          </div>
        </div>
      )}
    </div>
  );
};
