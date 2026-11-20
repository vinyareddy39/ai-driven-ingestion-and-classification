import React, { useState, useEffect, useCallback } from 'react';
import {
  ArrowRight,
  Download,
  AlertCircle,
  RefreshCw,
  FolderArchive,
  Loader2,
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
}

export interface BatchListResponse {
  items: BatchSummaryItem[];
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
  const [batches, setBatches] = useState<BatchSummaryItem[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [downloadingId, setDownloadingId] = useState<string | null>(null);
  const [downloadError, setDownloadError] = useState<string | null>(null);

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

  useEffect(() => {
    void fetchBatches();
  }, [fetchBatches]);

  const handleDownloadZip = async (batchId: string, batchName: string) => {
    setDownloadingId(batchId);
    setDownloadError(null);
    try {
      const headers: Record<string, string> = {};
      const token = getAuthToken();
      if (token) headers['Authorization'] = `Bearer ${token}`;

      const res = await fetch(`${BASE_URL}/api/v1/batches/${encodeURIComponent(batchId)}/export`, {
        headers,
      });

      if (!res.ok) {
        const errJson = await res.json().catch(() => null);
        throw new Error(errJson?.detail || `Export failed (${res.status})`);
      }

      const blob = await res.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `${batchName.toLowerCase().replace(/\s+/g, '_')}_sorted.zip`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.URL.revokeObjectURL(url);
    } catch (e) {
      setDownloadError(e instanceof Error ? e.message : 'Failed to download zip');
    } finally {
      setDownloadingId(null);
    }
  };

  const formatDate = (isoString: string) => {
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
            onClick={() => void fetchBatches()}
            disabled={isLoading}
            className="flex items-center space-x-2 px-3 py-2 text-sm bg-slate-800/80 hover:bg-slate-700/80 text-slate-300 rounded-lg border border-slate-700/60 transition-colors"
          >
            <RefreshCw className={`w-4 h-4 ${isLoading ? 'animate-spin' : ''}`} />
            <span>Refresh</span>
          </button>
          <button
            onClick={onNavigateUpload}
            className="flex items-center space-x-2 px-4 py-2 text-sm font-semibold bg-teal-500 hover:bg-teal-400 text-slate-950 rounded-lg shadow-lg shadow-teal-500/20 transition-colors"
          >
            <span>Upload files</span>
            <ArrowRight className="w-4 h-4" />
          </button>
        </div>
      </div>

      {downloadError && (
        <div className="p-4 rounded-xl bg-rose-500/10 border border-rose-500/30 text-rose-300 text-sm flex items-center space-x-2">
          <AlertCircle className="w-4 h-4 flex-shrink-0" />
          <span>{downloadError}</span>
        </div>
      )}

      {error && (
        <div className="p-4 rounded-xl bg-rose-500/10 border border-rose-500/30 text-rose-300 text-sm flex items-center space-x-2">
          <AlertCircle className="w-4 h-4 flex-shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {/* Loading state */}
      {isLoading && batches.length === 0 && (
        <div className="py-20 text-center text-slate-400 flex flex-col items-center justify-center space-y-3">
          <Loader2 className="w-8 h-8 text-teal-400 animate-spin" />
          <p className="text-sm">Loading your uploads...</p>
        </div>
      )}

      {/* Empty State */}
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
            className="inline-flex items-center space-x-2 px-5 py-2.5 text-sm font-semibold bg-teal-500 hover:bg-teal-400 text-slate-950 rounded-xl shadow-lg shadow-teal-500/20 transition-all"
          >
            <span>Upload files now</span>
            <ArrowRight className="w-4 h-4" />
          </button>
        </div>
      )}

      {/* Batches List */}
      <div className="space-y-4">
        {batches.map((batch) => {
          const isDone = batch.progress_percent >= 100 || batch.is_finished;
          const isDownloading = downloadingId === batch.batch_id;

          return (
            <div
              key={batch.batch_id}
              className="p-5 rounded-2xl bg-slate-900/70 border border-slate-800 hover:border-slate-700/80 transition-all shadow-sm space-y-4"
            >
              <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
                <div>
                  <div className="flex items-center space-x-3">
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

                  {/* Plain language summary sentence */}
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
                    onClick={() => handleDownloadZip(batch.batch_id, batch.name || `Upload #${batch.number}`)}
                    disabled={isDownloading || batch.file_count === 0}
                    className="flex items-center space-x-1.5 px-3 py-1.5 text-xs font-semibold rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 transition-colors disabled:opacity-50"
                  >
                    {isDownloading ? (
                      <Loader2 className="w-3.5 h-3.5 animate-spin text-teal-400" />
                    ) : (
                      <Download className="w-3.5 h-3.5 text-teal-400" />
                    )}
                    <span>Download (zip)</span>
                  </button>

                  <button
                    onClick={() => onSelectBatch(batch.batch_id)}
                    className="flex items-center space-x-1.5 px-3.5 py-1.5 text-xs font-semibold rounded-lg bg-teal-500/15 hover:bg-teal-500/25 text-teal-300 border border-teal-500/30 transition-colors"
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
    </div>
  );
};
