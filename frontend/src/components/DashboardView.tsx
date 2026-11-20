import React, { useState, useEffect } from 'react';
import {
  FileCheck,
  CheckCircle2,
  Clock,
  AlertTriangle,
  ArrowRight,
  ChevronDown,
  ChevronUp,
  Cpu,
  FolderArchive,
} from 'lucide-react';
import type { DashboardStats } from '../types';
import { BASE_URL, getAuthToken } from '../api/client';

interface DashboardViewProps {
  stats: DashboardStats | null;
  onNavigateTab: (tab: string) => void;
  onSelectBatch?: (batchId: string) => void;
}

interface RecentBatch {
  batch_id: string;
  name: string;
  number: number;
  created_at: string;
  file_count: number;
  progress_percent: number;
  needs_check_count: number;
}

export const DashboardView: React.FC<DashboardViewProps> = ({
  stats,
  onNavigateTab,
  onSelectBatch,
}) => {
  const [showTechnicalDetails, setShowTechnicalDetails] = useState(false);
  const [recentBatches, setRecentBatches] = useState<RecentBatch[]>([]);
  const [loadingBatches, setLoadingBatches] = useState(false);

  useEffect(() => {
    let cancelled = false;
    async function loadRecentBatches() {
      setLoadingBatches(true);
      try {
        const headers: Record<string, string> = {};
        const tok = getAuthToken();
        if (tok) headers['Authorization'] = `Bearer ${tok}`;
        const res = await fetch(`${BASE_URL}/api/v1/batches?page=1&page_size=5`, { headers });
        if (res.ok) {
          const json = await res.json();
          if (!cancelled) setRecentBatches(json.items || []);
        }
      } catch {
        // Ignore
      } finally {
        if (!cancelled) setLoadingBatches(false);
      }
    }
    void loadRecentBatches();
    return () => {
      cancelled = true;
    };
  }, []);

  const total = stats?.total_documents ?? 0;
  const sortedAuto = stats?.auto_accepted ?? 0;
  const needsCheck = stats?.pending_review ?? 0;
  const failed = stats?.quarantined ?? 0;

  // Single plain sentence summarizing state
  const summarySentence =
    total === 0
      ? 'No files received yet. Upload your first document batch to begin.'
      : needsCheck > 0
        ? `All ${total} files received, ${needsCheck} ${needsCheck === 1 ? 'needs' : 'need'} a quick check.`
        : `All ${total} files sorted automatically with zero errors.`;

  const stages = [
    { id: 'virus_scan', name: 'Virus Scan', tag: 'ClamAV', desc: 'Safety & integrity check' },
    { id: 'deduplication', name: 'Deduplication', tag: 'SHA-256', desc: 'Duplicate file prevention' },
    { id: 'ocr', name: 'Reading text', tag: 'Tesseract OCR', desc: 'Text & bounding box capture' },
    { id: 'classify', name: 'Classifier', tag: 'TF-IDF+LR', desc: 'Automatic document classification' },
    { id: 'extract', name: 'Field Extraction', tag: 'Pydantic v2', desc: 'Key-value extraction' },
    { id: 'pii', name: 'Private info checked', tag: 'Presidio', desc: 'PII detection and masking' },
    { id: 'decision_gate', name: 'Decision Gate', tag: 'Confidence', desc: 'Automated vs Human triage' },
  ];

  return (
    <div className="space-y-8 max-w-6xl mx-auto">
      {/* ── Top Summary Sentence Banner ── */}
      <div className="p-6 rounded-3xl bg-gradient-to-r from-slate-900/90 to-teal-950/30 border border-slate-800 shadow-xl flex flex-col md:flex-row md:items-center md:justify-between gap-4">
        <div>
          <span className="text-xs font-semibold text-teal-400 uppercase tracking-wider block mb-1">
            Status Overview
          </span>
          <h1 className="text-xl sm:text-2xl font-bold text-white tracking-tight">
            {summarySentence}
          </h1>
          <p className="text-xs text-slate-400 mt-1">
            Files are classified, text is read, and sensitive data is automatically protected.
          </p>
        </div>

        <button
          onClick={() => onNavigateTab('ingest')}
          className="flex items-center space-x-2 px-5 py-2.5 rounded-xl text-xs font-bold bg-teal-500 hover:bg-teal-400 text-slate-950 shadow-lg shadow-teal-500/20 transition whitespace-nowrap self-start md:self-auto"
        >
          <span>Upload files</span>
          <ArrowRight className="w-4 h-4" />
        </button>
      </div>

      {/* ── 4 Large Numbers with Plain Labels ── */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {/* 1. Files received */}
        <div className="p-5 rounded-2xl bg-slate-900/80 border border-slate-800 shadow-sm relative overflow-hidden group">
          <div className="flex items-center justify-between text-slate-400">
            <span className="text-xs font-semibold uppercase tracking-wider">Files received</span>
            <FileCheck className="w-5 h-5 text-slate-400" />
          </div>
          <div className="mt-3">
            <span className="text-4xl font-extrabold text-white font-mono tracking-tight">{total}</span>
          </div>
          <p className="mt-1 text-xs text-slate-500">Total documents uploaded</p>
        </div>

        {/* 2. Sorted automatically */}
        <div className="p-5 rounded-2xl bg-slate-900/80 border border-emerald-500/20 shadow-sm relative overflow-hidden group">
          <div className="flex items-center justify-between text-emerald-400">
            <span className="text-xs font-semibold uppercase tracking-wider">Sorted automatically</span>
            <CheckCircle2 className="w-5 h-5 text-emerald-400" />
          </div>
          <div className="mt-3">
            <span className="text-4xl font-extrabold text-emerald-400 font-mono tracking-tight">{sortedAuto}</span>
          </div>
          <p className="mt-1 text-xs text-emerald-500/70">Classified with high confidence</p>
        </div>

        {/* 3. Need a quick check */}
        <div
          onClick={() => onNavigateTab('review')}
          className="p-5 rounded-2xl bg-slate-900/80 border border-amber-500/30 hover:border-amber-500/60 cursor-pointer shadow-sm relative overflow-hidden group transition"
        >
          <div className="flex items-center justify-between text-amber-300">
            <span className="text-xs font-semibold uppercase tracking-wider">Need a quick check</span>
            <Clock className="w-5 h-5 text-amber-400" />
          </div>
          <div className="mt-3">
            <span className="text-4xl font-extrabold text-amber-300 font-mono tracking-tight">{needsCheck}</span>
          </div>
          <p className="mt-1 text-xs text-amber-400/70">Awaiting human review →</p>
        </div>

        {/* 4. Failed / Blocked */}
        <div className="p-5 rounded-2xl bg-slate-900/80 border border-rose-500/20 shadow-sm relative overflow-hidden group">
          <div className="flex items-center justify-between text-rose-400">
            <span className="text-xs font-semibold uppercase tracking-wider">Failed</span>
            <AlertTriangle className="w-5 h-5 text-rose-400" />
          </div>
          <div className="mt-3">
            <span className="text-4xl font-extrabold text-rose-400 font-mono tracking-tight">{failed}</span>
          </div>
          <p className="mt-1 text-xs text-rose-500/70">Blocked by safety check</p>
        </div>
      </div>

      {/* ── Latest Uploads List ── */}
      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <h2 className="text-base font-bold text-white flex items-center space-x-2">
            <FolderArchive className="w-5 h-5 text-teal-400" />
            <span>Latest uploads</span>
          </h2>
          <button
            onClick={() => onNavigateTab('my_uploads')}
            className="text-xs font-semibold text-teal-400 hover:text-teal-300 transition"
          >
            See all uploads →
          </button>
        </div>

        {loadingBatches && recentBatches.length === 0 ? (
          <div className="py-8 text-center text-xs text-slate-500">Loading recent uploads...</div>
        ) : recentBatches.length === 0 ? (
          <div className="p-8 text-center rounded-2xl border border-slate-800 bg-slate-900/40 text-xs text-slate-400">
            No uploads yet. Click "Upload files" to start your first batch.
          </div>
        ) : (
          <div className="space-y-2.5">
            {recentBatches.map((batch) => (
              <div
                key={batch.batch_id}
                className="p-4 rounded-xl bg-slate-900/60 border border-slate-800 flex items-center justify-between gap-4 hover:border-slate-700 transition"
              >
                <div>
                  <div className="flex items-center space-x-2">
                    <span className="text-sm font-bold text-white">{batch.name || `Upload #${batch.number}`}</span>
                    <span className="text-xs text-slate-500">·</span>
                    <span className="text-xs text-slate-400">{batch.file_count} files</span>
                    <span className="text-xs text-slate-500">·</span>
                    <span className="text-xs text-emerald-400 font-semibold">{batch.progress_percent}% done</span>
                  </div>
                  {batch.needs_check_count > 0 && (
                    <span className="text-[11px] text-amber-400 font-medium mt-0.5 block">
                      {batch.needs_check_count} need a quick check
                    </span>
                  )}
                </div>

                <button
                  onClick={() => {
                    if (onSelectBatch) onSelectBatch(batch.batch_id);
                    else onNavigateTab('my_uploads');
                  }}
                  className="flex items-center space-x-1 px-3 py-1.5 text-xs font-semibold rounded-lg bg-teal-500/15 hover:bg-teal-500/25 text-teal-300 border border-teal-500/30 transition"
                >
                  <span>View</span>
                  <ArrowRight className="w-3.5 h-3.5" />
                </button>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* ── Technical Details Collapsible (Collapsed by default) ── */}
      <div className="rounded-2xl border border-slate-800/80 bg-slate-900/40 overflow-hidden">
        <button
          onClick={() => setShowTechnicalDetails(!showTechnicalDetails)}
          className="w-full px-5 py-4 flex items-center justify-between text-left hover:bg-slate-800/30 transition"
        >
          <div className="flex items-center space-x-2">
            <Cpu className="w-4 h-4 text-slate-400" />
            <span className="text-xs font-bold text-slate-300 uppercase tracking-wider">
              Technical details
            </span>
            <span className="text-[11px] text-slate-500">
              (Throughput, latency, model versions, OCR engine)
            </span>
          </div>
          {showTechnicalDetails ? (
            <ChevronUp className="w-4 h-4 text-slate-400" />
          ) : (
            <ChevronDown className="w-4 h-4 text-slate-400" />
          )}
        </button>

        {showTechnicalDetails && (
          <div className="p-6 border-t border-slate-800/80 space-y-6">
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
              <div className="p-3.5 rounded-xl bg-slate-950/60 border border-slate-800">
                <span className="text-[11px] text-slate-400 font-medium block">STP Success Rate</span>
                <span className="text-xl font-bold text-emerald-400 font-mono mt-1 block">
                  {stats?.stp_rate ?? 0}%
                </span>
              </div>
              <div className="p-3.5 rounded-xl bg-slate-950/60 border border-slate-800">
                <span className="text-[11px] text-slate-400 font-medium block">Live Queue Depth</span>
                <span className="text-xl font-bold text-teal-300 font-mono mt-1 block">
                  {stats?.queue_depths?.live ?? 0}
                </span>
              </div>
              <div className="p-3.5 rounded-xl bg-slate-950/60 border border-slate-800">
                <span className="text-[11px] text-slate-400 font-medium block">Classifier Model</span>
                <span className="text-sm font-semibold text-slate-200 mt-1 block">
                  TF-IDF + LR (v2.0)
                </span>
              </div>
              <div className="p-3.5 rounded-xl bg-slate-950/60 border border-slate-800">
                <span className="text-[11px] text-slate-400 font-medium block">PII Engine</span>
                <span className="text-sm font-semibold text-slate-200 mt-1 block">
                  Microsoft Presidio
                </span>
              </div>
            </div>

            <div>
              <h4 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-3">
                Pipeline Stages
              </h4>
              <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-3">
                {stages.map((stg) => (
                  <div key={stg.id} className="p-3 rounded-xl bg-slate-950/40 border border-slate-800 text-xs">
                    <div className="flex items-center justify-between">
                      <span className="font-bold text-slate-200">{stg.name}</span>
                      <span className="text-[10px] px-1.5 py-0.5 rounded bg-slate-800 text-teal-400 font-mono">
                        {stg.tag}
                      </span>
                    </div>
                    <p className="text-[11px] text-slate-500 mt-1">{stg.desc}</p>
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};
