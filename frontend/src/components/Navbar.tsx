import React, { useState, useRef, useEffect } from 'react';
import {
  UploadCloud,
  FolderArchive,
  CheckSquare,
  Search,
  RefreshCw,
  Cpu,
  Shield,
  ChevronDown,
  Activity,
  History,
  RotateCcw,
} from 'lucide-react';
import type { DashboardStats } from '../types';
import { getActiveRole } from '../api/client';
import { NotificationsDropdown } from './NotificationsDropdown';

interface NavbarProps {
  activeTab: string;
  setActiveTab: (tab: string) => void;
  stats: DashboardStats | null;
  onRefresh: () => void;
  isRefreshing: boolean;
  onSelectBatch?: (batchId: string) => void;
}

export const Navbar: React.FC<NavbarProps> = ({
  activeTab,
  setActiveTab,
  stats,
  onRefresh,
  isRefreshing,
  onSelectBatch,
}) => {
  const [adminMenuOpen, setAdminMenuOpen] = useState(false);
  const adminMenuRef = useRef<HTMLDivElement>(null);

  const role = getActiveRole() || 'admin';
  const isStaff = ['admin', 'reviewer', 'compliance'].includes(role);

  // Close admin menu when clicking outside
  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (adminMenuRef.current && !adminMenuRef.current.contains(e.target as Node)) {
        setAdminMenuOpen(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  // 4 Main Items for Ordinary Users
  const mainTabs = [
    { id: 'ingest', label: 'Upload', icon: UploadCloud },
    { id: 'my_uploads', label: 'My uploads', icon: FolderArchive },
    {
      id: 'review',
      label: 'Needs a check',
      icon: CheckSquare,
      badge: stats?.pending_review && stats.pending_review > 0 ? stats.pending_review : undefined,
    },
    { id: 'audit', label: 'Find a file', icon: Search },
  ];

  const adminItems = [
    { id: 'dashboard', label: 'Pipeline metrics', icon: Activity },
    { id: 'reprocess', label: 'Try sorting again', icon: RotateCcw },
    { id: 'file_history', label: 'File history & audit', icon: History },
  ];

  return (
    <header className="sticky top-0 z-50 border-b border-slate-800 bg-slate-900/90 backdrop-blur-md">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex items-center justify-between h-16">
          {/* Brand Logo & Name */}
          <div
            onClick={() => setActiveTab('ingest')}
            className="flex items-center space-x-3 cursor-pointer group"
          >
            <div className="w-10 h-10 rounded-xl bg-gradient-to-tr from-teal-500 to-emerald-400 flex items-center justify-center shadow-lg shadow-teal-500/20 text-slate-950 font-bold group-hover:scale-105 transition-transform">
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
              <p className="text-xs text-slate-400">Automatic document sorting & reading</p>
            </div>
          </div>

          {/* Simple 4-Item Navigation */}
          <nav className="hidden md:flex items-center space-x-1">
            {mainTabs.map((tab) => {
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

            {/* Staff Admin Dropdown */}
            {isStaff && (
              <div className="relative ml-1" ref={adminMenuRef}>
                <button
                  onClick={() => setAdminMenuOpen(!adminMenuOpen)}
                  className={`flex items-center space-x-1.5 px-3 py-2 rounded-lg text-sm font-medium transition-all ${
                    ['dashboard', 'reprocess', 'file_history'].includes(activeTab)
                      ? 'bg-slate-800 text-teal-300 border border-slate-700'
                      : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/60'
                  }`}
                >
                  <Shield className="w-4 h-4 text-slate-400" />
                  <span>Admin</span>
                  <ChevronDown className={`w-3.5 h-3.5 transition-transform ${adminMenuOpen ? 'rotate-180' : ''}`} />
                </button>

                {adminMenuOpen && (
                  <div className="absolute right-0 mt-2 w-52 rounded-xl bg-slate-900 border border-slate-800 shadow-2xl py-1 z-50">
                    <div className="px-3 py-1.5 text-[11px] font-semibold text-slate-500 uppercase tracking-wider border-b border-slate-800">
                      Staff tools
                    </div>
                    {adminItems.map((item) => {
                      const Icon = item.icon;
                      const isItemActive = activeTab === item.id;
                      return (
                        <button
                          key={item.id}
                          onClick={() => {
                            setActiveTab(item.id);
                            setAdminMenuOpen(false);
                          }}
                          className={`w-full flex items-center space-x-2.5 px-3.5 py-2 text-xs font-medium text-left transition-colors ${
                            isItemActive
                              ? 'bg-teal-500/15 text-teal-300'
                              : 'text-slate-300 hover:bg-slate-800 hover:text-white'
                          }`}
                        >
                          <Icon className="w-4 h-4 text-slate-400" />
                          <span>{item.label}</span>
                        </button>
                      );
                    })}
                  </div>
                )}
              </div>
            )}
          </nav>

          {/* Right Header Status, Notifications & Controls */}
          <div className="flex items-center space-x-2 sm:space-x-3">
            {/* Notifications Dropdown */}
            <NotificationsDropdown onSelectBatch={onSelectBatch} />

            {/* Mode badge & Health indicator */}
            <div className="flex items-center space-x-2">
              <span
                data-testid="mode-badge"
                className="text-xs px-2 py-0.5 rounded-full bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 font-mono font-semibold"
              >
                LOCAL MODE
              </span>
              <span
                data-testid="health-dot"
                className="w-2.5 h-2.5 rounded-full bg-emerald-400 shadow-sm shadow-emerald-400/50"
                title="System Healthy"
              />
            </div>

            {/* Refresh Button */}
            <button
              onClick={onRefresh}
              disabled={isRefreshing}
              title="Refresh Pipeline Status"
              aria-label="Refresh Status"
              className="p-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 border border-slate-700 transition"
            >
              <RefreshCw className={`w-4 h-4 ${isRefreshing ? 'animate-spin text-teal-400' : ''}`} />
            </button>
          </div>
        </div>
      </div>

      {/* Mobile Tab Navigation */}
      <div className="md:hidden flex overflow-x-auto px-4 py-2 border-t border-slate-800 gap-1">
        {mainTabs.map((tab) => {
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
                <span className="ml-1 px-1 py-0.2 rounded-full bg-amber-500/20 text-amber-300 text-[10px]">
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
