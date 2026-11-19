import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  AlertCircle,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  ChevronUp,
  Clock,
  FileText,
  Filter,
  Loader2,
  Search,
  ShieldCheck,
  X,
} from 'lucide-react';
import { client } from '../api/client';
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

const PAGE_SIZE = 20;

function statusColor(status: string): string {
  switch (status.toUpperCase()) {
    case 'AUTO_ACCEPTED':
      return 'bg-teal-700 text-teal-100';
    case 'PENDING_REVIEW':
      return 'bg-amber-700 text-amber-100';
    case 'QUARANTINED':
      return 'bg-red-700 text-red-100';
    case 'HUMAN_VERIFIED':
      return 'bg-blue-700 text-blue-100';
    case 'REJECTED':
      return 'bg-rose-800 text-rose-100';
    default:
      return 'bg-slate-600 text-slate-200';
  }
}

function fmtDate(ts: string | null): string {
  if (!ts) return '—';
  try {
    return new Date(ts).toLocaleString();
  } catch {
    return ts;
  }
}

function truncate(str: string, len = 20): string {
  return str.length > len ? `${str.slice(0, len)}…` : str;
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

const Badge: React.FC<{ label: string; className?: string }> = ({ label, className = '' }) => (
  <span className={`inline-block rounded px-1.5 py-0.5 text-xs font-semibold uppercase tracking-wide ${className}`}>
    {label}
  </span>
);

const AuditTimeline: React.FC<{ events: AuditEvent[] }> = ({ events }) => {
  if (events.length === 0) {
    return <p className="text-sm text-slate-400 italic">No audit events recorded.</p>;
  }
  return (
    <ol className="relative border-l border-slate-600 ml-3 space-y-4">
      {events.map((ev) => (
        <li key={ev.event_id} className="ml-4">
          <span className="absolute -left-1.5 mt-1.5 h-3 w-3 rounded-full bg-teal-500 border-2 border-slate-800" />
          <div className="flex flex-wrap items-center gap-2">
            <Badge label={ev.event_type} className="bg-slate-700 text-slate-200" />
            {ev.stage && (
              <Badge label={ev.stage} className="bg-slate-600 text-slate-300" />
            )}
            <span className="text-xs text-slate-400 flex items-center gap-1">
              <Clock size={11} />
              {fmtDate(ev.timestamp)}
            </span>
          </div>
        </li>
      ))}
    </ol>
  );
};

const KVTable: React.FC<{
  data: Record<string, unknown>;
  highlightKeys?: Record<string, unknown>;
}> = ({ data, highlightKeys = {} }) => {
  const entries = Object.entries(data);
  if (entries.length === 0) {
    return <p className="text-sm text-slate-400 italic">None.</p>;
  }
  return (
    <table className="w-full text-sm">
      <tbody>
        {entries.map(([k, v]) => (
          <tr key={k} className="border-b border-slate-700 last:border-0">
            <td className="py-1.5 pr-4 font-medium text-slate-300 whitespace-nowrap w-1/3">{k}</td>
            <td className="py-1.5 text-slate-200 break-all">
              {String(v ?? '—')}
              {k in highlightKeys && (
                <Badge
                  label="Human Verified"
                  className="ml-2 bg-green-800 text-green-200"
                />
              )}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
};

// ---------------------------------------------------------------------------
// Inline Audit Panel
// ---------------------------------------------------------------------------

interface AuditPanelProps {
  uid: string;
  onClose: () => void;
}

const AuditPanel: React.FC<AuditPanelProps> = ({ uid, onClose }) => {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [detail, setDetail] = useState<DocumentAuditDetail | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);

    client
      .GET('/api/v1/documents/{uid}', { params: { path: { uid } } })
      .then(({ data, error: apiErr }) => {
        if (cancelled) return;
        if (apiErr || !data) {
          setError(
            typeof apiErr === 'object' && apiErr !== null && 'detail' in apiErr
              ? String((apiErr as Record<string, unknown>).detail)
              : 'Failed to load document detail.'
          );
        } else {
          setDetail(data as unknown as DocumentAuditDetail);
        }
      })
      .catch((e: unknown) => {
        if (cancelled) return;
        setError(e instanceof Error ? e.message : 'Unexpected error.');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [uid]);

  return (
    <div className="bg-slate-800 border border-slate-600 rounded-lg mt-1 mb-2 p-5 space-y-5">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h3 className="text-teal-400 font-semibold text-sm flex items-center gap-2">
          <ShieldCheck size={16} />
          Audit Detail — <span className="font-mono text-xs text-slate-300">{uid}</span>
        </h3>
        <button
          onClick={onClose}
          className="text-slate-400 hover:text-slate-100 transition-colors"
          aria-label="Close audit panel"
        >
          <X size={18} />
        </button>
      </div>

      {/* Loading */}
      {loading && (
        <div className="flex items-center gap-2 text-slate-400 text-sm py-6 justify-center">
          <Loader2 size={18} className="animate-spin" />
          Loading audit detail…
        </div>
      )}

      {/* Error */}
      {!loading && error && (
        <div className="flex items-center gap-2 text-red-400 text-sm bg-red-950/40 rounded p-3">
          <AlertCircle size={16} />
          {error}
        </div>
      )}

      {/* Content */}
      {!loading && !error && detail && (
        <>
          {/* Metadata grid */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-xs">
            {[
              ['Predicted Type', detail.predictedType],
              ['Review Status', detail.reviewStatus],
              ['Retention Class', detail.retentionClass],
              ['Assigned ACL', detail.assignedAcl],
              ['OCR Engine', detail.ocrEngine],
              ['Classifier Model', detail.classifierModel],
              ['Classifier Version', detail.classifierVersion],
            ].map(([label, value]) => (
              <div key={label} className="bg-slate-700/50 rounded p-2">
                <p className="text-slate-400 mb-0.5">{label}</p>
                <p className="text-slate-100 font-medium break-all">{value || '—'}</p>
              </div>
            ))}
            {detail.decisionReason && (
              <div className="bg-slate-700/50 rounded p-2 col-span-2 md:col-span-4">
                <p className="text-slate-400 mb-0.5">Decision Reason</p>
                <p className="text-slate-100">{detail.decisionReason}</p>
              </div>
            )}
          </div>

          {/* Audit Trail */}
          <div>
            <h4 className="text-slate-300 font-semibold text-xs uppercase tracking-widest mb-3">
              Audit Trail
            </h4>
            <AuditTimeline events={detail.auditTrail ?? []} />
          </div>

          {/* Human Verified Fields */}
          {detail.humanVerifiedFields &&
            Object.keys(detail.humanVerifiedFields).length > 0 && (
              <div>
                <h4 className="text-slate-300 font-semibold text-xs uppercase tracking-widest mb-3 flex items-center gap-2">
                  <Badge label="Human Verified" className="bg-green-800 text-green-200" />
                  Human Verified Fields
                </h4>
                <KVTable
                  data={detail.humanVerifiedFields as Record<string, unknown>}
                />
              </div>
            )}

          {/* Extracted Fields */}
          <div>
            <h4 className="text-slate-300 font-semibold text-xs uppercase tracking-widest mb-3">
              Extracted Fields
            </h4>
            <KVTable
              data={detail.extractedFields as Record<string, unknown>}
              highlightKeys={detail.humanVerifiedFields as Record<string, unknown>}
            />
          </div>
        </>
      )}
    </div>
  );
};

// ---------------------------------------------------------------------------
// Main Component
// ---------------------------------------------------------------------------

export const AuditSearch: React.FC<AuditSearchProps> = ({ initialUid }) => {
  // Search & pagination
  const [query, setQuery] = useState<string>(initialUid ?? '');
  const [committedQuery, setCommittedQuery] = useState<string>(initialUid ?? '');
  const [page, setPage] = useState(1);

  // Data
  const [items, setItems] = useState<DocumentItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Client-side filters
  const [filterType, setFilterType] = useState('');
  const [filterStatus, setFilterStatus] = useState('');
  const [filterDupOnly, setFilterDupOnly] = useState(false);

  // Expanded audit panel
  const [expandedUid, setExpandedUid] = useState<string | null>(null);

  // Ref to track if initial uid auto-load has been done
  const initialLoadDone = useRef(false);

  // Fetch documents
  const fetchDocuments = useCallback(
    async (searchQuery: string, pageNum: number) => {
      setLoading(true);
      setError(null);
      try {
        const { data, error: apiErr } = await client.GET('/api/v1/documents', {
          params: {
            query: {
              page: pageNum,
              page_size: PAGE_SIZE,
              search: searchQuery || undefined,
            },
          },
        });
        if (apiErr || !data) {
          const msg =
            typeof apiErr === 'object' && apiErr !== null && 'detail' in apiErr
              ? String((apiErr as Record<string, unknown>).detail)
              : 'Failed to fetch documents.';
          setError(msg);
          setItems([]);
          setTotal(0);
        } else {
          const payload = data as unknown as {
            total: number;
            items: DocumentItem[];
          };
          setItems(payload.items ?? []);
          setTotal(payload.total ?? 0);
        }
      } catch (e: unknown) {
        setError(e instanceof Error ? e.message : 'Unexpected error.');
        setItems([]);
        setTotal(0);
      } finally {
        setLoading(false);
      }
    },
    []
  );

  // On mount: if initialUid, auto-expand that document and load it
  useEffect(() => {
    if (!initialLoadDone.current) {
      initialLoadDone.current = true;
      fetchDocuments(initialUid ?? '', 1);
      if (initialUid) {
        setExpandedUid(initialUid);
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Re-fetch when committed query or page changes (not on mount — that's handled above)
  const isFirstRender = useRef(true);
  useEffect(() => {
    if (isFirstRender.current) {
      isFirstRender.current = false;
      return;
    }
    fetchDocuments(committedQuery, page);
  }, [committedQuery, page, fetchDocuments]);

  // Handle search submit
  const handleSearch = () => {
    setPage(1);
    setCommittedQuery(query);
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') handleSearch();
  };

  // Client-side filtering
  const filteredItems = items.filter((doc) => {
    if (filterType && doc.doc_type !== filterType) return false;
    if (filterStatus && doc.review_status !== filterStatus) return false;
    if (filterDupOnly && !doc.is_link) return false;
    return true;
  });

  // Unique values for filter dropdowns (from current page results)
  const uniqueTypes = Array.from(new Set(items.map((d) => d.doc_type))).filter(Boolean).sort();
  const uniqueStatuses = Array.from(new Set(items.map((d) => d.review_status))).filter(Boolean).sort();

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  const toggleExpand = (uid: string) => {
    setExpandedUid((prev) => (prev === uid ? null : uid));
  };

  return (
    <div className="space-y-5">
      {/* ------------------------------------------------------------------ */}
      {/* Search bar                                                          */}
      {/* ------------------------------------------------------------------ */}
      <div className="flex gap-2">
        <div className="relative flex-1">
          <Search
            size={16}
            className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400 pointer-events-none"
          />
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Search by UID or filename…"
            className="w-full bg-slate-700 border border-slate-600 rounded-lg pl-9 pr-3 py-2.5 text-sm text-slate-100 placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-teal-500 transition"
          />
        </div>
        <button
          onClick={handleSearch}
          disabled={loading}
          className="bg-teal-600 hover:bg-teal-500 disabled:opacity-50 text-white rounded-lg px-4 py-2.5 text-sm font-medium transition flex items-center gap-2"
        >
          {loading ? <Loader2 size={15} className="animate-spin" /> : <Search size={15} />}
          Search
        </button>
      </div>

      {/* ------------------------------------------------------------------ */}
      {/* Filter bar                                                          */}
      {/* ------------------------------------------------------------------ */}
      <div className="flex flex-wrap items-center gap-3 text-sm">
        <span className="text-slate-400 flex items-center gap-1">
          <Filter size={14} />
          Filter:
        </span>

        {/* Doc type */}
        <select
          value={filterType}
          onChange={(e) => setFilterType(e.target.value)}
          className="bg-slate-700 border border-slate-600 rounded-md px-3 py-1.5 text-slate-200 focus:outline-none focus:ring-2 focus:ring-teal-500 cursor-pointer"
        >
          <option value="">All types</option>
          {uniqueTypes.map((t) => (
            <option key={t} value={t}>
              {t}
            </option>
          ))}
        </select>

        {/* Review status */}
        <select
          value={filterStatus}
          onChange={(e) => setFilterStatus(e.target.value)}
          className="bg-slate-700 border border-slate-600 rounded-md px-3 py-1.5 text-slate-200 focus:outline-none focus:ring-2 focus:ring-teal-500 cursor-pointer"
        >
          <option value="">All statuses</option>
          {uniqueStatuses.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>

        {/* Duplicates */}
        <label className="flex items-center gap-2 text-slate-300 cursor-pointer select-none">
          <input
            type="checkbox"
            checked={filterDupOnly}
            onChange={(e) => setFilterDupOnly(e.target.checked)}
            className="accent-teal-500 h-4 w-4 cursor-pointer"
          />
          Show duplicates only
        </label>

        {/* Result count */}
        {!loading && !error && (
          <span className="ml-auto text-slate-400 text-xs">
            {filteredItems.length} shown · {total.toLocaleString()} total
          </span>
        )}
      </div>

      {/* ------------------------------------------------------------------ */}
      {/* Error state                                                         */}
      {/* ------------------------------------------------------------------ */}
      {error && (
        <div className="flex items-center gap-2 text-red-400 bg-red-950/40 border border-red-800 rounded-lg px-4 py-3 text-sm">
          <AlertCircle size={16} className="shrink-0" />
          {error}
        </div>
      )}

      {/* ------------------------------------------------------------------ */}
      {/* Loading skeleton                                                    */}
      {/* ------------------------------------------------------------------ */}
      {loading && (
        <div className="space-y-2">
          {Array.from({ length: 5 }).map((_, i) => (
            <div
              key={i}
              className="h-12 rounded-lg bg-slate-700/50 animate-pulse"
            />
          ))}
        </div>
      )}

      {/* ------------------------------------------------------------------ */}
      {/* Table                                                               */}
      {/* ------------------------------------------------------------------ */}
      {!loading && !error && (
        <>
          {filteredItems.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-20 text-slate-500 gap-3">
              <FileText size={36} className="opacity-40" />
              <p className="text-sm">No documents found.</p>
            </div>
          ) : (
            <div className="overflow-x-auto rounded-lg border border-slate-700">
              <table className="w-full text-sm text-left">
                <thead>
                  <tr className="bg-slate-800 text-slate-400 uppercase text-xs tracking-widest border-b border-slate-700">
                    <th className="px-4 py-3 font-semibold">File Name</th>
                    <th className="px-4 py-3 font-semibold">UID</th>
                    <th className="px-4 py-3 font-semibold">Type</th>
                    <th className="px-4 py-3 font-semibold">Confidence</th>
                    <th className="px-4 py-3 font-semibold">Status</th>
                    <th className="px-4 py-3 font-semibold">PII</th>
                    <th className="px-4 py-3 font-semibold">Duplicate</th>
                    <th className="px-4 py-3 font-semibold">Created At</th>
                    <th className="px-4 py-3 font-semibold">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredItems.map((doc) => {
                    const isExpanded = expandedUid === doc.uid;
                    return (
                      <React.Fragment key={doc.uid}>
                        <tr
                          className={`border-b border-slate-700 transition-colors ${
                            isExpanded
                              ? 'bg-slate-700/60'
                              : 'bg-slate-800/60 hover:bg-slate-700/40'
                          }`}
                        >
                          {/* File Name */}
                          <td className="px-4 py-3 text-slate-100 font-medium max-w-[160px] truncate">
                            <span title={doc.file_name}>{doc.file_name}</span>
                          </td>

                          {/* UID */}
                          <td className="px-4 py-3 font-mono text-slate-400 text-xs whitespace-nowrap">
                            <span title={doc.uid}>{truncate(doc.uid, 12)}</span>
                          </td>

                          {/* Type */}
                          <td className="px-4 py-3 text-slate-300 whitespace-nowrap">
                            {doc.doc_type}
                          </td>

                          {/* Confidence */}
                          <td className="px-4 py-3">
                            <div className="flex items-center gap-2">
                              <div className="w-14 h-1.5 rounded-full bg-slate-600 overflow-hidden">
                                <div
                                  className="h-full rounded-full bg-teal-500"
                                  style={{ width: `${Math.round(doc.confidence * 100)}%` }}
                                />
                              </div>
                              <span className="text-slate-300 text-xs whitespace-nowrap">
                                {Math.round(doc.confidence * 100)}%
                              </span>
                            </div>
                          </td>

                          {/* Status */}
                          <td className="px-4 py-3">
                            <Badge
                              label={doc.review_status.replace(/_/g, ' ')}
                              className={statusColor(doc.review_status)}
                            />
                          </td>

                          {/* PII */}
                          <td className="px-4 py-3 text-center">
                            {doc.pii_detected ? (
                              <span className="text-amber-400 font-bold text-xs">YES</span>
                            ) : (
                              <span className="text-slate-500 text-xs">—</span>
                            )}
                          </td>

                          {/* Duplicate */}
                          <td className="px-4 py-3">
                            {doc.is_link ? (
                              <Badge label="LINK →" className="bg-indigo-700 text-indigo-100" />
                            ) : (
                              <span className="text-slate-500 text-xs">—</span>
                            )}
                          </td>

                          {/* Created At */}
                          <td className="px-4 py-3 text-slate-400 text-xs whitespace-nowrap">
                            {fmtDate(doc.created_at)}
                          </td>

                          {/* Actions */}
                          <td className="px-4 py-3">
                            <button
                              onClick={() => toggleExpand(doc.uid)}
                              className={`flex items-center gap-1 text-xs font-semibold rounded px-3 py-1.5 transition-colors ${
                                isExpanded
                                  ? 'bg-teal-700 text-teal-100 hover:bg-teal-600'
                                  : 'bg-slate-700 text-slate-200 hover:bg-slate-600'
                              }`}
                            >
                              {isExpanded ? (
                                <>
                                  <ChevronUp size={13} />
                                  Close
                                </>
                              ) : (
                                <>
                                  <ChevronDown size={13} />
                                  Audit
                                </>
                              )}
                            </button>
                          </td>
                        </tr>

                        {/* Inline Audit Panel */}
                        {isExpanded && (
                          <tr className="bg-slate-900">
                            <td colSpan={9} className="px-4 pb-2 pt-1">
                              <AuditPanel
                                uid={doc.uid}
                                onClose={() => setExpandedUid(null)}
                              />
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

          {/* -------------------------------------------------------------- */}
          {/* Pagination                                                      */}
          {/* -------------------------------------------------------------- */}
          {total > PAGE_SIZE && (
            <div className="flex items-center justify-between pt-1">
              <span className="text-xs text-slate-400">
                Page {page} of {totalPages}
              </span>
              <div className="flex gap-2">
                <button
                  onClick={() => setPage((p) => Math.max(1, p - 1))}
                  disabled={page === 1}
                  className="flex items-center gap-1 text-xs font-medium bg-slate-700 hover:bg-slate-600 disabled:opacity-40 disabled:cursor-not-allowed text-slate-200 rounded px-3 py-1.5 transition-colors"
                >
                  <ChevronLeft size={14} />
                  Prev
                </button>
                <button
                  onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                  disabled={page === totalPages}
                  className="flex items-center gap-1 text-xs font-medium bg-slate-700 hover:bg-slate-600 disabled:opacity-40 disabled:cursor-not-allowed text-slate-200 rounded px-3 py-1.5 transition-colors"
                >
                  Next
                  <ChevronRight size={14} />
                </button>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
};
