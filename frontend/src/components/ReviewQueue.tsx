import React, { useCallback, useEffect, useState } from 'react';
import { AlertCircle, Loader2, RefreshCw } from 'lucide-react';
import { client } from '../api/client';
import type { ReviewTaskSummary } from '../types';

interface ReviewQueueProps {
  onOpenDetail: (uid: string) => void;
}

function confidenceColor(confidence: number): string {
  const pct = confidence * 100;
  if (pct >= 85) return 'text-green-400';
  if (pct >= 70) return 'text-amber-400';
  return 'text-red-400';
}

function statusBadgeClass(status: string): string {
  switch (status.toLowerCase()) {
    case 'pending':
      return 'bg-amber-500/20 text-amber-300 border border-amber-500/40';
    case 'confirmed':
      return 'bg-green-500/20 text-green-300 border border-green-500/40';
    case 'rejected':
      return 'bg-red-500/20 text-red-300 border border-red-500/40';
    case 'corrected':
      return 'bg-teal-500/20 text-teal-300 border border-teal-500/40';
    default:
      return 'bg-slate-600/40 text-slate-300 border border-slate-500/40';
  }
}

function formatDate(value: string | null): string {
  if (!value) return '—';
  try {
    return new Date(value).toLocaleString();
  } catch {
    return value;
  }
}

export const ReviewQueue: React.FC<ReviewQueueProps> = ({ onOpenDetail }) => {
  const [tasks, setTasks] = useState<ReviewTaskSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchQueue = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const { data, error: apiError } = await client.GET('/api/v1/review/queue');
      if (apiError) {
        const msg =
          typeof apiError === 'object' && apiError !== null && 'detail' in apiError
            ? String((apiError as Record<string, unknown>)['detail'])
            : JSON.stringify(apiError);
        setError(msg);
        return;
      }
      const items = Array.isArray(data) ? (data as ReviewTaskSummary[]) : [];
      const sorted = [...items].sort((a, b) => {
        const ta = a.created_at ? new Date(a.created_at).getTime() : 0;
        const tb = b.created_at ? new Date(b.created_at).getTime() : 0;
        return tb - ta;
      });
      setTasks(sorted);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Unknown error');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void fetchQueue();
  }, [fetchQueue]);

  return (
    <div className="space-y-4">
      {/* Header row */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <h2 className="text-xl font-semibold text-slate-100">Review Queue</h2>
          {!loading && !error && (
            <span className="rounded-full bg-teal-600/30 border border-teal-500/40 px-3 py-0.5 text-sm font-medium text-teal-300">
              {tasks.length} pending
            </span>
          )}
        </div>
        <button
          onClick={() => void fetchQueue()}
          disabled={loading}
          className="flex items-center gap-1.5 rounded-md bg-slate-700 px-3 py-1.5 text-sm text-slate-200 hover:bg-slate-600 disabled:opacity-50 transition-colors"
        >
          <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
          Refresh
        </button>
      </div>

      {/* Loading */}
      {loading && (
        <div className="flex items-center gap-3 py-16 justify-center text-slate-400">
          <Loader2 size={22} className="animate-spin text-teal-400" />
          <span>Loading review queue…</span>
        </div>
      )}

      {/* Error */}
      {!loading && error && (
        <div className="flex items-center gap-2 rounded-lg bg-red-900/30 border border-red-700/50 px-4 py-3 text-red-300">
          <AlertCircle size={18} className="shrink-0" />
          <span>Error loading queue: {error}</span>
        </div>
      )}

      {/* Empty */}
      {!loading && !error && tasks.length === 0 && (
        <div className="rounded-lg border border-slate-700 bg-slate-800/60 py-16 text-center text-slate-400">
          No documents pending review.
        </div>
      )}

      {/* Table */}
      {!loading && !error && tasks.length > 0 && (
        <div className="overflow-x-auto rounded-lg border border-slate-700">
          <table className="min-w-full divide-y divide-slate-700 text-sm">
            <thead className="bg-slate-800">
              <tr>
                {[
                  'File Name',
                  'Predicted Type',
                  'Confidence',
                  'PII',
                  'Decision Reason',
                  'Status',
                  'Created At',
                  'Action',
                ].map((col) => (
                  <th
                    key={col}
                    className="whitespace-nowrap px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-slate-400"
                  >
                    {col}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-700/60 bg-slate-800/40">
              {tasks.map((task) => (
                <tr key={task.task_id} className="hover:bg-slate-700/40 transition-colors">
                  {/* File Name */}
                  <td className="max-w-[180px] truncate px-4 py-3 font-medium text-slate-200" title={task.file_name}>
                    {task.file_name}
                  </td>

                  {/* Predicted Type */}
                  <td className="whitespace-nowrap px-4 py-3 text-slate-300">{task.predicted_type}</td>

                  {/* Confidence */}
                  <td className={`whitespace-nowrap px-4 py-3 font-semibold ${confidenceColor(task.confidence)}`}>
                    {Math.round(task.confidence * 100)}%
                  </td>

                  {/* PII */}
                  <td className="px-4 py-3">
                    {task.pii_detected ? (
                      <span className="rounded-full bg-red-500/20 border border-red-500/40 px-2 py-0.5 text-xs font-medium text-red-300">
                        PII
                      </span>
                    ) : (
                      <span className="text-slate-500 text-xs">—</span>
                    )}
                  </td>

                  {/* Decision Reason */}
                  <td
                    className="max-w-[200px] truncate px-4 py-3 text-slate-400"
                    title={task.decision_reason}
                  >
                    {task.decision_reason || '—'}
                  </td>

                  {/* Status */}
                  <td className="whitespace-nowrap px-4 py-3">
                    <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${statusBadgeClass(task.status)}`}>
                      {task.status}
                    </span>
                  </td>

                  {/* Created At */}
                  <td className="whitespace-nowrap px-4 py-3 text-slate-400">
                    {formatDate(task.created_at)}
                  </td>

                  {/* Action */}
                  <td className="whitespace-nowrap px-4 py-3">
                    <button
                      onClick={() => onOpenDetail(task.document_uid)}
                      className="rounded-md bg-teal-600 px-3 py-1 text-xs font-semibold text-white hover:bg-teal-500 transition-colors"
                    >
                      Review →
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
};
