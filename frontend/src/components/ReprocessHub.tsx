import React, { useState } from 'react';
import {
  AlertTriangle,
  Eye,
  Play,
  Loader2,
  CheckCircle2,
  XCircle,
  ShieldCheck,
} from 'lucide-react';
import { client } from '../api/client';
import type { ReprocessRequest, ReprocessResponse } from '../types';

interface FormState {
  query: string;
  classifier_version_filter: string;
  min_confidence: string;
  target_types: string;
}

const INITIAL_FORM: FormState = {
  query: '',
  classifier_version_filter: '',
  min_confidence: '',
  target_types: '',
};

export const ReprocessHub: React.FC = () => {
  const [form, setForm] = useState<FormState>(INITIAL_FORM);

  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [previewResult, setPreviewResult] = useState<ReprocessResponse | null>(null);

  const [runLoading, setRunLoading] = useState(false);
  const [runError, setRunError] = useState<string | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);

  /* ------------------------------------------------------------------ */
  /*  Helpers                                                             */
  /* ------------------------------------------------------------------ */

  const buildRequestBody = (dry_run: boolean): ReprocessRequest => {
    const body: ReprocessRequest = { dry_run };

    if (form.query.trim()) body.query = form.query.trim();
    if (form.classifier_version_filter.trim())
      body.classifier_version_filter = form.classifier_version_filter.trim();
    if (form.min_confidence.trim()) {
      const val = parseFloat(form.min_confidence);
      if (!isNaN(val)) body.min_confidence = val;
    }
    if (form.target_types.trim()) {
      body.target_types = form.target_types
        .split(',')
        .map((t) => t.trim())
        .filter(Boolean);
    }

    return body;
  };

  const handleFieldChange = (
    e: React.ChangeEvent<HTMLInputElement>
  ) => {
    const { name, value } = e.target;
    setForm((prev) => ({ ...prev, [name]: value }));
    // Reset preview + job when form changes so user must re-run preview
    setPreviewResult(null);
    setPreviewError(null);
    setJobId(null);
    setRunError(null);
  };

  /* ------------------------------------------------------------------ */
  /*  Preview (dry_run: true)                                             */
  /* ------------------------------------------------------------------ */

  const handlePreview = async () => {
    setPreviewLoading(true);
    setPreviewError(null);
    setPreviewResult(null);
    setJobId(null);
    setRunError(null);

    try {
      const { data, error } = await client.POST('/api/v1/reprocess/preview', {
        body: buildRequestBody(true),
      });

      if (error) {
        const msg =
          (error as Record<string, string>).detail ??
          (error as Record<string, string>).message ??
          'Preview failed — unknown error.';
        setPreviewError(msg);
      } else if (data) {
        setPreviewResult(data as unknown as ReprocessResponse);
      }
    } catch (err: unknown) {
      setPreviewError(
        err instanceof Error ? err.message : 'Unexpected error during preview.'
      );
    } finally {
      setPreviewLoading(false);
    }
  };

  /* ------------------------------------------------------------------ */
  /*  Run (dry_run: false)                                                */
  /* ------------------------------------------------------------------ */

  const handleRun = async () => {
    setRunLoading(true);
    setRunError(null);
    setJobId(null);

    try {
      const { data, error } = await client.POST('/api/v1/reprocess/preview', {
        body: buildRequestBody(false),
      });

      if (error) {
        const msg =
          (error as Record<string, string>).detail ??
          (error as Record<string, string>).message ??
          'Reprocess run failed — unknown error.';
        setRunError(msg);
      } else if (data) {
        const resp = data as unknown as ReprocessResponse;
        setJobId(resp.job_id);
      }
    } catch (err: unknown) {
      setRunError(
        err instanceof Error ? err.message : 'Unexpected error during reprocess run.'
      );
    } finally {
      setRunLoading(false);
    }
  };

  /* ------------------------------------------------------------------ */
  /*  Render                                                              */
  /* ------------------------------------------------------------------ */

  const runEnabled = previewResult !== null && !previewLoading && !runLoading;

  return (
    <div className="min-h-full p-6 space-y-6">
      {/* Page heading */}
      <div>
        <h1 className="text-2xl font-semibold text-slate-100">Reprocess Hub</h1>
        <p className="mt-1 text-sm text-slate-400">
          Preview and trigger bulk reprocessing runs with optional filters.
        </p>
      </div>

      {/* Warning banner — always visible */}
      <div className="flex items-start gap-3 rounded-lg border border-amber-500/40 bg-amber-500/10 px-4 py-3">
        <ShieldCheck className="mt-0.5 h-5 w-5 shrink-0 text-amber-400" aria-hidden />
        <p className="text-sm text-amber-300">
          <span className="font-semibold">Important:</span> Reprocessing does{' '}
          <span className="underline">not</span> overwrite human-verified fields. All
          manual reviewer decisions are preserved.
        </p>
      </div>

      {/* Filter form */}
      <section className="rounded-xl border border-slate-700 bg-slate-800 p-6 space-y-5">
        <h2 className="text-base font-medium text-slate-200">Filters (all optional)</h2>

        <div className="grid gap-5 sm:grid-cols-2">
          {/* Query */}
          <div className="flex flex-col gap-1.5">
            <label
              htmlFor="query"
              className="text-xs font-medium uppercase tracking-wide text-slate-400"
            >
              Query
            </label>
            <input
              id="query"
              name="query"
              type="text"
              value={form.query}
              onChange={handleFieldChange}
              placeholder="e.g. status:PENDING"
              className="rounded-lg border border-slate-600 bg-slate-900 px-3 py-2 text-sm text-slate-100 placeholder-slate-500 outline-none focus:border-teal-500 focus:ring-1 focus:ring-teal-500"
            />
          </div>

          {/* Classifier version filter */}
          <div className="flex flex-col gap-1.5">
            <label
              htmlFor="classifier_version_filter"
              className="text-xs font-medium uppercase tracking-wide text-slate-400"
            >
              Classifier Version Filter
            </label>
            <input
              id="classifier_version_filter"
              name="classifier_version_filter"
              type="text"
              value={form.classifier_version_filter}
              onChange={handleFieldChange}
              placeholder="e.g. v2.1"
              className="rounded-lg border border-slate-600 bg-slate-900 px-3 py-2 text-sm text-slate-100 placeholder-slate-500 outline-none focus:border-teal-500 focus:ring-1 focus:ring-teal-500"
            />
          </div>

          {/* Min confidence */}
          <div className="flex flex-col gap-1.5">
            <label
              htmlFor="min_confidence"
              className="text-xs font-medium uppercase tracking-wide text-slate-400"
            >
              Min Confidence (0 – 1)
            </label>
            <input
              id="min_confidence"
              name="min_confidence"
              type="number"
              min={0}
              max={1}
              step={0.01}
              value={form.min_confidence}
              onChange={handleFieldChange}
              placeholder="e.g. 0.75"
              className="rounded-lg border border-slate-600 bg-slate-900 px-3 py-2 text-sm text-slate-100 placeholder-slate-500 outline-none focus:border-teal-500 focus:ring-1 focus:ring-teal-500"
            />
          </div>

          {/* Target types */}
          <div className="flex flex-col gap-1.5">
            <label
              htmlFor="target_types"
              className="text-xs font-medium uppercase tracking-wide text-slate-400"
            >
              Target Types{' '}
              <span className="normal-case font-normal text-slate-500">
                (comma-separated)
              </span>
            </label>
            <input
              id="target_types"
              name="target_types"
              type="text"
              value={form.target_types}
              onChange={handleFieldChange}
              placeholder="e.g. invoice, contract, receipt"
              className="rounded-lg border border-slate-600 bg-slate-900 px-3 py-2 text-sm text-slate-100 placeholder-slate-500 outline-none focus:border-teal-500 focus:ring-1 focus:ring-teal-500"
            />
          </div>
        </div>

        {/* Action buttons */}
        <div className="flex flex-wrap items-center gap-3 pt-1">
          {/* Preview button */}
          <button
            type="button"
            onClick={handlePreview}
            disabled={previewLoading || runLoading}
            className="inline-flex items-center gap-2 rounded-lg bg-teal-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-teal-500 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {previewLoading ? (
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
            ) : (
              <Eye className="h-4 w-4" aria-hidden />
            )}
            {previewLoading ? 'Previewing…' : 'Preview (dry run)'}
          </button>

          {/* Run button — gated until preview succeeds */}
          <button
            type="button"
            onClick={handleRun}
            disabled={!runEnabled}
            title={
              !runEnabled
                ? 'Run a successful dry-run preview first'
                : 'Start reprocess job'
            }
            className="inline-flex items-center gap-2 rounded-lg bg-slate-700 px-4 py-2 text-sm font-medium text-slate-100 transition-colors hover:bg-slate-600 disabled:cursor-not-allowed disabled:opacity-40"
          >
            {runLoading ? (
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
            ) : (
              <Play className="h-4 w-4" aria-hidden />
            )}
            {runLoading ? 'Starting…' : 'Run Reprocess'}
          </button>
        </div>
      </section>

      {/* Preview error */}
      {previewError && (
        <div className="flex items-start gap-3 rounded-lg border border-red-500/40 bg-red-500/10 px-4 py-3">
          <XCircle className="mt-0.5 h-5 w-5 shrink-0 text-red-400" aria-hidden />
          <p className="text-sm text-red-300">
            <span className="font-semibold">Preview error: </span>
            {previewError}
          </p>
        </div>
      )}

      {/* Preview result card */}
      {previewResult && (
        <section className="rounded-xl border border-teal-600/40 bg-slate-800 p-5 space-y-4">
          <div className="flex items-center gap-2">
            <Eye className="h-5 w-5 text-teal-400" aria-hidden />
            <h2 className="text-base font-medium text-slate-100">Dry-Run Preview</h2>
            <span className="ml-auto rounded-full border border-teal-500/30 bg-teal-500/10 px-2.5 py-0.5 text-xs font-medium text-teal-400">
              Dry run
            </span>
          </div>

          <p className="text-slate-200">
            Would reprocess{' '}
            <span className="font-semibold text-teal-300">
              {previewResult.matched_count}
            </span>{' '}
            document{previewResult.matched_count !== 1 ? 's' : ''}{' '}
            <span className="text-slate-400">
              (queued:{' '}
              <span className="text-slate-200 font-medium">
                {previewResult.queued_count}
              </span>
              , skipped:{' '}
              <span className="text-slate-200 font-medium">
                {previewResult.skipped_count}
              </span>
              )
            </span>
          </p>

          <dl className="grid grid-cols-3 gap-3">
            {(
              [
                { label: 'Matched', value: previewResult.matched_count, color: 'text-teal-300' },
                { label: 'Queued', value: previewResult.queued_count, color: 'text-sky-300' },
                { label: 'Skipped', value: previewResult.skipped_count, color: 'text-amber-300' },
              ] as const
            ).map(({ label, value, color }) => (
              <div
                key={label}
                className="flex flex-col items-center rounded-lg border border-slate-700 bg-slate-900 px-4 py-3 gap-1"
              >
                <dt className="text-xs text-slate-400">{label}</dt>
                <dd className={`text-2xl font-bold tabular-nums ${color}`}>{value}</dd>
              </div>
            ))}
          </dl>

          <div className="flex items-center gap-2 rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-xs text-slate-400">
            <AlertTriangle className="h-3.5 w-3.5 text-amber-400 shrink-0" aria-hidden />
            Human-verified fields will <strong className="text-slate-300">not</strong> be
            overwritten during the actual run.
          </div>
        </section>
      )}

      {/* Run error */}
      {runError && (
        <div className="flex items-start gap-3 rounded-lg border border-red-500/40 bg-red-500/10 px-4 py-3">
          <XCircle className="mt-0.5 h-5 w-5 shrink-0 text-red-400" aria-hidden />
          <p className="text-sm text-red-300">
            <span className="font-semibold">Run error: </span>
            {runError}
          </p>
        </div>
      )}

      {/* Job started success */}
      {jobId && (
        <div className="flex items-start gap-3 rounded-lg border border-teal-500/40 bg-teal-500/10 px-4 py-3">
          <CheckCircle2 className="mt-0.5 h-5 w-5 shrink-0 text-teal-400" aria-hidden />
          <p className="text-sm text-teal-200">
            <span className="font-semibold">Job started:</span>{' '}
            <code className="rounded bg-slate-800 px-1.5 py-0.5 font-mono text-teal-300">
              {jobId}
            </code>
          </p>
        </div>
      )}
    </div>
  );
};
