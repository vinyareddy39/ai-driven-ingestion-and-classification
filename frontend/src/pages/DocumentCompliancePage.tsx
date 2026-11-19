import React from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import {
  AlertTriangle,
  ArrowLeft,
  Calendar,
  CheckCircle,
  Clock,
  FileCheck,
  FileText,
  Lock,
  Scale,
  Shield,
  ShieldAlert,
} from 'lucide-react';
import { api } from '../api/client';
import { ConfidenceBadge } from '../components/ConfidenceBadge';
import { PIIMaskedValue } from '../components/PIIMaskedValue';

export const DocumentCompliancePage: React.FC = () => {
  const { documentUid } = useParams<{ documentUid: string }>();
  const navigate = useNavigate();

  const {
    data: doc,
    isLoading: isDocLoading,
    error: docError,
  } = useQuery({
    queryKey: ['documentCompliance', documentUid],
    queryFn: () => api.getDocumentCompliance(documentUid!),
    enabled: !!documentUid,
  });

  const {
    data: auditData,
    isLoading: isAuditLoading,
    error: auditError,
  } = useQuery({
    queryKey: ['documentAudit', documentUid],
    queryFn: () => api.getDocumentAudit(documentUid!),
    enabled: !!documentUid,
  });

  if (isDocLoading || isAuditLoading) {
    return (
      <div className="p-16 text-center text-slate-400">
        <div className="w-8 h-8 border-2 border-sky-400 border-t-transparent rounded-full animate-spin mx-auto mb-3" />
        Loading compliance records and immutable audit trail...
      </div>
    );
  }

  if (docError || !doc) {
    return (
      <div className="p-12 text-center text-rose-400">
        <AlertTriangle className="w-10 h-10 mx-auto mb-3 text-rose-500" />
        <h2 className="text-lg font-bold">Failed to load compliance record</h2>
        <p className="text-sm mt-1">{docError ? (docError as Error).message : 'Document not found'}</p>
        <button
          onClick={() => navigate('/documents')}
          className="mt-4 px-4 py-2 bg-slate-800 text-slate-200 rounded-lg hover:bg-slate-700"
        >
          Return to Documents
        </button>
      </div>
    );
  }

  const renderOrMissing = (val: string | null | undefined) => {
    if (!val || val.trim() === '') {
      return <span className="text-rose-400 font-bold font-mono uppercase text-xs">missing</span>;
    }
    return <span className="font-mono text-slate-200">{val}</span>;
  };

  const auditEvents = auditData?.events || [];

  return (
    <div className="p-8 max-w-6xl mx-auto w-full space-y-6">
      {/* Top Header */}
      <div className="flex items-center justify-between pb-4 border-b border-slate-800">
        <div className="flex items-center gap-4">
          <button
            onClick={() => navigate('/documents')}
            className="p-2 rounded-lg bg-slate-900 border border-slate-800 hover:bg-slate-800 text-slate-300 transition-colors"
          >
            <ArrowLeft className="w-4 h-4" />
          </button>
          <div>
            <div className="flex items-center gap-2.5">
              <Scale className="w-5 h-5 text-sky-400" />
              <h1 className="text-xl font-bold text-white">{doc.file_name}</h1>
              <ConfidenceBadge confidence={doc.confidence} />
            </div>
            <p className="font-mono text-xs text-slate-400 mt-1">
              UID: <span className="text-slate-300">{doc.uid}</span> • SHA256:{' '}
              <span className="text-slate-300">{doc.sha256}</span>
            </p>
          </div>
        </div>
      </div>

      {/* WHY WAS THIS CLASSIFIED, RETAINED AND RESTRICTED THIS WAY PANEL */}
      <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6 shadow-xl">
        <div className="flex items-center gap-2 mb-4">
          <FileCheck className="w-5 h-5 text-sky-400" />
          <h2 className="text-base font-bold text-slate-100">
            Explainability: Why Was This Classified, Retained, and Restricted?
          </h2>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">
          {/* Classification Rationale */}
          <div className="bg-slate-950/70 border border-slate-800/80 rounded-xl p-4">
            <span className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider block mb-1">
              1. Document Classification
            </span>
            <div className="text-sm font-bold text-slate-200 mb-2">
              Type: {renderOrMissing(doc.doc_type)}
            </div>
            <p className="text-xs text-slate-400 leading-relaxed">
              Model: {renderOrMissing(doc.classifier_model)} ({renderOrMissing(doc.classifier_version)})
            </p>
            <div className="mt-2 text-xs text-slate-400">
              Rule: {renderOrMissing(doc.decision_rule)}
            </div>
          </div>

          {/* Retention Rationale */}
          <div className="bg-slate-950/70 border border-slate-800/80 rounded-xl p-4">
            <span className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider block mb-1">
              2. Retention Policy
            </span>
            <div className="text-sm font-bold text-sky-300 mb-2">
              Class: {renderOrMissing(doc.retention_class)}
            </div>
            <p className="text-xs text-slate-400 leading-relaxed">
              Workflow: {renderOrMissing(doc.target_workflow)}
            </p>
          </div>

          {/* ACL & Security Rationale */}
          <div className="bg-slate-950/70 border border-slate-800/80 rounded-xl p-4">
            <span className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider block mb-1">
              3. Security ACL & Governance
            </span>
            <div className="text-sm font-bold text-amber-300 mb-2 flex items-center gap-1.5">
              <Lock className="w-3.5 h-3.5" />
              ACL: {renderOrMissing(doc.acl)}
            </div>
            <p className="text-xs text-slate-400 leading-relaxed">
              PII Detected: {doc.pii_detected ? <span className="text-amber-400 font-bold">YES</span> : <span className="text-slate-400 font-mono">NO</span>}
            </p>
          </div>
        </div>

        <div className="bg-slate-950 border border-slate-800 rounded-lg p-3 text-xs text-slate-300">
          <span className="font-semibold text-slate-400">Decision Reason Text: </span>
          {renderOrMissing(doc.decision_reason)}
        </div>
      </div>

      {/* PII & Grounded Extracted Fields */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {/* Extracted Fields */}
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 shadow-lg">
          <h3 className="text-sm font-bold text-slate-200 mb-3 flex items-center gap-2">
            <FileText className="w-4 h-4 text-sky-400" />
            Extracted Fields Grounding
          </h3>
          <div className="divide-y divide-slate-800 border border-slate-800 rounded-lg overflow-hidden bg-slate-950">
            {Object.entries(doc.extracted_fields || {}).length === 0 ? (
              <div className="p-4 text-xs text-slate-500">No fields extracted.</div>
            ) : (
              Object.entries(doc.extracted_fields || {}).map(([k, v]) => (
                <div key={k} className="p-2.5 text-xs flex justify-between">
                  <span className="font-mono text-slate-400">{k}</span>
                  <span className="font-mono text-slate-200 font-medium">
                    {v !== null && v !== undefined ? String(v) : <span className="text-rose-400">null</span>}
                  </span>
                </div>
              ))
            )}
          </div>
        </div>

        {/* PII Entity Breakdown */}
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 shadow-lg">
          <h3 className="text-sm font-bold text-slate-200 mb-3 flex items-center gap-2">
            <Shield className="w-4 h-4 text-amber-400" />
            Detected PII Breakdown (Masked)
          </h3>
          {(!doc.pii_entities || doc.pii_entities.length === 0) ? (
            <p className="text-xs text-slate-500">No PII tags identified in this document.</p>
          ) : (
            <div className="flex flex-wrap gap-2">
              {(doc.pii_entities as Array<Record<string, any>>).map((p, idx) => (
                <PIIMaskedValue
                  key={idx}
                  value={String(p.value || p.entity_type || 'PII')}
                  piiType={String(p.entity_type || p.type || 'PII')}
                />
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Immutable Audit Trail Timeline */}
      <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6 shadow-xl">
        <h3 className="text-base font-bold text-slate-100 mb-4 flex items-center gap-2">
          <Clock className="w-4 h-4 text-sky-400" />
          Chronological Audit Trail Timeline
        </h3>

        {auditEvents.length === 0 ? (
          <p className="text-xs text-slate-500">No audit events recorded for this asset.</p>
        ) : (
          <div className="relative pl-6 border-l-2 border-slate-800 space-y-6">
            {auditEvents.map((evt) => (
              <div key={evt.event_id} className="relative">
                <span className="w-3 h-3 rounded-full bg-sky-500 absolute -left-[31px] top-1 border-2 border-slate-900" />
                <div className="flex items-center gap-3">
                  <span className="font-bold text-xs text-slate-200">{evt.event_type}</span>
                  <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-slate-800 text-sky-400 border border-slate-700">
                    {evt.stage_name || 'system'}
                  </span>
                  <span className="text-[10px] text-slate-500 font-mono ml-auto">
                    {evt.created_at ? new Date(evt.created_at).toLocaleString() : ''}
                  </span>
                </div>
                {evt.payload && Object.keys(evt.payload).length > 0 && (
                  <pre className="mt-2 p-2.5 rounded-lg bg-slate-950 border border-slate-800 text-[11px] text-slate-400 font-mono overflow-x-auto">
                    {JSON.stringify(evt.payload, null, 2)}
                  </pre>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
};
