import React, { useCallback, useEffect, useState, useMemo } from 'react';
import {
  AlertCircle,
  ChevronDown,
  Clock,
  FileText,
  Filter,
  Loader2,
  Search,
  X,
  CheckCircle2,
  AlertTriangle,
  ShieldAlert,
} from 'lucide-react';
import { client, BASE_URL } from '../api/client';
import type { AuditEvent, DocumentAuditDetail, DocumentItem } from '../types';

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface AuditSearchProps {
  initialUid?: string | null;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const PAGE_SIZE = 25;

function fmtDate(ts: string | null): string {
  if (!ts) return '—';
  try {
    return new Date(ts).toLocaleString([], {
      day: 'numeric',
      month: 'short',
      hour: '2-digit',
      minute: '2-digit',
    });
  } catch {
    return ts;
  }
}

// Plain status pill rendering
function renderStatusPill(status: string) {
  const norm = (status || '').toUpperCase();
  switch (norm) {
    case 'AUTO_ACCEPTED':
    case 'SORTED_AUTOMATICALLY':
    case 'APPROVED':
    case 'HUMAN_VERIFIED':
      return (
        <span className="inline-flex items-center space-x-1 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-emerald-500/15 text-emerald-400 border border-emerald-500/30">
          <CheckCircle2 className="w-3 h-3" />
          <span>Sorted automatically</span>
        </span>
      );
    case 'PENDING_REVIEW':
    case 'NEEDS_CHECK':
      return (
        <span className="inline-flex items-center space-x-1 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-amber-500/15 text-amber-300 border border-amber-500/30">
          <Clock className="w-3 h-3" />
          <span>Needs a quick check</span>
        </span>
      );
    case 'FAILED':
    case 'REJECTED':
      return (
        <span className="inline-flex items-center space-x-1 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-rose-500/15 text-rose-400 border border-rose-500/30">
          <AlertTriangle className="w-3 h-3" />
          <span>Failed</span>
        </span>
      );
    case 'QUARANTINED':
    case 'BLOCKED':
      return (
        <span className="inline-flex items-center space-x-1 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-red-500/15 text-red-400 border border-red-500/30">
          <ShieldAlert className="w-3 h-3" />
          <span>Blocked (safety check)</span>
        </span>
      );
    case 'DUPLICATE':
    case 'ALREADY_UPLOADED':
      return (
        <span className="inline-flex items-center space-x-1 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-sky-500/15 text-sky-400 border border-sky-500/30">
          <FileText className="w-3 h-3" />
          <span>Already uploaded</span>
        </span>
      );
    default:
      return (
        <span className="inline-flex items-center space-x-1 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-slate-800 text-slate-300 border border-slate-700">
          <span>{status.replace(/_/g, ' ')}</span>
        </span>
      );
  }
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

const AuditTimeline: React.FC<{ events: AuditEvent[] }> = ({ events }) => {
  if (events.length === 0) {
    return <p className="text-xs text-slate-500 italic">No history recorded.</p>;
  }
  return (
    <ol className="relative border-l border-slate-700 ml-3 space-y-3.5 my-2">
      {events.map((ev) => (
        <li key={ev.event_id} className="ml-4 text-xs">
          <span className="absolute -left-1.5 mt-1.5 h-3 w-3 rounded-full bg-teal-500 border-2 border-slate-900 shadow-sm" />
          <div className="flex flex-wrap items-center gap-2">
            <span className="px-2 py-0.5 rounded bg-slate-800 text-slate-200 font-mono font-semibold">
              {ev.event_type.replace(/_/g, ' ')}
            </span>
            {ev.stage && (
              <span className="px-2 py-0.5 rounded bg-slate-800/80 text-teal-400 font-mono text-[11px]">
                {ev.stage}
              </span>
            )}
            <span className="text-[11px] text-slate-400 flex items-center gap-1">
              <Clock size={11} />
              {fmtDate(ev.timestamp)}
            </span>
          </div>
        </li>
      ))}
    </ol>
  );
};

const KVTable: React.FC<{ data: Record<string, unknown> }> = ({ data }) => {
  const entries = Object.entries(data);
  if (entries.length === 0) {
    return <p className="text-xs text-slate-500 italic">No extracted fields available.</p>;
  }
  return (
    <div className="rounded-xl border border-slate-800 divide-y divide-slate-800 bg-slate-950/40 text-xs">
      {entries.map(([key, val]) => (
        <div key={key} className="px-3.5 py-2 flex items-start justify-between gap-3">
          <span className="text-slate-400 font-medium capitalize">{key.replace(/_/g, ' ')}</span>
          <span className="text-slate-200 font-mono text-right break-all">
            {typeof val === 'object' ? JSON.stringify(val) : String(val)}
          </span>
        </div>
      ))}
    </div>
  );
};

// ---------------------------------------------------------------------------
// Document Details Drawer
// ---------------------------------------------------------------------------

const DocumentAuditPanel: React.FC<{ uid: string }> = ({ uid }) => {
  const [detail, setDetail] = useState<DocumentAuditDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showTechnicalDetails, setShowTechnicalDetails] = useState(false);

  useEffect(() => {
    let cancelled = false;
    async function loadDetail() {
      setLoading(true);
      setError(null);
      try {
        const res = await fetch(`${BASE_URL}/api/v1/documents/${encodeURIComponent(uid)}/audit`);
        if (cancelled) return;
        if (!res.ok) {
          setError('Could not load file history.');
        } else {
          const json = await res.json();
          setDetail(json as unknown as DocumentAuditDetail);
        }
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : 'Error loading details');
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    void loadDetail();
    return () => {
      cancelled = true;
    };
  }, [uid]);

  if (loading) {
    return (
      <div className="p-6 text-center text-slate-400 flex items-center justify-center space-x-2 text-xs">
        <Loader2 className="w-4 h-4 animate-spin text-teal-400" />
        <span>Loading file history and fields...</span>
      </div>
    );
  }

  if (error || !detail) {
    return (
      <div className="p-4 text-xs text-rose-300 bg-rose-500/10 rounded-xl border border-rose-500/20">
        {error || 'No details available.'}
      </div>
    );
  }

  return (
    <div className="p-5 bg-slate-900/90 rounded-2xl border border-slate-800 space-y-5 my-2">
      {/* File Overview Summary */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-xs">
        <div className="p-3 rounded-xl bg-slate-950/60 border border-slate-800/80">
          <span className="text-slate-400 font-medium block">Document Type</span>
          <span className="text-slate-100 font-bold capitalize mt-1 block">
            {detail.predictedType || 'unknown'}
          </span>
        </div>
        <div className="p-3 rounded-xl bg-slate-950/60 border border-slate-800/80">
          <span className="text-slate-400 font-medium block">Confidence</span>
          <span className="text-slate-100 font-bold mt-1 block">
            {Math.round((detail.confidence || 0) * 100)}% sure
          </span>
        </div>
        <div className="p-3 rounded-xl bg-slate-950/60 border border-slate-800/80">
          <span className="text-slate-400 font-medium block">Status</span>
          <div className="mt-1">{renderStatusPill(detail.reviewStatus)}</div>
        </div>
        <div className="p-3 rounded-xl bg-slate-950/60 border border-slate-800/80">
          <span className="text-slate-400 font-medium block">Private Info</span>
          <span className="text-slate-200 mt-1 block">
            {detail.piiDetected ? 'Protected & masked' : 'None detected'}
          </span>
        </div>
      </div>

      {detail.decisionReason && (
        <div className="p-3.5 rounded-xl bg-slate-950/40 border border-slate-800/80 text-xs">
          <span className="text-slate-400 font-semibold block mb-1">Decision reason:</span>
          <span className="text-slate-200">{detail.decisionReason}</span>
        </div>
      )}

      {/* Extracted Fields */}
      {detail.extractedFields && Object.keys(detail.extractedFields).length > 0 && (
        <div className="space-y-2">
          <h4 className="text-xs font-bold text-slate-300 uppercase tracking-wider">
            Reading text & extracted fields
          </h4>
          <KVTable data={detail.extractedFields as Record<string, unknown>} />
        </div>
      )}

      {/* File History (Audit Trail) */}
      <div className="space-y-2">
        <h4 className="text-xs font-bold text-slate-300 uppercase tracking-wider">
          File history
        </h4>
        <AuditTimeline events={detail.auditTrail ?? []} />
      </div>

      {/* Technical Details Toggle */}
      <div className="pt-2 border-t border-slate-800">
        <button
          onClick={() => setShowTechnicalDetails(!showTechnicalDetails)}
          className="text-xs text-slate-400 hover:text-teal-400 flex items-center space-x-1"
        >
          <span>{showTechnicalDetails ? 'Hide technical identifiers' : 'Show technical identifiers (UID, SHA-256)'}</span>
          <ChevronDown className={`w-3.5 h-3.5 transition-transform ${showTechnicalDetails ? 'rotate-180' : ''}`} />
        </button>

        {showTechnicalDetails && (
          <div className="mt-3 p-3.5 rounded-xl bg-slate-950/80 border border-slate-800 font-mono text-[11px] space-y-2 text-slate-400">
            <div>
              <span className="text-slate-500">Document UID: </span>
              <span className="text-slate-300">{detail.uid}</span>
            </div>
            <div>
              <span className="text-slate-500">SHA-256 Digest: </span>
              <span className="text-slate-300 break-all">{detail.sha256}</span>
            </div>
            <div>
              <span className="text-slate-500">Storage Location: </span>
              <span className="text-slate-300">{(detail as any).storagePath || 'data/storage'}</span>
            </div>
            <div>
              <span className="text-slate-500">Classifier Model: </span>
              <span className="text-slate-300">{detail.classifierModel} ({detail.classifierVersion})</span>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

// ---------------------------------------------------------------------------
// Main Find a File Component
// ---------------------------------------------------------------------------

export const AuditSearch: React.FC<AuditSearchProps> = ({ initialUid }) => {
  const [query, setQuery] = useState<string>(initialUid ?? '');
  const [items, setItems] = useState<DocumentItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Filters
  const [filterType, setFilterType] = useState('');
  const [filterStatus, setFilterStatus] = useState('');
  const [groupByType, setGroupByType] = useState(false);

  // Expanded detail
  const [expandedUid, setExpandedUid] = useState<string | null>(initialUid ?? null);

  // Fetch documents
  const fetchDocuments = useCallback(async (searchQuery: string) => {
    setLoading(true);
    setError(null);
    try {
      const { data, error: apiErr } = await client.GET('/api/v1/documents', {
        params: {
          query: {
            page: 1,
            page_size: PAGE_SIZE,
            search: searchQuery.trim() || undefined,
          },
        },
      });
      if (apiErr || !data) {
        setError('Failed to fetch documents.');
        setItems([]);
        setTotal(0);
      } else {
        const payload = data as unknown as { total: number; items: DocumentItem[] };
        setItems(payload.items ?? []);
        setTotal(payload.total ?? 0);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Network error');
      setItems([]);
      setTotal(0);
    } finally {
      setLoading(false);
    }
  }, []);

  // Default to loading results on mount so users don't see an empty page!
  useEffect(() => {
    void fetchDocuments(initialUid ?? '');
  }, [fetchDocuments, initialUid]);

  const handleSearch = () => {
    void fetchDocuments(query);
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') handleSearch();
  };

  // Filtered documents
  const filteredItems = useMemo(() => {
    return items.filter((doc) => {
      if (filterType && doc.doc_type !== filterType) return false;
      if (filterStatus) {
        const s = (doc.review_status || '').toLowerCase();
        if (filterStatus === 'SORTED_AUTOMATICALLY') {
          if (!['auto_accepted', 'approved', 'human_verified'].includes(s)) return false;
        } else if (filterStatus === 'NEEDS_CHECK') {
          if (s !== 'pending_review') return false;
        } else if (filterStatus === 'FAILED') {
          if (!['failed', 'rejected'].includes(s)) return false;
        } else if (filterStatus === 'BLOCKED') {
          if (s !== 'quarantined') return false;
        } else if (filterStatus === 'ALREADY_UPLOADED') {
          if (s !== 'duplicate' && !doc.is_link) return false;
        }
      }
      return true;
    });
  }, [items, filterType, filterStatus]);

  // Grouped items by type
  const itemsGroupedByType = useMemo(() => {
    const groups: Record<string, DocumentItem[]> = {};
    filteredItems.forEach((doc) => {
      const t = doc.doc_type || 'unknown';
      if (!groups[t]) groups[t] = [];
      groups[t].push(doc);
    });
    return groups;
  }, [filteredItems]);

  const uniqueTypes = useMemo(() => {
    const set = new Set<string>();
    items.forEach((i) => {
      if (i.doc_type) set.add(i.doc_type);
    });
    return Array.from(set).sort();
  }, [items]);

  return (
    <div className="space-y-6 max-w-6xl mx-auto">
      {/* Header */}
      <div className="pb-4 border-b border-slate-800">
        <h1 className="text-2xl font-bold text-white flex items-center space-x-2">
          <Search className="w-6 h-6 text-teal-400" />
          <span>Find a file</span>
        </h1>
        <p className="text-sm text-slate-400 mt-1">
          Search across all your processed files by name or extracted content.
        </p>
      </div>

      {/* Search Input Bar */}
      <div className="flex gap-2">
        <div className="relative flex-1">
          <Search
            size={16}
            className="absolute left-3.5 top-1/2 -translate-y-1/2 text-slate-400 pointer-events-none"
          />
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Search by file name or extracted text..."
            className="w-full bg-slate-900 border border-slate-800 rounded-xl pl-10 pr-4 py-2.5 text-sm text-slate-100 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-teal-500/50 transition"
          />
          {query && (
            <button
              onClick={() => {
                setQuery('');
                void fetchDocuments('');
              }}
              className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-500 hover:text-slate-300"
            >
              <X size={15} />
            </button>
          )}
        </div>
        <button
          onClick={handleSearch}
          disabled={loading}
          className="bg-teal-500 hover:bg-teal-400 text-slate-950 font-bold rounded-xl px-5 py-2.5 text-sm transition flex items-center gap-2 shadow-lg shadow-teal-500/20"
        >
          {loading ? <Loader2 size={16} className="animate-spin text-slate-950" /> : <Search size={16} />}
          <span>Search</span>
        </button>
      </div>

      {/* Filter Bar & Controls */}
      <div className="flex flex-wrap items-center justify-between gap-3 text-xs bg-slate-900/60 p-3.5 rounded-2xl border border-slate-800">
        <div className="flex flex-wrap items-center gap-3">
          <span className="text-slate-400 flex items-center gap-1 font-semibold">
            <Filter size={13} />
            Filter:
          </span>

          {/* Doc Type Dropdown */}
          <select
            value={filterType}
            onChange={(e) => setFilterType(e.target.value)}
            className="bg-slate-800 border border-slate-700 rounded-lg px-2.5 py-1.5 text-slate-200 focus:outline-none focus:ring-2 focus:ring-teal-500 cursor-pointer"
          >
            <option value="">All document types</option>
            {uniqueTypes.map((t) => (
              <option key={t} value={t}>
                {t.replace(/_/g, ' ')}
              </option>
            ))}
          </select>

          {/* Status Dropdown */}
          <select
            value={filterStatus}
            onChange={(e) => setFilterStatus(e.target.value)}
            className="bg-slate-800 border border-slate-700 rounded-lg px-2.5 py-1.5 text-slate-200 focus:outline-none focus:ring-2 focus:ring-teal-500 cursor-pointer"
          >
            <option value="">All statuses</option>
            <option value="SORTED_AUTOMATICALLY">Sorted automatically</option>
            <option value="NEEDS_CHECK">Needs a quick check</option>
            <option value="FAILED">Failed</option>
            <option value="BLOCKED">Blocked (safety check)</option>
            <option value="ALREADY_UPLOADED">Already uploaded</option>
          </select>
        </div>

        {/* Group by type switch & count */}
        <div className="flex items-center space-x-4">
          <span className="text-slate-500 font-mono">
            {filteredItems.length} of {total} files
          </span>
          <label className="flex items-center space-x-2 cursor-pointer select-none text-slate-300">
            <input
              type="checkbox"
              checked={groupByType}
              onChange={(e) => setGroupByType(e.target.checked)}
              className="accent-teal-500 h-4 w-4 rounded cursor-pointer"
            />
            <span className="font-medium">Group by type</span>
          </label>
        </div>
      </div>

      {/* Error state */}
      {error && (
        <div className="flex items-center gap-2 text-rose-300 bg-rose-500/10 border border-rose-500/30 rounded-xl px-4 py-3 text-xs">
          <AlertCircle size={15} className="shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {/* Loading */}
      {loading && items.length === 0 && (
        <div className="py-20 text-center text-slate-400 flex flex-col items-center justify-center space-y-2">
          <Loader2 className="w-8 h-8 text-teal-400 animate-spin" />
          <p className="text-xs">Finding documents...</p>
        </div>
      )}

      {/* Table or Grouped View */}
      {!loading && !error && filteredItems.length === 0 && (
        <div className="py-16 text-center rounded-2xl border border-dashed border-slate-800 bg-slate-900/40 text-slate-500">
          <FileText className="w-10 h-10 mx-auto mb-2 opacity-40 text-teal-400" />
          <p className="text-sm font-medium text-slate-300">No matching files found</p>
          <p className="text-xs text-slate-500 mt-1">Try a different search query or clear your filters.</p>
        </div>
      )}

      {!loading && !error && filteredItems.length > 0 && !groupByType && (
        <div className="overflow-x-auto rounded-2xl border border-slate-800 bg-slate-900/60 shadow-sm">
          <table className="w-full text-xs text-left">
            <thead>
              <tr className="bg-slate-950/60 text-slate-400 uppercase text-[11px] tracking-wider border-b border-slate-800">
                <th className="px-5 py-3 font-semibold">File Name</th>
                <th className="px-5 py-3 font-semibold">Type</th>
                <th className="px-5 py-3 font-semibold">Confidence</th>
                <th className="px-5 py-3 font-semibold">Status</th>
                <th className="px-5 py-3 font-semibold">Private Info</th>
                <th className="px-5 py-3 font-semibold">Uploaded At</th>
                <th className="px-5 py-3 font-semibold text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/60">
              {filteredItems.map((doc) => {
                const isExpanded = expandedUid === doc.uid;
                const pct = Math.round((doc.confidence || 0) * 100);
                return (
                  <React.Fragment key={doc.uid}>
                    <tr
                      className={`transition-colors ${
                        isExpanded ? 'bg-slate-800/60' : 'hover:bg-slate-800/30'
                      }`}
                    >
                      <td className="px-5 py-3 font-medium text-white max-w-[200px] truncate">
                        <span title={doc.file_name}>{doc.file_name}</span>
                      </td>

                      <td className="px-5 py-3 text-slate-300 capitalize font-medium">
                        {doc.doc_type ? doc.doc_type.replace(/_/g, ' ') : '—'}
                      </td>

                      <td className="px-5 py-3">
                        <div className="flex items-center space-x-2">
                          <div className="w-14 h-1.5 rounded-full bg-slate-800 overflow-hidden">
                            <div
                              className="h-full bg-teal-400 rounded-full"
                              style={{ width: `${Math.min(100, Math.max(5, pct))}%` }}
                            />
                          </div>
                          <span className="text-slate-300 font-mono">{pct}% sure</span>
                        </div>
                      </td>

                      <td className="px-5 py-3">{renderStatusPill(doc.review_status)}</td>

                      <td className="px-5 py-3 text-slate-400">
                        {doc.pii_detected ? (
                          <span className="text-teal-400 font-medium">Checked & masked</span>
                        ) : (
                          <span>None detected</span>
                        )}
                      </td>

                      <td className="px-5 py-3 text-slate-400">{fmtDate(doc.created_at ?? null)}</td>

                      <td className="px-5 py-3 text-right">
                        <button
                          onClick={() => setExpandedUid(isExpanded ? null : doc.uid)}
                          className="px-3 py-1 rounded-lg text-xs font-semibold bg-slate-800 hover:bg-slate-700 text-teal-300 border border-slate-700 transition"
                        >
                          {isExpanded ? 'Close' : 'Details'}
                        </button>
                      </td>
                    </tr>

                    {isExpanded && (
                      <tr>
                        <td colSpan={7} className="p-4 bg-slate-950/80">
                          <DocumentAuditPanel uid={doc.uid} />
                        </td>
                      </tr>
                    )}
                  </React.Fragment>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {/* Group by Type View */}
      {!loading && !error && filteredItems.length > 0 && groupByType && (
        <div className="space-y-4">
          {Object.entries(itemsGroupedByType).map(([docType, group]) => (
            <div key={docType} className="rounded-2xl border border-slate-800 bg-slate-900/60 overflow-hidden">
              <div className="px-5 py-3.5 bg-slate-950/50 border-b border-slate-800 flex items-center justify-between">
                <div className="flex items-center space-x-2">
                  <span className="text-sm font-bold text-white capitalize">{docType.replace(/_/g, ' ')}</span>
                  <span className="text-xs px-2 py-0.5 rounded-full bg-teal-500/10 text-teal-400 font-mono font-semibold">
                    {group.length} {group.length === 1 ? 'file' : 'files'}
                  </span>
                </div>
              </div>

              <div className="divide-y divide-slate-800/60">
                {group.map((doc) => {
                  const isExpanded = expandedUid === doc.uid;
                  const pct = Math.round((doc.confidence || 0) * 100);
                  return (
                    <div key={doc.uid}>
                      <div className="px-5 py-3 flex items-center justify-between hover:bg-slate-800/30 text-xs">
                        <span className="font-medium text-white truncate max-w-sm">{doc.file_name}</span>
                        <div className="flex items-center space-x-3">
                          <span className="text-slate-400 font-mono">{pct}% sure</span>
                          {renderStatusPill(doc.review_status)}
                          <button
                            onClick={() => setExpandedUid(isExpanded ? null : doc.uid)}
                            className="text-xs text-teal-400 hover:text-teal-300 font-semibold"
                          >
                            {isExpanded ? 'Close' : 'Details →'}
                          </button>
                        </div>
                      </div>
                      {isExpanded && (
                        <div className="p-4 bg-slate-950/80 border-t border-slate-800">
                          <DocumentAuditPanel uid={doc.uid} />
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};
