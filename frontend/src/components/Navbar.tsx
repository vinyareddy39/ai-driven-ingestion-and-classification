import React from 'react';
import {
  Activity,
  UploadCloud,
  CheckSquare,
  Search,
  RefreshCw,
  Cpu,
  Layers,
} from 'lucide-react';
import type { DashboardStats } from '../types';

interface NavbarProps {
  activeTab: string;
  setActiveTab: (tab: string) => void;
  stats: DashboardStats | null;
  onRefresh: () => void;
  isRefreshing: boolean;
}

export const Navbar: React.FC<NavbarProps> = ({
  activeTab,
  setActiveTab,
  stats,
  onRefresh,
  isRefreshing,
}) => {
  const tabs = [
    { id: 'dashboard', label: 'Pipeline Dashboard', icon: Activity },
    { id: 'ingest', label: 'Ingestion Desk', icon: UploadCloud },
    {
      id: 'review',
      label: 'Review & Triage',
      icon: CheckSquare,
      badge: stats?.pending_review && stats.pending_review > 0 ? stats.pending_review : undefined,
    },
    { id: 'audit', label: 'Audit & Search', icon: Search },
    { id: 'reprocess', label: 'Reprocessing Hub', icon: RefreshCw },
  ];

  return (
    <header className="sticky top-0 z-50 border-b border-slate-800 bg-slate-900/90 backdrop-blur-md">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex items-center justify-between h-16">
          {/* Brand Logo & Name */}
          <div className="flex items-center space-x-3">
            <div className="w-10 h-10 rounded-xl bg-gradient-to-tr from-teal-500 to-emerald-400 flex items-center justify-center shadow-lg shadow-teal-500/20 text-slate-950 font-bold">
              <Cpu className="w-6 h-6 text-slate-950" />
            </div>
            <div>
              <div className="flex items-center space-x-2">
                <span className="text-lg font-bold bg-clip-text text-transparent bg-gradient-to-r from-teal-400 via-emerald-300 to-sky-400">
                  ECM IngestAI
                </span>
                <span className="text-xs px-2 py-0.5 rounded-full bg-teal-500/10 text-teal-400 border border-teal-500/20 font-mono">
                  v2.0
                </span>
              </div>
              <p className="text-xs text-slate-400">AI Document Classification & Presidio PII Pipeline</p>
            </div>
          </div>

          {/* Navigation Tabs */}
          <nav className="hidden md:flex space-x-1">
            {tabs.map((tab) => {
              const Icon = tab.icon;
              const isActive = activeTab === tab.id;
              return (
                <button
                  key={tab.id}
                  onClick={() => setActiveTab(tab.id)}
                  className={`flex items-center space-x-2 px-3.5 py-2 rounded-lg text-sm font-medium transition-all ${
                    isActive
                      ? 'bg-teal-500/15 text-teal-300 border border-teal-500/30 shadow-sm'
                      : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/60'
                  }`}
                >
                  <Icon className={`w-4 h-4 ${isActive ? 'text-teal-400' : 'text-slate-400'}`} />
                  <span>{tab.label}</span>
                  {tab.badge !== undefined && (
                    <span className="ml-1.5 px-1.5 py-0.5 text-xs font-semibold rounded-full bg-amber-500/20 text-amber-300 border border-amber-500/40">
                      {tab.badge}
                    </span>
                  )}
                </button>
              );
            })}
          </nav>

          {/* Right Header Status & Controls */}
          <div className="flex items-center space-x-3">
            {/* Live Queue Pill */}
            <div className="hidden lg:flex items-center space-x-2 px-2.5 py-1 rounded-md bg-slate-800/80 border border-slate-700/60 text-xs">
              <Layers className="w-3.5 h-3.5 text-slate-400" />
              <span className="text-slate-400">Live Queue:</span>
              <span className="font-semibold text-emerald-400 font-mono">
                {stats?.queue_depths?.live ?? 0}
              </span>
            </div>

            {/* Refresh Button */}
            <button
              onClick={onRefresh}
              disabled={isRefreshing}
              title="Refresh Pipeline Status"
              className="p-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 border border-slate-700 transition"
            >
              <RefreshCw className={`w-4 h-4 ${isRefreshing ? 'animate-spin text-teal-400' : ''}`} />
            </button>
          </div>
        </div>
      </div>

      {/* Mobile Tab Navigation */}
      <div className="md:hidden flex overflow-x-auto px-4 py-2 border-t border-slate-800 gap-1">
        {tabs.map((tab) => {
          const Icon = tab.icon;
          const isActive = activeTab === tab.id;
          return (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`flex items-center space-x-1.5 px-3 py-1.5 rounded-lg text-xs font-medium whitespace-nowrap ${
                isActive
                  ? 'bg-teal-500/15 text-teal-300 border border-teal-500/30'
                  : 'text-slate-400 hover:bg-slate-800'
              }`}
            >
              <Icon className="w-3.5 h-3.5" />
              <span>{tab.label}</span>
              {tab.badge !== undefined && (
                <span className="px-1 text-[10px] rounded-full bg-amber-500/30 text-amber-200">
                  {tab.badge}
                </span>
              )}
            </button>
          );
        })}
      </div>
    </header>
  );
};
