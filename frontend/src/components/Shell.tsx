import React, { useState } from 'react';
import { NavLink, Outlet, useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import {
  Activity,
  CheckSquare,
  FileText,
  LayoutDashboard,
  RefreshCw,
  Settings,
  ShieldCheck,
  Upload,
  UserCheck,
} from 'lucide-react';
import { api, getActiveRole, setActiveRole } from '../api/client';

export const Shell: React.FC = () => {
  const [role, setRoleState] = useState(getActiveRole());
  const navigate = useNavigate();

  // Mode badge from backend system info endpoint
  const { data: sysInfo } = useQuery({
    queryKey: ['systemInfo'],
    queryFn: api.getSystemInfo,
    refetchInterval: 30000,
  });

  // Health indicator
  const { isSuccess: isHealthy } = useQuery({
    queryKey: ['healthLive'],
    queryFn: async () => {
      const res = await fetch('/health/live');
      return res.json();
    },
    refetchInterval: 10000,
  });

  const handleRoleChange = (newRole: string) => {
    setActiveRole(newRole);
    setRoleState(newRole);
    // Refresh current route to apply permissions
    navigate(0);
  };

  const navItems = [
    { label: 'Dashboard', to: '/', icon: LayoutDashboard, roles: ['admin', 'reviewer', 'compliance', 'viewer'] },
    { label: 'Review Queue', to: '/review', icon: CheckSquare, roles: ['admin', 'reviewer'] },
    { label: 'Documents', to: '/documents', icon: FileText, roles: ['admin', 'reviewer', 'compliance', 'viewer'] },
    { label: 'Upload & Ingest', to: '/upload', icon: Upload, roles: ['admin', 'reviewer', 'compliance', 'viewer'] },
    { label: 'Reprocess', to: '/reprocess', icon: RefreshCw, roles: ['admin'] },
    { label: 'Admin', to: '/admin', icon: Settings, roles: ['admin'] },
  ];

  const visibleNav = navItems.filter((item) => item.roles.includes(role));

  const isLocalMode = sysInfo?.mode === 'LOCAL MODE';

  return (
    <div className="flex h-screen bg-slate-950 text-slate-100 overflow-hidden font-sans">
      {/* Sidebar */}
      <aside className="w-64 border-r border-slate-800 bg-slate-900/95 flex flex-col justify-between shrink-0">
        <div>
          {/* Logo & Pipeline Title */}
          <div className="p-5 border-b border-slate-800">
            <div className="flex items-center gap-2.5">
              <div className="w-8 h-8 rounded-lg bg-sky-600 flex items-center justify-center font-bold text-white shadow-md shadow-sky-900/40">
                AI
              </div>
              <div>
                <h1 className="font-semibold text-sm tracking-tight text-white leading-none">
                  ECM Pipeline
                </h1>
                <p className="text-[11px] text-slate-400 mt-1 font-mono">
                  v{sysInfo?.version || '1.0.0'}
                </p>
              </div>
            </div>

            {/* Mode Badge & Health Indicator */}
            <div className="mt-4 flex items-center justify-between pt-3 border-t border-slate-800/80">
              <span
                data-testid="mode-badge"
                className={`text-[10px] font-bold tracking-wider px-2 py-0.5 rounded uppercase border ${
                  isLocalMode
                    ? 'bg-amber-950/80 text-amber-300 border-amber-800/80'
                    : 'bg-emerald-950/80 text-emerald-300 border-emerald-800/80'
                }`}
              >
                {sysInfo?.mode || 'LOCAL MODE'}
              </span>

              <div className="flex items-center gap-1.5" title={isHealthy ? 'Backend Healthy' : 'Backend Unreachable'}>
                <span
                  data-testid="health-dot"
                  className={`w-2 h-2 rounded-full ${
                    isHealthy ? 'bg-emerald-400 animate-pulse' : 'bg-rose-500'
                  }`}
                />
                <span className="text-[11px] text-slate-400 font-mono">
                  {isHealthy ? 'HEALTHY' : 'OFFLINE'}
                </span>
              </div>
            </div>
          </div>

          {/* Navigation Links */}
          <nav className="p-3 space-y-1">
            {visibleNav.map((item) => {
              const Icon = item.icon;
              return (
                <NavLink
                  key={item.to}
                  to={item.to}
                  end={item.to === '/'}
                  className={({ isActive }) =>
                    `flex items-center gap-3 px-3 py-2 rounded-lg text-sm font-medium transition-colors ${
                      isActive
                        ? 'bg-sky-600/20 text-sky-400 border border-sky-500/30'
                        : 'text-slate-400 hover:text-slate-100 hover:bg-slate-800/60'
                    }`
                  }
                >
                  <Icon className="w-4 h-4 shrink-0" />
                  <span>{item.label}</span>
                </NavLink>
              );
            })}
          </nav>
        </div>

        {/* User Role Switcher Stub */}
        <div className="p-4 border-t border-slate-800 bg-slate-900/60">
          <div className="flex items-center justify-between mb-2">
            <span className="text-[11px] uppercase tracking-wider text-slate-400 font-medium flex items-center gap-1">
              <UserCheck className="w-3.5 h-3.5 text-sky-400" />
              Active Role (Stub)
            </span>
            <span className="text-[10px] bg-slate-800 px-1.5 py-0.5 rounded text-slate-400">Phase 4</span>
          </div>

          <select
            value={role}
            onChange={(e) => handleRoleChange(e.target.value)}
            className="w-full bg-slate-800 text-slate-200 text-xs border border-slate-700 rounded-md px-2.5 py-1.5 focus:outline-none focus:border-sky-500 font-mono"
          >
            <option value="admin">Admin (All Access)</option>
            <option value="reviewer">Reviewer (Queue & Actions)</option>
            <option value="compliance">Compliance (Audit & Search)</option>
            <option value="viewer">Viewer (Read-Only)</option>
          </select>
        </div>
      </aside>

      {/* Main Content Area */}
      <main className="flex-1 flex flex-col overflow-y-auto bg-slate-950">
        <Outlet />
      </main>
    </div>
  );
};
