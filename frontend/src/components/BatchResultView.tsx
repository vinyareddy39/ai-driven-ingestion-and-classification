import React, { useEffect, useState, useCallback, useMemo } from 'react';
import {
  CheckCircle2,
  Clock,
  AlertTriangle,
  ShieldAlert,
  ArrowRight,
  RefreshCw,
  FileText,
  ChevronDown,
  ChevronRight,
  Download,
  Eye,
  X,
  Loader2,
  ArrowLeft,
} from 'lucide-react';
import { BASE_URL, getAuthToken, getActiveRole } from '../api/client';
import { AuthenticatedImage } from './AuthenticatedImage';

export interface BatchFileItem {
  uid: string;
  file_name: string;
  doc_type: string;
  review_status: string;
  plain_status: string;
  confidence: number;
  how_sure: number;
  review_reason?: string | null;
  error_detail?: string | null;
  is_link?: boolean;
  created_at: string;
}

export interface BatchDetailResponse {
  batch_id: string;
  number: number;
  name: string;
  user_id?: string | null;
  created_at?: string;
  progress: {
    total: number;
    queued: number;
    processing: number;
    done: number;
    needs_review: number;
    failed: number;
    quarantined: number;
    duplicate: number;
  };
  progress_percent: number;
  counts_by_type: Record<string, number>;
  counts_by_status: Record<string, number>;
  needs_check_count: number;
  is_finished: boolean;
  items: BatchFileItem[];
  total_items: number;
  page: number;
  page_size: number;
}

interface BatchResultViewProps {
  batchId: string;
  onReset: () => void;
  onNavigateTab?: (tab: string) => void;
  onOpenReviewQueue?: (batchId?: string) => void;
}

export const BatchResultView: React.FC<BatchResultViewProps> = ({
  batchId,
  onReset,
  onNavigateTab,
  onOpenReviewQueue,
}) => {
  const [data, setData] = useState<BatchDetailResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [collapsedTypes, setCollapsedTypes] = useState<Record<string, boolean>>({});
  const [downloading, setDownloading] = useState(false);
  const [downloadError, setDownloadError] = useState<string | null>(null);

  // File detail modal state
  const [selectedFileUid, setSelectedFileUid] = useState<string | null>(null);
  const [fileDetail, setFileDetail] = useState<any | null>(null);
  const [fileDetailLoading, setFileDetailLoading] = useState(false);

  const fetchBatch = useCallback(async () => {
    setIsRefreshing(true);
    try {
      const headers: Record<string, string> = {};
      const tok = getAuthToken();
      if (tok) {
        headers['Authorization'] = `Bearer ${tok}`;
      } else {
        const r = getActiveRole() || 'admin';
        if (r) headers['X-User-Role'] = r;
      }

      const res = await fetch(`${BASE_URL}/api/v1/batches/${encodeURIComponent(batchId)}?page=1&page_size=200`, {
        headers,
      });

      if (!res.ok) {
        throw new Error(`Failed to load batch status: ${res.statusText}`);
      }

      const json = (await res.json()) as BatchDetailResponse;
      setData(json);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Error fetching batch');
    } finally {
      setIsRefreshing(false);
    }
  }, [batchId]);

  // Initial fetch and 2-second polling while batch is still processing
  useEffect(() => {
    void fetchBatch();
    const interval = setInterval(() => {
      setData((prev) => {
        if (!prev) {
          void fetchBatch();
          return prev;
        }
        if (!prev.is_finished && prev.progress_percent < 100) {
          void fetchBatch();
        }
        return prev;
      });
    }, 2000);
    return () => clearInterval(interval);
  }, [fetchBatch]);

  // Download ZIP
  const handleDownloadZip = async () => {
    setDownloading(true);
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
        throw new Error(errJson?.detail || `Export failed with status ${res.status}`);
      }

      const blob = await res.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      const bName = data?.name ? data.name.toLowerCase().replace(/\s+/g, '_') : 'sorted_files';
      a.download = `${bName}_sorted.zip`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.URL.revokeObjectURL(url);
    } catch (e) {
      setDownloadError(e instanceof Error ? e.message : 'Download failed');
    } finally {
      setDownloading(false);
    }
  };

  // Toggle Collapse / Expand all sections
  const handleToggleExpandAll = () => {
    const areAllOpen = Object.values(collapsedTypes).every((v) => !v);
    if (areAllOpen && Object.keys(collapsedTypes).length > 0) {
      // Collapse all
      const next: Record<string, boolean> = {};
      if (data?.counts_by_type) {
        Object.keys(data.counts_by_type).forEach((t) => {
          next[t] = true;
        });
      }
      setCollapsedTypes(next);
    } else {
      // Expand all
      setCollapsedTypes({});
    }
  };

  const toggleTypeCollapse = (docType: string) => {
    setCollapsedTypes((prev) => ({
      ...prev,
      [docType]: !prev[docType],
    }));
  };

  // Fetch single file detail for modal
  const openFileDetail = async (uid: string) => {
    setSelectedFileUid(uid);
    setFileDetailLoading(true);
    try {
      const headers: Record<string, string> = {};
      const tok = getAuthToken();
      if (tok) headers['Authorization'] = `Bearer ${tok}`;
      else headers['X-User-Role'] = 'admin';

      const res = await fetch(`${BASE_URL}/review/api/task/${encodeURIComponent(uid)}`, {
        headers,
      });
      if (res.ok) {
        const json = await res.json();
        setFileDetail(json);
      } else {
        // Fallback to basic file info from data items
        const item = data?.items.find((i) => i.uid === uid);
        setFileDetail({
          file_name: item?.file_name || 'Document',
          predicted_type: item?.doc_type || 'unknown',
          confidence: item?.confidence || 0,
          decision_reason: item?.review_reason || '',
          review_status: item?.plain_status || '',
          extracted_fields: {},
          page_image_url: `/api/v1/documents/${uid}/file`,
        });
      }
    } catch {
      const item = data?.items.find((i) => i.uid === uid);
      setFileDetail({
        file_name: item?.file_name || 'Document',
        predicted_type: item?.doc_type || 'unknown',
        confidence: item?.confidence || 0,
        decision_reason: item?.review_reason || '',
        review_status: item?.plain_status || '',
        extracted_fields: {},
        page_image_url: `/api/v1/documents/${uid}/file`,
      });
    } finally {
      setFileDetailLoading(false);
    }
  };

  // Group items by doc_type
  const itemsByType = useMemo(() => {
    const groups: Record<string, BatchFileItem[]> = {};
    if (!data?.items) return groups;
    for (const item of data.items) {
      const t = item.doc_type || 'unknown';
      if (!groups[t]) groups[t] = [];
      groups[t].push(item);
    }
    return groups;
  }, [data?.items]);

  const totalFiles = data?.progress.total || 0;
  const finishedFiles =
    (data?.counts_by_status?.SORTED_AUTOMATICALLY || 0) +
    (data?.counts_by_status?.NEEDS_CHECK || 0) +
    (data?.counts_by_status?.FAILED || 0) +
    (data?.counts_by_status?.ALREADY_UPLOADED || 0) +
    (data?.counts_by_status?.BLOCKED || 0);

  const isDone = data ? data.is_finished || data.progress_percent >= 100 : false;
  const needsCheckCount = data?.needs_check_count || 0;

  // Plain status pill rendering
  const renderStatusBadge = (plainStatus: string) => {
    switch (plainStatus) {
      case 'SORTED_AUTOMATICALLY':
        return (
          <span className="inline-flex items-center space-x-1 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-emerald-500/15 text-emerald-400 border border-emerald-500/30">
            <CheckCircle2 className="w-3.5 h-3.5" />
            <span>Sorted automatically</span>
          </span>
        );
      case 'NEEDS_CHECK':
        return (
          <span className="inline-flex items-center space-x-1 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-amber-500/15 text-amber-300 border border-amber-500/30">
            <Clock className="w-3.5 h-3.5" />
            <span>Needs a quick check</span>
          </span>
        );
      case 'FAILED':
        return (
          <span className="inline-flex items-center space-x-1 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-rose-500/15 text-rose-400 border border-rose-500/30">
            <AlertTriangle className="w-3.5 h-3.5" />
            <span>Failed</span>
          </span>
        );
      case 'ALREADY_UPLOADED':
        return (
          <span className="inline-flex items-center space-x-1 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-sky-500/15 text-sky-400 border border-sky-500/30">
            <FileText className="w-3.5 h-3.5" />
            <span>Already uploaded</span>
          </span>
        );
      case 'BLOCKED':
        return (
          <span className="inline-flex items-center space-x-1 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-red-500/15 text-red-400 border border-red-500/30">
            <ShieldAlert className="w-3.5 h-3.5" />
            <span>Blocked (safety check)</span>
          </span>
        );
      default:
        return (
          <span className="inline-flex items-center space-x-1 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-slate-800 text-slate-300 border border-slate-700">
            <span>{plainStatus.replace(/_/g, ' ')}</span>
          </span>
        );
    }
  };

  // Confidence bar
  const renderConfidenceBar = (pct: number) => {
    let color = 'bg-teal-400';
    if (pct < 70) color = 'bg-rose-400';
    else if (pct < 85) color = 'bg-amber-400';

    return (
      <div className="flex items-center space-x-2">
        <div className="w-16 h-1.5 rounded-full bg-slate-800 overflow-hidden">
          <div className={`h-full rounded-full ${color}`} style={{ width: `${Math.min(100, Math.max(5, pct))}%` }} />
        </div>
        <span className="text-xs font-medium text-slate-300 whitespace-nowrap">{pct}% sure</span>
      </div>
    );
  };

  return (
    <div className="space-y-6">
      {/* Header Bar */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 pb-4 border-b border-slate-800">
        <div>
          <div className="flex items-center space-x-3">
            <h1 className="text-2xl font-bold text-white">
              {data?.name || `Upload #${data?.number || 1}`}
            </h1>
            <span className="text-xs px-2.5 py-1 rounded-md bg-slate-800 text-slate-400 font-mono border border-slate-700">
              {batchId}
            </span>
          </div>
          <p className="text-sm text-slate-400 mt-1">
            {isDone
              ? `Your ${totalFiles} ${totalFiles === 1 ? 'file is' : 'files are'} sorted.`
              : `Sorting your files... ${finishedFiles} of ${totalFiles} done`}
          </p>
        </div>

        <div className="flex items-center space-x-3">
          <button
            onClick={() => void fetchBatch()}
            disabled={isRefreshing}
            className="flex items-center space-x-1.5 px-3 py-2 text-xs font-medium bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-lg border border-slate-700 transition"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${isRefreshing ? 'animate-spin text-teal-400' : ''}`} />
            <span>Refresh</span>
          </button>
          <button
            onClick={onReset}
            className="flex items-center space-x-1.5 px-4 py-2 text-xs font-semibold bg-slate-800 hover:bg-slate-700 text-teal-300 border border-teal-500/30 rounded-lg transition"
          >
            <ArrowLeft className="w-3.5 h-3.5" />
            <span>Upload another batch</span>
          </button>
        </div>
      </div>

      {/* Error Banners */}
      {error && (
        <div className="p-4 rounded-xl bg-rose-500/10 border border-rose-500/30 text-rose-300 text-sm flex items-center space-x-2">
          <AlertTriangle className="w-4 h-4 flex-shrink-0" />
          <span>{error}</span>
        </div>
      )}
      {downloadError && (
        <div className="p-4 rounded-xl bg-rose-500/10 border border-rose-500/30 text-rose-300 text-sm flex items-center space-x-2">
          <AlertTriangle className="w-4 h-4 flex-shrink-0" />
          <span>{downloadError}</span>
        </div>
      )}

      {/* ── Processing State: Large Progress Bar ── */}
      {!isDone && (
        <div className="p-8 rounded-2xl bg-slate-900/80 border border-slate-800 text-center space-y-4">
          <div className="flex items-center justify-between text-sm font-semibold text-slate-300 max-w-md mx-auto">
            <span>Sorting your files...</span>
            <span className="text-teal-400 font-mono">{finishedFiles} of {totalFiles} done</span>
          </div>

          <div className="w-full max-w-md mx-auto h-3.5 rounded-full bg-slate-800 overflow-hidden relative shadow-inner">
            <div
              className="h-full bg-gradient-to-r from-teal-500 to-emerald-400 rounded-full transition-all duration-500"
              style={{ width: `${Math.min(100, Math.max(5, data?.progress_percent || 0))}%` }}
            />
          </div>

          <p className="text-xs text-slate-400">
            {data?.progress_percent || 0}% complete · You can leave this page anytime; we'll notify you when it's done.
          </p>
        </div>
      )}

      {/* ── Finished State Banner & Actions ── */}
      {isDone && (
        <div className="p-6 rounded-2xl bg-gradient-to-r from-emerald-950/40 to-teal-950/30 border border-emerald-500/30 flex flex-col md:flex-row md:items-center md:justify-between gap-4">
          <div className="flex items-center space-x-3">
            <div className="w-10 h-10 rounded-xl bg-emerald-500/10 border border-emerald-500/30 flex items-center justify-center text-emerald-400">
              <CheckCircle2 className="w-6 h-6" />
            </div>
            <div>
              <h2 className="text-lg font-bold text-white">Your {totalFiles} files are sorted.</h2>
              <p className="text-xs text-emerald-300/80">
                All documents have been classified, text read, and organized into type folders.
              </p>
            </div>
          </div>

          <div className="flex items-center space-x-3">
            <button
              onClick={handleToggleExpandAll}
              className="flex items-center space-x-1.5 px-4 py-2.5 text-xs font-semibold rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 transition"
            >
              <Eye className="w-4 h-4 text-slate-400" />
              <span>View sorted files</span>
            </button>

            <button
              onClick={handleDownloadZip}
              disabled={downloading || totalFiles === 0}
              className="flex items-center space-x-2 px-5 py-2.5 text-xs font-bold rounded-xl bg-teal-500 hover:bg-teal-400 text-slate-950 shadow-lg shadow-teal-500/25 transition disabled:opacity-50"
            >
              {downloading ? (
                <Loader2 className="w-4 h-4 animate-spin text-slate-950" />
              ) : (
                <Download className="w-4 h-4" />
              )}
              <span>Download sorted files (zip)</span>
            </button>
          </div>
        </div>
      )}

      {/* ── Needs a Quick Check Section ── */}
      {needsCheckCount > 0 && (
        <div className="p-5 rounded-2xl bg-amber-500/10 border border-amber-500/30 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
          <div className="flex items-center space-x-3">
            <div className="w-9 h-9 rounded-lg bg-amber-500/20 border border-amber-500/40 flex items-center justify-center text-amber-300">
              <Clock className="w-5 h-5" />
            </div>
            <div>
              <h3 className="text-sm font-bold text-amber-200">
                {needsCheckCount} {needsCheckCount === 1 ? 'file needs' : 'files need'} a quick check
              </h3>
              <p className="text-xs text-amber-300/80">
                Some items have lower confidence or need human eyes before filing.
              </p>
            </div>
          </div>

          <button
            onClick={() => {
              if (onOpenReviewQueue) onOpenReviewQueue(batchId);
              else if (onNavigateTab) onNavigateTab('review');
            }}
            className="flex items-center space-x-1.5 px-4 py-2 text-xs font-bold bg-amber-500 hover:bg-amber-400 text-slate-950 rounded-lg shadow-sm transition"
          >
            <span>Check these now</span>
            <ArrowRight className="w-3.5 h-3.5" />
          </button>
        </div>
      )}

      {/* ── Summary Row of Counts by Type ── */}
      {data?.counts_by_type && Object.keys(data.counts_by_type).length > 0 && (
        <div className="space-y-2">
          <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-wider">
            Files grouped by type
          </h3>
          <div className="flex flex-wrap gap-2">
            {Object.entries(data.counts_by_type).map(([type, count]) => (
              <div
                key={type}
                className="flex items-center space-x-2 px-3 py-1.5 rounded-xl bg-slate-900 border border-slate-800 text-xs"
              >
                <span className="font-medium text-slate-300 capitalize">{type.replace(/_/g, ' ')}</span>
                <span className="px-2 py-0.5 rounded-full bg-teal-500/15 text-teal-400 font-mono font-bold text-[11px]">
                  {count}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ── Collapsible Sections per Type ── */}
      <div className="space-y-3">
        {Object.entries(itemsByType).map(([docType, items]) => {
          const isCollapsed = !!collapsedTypes[docType];
          return (
            <div
              key={docType}
              className="rounded-2xl border border-slate-800 bg-slate-900/60 overflow-hidden shadow-sm"
            >
              {/* Group Header */}
              <button
                onClick={() => toggleTypeCollapse(docType)}
                className="w-full flex items-center justify-between px-5 py-4 bg-slate-800/40 hover:bg-slate-800/70 transition text-left"
              >
                <div className="flex items-center space-x-3">
                  {isCollapsed ? (
                    <ChevronRight className="w-4 h-4 text-slate-400" />
                  ) : (
                    <ChevronDown className="w-4 h-4 text-teal-400" />
                  )}
                  <span className="text-sm font-bold text-white capitalize">
                    {docType.replace(/_/g, ' ')}
                  </span>
                  <span className="text-xs px-2 py-0.5 rounded-full bg-slate-800 text-slate-400 border border-slate-700">
                    {items.length} {items.length === 1 ? 'file' : 'files'}
                  </span>
                </div>
                <span className="text-xs text-slate-400">
                  {isCollapsed ? 'Click to show files' : 'Click to hide'}
                </span>
              </button>

              {/* Group Files List */}
              {!isCollapsed && (
                <div className="divide-y divide-slate-800/60">
                  {items.map((file) => (
                    <div
                      key={file.uid}
                      onClick={() => openFileDetail(file.uid)}
                      className="px-5 py-3.5 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 hover:bg-slate-800/40 cursor-pointer transition"
                    >
                      <div className="flex items-center space-x-3 min-w-0">
                        <FileText className="w-4 h-4 text-slate-400 flex-shrink-0" />
                        <span className="text-sm font-medium text-slate-200 truncate">
                          {file.file_name}
                        </span>
                      </div>

                      <div className="flex items-center space-x-4 flex-shrink-0">
                        {renderConfidenceBar(file.how_sure)}
                        {renderStatusBadge(file.plain_status)}
                        <span className="text-xs text-teal-400 hover:text-teal-300 font-medium">
                          Details →
                        </span>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          );
        })}
      </div>

      {/* ── Document Detail Modal (Image beside Extracted Fields) ── */}
      {selectedFileUid && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-950/80 backdrop-blur-sm animate-fade-in">
          <div className="w-full max-w-5xl max-h-[90vh] bg-slate-900 border border-slate-800 rounded-2xl shadow-2xl flex flex-col overflow-hidden">
            {/* Modal Header */}
            <div className="px-6 py-4 border-b border-slate-800 flex items-center justify-between bg-slate-950/40">
              <div className="flex items-center space-x-3">
                <FileText className="w-5 h-5 text-teal-400" />
                <h3 className="font-bold text-white text-base truncate max-w-lg">
                  {fileDetail?.file_name || 'Document Details'}
                </h3>
              </div>
              <button
                onClick={() => setSelectedFileUid(null)}
                className="p-1 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800 transition"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            {/* Modal Content */}
            <div className="flex-1 overflow-y-auto p-6">
              {fileDetailLoading ? (
                <div className="py-24 text-center text-slate-400 flex flex-col items-center justify-center space-y-3">
                  <Loader2 className="w-8 h-8 text-teal-400 animate-spin" />
                  <p className="text-sm">Loading document preview...</p>
                </div>
              ) : (
                <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                  {/* Left: Document Image */}
                  <div className="border border-slate-800 rounded-xl bg-slate-950 p-3 flex flex-col items-center justify-center min-h-[360px]">
                    {fileDetail?.page_image_url ? (
                      <AuthenticatedImage
                        src={fileDetail.page_image_url}
                        alt={fileDetail.file_name}
                        className="max-h-[500px] w-auto rounded object-contain"
                      />
                    ) : (
                      <div className="text-center text-slate-500 py-12">
                        <FileText className="w-12 h-12 mx-auto mb-2 opacity-50" />
                        <p className="text-xs">No image preview available for this document format.</p>
                      </div>
                    )}
                  </div>

                  {/* Right: Extracted Fields & Sorting Info */}
                  <div className="space-y-4">
                    <div className="p-4 rounded-xl bg-slate-800/40 border border-slate-700/60 space-y-2">
                      <div className="flex items-center justify-between">
                        <span className="text-xs text-slate-400 font-medium">Predicted Type</span>
                        <span className="text-xs font-bold text-teal-300 capitalize">
                          {fileDetail?.predicted_type?.replace(/_/g, ' ') || 'unknown'}
                        </span>
                      </div>
                      <div className="flex items-center justify-between">
                        <span className="text-xs text-slate-400 font-medium">How Sure</span>
                        <span className="text-xs font-bold text-white">
                          {Math.round((fileDetail?.confidence || 0) * 100)}% sure
                        </span>
                      </div>
                      {fileDetail?.decision_reason && (
                        <div className="pt-2 border-t border-slate-700/40 text-xs text-slate-300">
                          <span className="text-slate-400">Decision: </span>
                          {fileDetail.decision_reason}
                        </div>
                      )}
                    </div>

                    {/* Extracted Fields Table */}
                    <div>
                      <h4 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-2">
                        Extracted text & fields
                      </h4>
                      {fileDetail?.extracted_fields && Object.keys(fileDetail.extracted_fields).length > 0 ? (
                        <div className="rounded-xl border border-slate-800 divide-y divide-slate-800 bg-slate-950/40">
                          {Object.entries(fileDetail.extracted_fields).map(([k, v]) => (
                            <div key={k} className="px-3.5 py-2.5 flex items-start justify-between gap-3 text-xs">
                              <span className="text-slate-400 font-medium capitalize">{k.replace(/_/g, ' ')}</span>
                              <span className="text-slate-200 font-mono text-right break-all">
                                {typeof v === 'object' ? JSON.stringify(v) : String(v)}
                              </span>
                            </div>
                          ))}
                        </div>
                      ) : (
                        <p className="text-xs text-slate-500 italic p-3 rounded-lg bg-slate-950/30 border border-slate-800">
                          No specific key-value fields extracted.
                        </p>
                      )}
                    </div>
                  </div>
                </div>
              )}
            </div>

            {/* Modal Footer */}
            <div className="px-6 py-3 border-t border-slate-800 bg-slate-950/40 flex justify-end">
              <button
                onClick={() => setSelectedFileUid(null)}
                className="px-4 py-2 text-xs font-semibold bg-slate-800 hover:bg-slate-700 text-slate-200 rounded-lg transition"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
