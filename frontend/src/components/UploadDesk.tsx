import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  AlertTriangle,
  CheckCircle2,
  CloudUpload,
  FileUp,
  Loader2,
  RefreshCw,
  XCircle,
} from 'lucide-react';
import { BASE_URL, client } from '../api/client';
import type { IngestResponse } from '../types';

// ─── Types ────────────────────────────────────────────────────────────────────

interface SystemInfo {
  max_upload_size_bytes: number;
  allowed_file_types: string[];
  allowed_extensions: string[];
}

interface StatusPollResult {
  status: string;
  [key: string]: unknown;
}

type UploadPhase = 'idle' | 'uploading' | 'polling' | 'done' | 'error';

// ─── Helpers ──────────────────────────────────────────────────────────────────

function formatBytes(bytes: number): string {
  if (bytes === 0) return '0 B';
  const mb = bytes / (1024 * 1024);
  return `${Math.round(mb)} MB`;
}

function truncateSha(sha: string): string {
  return sha.length > 16 ? `${sha.slice(0, 8)}…${sha.slice(-8)}` : sha;
}

const STATUS_COLORS: Record<string, string> = {
  QUEUED: 'bg-yellow-500/20 text-yellow-300 border-yellow-500/40',
  PROCESSING: 'bg-blue-500/20 text-blue-300 border-blue-500/40',
  CLASSIFIED: 'bg-teal-500/20 text-teal-300 border-teal-500/40',
  AUTO_ACCEPTED: 'bg-green-500/20 text-green-300 border-green-500/40',
  PENDING_REVIEW: 'bg-orange-500/20 text-orange-300 border-orange-500/40',
  QUARANTINED: 'bg-red-500/20 text-red-300 border-red-500/40',
  ERROR: 'bg-red-500/20 text-red-300 border-red-500/40',
};

function statusBadgeClass(status: string): string {
  return (
    STATUS_COLORS[status.toUpperCase()] ??
    'bg-slate-700 text-slate-300 border-slate-600'
  );
}

// ─── Component ────────────────────────────────────────────────────────────────

export const UploadDesk: React.FC = () => {
  // System info
  const [systemInfo, setSystemInfo] = useState<SystemInfo | null>(null);
  const [systemInfoError, setSystemInfoError] = useState<string | null>(null);

  // Drag state
  const [isDragOver, setIsDragOver] = useState(false);

  // Upload flow
  const [phase, setPhase] = useState<UploadPhase>('idle');
  const [validationError, setValidationError] = useState<string | null>(null);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [ingestResult, setIngestResult] = useState<IngestResponse | null>(null);
  const [liveStatus, setLiveStatus] = useState<string | null>(null);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);

  const fileInputRef = useRef<HTMLInputElement>(null);
  const pollCountRef = useRef(0);
  const pollTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // ── Fetch system info on mount ────────────────────────────────────────────

  useEffect(() => {
    let cancelled = false;

    async function loadSystemInfo() {
      const { data, error } = await client.GET('/api/v1/system/info');
      if (cancelled) return;
      if (error || !data) {
        setSystemInfoError(
          typeof error === 'object' && error !== null && 'detail' in error
            ? String((error as Record<string, unknown>).detail)
            : 'Could not load upload limits — upload may still work.',
        );
        return;
      }
      setSystemInfo({
        max_upload_size_bytes:
          (data as Record<string, unknown>).max_upload_size_bytes as number,
        allowed_file_types:
          (data as Record<string, unknown>).allowed_file_types as string[],
        allowed_extensions:
          (data as Record<string, unknown>).allowed_extensions as string[],
      });
    }

    void loadSystemInfo();
    return () => { cancelled = true; };
  }, []);

  // ── Cleanup poll timer on unmount ─────────────────────────────────────────

  useEffect(() => {
    return () => {
      if (pollTimerRef.current !== null) clearTimeout(pollTimerRef.current);
    };
  }, []);

  // ── Validation ────────────────────────────────────────────────────────────

  function validateFile(file: File): string | null {
    if (!systemInfo) return null; // let backend decide if limits unknown

    if (file.size > systemInfo.max_upload_size_bytes) {
      const limitMb = formatBytes(systemInfo.max_upload_size_bytes);
      return `File exceeds limit (${limitMb})`;
    }

    const mimeOk = systemInfo.allowed_file_types.includes(file.type);
    const ext = `.${file.name.split('.').pop()?.toLowerCase() ?? ''}`;
    const extOk = systemInfo.allowed_extensions.includes(ext);

    if (!mimeOk && !extOk) {
      return `File type not allowed. Accepted: ${systemInfo.allowed_extensions.join(', ')}`;
    }

    return null;
  }

  // ── Polling ───────────────────────────────────────────────────────────────

  function startPolling(uid: string) {
    pollCountRef.current = 0;

    async function poll() {
      if (pollCountRef.current >= 30) {
        setPhase('done');
        return;
      }
      pollCountRef.current += 1;

      try {
        const res = await fetch(
          `${BASE_URL}/api/v1/documents/${encodeURIComponent(uid)}/status`,
          { headers: { 'X-User-Role': 'admin' } },
        );
        if (res.ok) {
          const json = (await res.json()) as StatusPollResult;
          const newStatus = String(json.status ?? '');
          setLiveStatus(newStatus);

          if (newStatus && newStatus !== 'QUEUED' && newStatus !== 'PROCESSING') {
            setPhase('done');
            return;
          }
        }
      } catch {
        // silent — keep polling
      }

      pollTimerRef.current = setTimeout(() => void poll(), 2000);
    }

    setPhase('polling');
    void poll();
  }

  // ── Upload ────────────────────────────────────────────────────────────────

  async function handleUpload(file: File) {
    setValidationError(null);
    setUploadError(null);
    setIngestResult(null);
    setLiveStatus(null);
    setSelectedFile(file);

    const err = validateFile(file);
    if (err) {
      setValidationError(err);
      return;
    }

    setPhase('uploading');

    const formData = new FormData();
    formData.append('file', file);

    try {
      const res = await fetch(`${BASE_URL}/ingest`, {
        method: 'POST',
        headers: { 'X-User-Role': 'admin' },
        body: formData,
      });

      const json = (await res.json()) as Record<string, unknown>;

      if (!res.ok) {
        const msg =
          typeof json.detail === 'string'
            ? json.detail
            : typeof json.message === 'string'
              ? json.message
              : `Upload failed: ${res.statusText}`;
        setUploadError(msg);
        setPhase('error');
        return;
      }

      const result: IngestResponse = {
        uid: String(json.uid ?? ''),
        sha256: String(json.sha256 ?? ''),
        file_name: String(json.file_name ?? file.name),
        status: String(json.status ?? ''),
        queue: String(json.queue ?? ''),
        message: String(json.message ?? ''),
      };

      setIngestResult(result);
      setLiveStatus(result.status);
      startPolling(result.uid);
    } catch (e) {
      const msg = e instanceof Error ? e.message : 'Network error during upload.';
      setUploadError(msg);
      setPhase('error');
    }
  }

  // ── Drag & Drop handlers ──────────────────────────────────────────────────

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
      const file = e.dataTransfer.files?.[0];
      if (file) void handleUpload(file);
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [systemInfo],
  );

  const onFileChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      if (file) void handleUpload(file);
      // reset input so same file can be re-picked
      if (fileInputRef.current) fileInputRef.current.value = '';
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [systemInfo],
  );

  // ── Reset ─────────────────────────────────────────────────────────────────

  function handleReset() {
    if (pollTimerRef.current !== null) clearTimeout(pollTimerRef.current);
    setPhase('idle');
    setValidationError(null);
    setUploadError(null);
    setIngestResult(null);
    setLiveStatus(null);
    setSelectedFile(null);
    pollCountRef.current = 0;
  }

  // ── Derived values ────────────────────────────────────────────────────────

  const isDuplicate =
    ingestResult !== null &&
    (ingestResult.is_link === true ||
      ingestResult.message?.toLowerCase().includes('duplicate'));

  const linkedUid =
    isDuplicate && typeof ingestResult?.linked_to_uid === 'string'
      ? ingestResult.linked_to_uid
      : null;

  const limitLabel = systemInfo
    ? `Max ${formatBytes(systemInfo.max_upload_size_bytes)} · ${systemInfo.allowed_extensions
        .map((e) => e.replace('.', '').toUpperCase())
        .join(', ')}`
    : systemInfoError
      ? 'Upload limits unavailable'
      : 'Loading limits…';

  const isActive = phase === 'uploading' || phase === 'polling';

  // ─────────────────────────────────────────────────────────────────────────
  // Render
  // ─────────────────────────────────────────────────────────────────────────

  return (
    <div className="min-h-screen bg-slate-900 flex items-start justify-center px-4 py-10">
      <div className="w-full max-w-xl space-y-6">

        {/* Header */}
        <div>
          <h1 className="text-2xl font-bold text-white tracking-tight">Upload Desk</h1>
          <p className="mt-1 text-sm text-slate-400">
            Drag a file into the zone or click to browse.
          </p>
        </div>

        {/* System info warning */}
        {systemInfoError && (
          <div className="flex items-start gap-2 rounded-lg border border-yellow-500/40 bg-yellow-500/10 px-4 py-3 text-sm text-yellow-300">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
            <span>{systemInfoError}</span>
          </div>
        )}

        {/* Drop zone — hidden when done/error */}
        {phase !== 'done' && phase !== 'error' && (
          <div
            onDragOver={onDragOver}
            onDragLeave={onDragLeave}
            onDrop={onDrop}
            onClick={() => !isActive && fileInputRef.current?.click()}
            className={[
              'relative flex flex-col items-center justify-center gap-4 rounded-2xl border-2 border-dashed px-6 py-14 transition-colors',
              isActive
                ? 'cursor-not-allowed border-slate-600 bg-slate-800/40'
                : isDragOver
                  ? 'cursor-copy border-teal-400 bg-teal-900/20'
                  : 'cursor-pointer border-slate-600 bg-slate-800/60 hover:border-teal-500 hover:bg-slate-800',
            ].join(' ')}
          >
            {phase === 'uploading' ? (
              <>
                <Loader2 className="h-10 w-10 animate-spin text-teal-400" />
                <p className="text-sm text-slate-300">
                  Uploading <span className="font-medium text-white">{selectedFile?.name}</span>…
                </p>
              </>
            ) : phase === 'polling' ? (
              <>
                <RefreshCw className="h-10 w-10 animate-spin text-teal-400" />
                <p className="text-sm text-slate-300">Processing — waiting for pipeline…</p>
              </>
            ) : (
              <>
                <div className="flex h-16 w-16 items-center justify-center rounded-full border border-slate-600 bg-slate-800">
                  {isDragOver ? (
                    <CloudUpload className="h-8 w-8 text-teal-300" />
                  ) : (
                    <FileUp className="h-8 w-8 text-slate-400" />
                  )}
                </div>
                <div className="text-center">
                  <p className="text-sm font-medium text-slate-200">
                    Drop file here or{' '}
                    <span className="text-teal-400 underline underline-offset-2">browse</span>
                  </p>
                  <p className="mt-1 text-xs text-slate-500">{limitLabel}</p>
                </div>
              </>
            )}
          </div>
        )}

        {/* Hidden file input */}
        <input
          ref={fileInputRef}
          type="file"
          className="hidden"
          onChange={onFileChange}
          disabled={isActive}
        />

        {/* Validation error */}
        {validationError && (
          <div className="flex items-start gap-2 rounded-lg border border-red-500/40 bg-red-500/10 px-4 py-3 text-sm text-red-300">
            <XCircle className="mt-0.5 h-4 w-4 shrink-0" />
            <span>{validationError}</span>
          </div>
        )}

        {/* Upload error */}
        {phase === 'error' && uploadError && (
          <div className="space-y-3">
            <div className="flex items-start gap-2 rounded-lg border border-red-500/40 bg-red-500/10 px-4 py-3 text-sm text-red-300">
              <XCircle className="mt-0.5 h-4 w-4 shrink-0" />
              <span>{uploadError}</span>
            </div>
            <button
              onClick={handleReset}
              className="flex w-full items-center justify-center gap-2 rounded-lg border border-slate-600 bg-slate-800 py-2.5 text-sm font-medium text-slate-200 transition hover:bg-slate-700"
            >
              <RefreshCw className="h-4 w-4" /> Upload another file
            </button>
          </div>
        )}

        {/* Result card */}
        {ingestResult && (phase === 'polling' || phase === 'done') && (
          <div className="rounded-2xl border border-slate-700 bg-slate-800 p-5 space-y-4">

            {/* Duplicate banner */}
            {isDuplicate && (
              <div className="flex items-start gap-2 rounded-lg border border-yellow-500/40 bg-yellow-500/10 px-4 py-3 text-sm text-yellow-300">
                <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
                <span>
                  Duplicate detected
                  {linkedUid ? (
                    <>
                      {' '}— linked to{' '}
                      <span className="font-mono font-semibold">{linkedUid}</span>
                    </>
                  ) : (
                    ''
                  )}
                </span>
              </div>
            )}

            {/* Status row */}
            <div className="flex items-center justify-between gap-2">
              <div className="flex items-center gap-2">
                {phase === 'polling' ? (
                  <Loader2 className="h-4 w-4 animate-spin text-teal-400" />
                ) : (
                  <CheckCircle2 className="h-4 w-4 text-teal-400" />
                )}
                <span className="text-sm font-semibold text-white">
                  {ingestResult.file_name}
                </span>
              </div>
              <span
                className={[
                  'rounded-full border px-2.5 py-0.5 text-xs font-semibold uppercase tracking-wide',
                  statusBadgeClass(liveStatus ?? ingestResult.status),
                ].join(' ')}
              >
                {liveStatus ?? ingestResult.status}
              </span>
            </div>

            {/* Meta grid */}
            <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
              <div>
                <dt className="text-xs text-slate-500 uppercase tracking-wide">UID</dt>
                <dd className="mt-0.5 font-mono text-slate-200 break-all">{ingestResult.uid}</dd>
              </div>
              <div>
                <dt className="text-xs text-slate-500 uppercase tracking-wide">Queue</dt>
                <dd className="mt-0.5 font-medium text-slate-200">{ingestResult.queue}</dd>
              </div>
              <div className="col-span-2">
                <dt className="text-xs text-slate-500 uppercase tracking-wide">SHA-256</dt>
                <dd className="mt-0.5 font-mono text-slate-400">{truncateSha(ingestResult.sha256)}</dd>
              </div>
              {ingestResult.message && (
                <div className="col-span-2">
                  <dt className="text-xs text-slate-500 uppercase tracking-wide">Message</dt>
                  <dd className="mt-0.5 text-slate-300">{ingestResult.message}</dd>
                </div>
              )}
            </dl>

            {/* Upload another */}
            {phase === 'done' && (
              <button
                onClick={handleReset}
                className="flex w-full items-center justify-center gap-2 rounded-lg border border-slate-600 bg-slate-700/60 py-2.5 text-sm font-medium text-slate-200 transition hover:bg-slate-700"
              >
                <FileUp className="h-4 w-4" /> Upload another file
              </button>
            )}
          </div>
        )}
      </div>
    </div>
  );
};
