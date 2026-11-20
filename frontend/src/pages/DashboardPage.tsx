import React from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  Activity,
  AlertTriangle,
  ArrowUpRight,
  CheckCircle2,
  Clock,
  Database,
  FileText,
  Inbox,
  LayoutDashboard,
  ShieldAlert,
  Zap,
} from 'lucide-react';
import { api } from '../api/client';

export const DashboardPage: React.FC = () => {
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ['dashboardMetrics'],
    queryFn: api.getDashboardMetrics,
    refetchInterval: 10000,
  });

  if (isLoading) {
    return (
      <div className="p-16 text-center text-slate-400">
        <div className="w-8 h-8 border-2 border-sky-400 border-t-transparent rounded-full animate-spin mx-auto mb-3" />
        Loading pipeline telemetry and operational metrics...
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-12 text-center text-rose-400">
        <AlertTriangle className="w-10 h-10 mx-auto mb-3 text-rose-500" />
        <h2 className="text-lg font-bold">Failed to load dashboard metrics</h2>
        <p className="text-sm mt-1">{(error as Error).message}</p>
        <button
          onClick={() => refetch()}
          className="mt-4 px-4 py-2 bg-slate-800 text-slate-200 rounded-lg hover:bg-slate-700"
        >
          Retry
        </button>
      </div>
    );
  }

  // Rule: show "no data yet" rather than zeros when nothing has run
  if (!data || !data.has_data) {
    return (
      <div className="p-16 max-w-xl mx-auto text-center space-y-4">
        <div className="w-16 h-16 rounded-2xl bg-slate-900 border border-slate-800 flex items-center justify-center mx-auto text-slate-500">
          <Database className="w-8 h-8" />
        </div>
        <h2 className="text-xl font-bold text-slate-200">No Data Yet</h2>
        <p className="text-sm text-slate-400 leading-relaxed">
          The ingestion pipeline has not processed any document assets yet. Upload files to generate real operational metrics.
        </p>
      </div>
    );
  }

  const stpPercent = data.stp_rate !== null && data.stp_rate !== undefined ? Math.round(data.stp_rate * 100) : null;
  const errorPercent = data.error_rate !== null && data.error_rate !== undefined ? Math.round(data.error_rate * 100) : null;

  return (
    <div className="p-8 max-w-7xl mx-auto w-full space-y-8">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-white flex items-center gap-2.5">
            <LayoutDashboard className="w-6 h-6 text-sky-400" />
            Pipeline Health & Telemetry Dashboard
          </h1>
          <p className="text-sm text-slate-400 mt-1">
            Real-time pipeline metrics sourced strictly from active workers and telemetry databases.
          </p>
        </div>
      </div>

      {/* KPI Cards Grid */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        {/* Total Ingested */}
        <div className="p-5 rounded-2xl bg-slate-900 border border-slate-800 shadow-xl flex flex-col justify-between">
          <div className="flex items-center justify-between text-slate-400 mb-2">
            <span className="text-[11px] font-semibold uppercase tracking-wider">Total Documents</span>
            <FileText className="w-4 h-4 text-sky-400" />
          </div>
          <div className="text-3xl font-extrabold font-mono text-white tracking-tight">
            {data.total_ingested}
          </div>
          <span className="text-[11px] text-slate-500 font-mono mt-2">All time ingested</span>
        </div>

        {/* Review Queue Depth */}
        <div className="p-5 rounded-2xl bg-slate-900 border border-slate-800 shadow-xl flex flex-col justify-between">
          <div className="flex items-center justify-between text-slate-400 mb-2">
            <span className="text-[11px] font-semibold uppercase tracking-wider">Review Queue Depth</span>
            <Inbox className="w-4 h-4 text-amber-400" />
          </div>
          <div className="text-3xl font-extrabold font-mono text-amber-400 tracking-tight">
            {data.review_queue_size}
          </div>
          <span className="text-[11px] text-slate-500 font-mono mt-2">Awaiting human review</span>
        </div>

        {/* Straight Through Processing Rate */}
        <div className="p-5 rounded-2xl bg-slate-900 border border-slate-800 shadow-xl flex flex-col justify-between">
          <div className="flex items-center justify-between text-slate-400 mb-2">
            <span className="text-[11px] font-semibold uppercase tracking-wider">STP Rate</span>
            <Zap className="w-4 h-4 text-emerald-400" />
          </div>
          <div className="text-3xl font-extrabold font-mono text-emerald-400 tracking-tight">
            {stpPercent !== null ? `${stpPercent}%` : '—'}
          </div>
          <span className="text-[11px] text-slate-500 font-mono mt-2">Auto-accepted without review</span>
        </div>

        {/* Dead Letter Queue / Quarantined */}
        <div className="p-5 rounded-2xl bg-slate-900 border border-slate-800 shadow-xl flex flex-col justify-between">
          <div className="flex items-center justify-between text-slate-400 mb-2">
            <span className="text-[11px] font-semibold uppercase tracking-wider">Quarantine / DLQ</span>
            <ShieldAlert className="w-4 h-4 text-rose-400" />
          </div>
          <div className="text-3xl font-extrabold font-mono text-rose-400 tracking-tight">
            {data.dead_letter_count}
          </div>
          <span className="text-[11px] text-slate-500 font-mono mt-2">
            Error rate: {errorPercent !== null ? `${errorPercent}%` : '0%'}
          </span>
        </div>
      </div>

      {/* Stage Latencies Table & Class Breakdown Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Stage Latencies */}
        <div className="p-6 rounded-2xl bg-slate-900 border border-slate-800 shadow-xl">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-sm font-bold text-slate-200 flex items-center gap-2">
              <Clock className="w-4 h-4 text-sky-400" />
              Pipeline Stage Latencies (Real Telemetry)
            </h3>
          </div>

          {Object.keys(data.stage_latencies_ms || {}).length === 0 ? (
            <p className="text-xs text-slate-500 p-4 text-center">No stage telemetry records yet.</p>
          ) : (
            <div className="border border-slate-800 rounded-xl overflow-hidden bg-slate-950">
              <table className="w-full text-left border-collapse text-xs">
                <thead>
                  <tr className="border-b border-slate-800 bg-slate-900/60 text-slate-400 uppercase text-[10px] font-semibold">
                    <th className="py-2.5 px-3">Stage Name</th>
                    <th className="py-2.5 px-3">Samples</th>
                    <th className="py-2.5 px-3">p50 Latency</th>
                    <th className="py-2.5 px-3">p95 Latency</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800/80 font-mono text-[11px]">
                  {Object.entries((data as any).stage_latencies_ms || {}).map(([stage, m]: [string, any]) => (
                    <tr key={stage} className="hover:bg-slate-900/40">
                      <td className="py-2.5 px-3 font-sans font-medium text-slate-200">{stage}</td>
                      <td className="py-2.5 px-3 text-slate-400">{m?.count}</td>
                      <td className="py-2.5 px-3 text-sky-300 font-bold">{m?.p50_ms?.toFixed?.(1) ?? '—'} ms</td>
                      <td className="py-2.5 px-3 text-amber-300 font-bold">{m?.p95_ms?.toFixed?.(1) ?? '—'} ms</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        {/* Per-Class Distribution */}
        <div className="p-6 rounded-2xl bg-slate-900 border border-slate-800 shadow-xl">
          <h3 className="text-sm font-bold text-slate-200 mb-4 flex items-center gap-2">
            <Activity className="w-4 h-4 text-sky-400" />
            Document Ingestion per Class
          </h3>

          <div className="space-y-3">
            {Object.entries(data.per_class_counts || {}).length === 0 ? (
              <p className="text-xs text-slate-500">No classified document batches recorded.</p>
            ) : (
              Object.entries((data as any).per_class_counts || {}).map(([cName, count]: [string, any]) => {
                const total = Number((data as any).total_ingested) || 1;
                const numCount = Number(count) || 0;
                const pct = Math.round((numCount / total) * 100);
                return (
                  <div key={cName}>
                    <div className="flex justify-between text-xs font-mono mb-1">
                      <span className="font-semibold text-slate-300">{cName}</span>
                      <span className="text-slate-400">
                        {numCount} ({pct}%)
                      </span>
                    </div>
                    <div className="w-full bg-slate-950 rounded-full h-2 overflow-hidden border border-slate-800">
                      <div
                        className="bg-sky-500 h-2 rounded-full transition-all duration-500"
                        style={{ width: `${pct}%` }}
                      />
                    </div>
                  </div>
                );
              })
            )}
          </div>
        </div>
      </div>
    </div>
  );
};
