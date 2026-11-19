import React, { useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import {
  AlertTriangle,
  CheckCircle2,
  Cpu,
  FileCheck2,
  Filter,
  Play,
  RefreshCw,
  ShieldAlert,
  Sparkles,
} from 'lucide-react';
import {
  api,
  ReprocessPreviewRequest,
  ReprocessPreviewResponse,
  ReprocessResponse,
} from '../api/client';
import { ConfidenceBadge } from '../components/ConfidenceBadge';

export const ReprocessPage: React.FC = () => {
  const [classifierVersion, setClassifierVersion] = useState('v1.0');
  const [minConfidence, setMinConfidence] = useState('0.90');
  const [selectedTypes, setSelectedTypes] = useState<string[]>(['kyc_form', 'invoice']);
  const [queryText, setQueryText] = useState('classifierVersion <= 1.0 AND confidence < 0.90');
  const [previewData, setPreviewData] = useState<ReprocessPreviewResponse | null>(null);
  const [executionResult, setExecutionResult] = useState<ReprocessResponse | null>(null);

  const previewMutation = useMutation({
    mutationFn: (req: ReprocessPreviewRequest) => api.previewReprocess(req),
    onSuccess: (data) => {
      setPreviewData(data);
    },
    onError: (err: Error) => {
      alert(`Dry run preview failed: ${err.message}`);
    },
  });

  const executeMutation = useMutation({
    mutationFn: (q: string) => api.executeReprocess(q),
    onSuccess: (data) => {
      setExecutionResult(data);
      alert(`Reprocessing job queued: ${data.queued_count} documents targeted for reprocessing.`);
    },
    onError: (err: Error) => {
      alert(`Reprocessing execution failed: ${err.message}`);
    },
  });

  const handleDryRun = () => {
    previewMutation.mutate({
      query: queryText,
      classifier_version_filter: classifierVersion || undefined,
      min_confidence: minConfidence ? parseFloat(minConfidence) : undefined,
      target_types: selectedTypes.length > 0 ? selectedTypes : undefined,
    });
  };

  const handleExecute = () => {
    if (!previewData) {
      alert('Please run a dry-run preview first to inspect candidate documents.');
      return;
    }
    if (
      !confirm(
        `Are you sure you want to execute reprocessing for ${previewData.matched_count} documents? Human-verified fields will remain strictly preserved.`
      )
    ) {
      return;
    }
    executeMutation.mutate(queryText);
  };

  const toggleType = (t: string) => {
    setSelectedTypes((prev) =>
      prev.includes(t) ? prev.filter((item) => item !== t) : [...prev, t]
    );
  };

  const allTypes = [
    'kyc_form',
    'bank_statement',
    'medical_report',
    'claim_form',
    'invoice',
    'contract',
    'purchase_order',
    'unknown',
  ];

  return (
    <div className="p-8 max-w-6xl mx-auto w-full space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight text-white flex items-center gap-2.5">
          <RefreshCw className="w-6 h-6 text-sky-400" />
          Model Reprocessing & Query Engine
        </h1>
        <p className="text-sm text-slate-400 mt-1">
          Query and re-evaluate stored document subsets with upgraded models while strictly safeguarding human-verified fields.
        </p>
      </div>

      {/* Query Builder Form */}
      <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6 shadow-xl space-y-5">
        <h2 className="text-base font-bold text-slate-200 flex items-center gap-2">
          <Filter className="w-4 h-4 text-sky-400" />
          1. Build Reprocessing Filter Criteria
        </h2>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div>
            <label className="block text-xs font-semibold text-slate-400 uppercase tracking-wider mb-1.5">
              Target Classifier Version
            </label>
            <input
              type="text"
              value={classifierVersion}
              onChange={(e) => setClassifierVersion(e.target.value)}
              placeholder="e.g. v1.0"
              className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-xs text-slate-200 focus:outline-none focus:border-sky-500 font-mono"
            />
          </div>

          <div>
            <label className="block text-xs font-semibold text-slate-400 uppercase tracking-wider mb-1.5">
              Maximum Confidence Cutoff
            </label>
            <input
              type="number"
              step="0.01"
              max="1.0"
              min="0.0"
              value={minConfidence}
              onChange={(e) => setMinConfidence(e.target.value)}
              className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-xs text-slate-200 focus:outline-none focus:border-sky-500 font-mono"
            />
          </div>
        </div>

        <div>
          <label className="block text-xs font-semibold text-slate-400 uppercase tracking-wider mb-2">
            Target Document Types
          </label>
          <div className="flex flex-wrap gap-2">
            {allTypes.map((t) => {
              const isSelected = selectedTypes.includes(t);
              return (
                <button
                  key={t}
                  type="button"
                  onClick={() => toggleType(t)}
                  className={`px-3 py-1.5 rounded-lg text-xs font-mono font-medium transition-colors border ${
                    isSelected
                      ? 'bg-sky-600/30 text-sky-300 border-sky-500/60'
                      : 'bg-slate-950 text-slate-400 border-slate-800 hover:border-slate-700'
                  }`}
                >
                  {t}
                </button>
              );
            })}
          </div>
        </div>

        <div className="flex items-center gap-3 pt-3 border-t border-slate-800">
          <button
            onClick={handleDryRun}
            disabled={previewMutation.isPending}
            className="px-5 py-2 bg-slate-800 hover:bg-slate-700 border border-slate-700 text-slate-200 text-xs font-bold rounded-lg flex items-center gap-2 transition-colors disabled:opacity-50"
          >
            <Sparkles className="w-4 h-4 text-sky-400" />
            {previewMutation.isPending ? 'Computing Preview...' : 'Run Dry-Run Preview'}
          </button>
        </div>
      </div>

      {/* Dry Run Preview Results */}
      {previewData && (
        <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6 shadow-xl space-y-5 animate-in fade-in duration-300">
          <div className="flex items-center justify-between pb-3 border-b border-slate-800">
            <div>
              <h2 className="text-base font-bold text-slate-200 flex items-center gap-2">
                <FileCheck2 className="w-4 h-4 text-emerald-400" />
                2. Dry-Run Analysis & Human Verification Safeguards
              </h2>
              <p className="text-xs text-slate-400 mt-0.5">
                Matched documents evaluated against human verification immutability policies.
              </p>
            </div>

            <button
              onClick={handleExecute}
              disabled={executeMutation.isPending || previewData.matched_count === 0}
              className="px-5 py-2 bg-sky-600 hover:bg-sky-500 text-white text-xs font-bold rounded-lg flex items-center gap-2 shadow-lg disabled:opacity-50 transition-colors"
            >
              <Play className="w-4 h-4" />
              {executeMutation.isPending ? 'Queuing Batch...' : `Execute Reprocessing (${previewData.matched_count})`}
            </button>
          </div>

          {/* Metric Badges */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div className="p-4 rounded-xl bg-slate-950 border border-slate-800 flex items-center justify-between">
              <div>
                <span className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider block">
                  Matched Documents
                </span>
                <span className="text-2xl font-bold font-mono text-white mt-1 block">
                  {previewData.matched_count}
                </span>
              </div>
              <Cpu className="w-8 h-8 text-sky-400/80" />
            </div>

            <div className="p-4 rounded-xl bg-slate-950 border border-slate-800 flex items-center justify-between">
              <div>
                <span className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider block">
                  Human-Verified Field Protections
                </span>
                <span className="text-2xl font-bold font-mono text-emerald-400 mt-1 block">
                  {previewData.human_verified_conflict_count}
                </span>
              </div>
              <ShieldAlert className="w-8 h-8 text-emerald-400/80" />
            </div>
          </div>

          <div className="p-3 bg-emerald-950/40 border border-emerald-800/60 rounded-lg text-xs text-emerald-300 flex items-center gap-2">
            <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0" />
            <span>
              <strong>Immutability Guaranteed:</strong> None of the {previewData.human_verified_conflict_count} human-verified fields will be overwritten. Automated re-runs will only evaluate unverified fields.
            </span>
          </div>

          {/* Sample Documents Table */}
          <div>
            <h3 className="text-xs font-bold text-slate-300 uppercase tracking-wider mb-2">
              Sample Candidate Documents (Top 10)
            </h3>
            <div className="border border-slate-800 rounded-xl overflow-hidden bg-slate-950">
              <table className="w-full text-left border-collapse text-xs">
                <thead>
                  <tr className="border-b border-slate-800 bg-slate-900/60 text-slate-400 text-[10px] uppercase font-semibold">
                    <th className="py-2.5 px-3">File Name</th>
                    <th className="py-2.5 px-3">Current Type</th>
                    <th className="py-2.5 px-3">Confidence</th>
                    <th className="py-2.5 px-3">Model</th>
                    <th className="py-2.5 px-3">Protected Human Fields</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800/80 font-mono text-[11px]">
                  {previewData.sample_documents.map((s) => (
                    <tr key={s.uid} className="hover:bg-slate-900/40">
                      <td className="py-2.5 px-3 font-sans text-slate-200">{s.file_name}</td>
                      <td className="py-2.5 px-3 text-slate-300">{s.current_doc_type}</td>
                      <td className="py-2.5 px-3 font-sans">
                        <ConfidenceBadge confidence={s.current_confidence} />
                      </td>
                      <td className="py-2.5 px-3 text-slate-400">{s.classifier_version}</td>
                      <td className="py-2.5 px-3">
                        {s.has_human_verified_fields && s.human_verified_field_names ? (
                          <div className="flex flex-wrap gap-1">
                            {s.human_verified_field_names.map((fn, idx) => (
                              <span
                                key={idx}
                                className="bg-emerald-950 text-emerald-300 border border-emerald-800/80 px-1.5 py-0.2 rounded text-[9px] font-bold"
                              >
                                {fn}
                              </span>
                            ))}
                          </div>
                        ) : (
                          <span className="text-slate-600">none</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
