import React, { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  AlertTriangle,
  ArrowLeft,
  Check,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  Edit2,
  FileText,
  Save,
  Shield,
  XCircle,
} from 'lucide-react';
import { api, getActiveRole, ReviewActionRequest, ReviewDetailResponse } from '../api/client';
import { ConfidenceBadge } from '../components/ConfidenceBadge';
import { PIIMaskedValue } from '../components/PIIMaskedValue';
import { AuthenticatedImage } from '../components/AuthenticatedImage';

export const ReviewDetailPage: React.FC = () => {
  const { documentUid } = useParams<{ documentUid: string }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const role = getActiveRole();

  const [pageNum, setPageNum] = useState(1);
  const [selectedField, setSelectedField] = useState<string | null>(null);
  const [editedType, setEditedType] = useState<string>('');
  const [fieldEdits, setFieldEdits] = useState<Record<string, string>>({});
  const [reviewNotes, setReviewNotes] = useState<string>('');
  const [isEditing, setIsEditing] = useState<boolean>(false);

  const { data: doc, isLoading, error } = useQuery<ReviewDetailResponse>({
    queryKey: ['reviewDetail', documentUid],
    queryFn: () => api.getReviewDetail(documentUid!),
    enabled: !!documentUid,
  });

  useEffect(() => {
    if (doc) {
      setEditedType(doc.predicted_type);
      const initial: Record<string, string> = {};
      Object.entries(doc.extracted_fields || {}).forEach(([k, v]) => {
        initial[k] = String(v ?? '');
      });
      Object.entries(doc.human_verified_fields || {}).forEach(([k, v]) => {
        initial[k] = String(v ?? '');
      });
      setFieldEdits(initial);
    }
  }, [doc]);

  const actionMutation = useMutation({
    mutationFn: (req: ReviewActionRequest) =>
      api.submitReviewAction(documentUid!, req),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['reviewDetail', documentUid] });
      queryClient.invalidateQueries({ queryKey: ['reviewQueue'] });
      alert(`Success: ${(data as any).message || 'Action submitted'}`);
      navigate('/review');
    },
    onError: (err: Error) => {
      alert(`Action failed: ${err.message}`);
    },
  });

  if (isLoading) {
    return (
      <div className="p-16 text-center text-slate-400">
        <div className="w-8 h-8 border-2 border-sky-400 border-t-transparent rounded-full animate-spin mx-auto mb-3" />
        Loading review detail and OCR evidence...
      </div>
    );
  }

  if (error || !doc) {
    return (
      <div className="p-12 text-center text-rose-400">
        <AlertTriangle className="w-10 h-10 mx-auto mb-3 text-rose-500" />
        <h2 className="text-lg font-bold">Failed to load document review</h2>
        <p className="text-sm mt-1">{error ? (error as Error).message : 'Document not found'}</p>
        <button
          onClick={() => navigate('/review')}
          className="mt-4 px-4 py-2 bg-slate-800 text-slate-200 rounded-lg hover:bg-slate-700"
        >
          Return to Review Queue
        </button>
      </div>
    );
  }

  const handleConfirm = () => {
    actionMutation.mutate({
      reviewer_id: `reviewer-${role}`,
      action: 'CONFIRM',
      review_notes: reviewNotes || 'Confirmed prediction without field changes',
    });
  };

  const handleCorrect = () => {
    actionMutation.mutate({
      reviewer_id: `reviewer-${role}`,
      action: 'CORRECT',
      corrected_type: editedType,
      corrected_fields: fieldEdits,
      review_notes: reviewNotes || 'Human reviewer modified fields',
    });
  };

  const handleReject = () => {
    if (!confirm('Are you sure you want to REJECT this document? It will be marked as rejected and excluded from ECM routing.')) {
      return;
    }
    actionMutation.mutate({
      reviewer_id: `reviewer-${role}`,
      action: 'REJECT',
      review_notes: reviewNotes || 'Document rejected as unprocessable / invalid',
    });
  };

  const piiList = (doc.pii_entities as Array<Record<string, any>>) || [];

  return (
    <div className="flex flex-col h-full bg-slate-950 overflow-hidden">
      {/* Top Bar */}
      <header className="px-6 py-3.5 border-b border-slate-800 bg-slate-900/90 flex items-center justify-between shrink-0">
        <div className="flex items-center gap-4">
          <button
            onClick={() => navigate('/review')}
            className="p-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 transition-colors"
            title="Back to queue"
          >
            <ArrowLeft className="w-4 h-4" />
          </button>
          <div>
            <div className="flex items-center gap-2">
              <h2 className="font-bold text-slate-100 text-base">{doc.file_name}</h2>
              <span className="font-mono text-xs text-slate-500">({doc.document_uid})</span>
              {doc.review_status === 'human_verified' && (
                <span className="bg-emerald-950 text-emerald-300 border border-emerald-800 text-[10px] font-bold px-2 py-0.5 rounded-full flex items-center gap-1">
                  <CheckCircle2 className="w-3 h-3 text-emerald-400" /> Human Verified
                </span>
              )}
            </div>
            <div className="flex items-center gap-3 mt-0.5 text-xs text-slate-400">
              <span>Model: <code className="text-slate-300">{doc.model_name}:{doc.model_version}</code></span>
              <span>•</span>
              <span>OCR: <code className="text-slate-300">{doc.ocr_engine}:{doc.ocr_version}</code></span>
            </div>
          </div>
        </div>

        {/* Action Buttons */}
        <div className="flex items-center gap-2">
          <button
            onClick={handleReject}
            disabled={actionMutation.isPending}
            className="px-3 py-1.5 bg-rose-950/80 hover:bg-rose-900 border border-rose-800 text-rose-300 text-xs font-semibold rounded-lg flex items-center gap-1.5 transition-colors disabled:opacity-50"
          >
            <XCircle className="w-3.5 h-3.5" /> Reject
          </button>
          <button
            onClick={() => setIsEditing(!isEditing)}
            className="px-3 py-1.5 bg-slate-800 hover:bg-slate-700 border border-slate-700 text-slate-200 text-xs font-semibold rounded-lg flex items-center gap-1.5 transition-colors"
          >
            <Edit2 className="w-3.5 h-3.5 text-sky-400" /> {isEditing ? 'Cancel Edits' : 'Edit Fields'}
          </button>
          <button
            onClick={isEditing ? handleCorrect : handleConfirm}
            disabled={actionMutation.isPending}
            className={`px-4 py-1.5 text-xs font-bold rounded-lg flex items-center gap-1.5 text-white shadow-md transition-colors disabled:opacity-50 ${
              isEditing ? 'bg-amber-600 hover:bg-amber-500' : 'bg-emerald-600 hover:bg-emerald-500'
            }`}
          >
            {isEditing ? <Save className="w-3.5 h-3.5" /> : <Check className="w-3.5 h-3.5" />}
            {isEditing ? 'Save Correction' : 'One-Click Confirm'}
          </button>
        </div>
      </header>

      {/* Main Split View: Page Image (Left) vs Extracted Fields & OCR (Right) */}
      <div className="flex-1 flex overflow-hidden">
        {/* Left: Document Page Image with Bounding Boxes */}
        <div className="w-1/2 border-r border-slate-800 bg-slate-900/40 p-4 flex flex-col justify-between overflow-y-auto">
          <div className="flex items-center justify-between mb-3 text-xs text-slate-400">
            <span className="font-semibold uppercase text-[11px] tracking-wider text-slate-300">
              Page Preview (DPI 150)
            </span>
            <div className="flex items-center gap-2">
              <button
                disabled={pageNum <= 1}
                onClick={() => setPageNum((p) => Math.max(p - 1, 1))}
                className="p-1 rounded bg-slate-800 disabled:opacity-40"
              >
                <ChevronLeft className="w-4 h-4" />
              </button>
              <span className="font-mono text-xs">
                Page {pageNum} of {doc.page_count}
              </span>
              <button
                disabled={pageNum >= doc.page_count}
                onClick={() => setPageNum((p) => Math.min(p + 1, doc.page_count))}
                className="p-1 rounded bg-slate-800 disabled:opacity-40"
              >
                <ChevronRight className="w-4 h-4" />
              </button>
            </div>
          </div>

          <div className="flex-1 rounded-xl bg-slate-950 border border-slate-800 overflow-hidden flex items-center justify-center p-2 relative shadow-inner">
            <AuthenticatedImage
              src={`/api/v1/documents/${doc.document_uid}/pages/${pageNum}/image`}
              alt={`Page ${pageNum}`}
              className="max-h-full max-w-full object-contain rounded shadow"
            />
          </div>
        </div>

        {/* Right: AI Prediction, Field Extraction, PII & OCR Evidence */}
        <div className="w-1/2 flex flex-col overflow-y-auto p-6 space-y-6">
          {/* Classification & Confidence Card */}
          <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 shadow-lg">
            <div className="flex items-center justify-between mb-4">
              <div>
                <span className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider">
                  Classification Decision
                </span>
                <div className="flex items-center gap-3 mt-1">
                  {isEditing ? (
                    <select
                      value={editedType}
                      onChange={(e) => setEditedType(e.target.value)}
                      className="bg-slate-800 text-sky-400 font-bold text-lg border border-sky-500 rounded px-2.5 py-1"
                    >
                      <option value="kyc_form">kyc_form</option>
                      <option value="bank_statement">bank_statement</option>
                      <option value="medical_report">medical_report</option>
                      <option value="claim_form">claim_form</option>
                      <option value="invoice">invoice</option>
                      <option value="contract">contract</option>
                      <option value="purchase_order">purchase_order</option>
                      <option value="unknown">unknown</option>
                    </select>
                  ) : (
                    <h3 className="text-xl font-bold text-slate-100">{doc.predicted_type}</h3>
                  )}
                  <ConfidenceBadge confidence={doc.confidence} />
                </div>
              </div>

              <div className="text-right">
                <span className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider">
                  Status
                </span>
                <div className="font-mono text-xs text-sky-400 font-bold uppercase mt-1">
                  {doc.review_status}
                </div>
              </div>
            </div>

            <div className="bg-slate-950/70 border border-slate-800 rounded-lg p-3 text-xs text-slate-300">
              <span className="font-semibold text-slate-400">Decision Reason: </span>
              {doc.decision_reason}
            </div>
          </div>

          {/* Extracted Fields Table */}
          <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 shadow-lg">
            <div className="flex items-center justify-between mb-3">
              <h4 className="text-sm font-bold text-slate-200 flex items-center gap-2">
                <FileText className="w-4 h-4 text-sky-400" />
                Extracted Fields & Grounding
              </h4>
              <span className="text-[11px] text-slate-400 font-mono">
                {Object.keys(fieldEdits).length} fields
              </span>
            </div>

            <div className="divide-y divide-slate-800 border border-slate-800 rounded-lg overflow-hidden bg-slate-950/50">
              {Object.keys(fieldEdits).length === 0 ? (
                <div className="p-4 text-center text-xs text-slate-500">No extracted fields available.</div>
              ) : (
                Object.entries(fieldEdits).map(([key, val]) => {
                  const isHumanVerified = key in ((doc.human_verified_fields as Record<string, any>) || {});
                  const conf = ((doc.field_confidences as Record<string, number>) || {})[key];

                  return (
                    <div
                      key={key}
                      onClick={() => setSelectedField(key)}
                      className={`p-3 text-xs flex items-center justify-between gap-4 transition-colors ${
                        selectedField === key ? 'bg-sky-950/30' : 'hover:bg-slate-900/60'
                      }`}
                    >
                      <div className="w-1/3">
                        <span className="font-mono text-slate-300 font-medium block">{key}</span>
                        {isHumanVerified && (
                          <span className="inline-flex items-center gap-1 text-[9px] text-emerald-400 font-bold mt-0.5">
                            <CheckCircle2 className="w-3 h-3" /> human-verified
                          </span>
                        )}
                      </div>

                      <div className="flex-1">
                        {isEditing ? (
                          <input
                            type="text"
                            value={val}
                            onChange={(e) =>
                              setFieldEdits({ ...fieldEdits, [key]: e.target.value })
                            }
                            className="w-full bg-slate-800 text-slate-100 border border-slate-700 rounded px-2.5 py-1 text-xs focus:outline-none focus:border-sky-500 font-mono"
                          />
                        ) : (
                          <span className="font-mono text-slate-200">{val || <span className="text-rose-400 italic">null</span>}</span>
                        )}
                      </div>

                      <div className="w-20 text-right">
                        {conf !== undefined ? (
                          <span className="font-mono text-[11px] text-slate-400">
                            {Math.round(conf * 100)}%
                          </span>
                        ) : (
                          <span className="text-slate-600">—</span>
                        )}
                      </div>
                    </div>
                  );
                })
              )}
            </div>
          </div>

          {/* Detected PII Section */}
          <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 shadow-lg">
            <h4 className="text-sm font-bold text-slate-200 mb-3 flex items-center gap-2">
              <Shield className="w-4 h-4 text-amber-400" />
              Detected PII Entities (Masked by Default)
            </h4>

            {piiList.length === 0 ? (
              <p className="text-xs text-slate-500">No sensitive personal PII entities identified.</p>
            ) : (
              <div className="flex flex-wrap gap-2">
                {piiList.map((p, idx) => (
                  <PIIMaskedValue
                    key={idx}
                    value={p.value || p.entity_type}
                    piiType={p.entity_type || p.type}
                    documentUid={doc.document_uid}
                  />
                ))}
              </div>
            )}
          </div>

          {/* Review Notes Input */}
          <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 shadow-lg">
            <h4 className="text-sm font-bold text-slate-200 mb-2">Reviewer Notes</h4>
            <textarea
              value={reviewNotes}
              onChange={(e) => setReviewNotes(e.target.value)}
              placeholder="Add optional reviewer comments or rationale..."
              rows={2}
              className="w-full bg-slate-950 border border-slate-800 rounded-lg p-2.5 text-xs text-slate-200 focus:outline-none focus:border-sky-500"
            />
          </div>
        </div>
      </div>
    </div>
  );
};
