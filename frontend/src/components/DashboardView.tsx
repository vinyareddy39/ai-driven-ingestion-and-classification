import React from 'react';
import {
  ShieldCheck,
  CheckCircle2,
  Clock,
  AlertTriangle,
  Copy,
  Zap,
  ArrowRight,
  TrendingUp,
  Server,
  FileCheck,
  Eye,
  ExternalLink,
} from 'lucide-react';
import type { DashboardStats } from '../types';

interface DashboardViewProps {
  stats: DashboardStats | null;
  onNavigateTab: (tab: string) => void;
  onSelectDocument: (uid: string) => void;
}

export const DashboardView: React.FC<DashboardViewProps> = ({
  stats,
  onNavigateTab,
  onSelectDocument,
}) => {
  const stages = [
    { id: 'virus_scan', name: 'Virus Scan', tag: 'ClamAV', desc: 'Infection check' },
    { id: 'deduplication', name: 'Deduplication', tag: 'SHA-256', desc: 'Bitwise digest link' },
    { id: 'preprocess', name: 'Preprocess', tag: 'Deskew', desc: 'Orientation correction' },
    { id: 'splitter', name: 'Splitter', tag: 'PyMuPDF', desc: 'Multi-doc boundary' },
    { id: 'ocr', name: 'OCR Engine', tag: 'Tesseract', desc: 'Text & bounding boxes' },
    { id: 'classify', name: 'Classifier', tag: 'TF-IDF+LR', desc: '9-class prediction' },
    { id: 'extract', name: 'Field Extraction', tag: 'Pydantic v2', desc: 'Schema validation' },
    { id: 'pii', name: 'PII Detection', tag: 'Presidio', desc: 'Entity masking & flags' },
    { id: 'decision_gate', name: 'Decision Gate', tag: 'Routing', desc: 'STP vs Review vs DLQ' },
  ];

  return (
    <div className="space-y-6">
      {/* Top Banner & Quick Metrics */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-4">
        {/* STP Rate */}
        <div className="p-4 rounded-xl bg-slate-900 border border-slate-800 relative overflow-hidden group">
          <div className="absolute top-0 right-0 p-3 opacity-15 group-hover:opacity-25 transition">
            <Zap className="w-12 h-12 text-emerald-400" />
          </div>
          <div className="flex items-center space-x-2 text-slate-400 text-xs font-medium">
            <Zap className="w-3.5 h-3.5 text-emerald-400" />
            <span>STP Success Rate</span>
          </div>
          <div className="mt-2 flex items-baseline space-x-2">
            <span className="text-3xl font-bold tracking-tight text-white font-mono">
              {stats?.stp_rate ?? 0}%
            </span>
            <span className="text-xs text-emerald-400 font-medium">Auto-Accepted</span>
          </div>
          <p className="mt-1 text-xs text-slate-500">Straight-through enterprise routing</p>
        </div>

        {/* Total Documents */}
        <div className="p-4 rounded-xl bg-slate-900 border border-slate-800 relative overflow-hidden group">
          <div className="absolute top-0 right-0 p-3 opacity-15 group-hover:opacity-25 transition">
            <FileCheck className="w-12 h-12 text-sky-400" />
          </div>
          <div className="flex items-center space-x-2 text-slate-400 text-xs font-medium">
            <FileCheck className="w-3.5 h-3.5 text-sky-400" />
            <span>Total Repository</span>
          </div>
          <div className="mt-2 flex items-baseline space-x-2">
            <span className="text-3xl font-bold tracking-tight text-white font-mono">
              {stats?.total_documents ?? 0}
            </span>
            <span className="text-xs text-slate-400">assets</span>
          </div>
          <p className="mt-1 text-xs text-slate-500">
            {stats?.human_verified ?? 0} verified by human review
          </p>
        </div>

        {/* Pending Review */}
        <div
          onClick={() => onNavigateTab('review')}
          className="p-4 rounded-xl bg-slate-900 border border-amber-500/30 hover:border-amber-500/60 cursor-pointer relative overflow-hidden group transition"
        >
          <div className="absolute top-0 right-0 p-3 opacity-15 group-hover:opacity-30 transition">
            <Clock className="w-12 h-12 text-amber-400" />
          </div>
          <div className="flex items-center space-x-2 text-amber-300 text-xs font-medium">
            <Clock className="w-3.5 h-3.5 text-amber-400" />
            <span>Pending Review</span>
          </div>
          <div className="mt-2 flex items-baseline space-x-2">
            <span className="text-3xl font-bold tracking-tight text-amber-300 font-mono">
              {stats?.pending_review ?? 0}
            </span>
            <span className="text-xs text-amber-400/80">needs triage</span>
          </div>
          <p className="mt-1 text-xs text-amber-400/70 flex items-center">
            Open review console <ArrowRight className="w-3 h-3 ml-1" />
          </p>
        </div>

        {/* Quarantined / Errors */}
        <div className="p-4 rounded-xl bg-slate-900 border border-slate-800 relative overflow-hidden group">
          <div className="absolute top-0 right-0 p-3 opacity-15 group-hover:opacity-25 transition">
            <AlertTriangle className="w-12 h-12 text-rose-400" />
          </div>
          <div className="flex items-center space-x-2 text-slate-400 text-xs font-medium">
            <ShieldCheck className="w-3.5 h-3.5 text-rose-400" />
            <span>Security Quarantined</span>
          </div>
          <div className="mt-2 flex items-baseline space-x-2">
            <span className="text-3xl font-bold tracking-tight text-white font-mono">
              {stats?.quarantined ?? 0}
            </span>
            <span className="text-xs text-rose-400 font-medium">restricted</span>
          </div>
          <p className="mt-1 text-xs text-slate-500">Infections & corrupted payloads</p>
        </div>

        {/* Deduplicated */}
        <div className="p-4 rounded-xl bg-slate-900 border border-slate-800 relative overflow-hidden group">
          <div className="absolute top-0 right-0 p-3 opacity-15 group-hover:opacity-25 transition">
            <Copy className="w-12 h-12 text-indigo-400" />
          </div>
          <div className="flex items-center space-x-2 text-slate-400 text-xs font-medium">
            <Copy className="w-3.5 h-3.5 text-indigo-400" />
            <span>SHA-256 Deduped</span>
          </div>
          <div className="mt-2 flex items-baseline space-x-2">
            <span className="text-3xl font-bold tracking-tight text-white font-mono">
              {stats?.duplicates_linked ?? 0}
            </span>
            <span className="text-xs text-indigo-400">linked</span>
          </div>
          <p className="mt-1 text-xs text-slate-500">Zero duplicate storage bytes</p>
        </div>
      </div>

      {/* Pipeline Stage Architecture Flow */}
      <div className="p-5 rounded-2xl bg-slate-900 border border-slate-800">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between pb-4 border-b border-slate-800 gap-2">
          <div>
            <h3 className="text-base font-semibold text-white flex items-center space-x-2">
              <Server className="w-4 h-4 text-teal-400" />
              <span>Real-Time Stage Pipeline Architecture</span>
            </h3>
            <p className="text-xs text-slate-400">
              Idempotent stages with SHA-256 checkpoints and automated retry resiliency
            </p>
          </div>
          <div className="flex items-center space-x-3 text-xs">
            <div className="flex items-center space-x-1.5">
              <span className="w-2.5 h-2.5 rounded-full bg-emerald-400 animate-pulse"></span>
              <span className="text-slate-300 font-medium">Live Queue: {stats?.queue_depths.live ?? 0}</span>
            </div>
            <div className="flex items-center space-x-1.5">
              <span className="w-2.5 h-2.5 rounded-full bg-sky-400"></span>
              <span className="text-slate-300 font-medium">Bulk Queue: {stats?.queue_depths.bulk ?? 0}</span>
            </div>
            <div className="flex items-center space-x-1.5">
              <span className="w-2.5 h-2.5 rounded-full bg-rose-400"></span>
              <span className="text-slate-300 font-medium">DLQ: {stats?.queue_depths.dlq ?? 0}</span>
            </div>
          </div>
        </div>

        {/* Stages Grid Flow */}
        <div className="mt-5 grid grid-cols-1 md:grid-cols-3 lg:grid-cols-9 gap-3">
          {stages.map((stage, idx) => {
            const latency = stats?.stage_latencies?.[stage.id];
            return (
              <div
                key={stage.id}
                className="relative p-3 rounded-xl bg-slate-800/60 border border-slate-750 hover:border-teal-500/40 transition flex flex-col justify-between"
              >
                <div>
                  <div className="flex items-center justify-between">
                    <span className="text-[10px] font-mono text-teal-400 font-semibold">
                      S{idx + 1}
                    </span>
                    <span className="text-[9px] px-1.5 py-0.5 rounded bg-slate-700/80 text-slate-300 font-mono">
                      {stage.tag}
                    </span>
                  </div>
                  <h4 className="mt-2 text-xs font-semibold text-white leading-tight">
                    {stage.name}
                  </h4>
                  <p className="mt-0.5 text-[10px] text-slate-400 leading-normal">{stage.desc}</p>
                </div>

                <div className="mt-3 pt-2 border-t border-slate-700/50 flex items-center justify-between text-[10px]">
                  <span className="text-slate-400">p50:</span>
                  <span className="font-mono text-emerald-400 font-medium">
                    {latency ? `${latency.p50}ms` : '<1ms'}
                  </span>
                </div>
              </div>
            );
          })}
        </div>

        {/* Decision Gate Branch Summary */}
        <div className="mt-4 pt-3 border-t border-slate-800/80 flex flex-wrap items-center justify-between text-xs text-slate-400 gap-2">
          <div className="flex items-center space-x-4">
            <span className="text-slate-500 font-medium">Decision Gate Routing:</span>
            <span className="flex items-center text-emerald-400">
              <CheckCircle2 className="w-3.5 h-3.5 mr-1" /> Confidence &ge; 85% &rarr; Auto-Accepted (FakeECM / Nuxeo)
            </span>
            <span className="flex items-center text-amber-400">
              <Clock className="w-3.5 h-3.5 mr-1" /> Low Conf / PII Conflict &rarr; Review Desk
            </span>
            <span className="flex items-center text-rose-400">
              <AlertTriangle className="w-3.5 h-3.5 mr-1" /> Virus / Corrupt &rarr; Quarantine DLQ
            </span>
          </div>
          <a
            href="/metrics"
            target="_blank"
            rel="noreferrer"
            className="flex items-center text-teal-400 hover:text-teal-300 transition"
          >
            Prometheus Metrics <ExternalLink className="w-3 h-3 ml-1" />
          </a>
        </div>
      </div>

      {/* Two Columns: Document Breakdown & Recent Stream */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Document Classification Distribution */}
        <div className="p-5 rounded-2xl bg-slate-900 border border-slate-800">
          <h3 className="text-sm font-semibold text-white flex items-center space-x-2">
            <TrendingUp className="w-4 h-4 text-teal-400" />
            <span>Classified Types Breakdown</span>
          </h3>
          <p className="text-xs text-slate-400 mt-0.5">Documents grouped by predicted class</p>

          <div className="mt-4 space-y-2.5">
            {stats?.type_breakdown && stats.type_breakdown.length > 0 ? (
              stats.type_breakdown.map((item) => {
                const total = stats.total_documents || 1;
                const percent = Math.round((item.count / total) * 100);
                return (
                  <div key={item.type} className="space-y-1">
                    <div className="flex justify-between text-xs">
                      <span className="font-medium capitalize text-slate-300">
                        {item.type.replace('_', ' ')}
                      </span>
                      <span className="font-mono text-slate-400">
                        {item.count} ({percent}%)
                      </span>
                    </div>
                    <div className="w-full h-2 rounded-full bg-slate-800 overflow-hidden">
                      <div
                        className="h-full rounded-full bg-gradient-to-r from-teal-500 to-emerald-400"
                        style={{ width: `${Math.max(4, percent)}%` }}
                      ></div>
                    </div>
                  </div>
                );
              })
            ) : (
              <p className="text-xs text-slate-500 py-4 text-center">No classified assets yet.</p>
            )}
          </div>
        </div>

        {/* Live Ingestion Stream */}
        <div className="lg:col-span-2 p-5 rounded-2xl bg-slate-900 border border-slate-800">
          <div className="flex items-center justify-between pb-3 border-b border-slate-800">
            <div>
              <h3 className="text-sm font-semibold text-white flex items-center space-x-2">
                <Clock className="w-4 h-4 text-teal-400" />
                <span>Recent Ingested Assets</span>
              </h3>
              <p className="text-xs text-slate-400 mt-0.5">Latest documents processed by pipeline</p>
            </div>
            <button
              onClick={() => onNavigateTab('audit')}
              className="text-xs text-teal-400 hover:text-teal-300 flex items-center font-medium"
            >
              View All Audit Records <ArrowRight className="w-3.5 h-3.5 ml-1" />
            </button>
          </div>

          <div className="mt-3 overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead>
                <tr className="text-slate-400 border-b border-slate-800/80">
                  <th className="pb-2 font-medium">Document</th>
                  <th className="pb-2 font-medium">Class</th>
                  <th className="pb-2 font-medium">Confidence</th>
                  <th className="pb-2 font-medium">PII</th>
                  <th className="pb-2 font-medium">Status</th>
                  <th className="pb-2 font-medium text-right">Action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/60">
                {stats?.recent_documents && stats.recent_documents.length > 0 ? (
                  stats.recent_documents.map((doc) => {
                    const confPercent = Math.round(doc.confidence * 100);
                    return (
                      <tr key={doc.uid} className="hover:bg-slate-800/40 transition">
                        <td className="py-2.5 pr-2">
                          <div className="font-medium text-white truncate max-w-[180px]">
                            {doc.file_name}
                          </div>
                          <div className="text-[10px] font-mono text-slate-500 truncate max-w-[150px]">
                            {doc.uid}
                          </div>
                        </td>
                        <td className="py-2.5 pr-2">
                          <span className="px-2 py-0.5 rounded bg-slate-800 text-teal-300 border border-slate-700 font-medium">
                            {doc.doc_type}
                          </span>
                        </td>
                        <td className="py-2.5 pr-2 font-mono">
                          <span
                            className={
                              confPercent >= 85
                                ? 'text-emerald-400'
                                : confPercent >= 70
                                ? 'text-amber-400'
                                : 'text-rose-400'
                            }
                          >
                            {confPercent}%
                          </span>
                        </td>
                        <td className="py-2.5 pr-2">
                          {doc.pii_detected ? (
                            <span className="px-1.5 py-0.5 rounded bg-rose-500/20 text-rose-300 text-[10px] font-medium border border-rose-500/30">
                              PII
                            </span>
                          ) : (
                            <span className="text-slate-500 text-[10px]">None</span>
                          )}
                        </td>
                        <td className="py-2.5 pr-2">
                          <span
                            className={`px-2 py-0.5 rounded-full text-[10px] font-medium ${
                              doc.review_status === 'auto_accepted'
                                ? 'bg-emerald-500/20 text-emerald-300'
                                : doc.review_status === 'pending_review'
                                ? 'bg-amber-500/20 text-amber-300'
                                : doc.review_status === 'human_verified'
                                ? 'bg-sky-500/20 text-sky-300'
                                : 'bg-slate-700 text-slate-300'
                            }`}
                          >
                            {doc.review_status.replace('_', ' ')}
                          </span>
                        </td>
                        <td className="py-2.5 text-right">
                          <button
                            onClick={() => onSelectDocument(doc.uid)}
                            className="p-1 rounded hover:bg-slate-700 text-slate-400 hover:text-white transition"
                            title="Inspect Audit"
                          >
                            <Eye className="w-3.5 h-3.5" />
                          </button>
                        </td>
                      </tr>
                    );
                  })
                ) : (
                  <tr>
                    <td colSpan={6} className="py-6 text-center text-slate-500">
                      No documents ingested yet. Upload documents via the Ingestion Desk!
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  );
};
