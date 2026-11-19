import React, { useCallback, useEffect, useRef, useState } from 'react';
import { AlertCircle, ArrowLeft, CheckCircle, Loader2 } from 'lucide-react';
import { client, BASE_URL } from '../api/client';
import type { ReviewTaskDetail, ReviewActionPayload } from '../types';

interface ReviewDetailProps {
  uid: string;
  onBack: () => void;
  onActionComplete: () => void;
}

type ActionChoice = 'CONFIRM' | 'CORRECT' | 'REJECT';

function confidenceColor(confidence: number): string {
  const pct = confidence * 100;
  if (pct >= 85) return 'text-green-400';
  if (pct >= 70) return 'text-amber-400';
  return 'text-red-400';
}

export const ReviewDetail: React.FC<ReviewDetailProps> = ({ uid, onBack, onActionComplete }) => {
  const [task, setTask] = useState<ReviewTaskDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notFound, setNotFound] = useState(false);

  // Action form state
  const [action, setAction] = useState<ActionChoice>('CONFIRM');
  const [correctedType, setCorrectedType] = useState('');
  const [reviewNotes, setReviewNotes] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [submitSuccess, setSubmitSuccess] = useState(false);

  // Guard against double-fire in StrictMode
  const hasFetched = useRef(false);

  const fetchTask = useCallback(async () => {
    setLoading(true);
    setError(null);
    setNotFound(false);
    try {
      // LOCAL MODE ONLY — reviewer-1 role header sent via raw fetch
      // VITE_API_BASE_URL drives the base so no hardcoded hostname leaks into prod.
      const base = BASE_URL;
      const res = await fetch(`${base}/review/api/task/${encodeURIComponent(uid)}`, {
        headers: {
          'X-User-Role': 'admin',
        },
      });
      if (res.status === 404) {
        setNotFound(true);
        return;
      }
      if (!res.ok) {
        let msg = `HTTP ${res.status}`;
        try {
          const body = (await res.json()) as Record<string, unknown>;
          msg = typeof body['detail'] === 'string' ? body['detail'] : JSON.stringify(body);
        } catch {
          // ignore parse failure
        }
        setError(msg);
        return;
      }
      const data = (await res.json()) as ReviewTaskDetail;
      setTask(data);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Unknown error');
    } finally {
      setLoading(false);
    }
  }, [uid]);

  useEffect(() => {
    // Prevent StrictMode double-fetch from triggering twice
    if (hasFetched.current) return;
    hasFetched.current = true;
    void fetchTask();
  }, [fetchTask]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!task) return;
    setSubmitting(true);
    setSubmitError(null);

    // LOCAL MODE ONLY — reviewer_id is hardcoded for local development
    const payload: ReviewActionPayload = {
      reviewer_id: 'reviewer-1', // LOCAL MODE ONLY
      action,
      ...(action === 'CORRECT' && correctedType ? { corrected_type: correctedType } : {}),
      ...(reviewNotes ? { review_notes: reviewNotes } : {}),
    };

    try {
      const { error: apiError } = await client.POST('/api/v1/review/{document_uid}/action', {
        params: { path: { document_uid: uid } },
        body: payload,
      });
      if (apiError) {
        const msg =
          typeof apiError === 'object' && apiError !== null && 'detail' in apiError
            ? String((apiError as Record<string, unknown>)['detail'])
            : JSON.stringify(apiError);
        setSubmitError(msg);
        return;
      }
      setSubmitSuccess(true);
      setTimeout(() => {
        onActionComplete();
      }, 1500);
    } catch (e: unknown) {
      setSubmitError(e instanceof Error ? e.message : 'Unknown error');
    } finally {
      setSubmitting(false);
    }
  };

  // ── Loading ────────────────────────────────────────────────────────────────
  if (loading) {
    return (
      <div className="flex items-center gap-3 py-24 justify-center text-slate-400">
        <Loader2 size={22} className="animate-spin text-teal-400" />
        <span>Loading document review…</span>
      </div>
    );
  }

  // ── Not found ──────────────────────────────────────────────────────────────
  if (notFound) {
    return (
      <div className="space-y-4">
        <button onClick={onBack} className="flex items-center gap-1.5 text-sm text-teal-400 hover:text-teal-300">
          <ArrowLeft size={16} />← Back to Queue
        </button>
        <div className="rounded-lg border border-slate-700 bg-slate-800/60 py-16 text-center text-slate-400">
          Task not found for document <span className="font-mono text-slate-300">{uid}</span>.
        </div>
      </div>
    );
  }

  // ── Error ──────────────────────────────────────────────────────────────────
  if (error) {
    return (
      <div className="space-y-4">
        <button onClick={onBack} className="flex items-center gap-1.5 text-sm text-teal-400 hover:text-teal-300">
          <ArrowLeft size={16} />← Back to Queue
        </button>
        <div className="flex items-center gap-2 rounded-lg bg-red-900/30 border border-red-700/50 px-4 py-3 text-red-300">
          <AlertCircle size={18} className="shrink-0" />
          <span>Error loading task: {error}</span>
        </div>
      </div>
    );
  }

  if (!task) return null;

  const extractedKeys = Object.keys(task.extracted_fields ?? {});

  return (
    <div className="space-y-6 pb-12">
      {/* Back */}
      <button
        onClick={onBack}
        className="flex items-center gap-1.5 text-sm text-teal-400 hover:text-teal-300 transition-colors"
      >
        <ArrowLeft size={16} />← Back to Queue
      </button>

      {/* Title */}
      <div>
        <h2 className="text-xl font-semibold text-slate-100 break-all">{task.file_name}</h2>
        <p className="mt-0.5 text-xs text-slate-500">Document UID: {task.document_uid}</p>
      </div>

      {/* Core metadata */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <MetaCard label="Document Type" value={task.doc_type} />
        <MetaCard
          label="Confidence"
          value={`${Math.round(task.confidence * 100)}%`}
          valueClass={confidenceColor(task.confidence)}
        />
        <MetaCard
          label="SHA-256"
          value={`${task.sha256.slice(0, 16)}…`}
          mono
          title={task.sha256}
        />
        <MetaCard label="Retention Class" value={task.retention_class || '—'} />
        <MetaCard label="ACL" value={task.acl || '—'} />
        <MetaCard label="Decision Reason" value={task.decision_reason || '—'} />
      </div>

      {/* PII */}
      <section className="rounded-lg border border-slate-700 bg-slate-800/50 p-4 space-y-2">
        <h3 className="text-sm font-semibold text-slate-300 uppercase tracking-wide">PII</h3>
        <div className="flex flex-wrap gap-2 items-center">
          {task.pii_detected ? (
            <span className="rounded-full bg-red-500/20 border border-red-500/40 px-2.5 py-0.5 text-xs font-medium text-red-300">
              PII Detected
            </span>
          ) : (
            <span className="rounded-full bg-slate-600/40 border border-slate-500/40 px-2.5 py-0.5 text-xs text-slate-400">
              No PII
            </span>
          )}
          {task.pii_types.map((t) => (
            <span
              key={t}
              className="rounded-full bg-orange-500/10 border border-orange-500/30 px-2.5 py-0.5 text-xs text-orange-300"
            >
              {t}
            </span>
          ))}
        </div>

        {task.pii_entities && task.pii_entities.length > 0 && (
          <div className="mt-2 space-y-1">
            <p className="text-xs text-slate-500 font-medium">Entities</p>
            <ul className="space-y-0.5">
              {task.pii_entities.map((ent, i) => (
                <li key={i} className="flex gap-2 text-xs text-slate-300">
                  <span className="font-medium text-orange-300">{ent.type}</span>
                  {ent.text && <span className="text-slate-400">{ent.text}</span>}
                  {ent.score !== undefined && (
                    <span className="text-slate-500">({Math.round(ent.score * 100)}%)</span>
                  )}
                </li>
              ))}
            </ul>
          </div>
        )}
      </section>

      {/* Extracted fields */}
      {extractedKeys.length > 0 && (
        <section className="rounded-lg border border-slate-700 bg-slate-800/50 p-4 space-y-2">
          <h3 className="text-sm font-semibold text-slate-300 uppercase tracking-wide">Extracted Fields</h3>
          <div className="overflow-x-auto">
            <table className="min-w-full text-xs divide-y divide-slate-700">
              <thead>
                <tr>
                  <th className="py-2 pr-4 text-left text-slate-400 font-semibold">Field</th>
                  <th className="py-2 pr-4 text-left text-slate-400 font-semibold">Value</th>
                  <th className="py-2 text-left text-slate-400 font-semibold">Confidence</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-700/40">
                {extractedKeys.map((key) => {
                  const rawVal = task.extracted_fields[key];
                  const val = typeof rawVal === 'object' ? JSON.stringify(rawVal) : String(rawVal ?? '—');
                  const conf = task.field_confidences?.[key];
                  return (
                    <tr key={key} className="hover:bg-slate-700/30 transition-colors">
                      <td className="py-1.5 pr-4 font-mono text-teal-300">{key}</td>
                      <td className="py-1.5 pr-4 text-slate-200 break-all">{val}</td>
                      <td className={`py-1.5 font-semibold ${conf !== undefined ? confidenceColor(conf) : 'text-slate-500'}`}>
                        {conf !== undefined ? `${Math.round(conf * 100)}%` : '—'}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {/* Evidence text */}
      {task.evidence_text && (
        <section className="rounded-lg border border-slate-700 bg-slate-800/50 p-4 space-y-2">
          <h3 className="text-sm font-semibold text-slate-300 uppercase tracking-wide">Evidence Text</h3>
          <pre className="max-h-40 overflow-y-auto rounded bg-slate-900 p-3 text-xs text-slate-300 whitespace-pre-wrap break-all">
            {task.evidence_text}
          </pre>
        </section>
      )}

      {/* Action form */}
      <section className="rounded-lg border border-slate-600 bg-slate-800/70 p-5 space-y-5">
        <h3 className="text-sm font-semibold text-slate-200 uppercase tracking-wide">Record Decision</h3>

        {submitSuccess ? (
          <div className="flex items-center gap-2 rounded-lg bg-green-900/30 border border-green-700/50 px-4 py-3 text-green-300">
            <CheckCircle size={18} className="shrink-0" />
            Decision recorded.
          </div>
        ) : (
          <form onSubmit={(e) => void handleSubmit(e)} className="space-y-4">
            {/* Action radio */}
            <div className="flex flex-wrap gap-4">
              {(['CONFIRM', 'CORRECT', 'REJECT'] as ActionChoice[]).map((opt) => (
                <label
                  key={opt}
                  className={`flex items-center gap-2 cursor-pointer rounded-md border px-4 py-2 text-sm font-medium transition-colors
                    ${action === opt
                      ? opt === 'CONFIRM'
                        ? 'bg-green-600/20 border-green-500/60 text-green-300'
                        : opt === 'CORRECT'
                          ? 'bg-teal-600/20 border-teal-500/60 text-teal-300'
                          : 'bg-red-600/20 border-red-500/60 text-red-300'
                      : 'bg-slate-700/50 border-slate-600 text-slate-400 hover:border-slate-500'
                    }`}
                >
                  <input
                    type="radio"
                    name="action"
                    value={opt}
                    checked={action === opt}
                    onChange={() => setAction(opt)}
                    className="accent-teal-500"
                  />
                  {opt}
                </label>
              ))}
            </div>

            {/* CORRECT-only fields */}
            {action === 'CORRECT' && (
              <div className="space-y-3 rounded-md border border-teal-700/40 bg-teal-900/10 p-4">
                <div>
                  <label className="block text-xs font-medium text-slate-400 mb-1">
                    Corrected Type <span className="text-red-400">*</span>
                  </label>
                  <input
                    type="text"
                    value={correctedType}
                    onChange={(e) => setCorrectedType(e.target.value)}
                    required
                    placeholder="e.g. INVOICE"
                    className="w-full rounded-md border border-slate-600 bg-slate-900 px-3 py-2 text-sm text-slate-200 placeholder-slate-500 focus:border-teal-500 focus:outline-none focus:ring-1 focus:ring-teal-500"
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium text-slate-400 mb-1">Review Notes</label>
                  <textarea
                    value={reviewNotes}
                    onChange={(e) => setReviewNotes(e.target.value)}
                    rows={3}
                    placeholder="Optional notes about the correction…"
                    className="w-full rounded-md border border-slate-600 bg-slate-900 px-3 py-2 text-sm text-slate-200 placeholder-slate-500 focus:border-teal-500 focus:outline-none focus:ring-1 focus:ring-teal-500 resize-y"
                  />
                </div>
              </div>
            )}

            {/* Notes for non-CORRECT actions */}
            {action !== 'CORRECT' && (
              <div>
                <label className="block text-xs font-medium text-slate-400 mb-1">Review Notes (optional)</label>
                <textarea
                  value={reviewNotes}
                  onChange={(e) => setReviewNotes(e.target.value)}
                  rows={2}
                  placeholder="Optional notes…"
                  className="w-full rounded-md border border-slate-600 bg-slate-900 px-3 py-2 text-sm text-slate-200 placeholder-slate-500 focus:border-teal-500 focus:outline-none focus:ring-1 focus:ring-teal-500 resize-y"
                />
              </div>
            )}

            {/* Submit error */}
            {submitError && (
              <div className="flex items-center gap-2 rounded-lg bg-red-900/30 border border-red-700/50 px-4 py-3 text-sm text-red-300">
                <AlertCircle size={16} className="shrink-0" />
                {submitError}
              </div>
            )}

            <button
              type="submit"
              disabled={submitting}
              className="flex items-center gap-2 rounded-md bg-teal-600 px-5 py-2 text-sm font-semibold text-white hover:bg-teal-500 disabled:opacity-50 transition-colors"
            >
              {submitting && <Loader2 size={14} className="animate-spin" />}
              Submit Decision
            </button>
          </form>
        )}
      </section>
    </div>
  );
};

// ── Helper ─────────────────────────────────────────────────────────────────

interface MetaCardProps {
  label: string;
  value: string;
  valueClass?: string;
  mono?: boolean;
  title?: string;
}

const MetaCard: React.FC<MetaCardProps> = ({ label, value, valueClass, mono, title }) => (
  <div className="rounded-lg border border-slate-700 bg-slate-800/50 px-4 py-3">
    <p className="text-xs font-medium text-slate-500 uppercase tracking-wide">{label}</p>
    <p
      className={`mt-1 break-all text-sm font-semibold ${valueClass ?? 'text-slate-200'} ${mono ? 'font-mono' : ''}`}
      title={title}
    >
      {value}
    </p>
  </div>
);
