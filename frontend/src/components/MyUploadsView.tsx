import React, { useState, useEffect, useCallback } from 'react';
import {
  ArrowRight,
  Download,
  AlertCircle,
  RefreshCw,
  FolderArchive,
  Loader2,
  CheckCircle2,
  CheckCircle,
  Clock,
  RotateCcw,
  Archive,
} from 'lucide-react';
import { BASE_URL, getAuthToken } from '../api/client';

export interface BatchSummaryItem {
  batch_id: string;
  number: number;
  name: string;
  created_at: string;
  file_count: number;
  progress_percent: number;
  counts_by_type: Record<string, number>;
  counts_by_status: Record<string, number>;
  needs_check_count: number;
  is_finished: boolean;
  last_downloaded_at?: string | null;
}

export interface BatchListResponse {
  items: BatchSummaryItem[];
  total: number;
  page: number;
  page_size: number;
}

export interface DownloadHistoryItem {
  id: string;
  batch_id: string;
  batch_number?: number | null;
  batch_name?: string | null;
  status: 'PREPARING' | 'READY' | 'DOWNLOADED' | 'FAILED' | 'EXPIRED';
  file_count: number;
  size_bytes: number;
  requested_at: string;
  completed_at?: string | null;
  last_downloaded_at?: string | null;
  error_message?: string | null;
  download_url: string;
}

export interface DownloadListResponse {
  items: DownloadHistoryItem[];
  total: number;
  page: number;
  page_size: number;
}

interface MyUploadsViewProps {
  onSelectBatch: (batchId: string) => void;
  onNavigateUpload: () => void;
}

export const MyUploadsView: React.FC<MyUploadsViewProps> = ({
  onSelectBatch,
  onNavigateUpload,
}) => {
  const [subTab, setSubTab] = useState<'uploads' | 'downloads'>('uploads');
  const [batches, setBatches] = useState<BatchSummaryItem[]>([]);
  const [downloads, setDownloads] = useState<DownloadHistoryItem[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Download & retry action state
  const [actionId, setActionId] = useState<string | null>(null);
  const [actionError, setActionError] = useState<{ message: string; resolution: string } | null>(null);

  const formatSize = (bytes: number): string => {
    if (!bytes || bytes <= 0) return '0 B';
    const units = ['B', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(1024));
    return `${(bytes / Math.pow(1024, i)).toFixed(1)} ${units[i]}`;
  };

  const formatDate = (isoString?: string | null) => {
    if (!isoString) return '';
    try {
      const d = new Date(isoString);
      return d.toLocaleDateString('en-GB', {
        day: 'numeric',
        month: 'short',
        hour: 'numeric',
        minute: '2-digit',
        hour12: true,
      });
    } catch {
      return isoString;
    }
  };

  const fetchBatches = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const headers: Record<string, string> = {};
      const token = getAuthToken();
      if (token) headers['Authorization'] = `Bearer ${token}`;

      const res = await fetch(`${BASE_URL}/api/v1/batches?page=1&page_size=50`, {
        headers,
      });

      if (!res.ok) {
        throw new Error(`Failed to load uploads (${res.status} ${res.statusText})`);
      }

      const data: BatchListResponse = await res.json();
      setBatches(data.items || []);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Error fetching uploads');
    } finally {
      setIsLoading(false);
    }
  }, []);

  const fetchDownloads = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const headers: Record<string, string> = {};
      const token = getAuthToken();
      if (token) headers['Authorization'] = `Bearer ${token}`;

      const res = await fetch(`${BASE_URL}/api/v1/downloads?page=1&page_size=50`, {
        headers,
      });

      if (!res.ok) {
        throw new Error(`Failed to load downloads (${res.status} ${res.statusText})`);
      }

      const data: DownloadListResponse = await res.json();
      setDownloads(data.items || []);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Error fetching downloads');
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    if (subTab === 'uploads') {
      void fetchBatches();
    } else {
      void fetchDownloads();
    }
  }, [subTab, fetchBatches, fetchDownloads]);

  // Auto-polling when downloads are preparing
  useEffect(() => {
    if (subTab !== 'downloads') return;
    const hasPreparing = downloads.some((d) => d.status === 'PREPARING');
    if (!hasPreparing) return;

    const interval = setInterval(() => {
      void fetchDownloads();
    }, 2000);
    return () => clearInterval(interval);
  }, [subTab, downloads, fetchDownloads]);

  // Direct batch export request
  const handleDownloadBatchZip = async (batchId: string, batchName: string) => {
    setActionId(batchId);
    setActionError(null);
    try {
      const headers: Record<string, string> = {};
      const token = getAuthToken();
      if (token) headers['Authorization'] = `Bearer ${token}`;

      // Create download record via POST /api/v1/batches/{id}/downloads
      const createRes = await fetch(`${BASE_URL}/api/v1/batches/${encodeURIComponent(batchId)}/downloads`, {
        method: 'POST',
        headers,
      });

      if (!createRes.ok) {
        const errJson = await createRes.json().catch(() => null);
        throw new Error(errJson?.detail || `Export failed (${createRes.status})`);
      }

      const dlItem: DownloadHistoryItem = await createRes.json();

      // If immediately ready, stream file now
      if (dlItem.status === 'READY') {
        const fileRes = await fetch(`${BASE_URL}/api/v1/downloads/${dlItem.id}/file`, { headers });
        if (!fileRes.ok) throw new Error('Failed to stream prepared zip');
        const blob = await fileRes.blob();
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `${batchName.toLowerCase().replace(/\s+/g, '_')}_sorted.zip`;
        document.body.appendChild(a);
        a.click();
        a.remove();
        window.URL.revokeObjectURL(url);
        // Refresh batch row to show Last downloaded date
        void fetchBatches();
      } else {
        // Switch to downloads tab so user sees preparation progress
        setSubTab('downloads');
      }
    } catch (e) {
      setActionError({
        message: e instanceof Error ? e.message : 'Could not download zip archive.',
        resolution: 'Please check your connection and click "Download (zip)" again.',
      });
    } finally {
      setActionId(null);
    }
  };

  // Download prepared file from My downloads
  const handleDownloadFile = async (downloadId: string, batchName?: string | null) => {
    setActionId(downloadId);
    setActionError(null);
    try {
      const headers: Record<string, string> = {};
      const token = getAuthToken();
      if (token) headers['Authorization'] = `Bearer ${token}`;

      const res = await fetch(`${BASE_URL}/api/v1/downloads/${encodeURIComponent(downloadId)}/file`, {
        headers,
      });

      if (!res.ok) {
        const errJson = await res.json().catch(() => null);
        throw new Error(errJson?.detail || `Download failed (${res.status})`);
      }

      const blob = await res.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `${(batchName || 'sorted_files').toLowerCase().replace(/\s+/g, '_')}_sorted.zip`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.URL.revokeObjectURL(url);

      void fetchDownloads();
    } catch (e) {
      setActionError({
        message: e instanceof Error ? e.message : 'Could not stream zip archive.',
        resolution: 'If the archive expired, click "Try again" to rebuild it.',
      });
    } finally {
      setActionId(null);
    }
  };

  // Retry / rebuild failed or expired download
  const handleRetryDownload = async (batchId: string) => {
    setActionId(batchId);
    setActionError(null);
    try {
      const headers: Record<string, string> = {};
      const token = getAuthToken();
      if (token) headers['Authorization'] = `Bearer ${token}`;

      const createRes = await fetch(`${BASE_URL}/api/v1/batches/${encodeURIComponent(batchId)}/downloads`, {
        method: 'POST',
        headers,
      });

      if (!createRes.ok) {
        const errJson = await createRes.json().catch(() => null);
        throw new Error(errJson?.detail || `Retry failed (${createRes.status})`);
      }

      await fetchDownloads();
    } catch (e) {
      setActionError({
        message: e instanceof Error ? e.message : 'Could not regenerate archive.',
        resolution: 'Please ensure the batch contains valid files and try again.',
      });
    } finally {
      setActionId(null);
    }
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 pb-4 border-b border-slate-800">
        <div>
          <h1 className="text-2xl font-bold text-white flex items-center space-x-2">
            <FolderArchive className="w-6 h-6 text-teal-400" />
            <span>My uploads</span>
          </h1>
          <p className="text-sm text-slate-400 mt-1">
            Review your previously sorted file batches or download them anytime.
          </p>
        </div>
        <div className="flex items-center space-x-3">
          <button
            onClick={() => (subTab === 'uploads' ? void fetchBatches() : void fetchDownloads())}
            disabled={isLoading}
            aria-label="Refresh list"
            className="flex items-center space-x-2 px-3 py-2 text-sm bg-slate-800/80 hover:bg-slate-700/80 text-slate-300 rounded-lg border border-slate-700/60 transition-colors focus:ring-2 focus:ring-teal-400 focus:outline-none"
          >
            <RefreshCw className={`w-4 h-4 ${isLoading ? 'animate-spin' : ''}`} />
            <span>Refresh</span>
          </button>
          <button
            onClick={onNavigateUpload}
            aria-label="Start new upload"
            className="flex items-center space-x-2 px-4 py-2 text-sm font-semibold bg-teal-500 hover:bg-teal-400 text-slate-950 rounded-lg shadow-lg shadow-teal-500/20 transition-colors focus:ring-2 focus:ring-teal-400 focus:outline-none"
          >
            <span>Upload files</span>
            <ArrowRight className="w-4 h-4" />
          </button>
        </div>
      </div>

      {/* Sub-tabs: Upload batches & My downloads */}
      <div className="flex items-center space-x-2 border-b border-slate-800/80 pb-2">
        <button
          onClick={() => setSubTab('uploads')}
          className={`flex items-center space-x-2 px-4 py-2 text-sm font-semibold rounded-lg transition-colors focus:ring-2 focus:ring-teal-400 focus:outline-none ${
            subTab === 'uploads'
              ? 'bg-teal-500/15 text-teal-300 border border-teal-500/30'
              : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/50'
          }`}
        >
          <FolderArchive className="w-4 h-4" />
          <span>Upload batches</span>
          <span className="text-xs px-2 py-0.5 rounded-full bg-slate-800 text-slate-400 border border-slate-700/60 font-mono">
            {batches.length}
          </span>
        </button>

        <button
          onClick={() => setSubTab('downloads')}
          className={`flex items-center space-x-2 px-4 py-2 text-sm font-semibold rounded-lg transition-colors focus:ring-2 focus:ring-teal-400 focus:outline-none ${
            subTab === 'downloads'
              ? 'bg-teal-500/15 text-teal-300 border border-teal-500/30'
              : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/50'
          }`}
        >
          <Archive className="w-4 h-4" />
          <span>My downloads</span>
          {downloads.length > 0 && (
            <span className="text-xs px-2 py-0.5 rounded-full bg-slate-800 text-slate-400 border border-slate-700/60 font-mono">
              {downloads.length}
            </span>
          )}
        </button>
      </div>

      {/* Clear error alert with resolution */}
      {actionError && (
        <div
          role="alert"
          className="p-4 rounded-xl bg-rose-500/10 border border-rose-500/30 text-rose-300 text-sm flex items-start space-x-3"
        >
          <AlertCircle className="w-5 h-5 flex-shrink-0 mt-0.5 text-rose-400" />
          <div>
            <p className="font-semibold">{actionError.message}</p>
            <p className="text-xs text-rose-300/80 mt-1">{actionError.resolution}</p>
          </div>
        </div>
      )}

      {error && (
        <div
          role="alert"
          className="p-4 rounded-xl bg-rose-500/10 border border-rose-500/30 text-rose-300 text-sm flex items-center space-x-2"
        >
          <AlertCircle className="w-4 h-4 flex-shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {/* ----------------- SUB-TAB 1: UPLOAD BATCHES ----------------- */}
      {subTab === 'uploads' && (
        <>
          {isLoading && batches.length === 0 && (
            <div className="py-20 text-center text-slate-400 flex flex-col items-center justify-center space-y-3">
              <Loader2 className="w-8 h-8 text-teal-400 animate-spin" />
              <p className="text-sm">Loading your uploads...</p>
            </div>
          )}

          {!isLoading && batches.length === 0 && (
            <div className="py-16 text-center rounded-2xl border border-dashed border-slate-800 bg-slate-900/40 p-8">
              <div className="w-16 h-16 mx-auto rounded-2xl bg-teal-500/10 border border-teal-500/20 flex items-center justify-center text-teal-400 mb-4">
                <FolderArchive className="w-8 h-8" />
              </div>
              <h3 className="text-lg font-semibold text-white">No uploads yet.</h3>
              <p className="text-sm text-slate-400 max-w-md mx-auto mt-1 mb-6">
                Upload your first batch of documents to see them classified and sorted automatically.
              </p>
              <button
                onClick={onNavigateUpload}
                className="inline-flex items-center space-x-2 px-5 py-2.5 text-sm font-semibold bg-teal-500 hover:bg-teal-400 text-slate-950 rounded-xl shadow-lg shadow-teal-500/20 transition-all focus:ring-2 focus:ring-teal-400 focus:outline-none"
              >
                <span>Upload files now</span>
                <ArrowRight className="w-4 h-4" />
              </button>
            </div>
          )}

          <div className="space-y-4">
            {batches.map((batch) => {
              const isDone = batch.progress_percent >= 100 || batch.is_finished;
              const isDownloading = actionId === batch.batch_id;

              return (
                <div
                  key={batch.batch_id}
                  className="p-5 rounded-2xl bg-slate-900/70 border border-slate-800 hover:border-slate-700/80 transition-all shadow-sm space-y-4"
                >
                  <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
                    <div>
                      <div className="flex flex-wrap items-center gap-2">
                        <h2 className="text-base font-bold text-white">
                          {batch.name || `Upload #${batch.number}`}
                        </h2>
                        <span className="text-xs text-slate-500">·</span>
                        <span className="text-xs text-slate-400 font-medium">
                          {formatDate(batch.created_at)}
                        </span>
                        <span className="text-xs text-slate-500">·</span>
                        <span className="text-xs text-slate-300 font-medium">
                          {batch.file_count} {batch.file_count === 1 ? 'file' : 'files'}
                        </span>
                        <span className="text-xs text-slate-500">·</span>
                        <span
                          className={`text-xs px-2 py-0.5 rounded-full font-semibold ${
                            isDone
                              ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20'
                              : 'bg-amber-500/10 text-amber-400 border border-amber-500/20 animate-pulse'
                          }`}
                        >
                          {isDone ? '100% done' : `${batch.progress_percent}% done`}
                        </span>
                      </div>

                      {/* Download status info */}
                      <div className="text-xs text-slate-400 mt-1.5 flex items-center space-x-1.5">
                        <Download className="w-3.5 h-3.5 text-slate-500" />
                        <span className="font-mono text-slate-400">
                          {batch.last_downloaded_at
                            ? `Last downloaded ${formatDate(batch.last_downloaded_at)}`
                            : 'Not downloaded yet'}
                        </span>
                      </div>

                      {/* Plain language summary pills */}
                      <div className="flex flex-wrap items-center gap-2 mt-2">
                        {batch.needs_check_count > 0 && (
                          <span className="text-xs px-2.5 py-0.5 rounded-full bg-amber-500/15 text-amber-300 border border-amber-500/30 font-medium">
                            {batch.needs_check_count} need a quick check
                          </span>
                        )}
                        {Object.entries(batch.counts_by_type || {}).map(([type, count]) => (
                          <span
                            key={type}
                            className="text-xs px-2 py-0.5 rounded-md bg-slate-800 text-slate-400 border border-slate-700/60 font-mono"
                          >
                            {type.replace(/_/g, ' ')}: {count}
                          </span>
                        ))}
                      </div>
                    </div>

                    {/* Actions */}
                    <div className="flex items-center space-x-3 pt-2 sm:pt-0">
                      <button
                        onClick={() => handleDownloadBatchZip(batch.batch_id, batch.name || `Upload #${batch.number}`)}
                        disabled={isDownloading || batch.file_count === 0}
                        aria-label={`Download zip archive for ${batch.name || `Upload #${batch.number}`}`}
                        className="flex items-center space-x-1.5 px-3 py-1.5 text-xs font-semibold rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 transition-colors disabled:opacity-50 focus:ring-2 focus:ring-teal-400 focus:outline-none"
                      >
                        {isDownloading ? (
                          <Loader2 className="w-3.5 h-3.5 animate-spin text-teal-400" />
                        ) : (
                          <Download className="w-3.5 h-3.5 text-teal-400" />
                        )}
                        <span>{isDownloading ? 'Downloading...' : 'Download (zip)'}</span>
                      </button>

                      <button
                        onClick={() => onSelectBatch(batch.batch_id)}
                        aria-label={`View sorted files for ${batch.name || `Upload #${batch.number}`}`}
                        className="flex items-center space-x-1.5 px-3.5 py-1.5 text-xs font-semibold rounded-lg bg-teal-500/15 hover:bg-teal-500/25 text-teal-300 border border-teal-500/30 transition-colors focus:ring-2 focus:ring-teal-400 focus:outline-none"
                      >
                        <span>View</span>
                        <ArrowRight className="w-3.5 h-3.5" />
                      </button>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        </>
      )}

      {/* ----------------- SUB-TAB 2: MY DOWNLOADS ----------------- */}
      {subTab === 'downloads' && (
        <>
          {isLoading && downloads.length === 0 && (
            <div className="py-20 text-center text-slate-400 flex flex-col items-center justify-center space-y-3">
              <Loader2 className="w-8 h-8 text-teal-400 animate-spin" />
              <p className="text-sm">Loading your download history...</p>
            </div>
          )}

          {!isLoading && downloads.length === 0 && (
            <div className="py-16 text-center rounded-2xl border border-dashed border-slate-800 bg-slate-900/40 p-8">
              <div className="w-16 h-16 mx-auto rounded-2xl bg-teal-500/10 border border-teal-500/20 flex items-center justify-center text-teal-400 mb-4">
                <Archive className="w-8 h-8" />
              </div>
              <h3 className="text-lg font-semibold text-white">No downloads yet.</h3>
              <p className="text-sm text-slate-400 max-w-md mx-auto mt-1 mb-6">
                When you request a sorted zip archive, it will appear here so you can download it again anytime.
              </p>
              <button
                onClick={() => setSubTab('uploads')}
                className="inline-flex items-center space-x-2 px-5 py-2.5 text-sm font-semibold bg-teal-500 hover:bg-teal-400 text-slate-950 rounded-xl shadow-lg shadow-teal-500/20 transition-all focus:ring-2 focus:ring-teal-400 focus:outline-none"
              >
                <span>Browse your uploads</span>
                <ArrowRight className="w-4 h-4" />
              </button>
            </div>
          )}

          <div className="space-y-4">
            {downloads.map((item) => {
              const isItemBusy = actionId === item.id || actionId === item.batch_id;

              return (
                <div
                  key={item.id}
                  className="p-5 rounded-2xl bg-slate-900/70 border border-slate-800 hover:border-slate-700/80 transition-all shadow-sm space-y-4"
                >
                  <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
                    <div>
                      {/* Name, number and dates */}
                      <div className="flex flex-wrap items-center gap-2">
                        <h2 className="text-base font-bold text-white">
                          {item.batch_name || `Upload #${item.batch_number || 1}`}
                        </h2>
                        <span className="text-xs text-slate-500">·</span>
                        <span className="text-xs text-slate-400 font-medium">
                          Requested {formatDate(item.requested_at)}
                        </span>
                        <span className="text-xs text-slate-500">·</span>
                        <span className="text-xs text-slate-300 font-medium">
                          {item.file_count} {item.file_count === 1 ? 'file' : 'files'}
                        </span>
                        {item.size_bytes > 0 && (
                          <>
                            <span className="text-xs text-slate-500">·</span>
                            <span className="text-xs text-teal-400 font-mono font-medium">
                              {formatSize(item.size_bytes)}
                            </span>
                          </>
                        )}
                      </div>

                      {/* Status Badges with Icon + Text (Never color alone) */}
                      <div className="flex flex-wrap items-center gap-2 mt-2">
                        {item.status === 'PREPARING' && (
                          <span className="inline-flex items-center space-x-1.5 text-xs px-2.5 py-1 rounded-full bg-amber-500/15 text-amber-300 border border-amber-500/30 font-medium animate-pulse">
                            <Loader2 className="w-3.5 h-3.5 animate-spin text-amber-400" />
                            <span>Preparing zip archive</span>
                          </span>
                        )}

                        {item.status === 'READY' && (
                          <span className="inline-flex items-center space-x-1.5 text-xs px-2.5 py-1 rounded-full bg-emerald-500/15 text-emerald-300 border border-emerald-500/30 font-medium">
                            <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" />
                            <span>Ready to download</span>
                          </span>
                        )}

                        {item.status === 'DOWNLOADED' && (
                          <span className="inline-flex items-center space-x-1.5 text-xs px-2.5 py-1 rounded-full bg-teal-500/15 text-teal-300 border border-teal-500/30 font-medium">
                            <CheckCircle className="w-3.5 h-3.5 text-teal-400" />
                            <span>Downloaded {item.last_downloaded_at ? formatDate(item.last_downloaded_at) : ''}</span>
                          </span>
                        )}

                        {item.status === 'FAILED' && (
                          <span className="inline-flex items-center space-x-1.5 text-xs px-2.5 py-1 rounded-full bg-rose-500/15 text-rose-300 border border-rose-500/30 font-medium">
                            <AlertCircle className="w-3.5 h-3.5 text-rose-400" />
                            <span>Preparation failed</span>
                          </span>
                        )}

                        {item.status === 'EXPIRED' && (
                          <span className="inline-flex items-center space-x-1.5 text-xs px-2.5 py-1 rounded-full bg-slate-800 text-slate-400 border border-slate-700/60 font-medium">
                            <Clock className="w-3.5 h-3.5 text-slate-400" />
                            <span>Archive expired (can be rebuilt)</span>
                          </span>
                        )}

                        {item.error_message && (
                          <span className="text-xs text-rose-300/90 font-mono">
                            {item.error_message}
                          </span>
                        )}
                      </div>
                    </div>

                    {/* Action Buttons */}
                    <div className="flex items-center space-x-3 pt-2 sm:pt-0">
                      {item.status === 'READY' && (
                        <button
                          onClick={() => handleDownloadFile(item.id, item.batch_name)}
                          disabled={isItemBusy}
                          aria-label={`Download zip for ${item.batch_name || 'upload'}`}
                          className="flex items-center space-x-1.5 px-4 py-2 text-xs font-semibold rounded-lg bg-teal-500 hover:bg-teal-400 text-slate-950 shadow-md shadow-teal-500/20 transition-all focus:ring-2 focus:ring-teal-400 focus:outline-none disabled:opacity-50"
                        >
                          {isItemBusy ? (
                            <Loader2 className="w-3.5 h-3.5 animate-spin" />
                          ) : (
                            <Download className="w-3.5 h-3.5" />
                          )}
                          <span>{isItemBusy ? 'Streaming...' : 'Download'}</span>
                        </button>
                      )}

                      {item.status === 'DOWNLOADED' && (
                        <button
                          onClick={() => handleDownloadFile(item.id, item.batch_name)}
                          disabled={isItemBusy}
                          aria-label={`Download again for ${item.batch_name || 'upload'}`}
                          className="flex items-center space-x-1.5 px-3.5 py-2 text-xs font-semibold rounded-lg bg-slate-800 hover:bg-slate-700 text-teal-300 border border-teal-500/30 transition-colors focus:ring-2 focus:ring-teal-400 focus:outline-none disabled:opacity-50"
                        >
                          {isItemBusy ? (
                            <Loader2 className="w-3.5 h-3.5 animate-spin" />
                          ) : (
                            <RotateCcw className="w-3.5 h-3.5" />
                          )}
                          <span>{isItemBusy ? 'Streaming...' : 'Download again'}</span>
                        </button>
                      )}

                      {(item.status === 'FAILED' || item.status === 'EXPIRED') && (
                        <button
                          onClick={() => handleRetryDownload(item.batch_id)}
                          disabled={isItemBusy}
                          aria-label={`Try assembling download again for ${item.batch_name || 'upload'}`}
                          className="flex items-center space-x-1.5 px-3.5 py-2 text-xs font-semibold rounded-lg bg-rose-500/15 hover:bg-rose-500/25 text-rose-300 border border-rose-500/30 transition-colors focus:ring-2 focus:ring-rose-400 focus:outline-none disabled:opacity-50"
                        >
                          {isItemBusy ? (
                            <Loader2 className="w-3.5 h-3.5 animate-spin" />
                          ) : (
                            <RotateCcw className="w-3.5 h-3.5" />
                          )}
                          <span>{isItemBusy ? 'Rebuilding...' : 'Try again'}</span>
                        </button>
                      )}

                      {item.status === 'PREPARING' && (
                        <button
                          disabled
                          aria-label="Archive is preparing in background"
                          className="flex items-center space-x-1.5 px-3.5 py-2 text-xs font-medium rounded-lg bg-slate-800/60 text-slate-400 border border-slate-700/50 cursor-not-allowed opacity-80"
                        >
                          <Loader2 className="w-3.5 h-3.5 animate-spin text-amber-400" />
                          <span>Preparing...</span>
                        </button>
                      )}
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        </>
      )}
    </div>
  );
};
