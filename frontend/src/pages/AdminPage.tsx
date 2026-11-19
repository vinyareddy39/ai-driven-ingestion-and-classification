import React, { useEffect, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  AlertOctagon,
  AlertTriangle,
  Check,
  CheckCircle2,
  Clock,
  History,
  Lock,
  Save,
  Settings,
  Sliders,
} from 'lucide-react';
import {
  AdminConfigResponse,
  AdminConfigUpdateRequest,
  api,
  ClassThresholdConfig,
  ConfigHistoryResponse,
  getActiveRole,
} from '../api/client';

export const AdminPage: React.FC = () => {
  const queryClient = useQueryClient();
  const role = getActiveRole();

  const [proposedThresholds, setProposedThresholds] = useState<Record<string, number>>({});
  const [showConfirmModal, setShowConfirmModal] = useState(false);
  const [validationError, setValidationError] = useState<string | null>(null);

  const { data: configData, isLoading, error } = useQuery<AdminConfigResponse>({
    queryKey: ['adminConfig'],
    queryFn: api.getAdminConfig,
  });

  useEffect(() => {
    if (configData && configData.classes) {
      const initial: Record<string, number> = {};
      Object.entries(configData.classes).forEach(([cName, cCfg]) => {
        initial[cName] = cCfg.current_threshold;
      });
      setProposedThresholds(initial);
    }
  }, [configData]);

  const { data: historyData } = useQuery<ConfigHistoryResponse>({
    queryKey: ['configHistory'],
    queryFn: api.getConfigHistory,
  });

  const updateMutation = useMutation({
    mutationFn: (req: AdminConfigUpdateRequest) => api.updateAdminConfig(req),
    onSuccess: (res) => {
      queryClient.invalidateQueries({ queryKey: ['adminConfig'] });
      queryClient.invalidateQueries({ queryKey: ['configHistory'] });
      setShowConfirmModal(false);
      alert(res.message);
    },
    onError: (err: Error) => {
      alert(`Update rejected: ${err.message}`);
    },
  });

  if (isLoading) {
    return (
      <div className="p-16 text-center text-slate-400">
        <div className="w-8 h-8 border-2 border-sky-400 border-t-transparent rounded-full animate-spin mx-auto mb-3" />
        Loading administrative configuration and floors...
      </div>
    );
  }

  if (error || !configData) {
    return (
      <div className="p-12 text-center text-rose-400">
        <AlertTriangle className="w-10 h-10 mx-auto mb-3 text-rose-500" />
        <h2 className="text-lg font-bold">Failed to load configuration</h2>
        <p className="text-sm mt-1">{error ? (error as Error).message : 'Configuration unavailable'}</p>
      </div>
    );
  }

  const handleThresholdChange = (className: string, val: number) => {
    setProposedThresholds((prev) => ({ ...prev, [className]: val }));
    setValidationError(null);
  };

  const handleOpenConfirm = () => {
    // Validate against floors
    for (const [cName, val] of Object.entries(proposedThresholds)) {
      const cCfg = configData.classes[cName];
      if (!cCfg) continue;
      const floor = cCfg.floor_threshold;
      if (val < floor) {
        setValidationError(
          `Violation: Proposed threshold ${val.toFixed(2)} for ${cCfg.risk}-risk class '${cName}' is below mandatory floor of ${floor.toFixed(2)}.`
        );
        return;
      }
    }
    setShowConfirmModal(true);
  };

  const handleConfirmSave = () => {
    updateMutation.mutate({
      updated_by: `admin-${role}`,
      class_thresholds: proposedThresholds,
    });
  };

  const historyItems = historyData?.history || [];

  return (
    <div className="p-8 max-w-6xl mx-auto w-full space-y-8">
      {/* Header */}
      <div className="flex items-center justify-between pb-4 border-b border-slate-800">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-white flex items-center gap-2.5">
            <Settings className="w-6 h-6 text-sky-400" />
            Admin Policy & Threshold Governance
          </h1>
          <p className="text-sm text-slate-400 mt-1">
            Configure decision gate thresholds and routing rules with strict compliance floor validation.
          </p>
        </div>

        <button
          onClick={handleOpenConfirm}
          className="px-5 py-2.5 bg-sky-600 hover:bg-sky-500 text-white font-bold text-xs rounded-xl shadow-lg flex items-center gap-2 transition-colors"
        >
          <Save className="w-4 h-4" /> Review & Apply Changes
        </button>
      </div>

      {validationError && (
        <div className="p-4 bg-rose-950/60 border border-rose-800 rounded-xl text-xs text-rose-300 flex items-center gap-3">
          <AlertOctagon className="w-5 h-5 text-rose-400 shrink-0" />
          <span>{validationError}</span>
        </div>
      )}

      {/* Thresholds Table */}
      <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6 shadow-xl">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-sm font-bold text-slate-200 flex items-center gap-2">
            <Sliders className="w-4 h-4 text-sky-400" />
            Per-Class Acceptance Thresholds & Mandatory Floors
          </h2>
          <div className="flex items-center gap-3 text-[11px] font-mono">
            <span className="text-rose-400 font-bold">High-Risk Floor: 0.92</span>
            <span>•</span>
            <span className="text-emerald-400 font-bold">Low-Risk Floor: 0.85</span>
          </div>
        </div>

        <div className="border border-slate-800 rounded-xl overflow-hidden bg-slate-950">
          <table className="w-full text-left border-collapse text-xs">
            <thead>
              <tr className="border-b border-slate-800 bg-slate-900/60 text-slate-400 text-[10px] uppercase font-semibold">
                <th className="py-3 px-4">Class Name</th>
                <th className="py-3 px-4">Risk Tier</th>
                <th className="py-3 px-4">Floor Limit</th>
                <th className="py-3 px-4">Current Value</th>
                <th className="py-3 px-4">Proposed Value</th>
                <th className="py-3 px-4">Adjust Slider</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/80 font-mono text-[11px]">
              {Object.entries(configData.classes || {}).map(([cName, cCfg]: [string, ClassThresholdConfig]) => {
                const proposed = proposedThresholds[cName] ?? cCfg.current_threshold;
                const isUnderFloor = proposed < cCfg.floor_threshold;
                const isChanged = Math.abs(proposed - cCfg.current_threshold) > 0.001;

                return (
                  <tr key={cName} className="hover:bg-slate-900/40">
                    <td className="py-3 px-4 font-sans font-medium text-slate-200">{cName}</td>
                    <td className="py-3 px-4">
                      <span
                        className={`text-[9px] font-bold px-1.5 py-0.5 rounded uppercase border ${
                          cCfg.risk === 'high'
                            ? 'bg-rose-950 text-rose-300 border-rose-800'
                            : 'bg-emerald-950 text-emerald-300 border-emerald-800'
                        }`}
                      >
                        {cCfg.risk}
                      </span>
                    </td>
                    <td className="py-3 px-4 text-slate-400 flex items-center gap-1">
                      <Lock className="w-3 h-3 text-slate-500" />
                      {cCfg.floor_threshold.toFixed(2)}
                    </td>
                    <td className="py-3 px-4 text-slate-300">{cCfg.current_threshold.toFixed(2)}</td>
                    <td className="py-3 px-4">
                      <span
                        className={`font-bold ${
                          isUnderFloor
                            ? 'text-rose-400'
                            : isChanged
                            ? 'text-sky-400'
                            : 'text-slate-200'
                        }`}
                      >
                        {proposed.toFixed(2)}
                      </span>
                    </td>
                    <td className="py-3 px-4">
                      <input
                        type="range"
                        min="0.70"
                        max="0.99"
                        step="0.01"
                        value={proposed}
                        onChange={(e) => handleThresholdChange(cName, parseFloat(e.target.value))}
                        className="w-36 accent-sky-500 cursor-pointer"
                      />
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

      {/* Configuration Change History */}
      <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6 shadow-xl">
        <h2 className="text-sm font-bold text-slate-200 mb-4 flex items-center gap-2">
          <History className="w-4 h-4 text-sky-400" />
          Configuration Change Audit History
        </h2>

        {historyItems.length === 0 ? (
          <p className="text-xs text-slate-500">No configuration changes recorded in this session.</p>
        ) : (
          <div className="divide-y divide-slate-800 border border-slate-800 rounded-xl overflow-hidden bg-slate-950 font-mono text-xs">
            {historyItems.map((h) => (
              <div key={h.change_id} className="p-3.5 flex items-center justify-between">
                <div>
                  <div className="font-bold text-slate-200 text-xs">
                    Modified by {h.updated_by}
                  </div>
                  <div className="text-[11px] text-slate-400 mt-0.5">
                    Changes: {JSON.stringify(h.changes)}
                  </div>
                </div>
                <div className="text-[10px] text-slate-500 flex items-center gap-1">
                  <Clock className="w-3 h-3 text-slate-600" />
                  {new Date(h.timestamp).toLocaleString()}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Confirmation Modal */}
      {showConfirmModal && (
        <div className="fixed inset-0 bg-black/70 backdrop-blur-sm z-50 flex items-center justify-center p-4">
          <div className="bg-slate-900 border border-slate-800 rounded-2xl max-w-lg w-full p-6 shadow-2xl space-y-4">
            <h3 className="text-base font-bold text-white flex items-center gap-2">
              <CheckCircle2 className="w-5 h-5 text-sky-400" />
              Confirm Proposed Policy Modifications
            </h3>
            <p className="text-xs text-slate-400 leading-relaxed">
              Verify the changes below before saving. All updates are validated against compliance floors and recorded in the immutable audit log.
            </p>

            <div className="divide-y divide-slate-800 border border-slate-800 rounded-xl bg-slate-950 p-3 max-h-60 overflow-y-auto text-xs font-mono">
              {Object.entries(proposedThresholds).map(([cName, val]) => {
                const current = configData.classes[cName]?.current_threshold;
                if (current === undefined || Math.abs(current - val) < 0.001) return null;
                return (
                  <div key={cName} className="py-2 flex justify-between">
                    <span className="text-slate-300 font-sans">{cName}</span>
                    <span className="text-slate-400">
                      {current.toFixed(2)} → <strong className="text-sky-400">{val.toFixed(2)}</strong>
                    </span>
                  </div>
                );
              })}
            </div>

            <div className="flex justify-end gap-3 pt-3 border-t border-slate-800">
              <button
                onClick={() => setShowConfirmModal(false)}
                className="px-4 py-2 bg-slate-800 text-slate-300 rounded-lg text-xs font-semibold hover:bg-slate-700"
              >
                Cancel
              </button>
              <button
                onClick={handleConfirmSave}
                disabled={updateMutation.isPending}
                className="px-4 py-2 bg-sky-600 text-white rounded-lg text-xs font-bold hover:bg-sky-500 shadow-md flex items-center gap-2"
              >
                <Check className="w-4 h-4" />
                {updateMutation.isPending ? 'Applying...' : 'Confirm & Apply'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
