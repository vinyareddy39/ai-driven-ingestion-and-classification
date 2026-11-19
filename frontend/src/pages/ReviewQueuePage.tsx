import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import {
  AlertTriangle,
  ArrowUpDown,
  CheckCircle2,
  Clock,
  Filter,
  Inbox,
  Shield,
  Sparkles,
} from 'lucide-react';
import { api, ReviewQueueItem } from '../api/client';
import { ConfidenceBadge } from '../components/ConfidenceBadge';
import { AuthenticatedImage } from '../components/AuthenticatedImage';

export const ReviewQueuePage: React.FC = () => {
  const navigate = useNavigate();
  const [page, setPage] = useState(1);
  const [sortBy, setSortBy] = useState<'risk' | 'confidence' | 'age'>('risk');
  const [docTypeFilter, setDocTypeFilter] = useState<string>('');
  const [riskFilter, setRiskFilter] = useState<string>('');
  const [piiFilter, setPiiFilter] = useState<string>('');
  const [selectedIndex, setSelectedIndex] = useState<number>(0);

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ['reviewQueue', page, sortBy, docTypeFilter, riskFilter, piiFilter],
    queryFn: () =>
      api.getReviewQueue({
        page,
        page_size: 20,
        sort_by: sortBy,
        doc_type: docTypeFilter || undefined,
        risk_level: riskFilter || undefined,
        pii_sensitivity: piiFilter || undefined,
      }),
    refetchInterval: 15000,
  });

  const items = data?.items || [];

  // Keyboard navigation: Up/Down arrow to select row, Enter to open review detail
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (!items.length) return;
      if (e.key === 'ArrowDown') {
        e.preventDefault();
        setSelectedIndex((prev) => Math.min(prev + 1, items.length - 1));
      } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        setSelectedIndex((prev) => Math.max(prev - 1, 0));
      } else if (e.key === 'Enter') {
        e.preventDefault();
        const selected = items[selectedIndex];
        if (selected) {
          navigate(`/review/${selected.document_uid}`);
        }
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [items, selectedIndex, navigate]);

  const formatAge = (seconds: number) => {
    if (seconds < 60) return `${seconds}s ago`;
    if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
    return `${Math.floor(seconds / 3600)}h ago`;
  };

  return (
    <div className="p-8 max-w-7xl mx-auto w-full">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-white flex items-center gap-2.5">
            <Inbox className="w-6 h-6 text-sky-400" />
            Human Review Queue
          </h1>
          <p className="text-sm text-slate-400 mt-1">
            Uncertain documents requiring human verification, sorted by risk profile and AI confidence.
          </p>
        </div>

        <div className="text-xs text-slate-400 bg-slate-900 border border-slate-800 rounded-lg px-3 py-2 flex items-center gap-2">
          <span className="font-mono text-sky-400">↑ / ↓</span> to navigate,{' '}
          <span className="font-mono text-sky-400">Enter</span> to review
        </div>
      </div>

      {/* Filter & Sort Bar */}
      <div className="bg-slate-900/90 border border-slate-800 rounded-xl p-4 mb-6 flex flex-wrap items-center gap-4 text-xs">
        <div className="flex items-center gap-2 text-slate-400">
          <Filter className="w-4 h-4 text-sky-400" />
          <span className="font-medium uppercase tracking-wider text-[11px]">Filters:</span>
        </div>

        {/* Risk Level Filter */}
        <select
          value={riskFilter}
          onChange={(e) => {
            setRiskFilter(e.target.value);
            setPage(1);
          }}
          className="bg-slate-800 text-slate-200 border border-slate-700 rounded-lg px-2.5 py-1.5 focus:outline-none focus:border-sky-500"
        >
          <option value="">All Risk Tiers</option>
          <option value="HIGH">High Risk Only</option>
          <option value="LOW">Low Risk Only</option>
        </select>

        {/* Doc Type Filter */}
        <select
          value={docTypeFilter}
          onChange={(e) => {
            setDocTypeFilter(e.target.value);
            setPage(1);
          }}
          className="bg-slate-800 text-slate-200 border border-slate-700 rounded-lg px-2.5 py-1.5 focus:outline-none focus:border-sky-500"
        >
          <option value="">All Document Types</option>
          <option value="kyc_form">KYC Form</option>
          <option value="bank_statement">Bank Statement</option>
          <option value="medical_report">Medical Report</option>
          <option value="claim_form">Claim Form</option>
          <option value="invoice">Invoice</option>
          <option value="contract">Legal Contract</option>
          <option value="purchase_order">Purchase Order</option>
          <option value="unknown">Unknown</option>
        </select>

        {/* PII Sensitivity Filter */}
        <select
          value={piiFilter}
          onChange={(e) => {
            setPiiFilter(e.target.value);
            setPage(1);
          }}
          className="bg-slate-800 text-slate-200 border border-slate-700 rounded-lg px-2.5 py-1.5 focus:outline-none focus:border-sky-500"
        >
          <option value="">All PII Levels</option>
          <option value="HIGH">High PII (SSN/Passport)</option>
          <option value="MEDIUM">Medium PII (Phone/Email)</option>
          <option value="LOW">Low PII</option>
          <option value="NONE">No PII</option>
        </select>

        <div className="ml-auto flex items-center gap-2">
          <ArrowUpDown className="w-4 h-4 text-slate-400" />
          <span className="text-slate-400 text-[11px] uppercase tracking-wider font-medium">Sort By:</span>
          <select
            value={sortBy}
            onChange={(e) => {
              setSortBy(e.target.value as 'risk' | 'confidence' | 'age');
              setPage(1);
            }}
            className="bg-slate-800 text-slate-200 border border-slate-700 rounded-lg px-2.5 py-1.5 focus:outline-none focus:border-sky-500 font-medium"
          >
            <option value="risk">Risk First, Then Confidence</option>
            <option value="confidence">Lowest Confidence First</option>
            <option value="age">Oldest First</option>
          </select>
        </div>
      </div>

      {/* Review Queue Table */}
      <div className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden shadow-xl">
        {isLoading ? (
          <div className="p-12 text-center text-slate-400">
            <div className="w-6 h-6 border-2 border-sky-400 border-t-transparent rounded-full animate-spin mx-auto mb-3" />
            Loading review queue from backend...
          </div>
        ) : error ? (
          <div className="p-8 text-center text-rose-400">
            <AlertTriangle className="w-8 h-8 mx-auto mb-2 text-rose-500" />
            <p className="font-medium">Failed to load review queue</p>
            <p className="text-xs text-rose-300 mt-1">{(error as Error).message}</p>
          </div>
        ) : items.length === 0 ? (
          <div className="p-16 text-center text-slate-400">
            <CheckCircle2 className="w-12 h-12 text-emerald-500/80 mx-auto mb-3" />
            <h3 className="text-lg font-semibold text-slate-200">Review Queue is Empty</h3>
            <p className="text-sm text-slate-500 mt-1">
              All documents have been auto-accepted or verified by human reviewers.
            </p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left border-collapse text-xs">
              <thead>
                <tr className="border-b border-slate-800 bg-slate-950/60 text-slate-400 uppercase text-[10px] tracking-wider font-semibold">
                  <th className="py-3 px-4">Preview</th>
                  <th className="py-3 px-4">Document / ID</th>
                  <th className="py-3 px-4">Predicted Type</th>
                  <th className="py-3 px-4">Confidence</th>
                  <th className="py-3 px-4">Review Reason</th>
                  <th className="py-3 px-4">PII Tier</th>
                  <th className="py-3 px-4">Age</th>
                  <th className="py-3 px-4 text-right">Action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/80">
                {items.map((item, index) => {
                  const isSelected = index === selectedIndex;
                  return (
                    <tr
                      key={item.document_uid}
                      onClick={() => {
                        setSelectedIndex(index);
                        navigate(`/review/${item.document_uid}`);
                      }}
                      className={`cursor-pointer transition-colors ${
                        isSelected
                          ? 'bg-sky-950/40 border-l-4 border-l-sky-500'
                          : 'hover:bg-slate-800/50'
                      }`}
                    >
                      {/* Thumbnail */}
                      <td className="py-3 px-4">
                        <div className="w-10 h-12 rounded bg-slate-800 border border-slate-700 overflow-hidden flex items-center justify-center">
                          <AuthenticatedImage
                            src={`${item.thumbnail_url || `/api/v1/documents/${item.document_uid}/pages/1/image`}?width=120`}
                            alt="thumb"
                            className="w-full h-full object-cover"
                          />
                        </div>
                      </td>

                      {/* File Name & UID */}
                      <td className="py-3 px-4">
                        <div className="font-semibold text-slate-200">{item.file_name}</div>
                        <div className="font-mono text-[10px] text-slate-500 mt-0.5">{item.document_uid}</div>
                      </td>

                      {/* Predicted Type & Risk */}
                      <td className="py-3 px-4">
                        <div className="font-medium text-slate-200">{item.predicted_type}</div>
                        <span
                          className={`inline-block mt-0.5 text-[9px] font-bold px-1.5 py-0.2 rounded uppercase border ${
                            item.risk_level === 'HIGH'
                              ? 'bg-rose-950 text-rose-300 border-rose-800'
                              : 'bg-emerald-950 text-emerald-300 border-emerald-800'
                          }`}
                        >
                          {item.risk_level} RISK
                        </span>
                      </td>

                      {/* Confidence */}
                      <td className="py-3 px-4">
                        <ConfidenceBadge confidence={item.confidence} />
                      </td>

                      {/* Review Reason */}
                      <td className="py-3 px-4 max-w-xs text-slate-300">
                        <span className="truncate block" title={item.review_reason}>
                          {item.review_reason}
                        </span>
                      </td>

                      {/* PII Sensitivity */}
                      <td className="py-3 px-4">
                        <span
                          className={`inline-flex items-center gap-1 font-mono text-[10px] font-medium px-2 py-0.5 rounded border ${
                            item.pii_sensitivity === 'HIGH'
                              ? 'bg-rose-950/80 text-rose-300 border-rose-800/80'
                              : item.pii_sensitivity === 'MEDIUM'
                              ? 'bg-amber-950/80 text-amber-300 border-amber-800/80'
                              : 'bg-slate-800 text-slate-400 border-slate-700'
                          }`}
                        >
                          <Shield className="w-3 h-3" />
                          {item.pii_sensitivity}
                        </span>
                      </td>

                      {/* Age */}
                      <td className="py-3 px-4 text-slate-400 font-mono text-[11px] whitespace-nowrap">
                        <div className="flex items-center gap-1">
                          <Clock className="w-3 h-3 text-slate-500" />
                          {formatAge(item.age_seconds)}
                        </div>
                      </td>

                      {/* Action */}
                      <td className="py-3 px-4 text-right">
                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            navigate(`/review/${item.document_uid}`);
                          }}
                          className="bg-sky-600 hover:bg-sky-500 text-white font-medium text-xs px-3 py-1.5 rounded-lg transition-colors shadow-sm"
                        >
                          Review
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
};
