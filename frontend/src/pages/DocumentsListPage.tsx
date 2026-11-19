import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import {
  AlertTriangle,
  Calendar,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  FileText,
  Filter,
  Search,
  Shield,
  ShieldAlert,
} from 'lucide-react';
import { api, DocumentSummaryItem } from '../api/client';
import { ConfidenceBadge } from '../components/ConfidenceBadge';

export const DocumentsListPage: React.FC = () => {
  const navigate = useNavigate();
  const [page, setPage] = useState(1);
  const [searchQuery, setSearchQuery] = useState('');
  const [activeSearch, setActiveSearch] = useState('');
  const [docTypeFilter, setDocTypeFilter] = useState('');
  const [statusFilter, setStatusFilter] = useState('');
  const [piiFilter, setPiiFilter] = useState('');
  const [minConf, setMinConf] = useState<string>('');

  const { data, isLoading, error } = useQuery({
    queryKey: ['documentsList', page, activeSearch, docTypeFilter, statusFilter, piiFilter, minConf],
    queryFn: () =>
      api.getDocuments({
        page,
        page_size: 20,
        q: activeSearch || undefined,
        doc_type: docTypeFilter || undefined,
        review_status: statusFilter || undefined,
        pii_type: piiFilter || undefined,
        min_confidence: minConf ? parseFloat(minConf) : undefined,
      }),
  });

  const handleSearchSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setActiveSearch(searchQuery);
    setPage(1);
  };

  const items = data?.items || [];
  const total = data?.total || 0;
  const totalPages = data?.total_pages || 1;

  return (
    <div className="p-8 max-w-7xl mx-auto w-full">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-white flex items-center gap-2.5">
            <FileText className="w-6 h-6 text-sky-400" />
            Documents Repository & Search
          </h1>
          <p className="text-sm text-slate-400 mt-1">
            Search full-text, metadata, classification confidences, and compliance classifications.
          </p>
        </div>
      </div>

      {/* Search & Filter Bar */}
      <div className="bg-slate-900/90 border border-slate-800 rounded-xl p-4 mb-6 space-y-3">
        <form onSubmit={handleSearchSubmit} className="flex gap-2">
          <div className="relative flex-1">
            <Search className="w-4 h-4 text-slate-400 absolute left-3 top-3" />
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Search by file name, document UID, or extracted keywords..."
              className="w-full bg-slate-950 border border-slate-800 rounded-lg pl-9 pr-4 py-2 text-xs text-slate-200 focus:outline-none focus:border-sky-500 font-medium"
            />
          </div>
          <button
            type="submit"
            className="px-4 py-2 bg-sky-600 hover:bg-sky-500 text-white font-bold text-xs rounded-lg transition-colors shadow-sm"
          >
            Search
          </button>
        </form>

        <div className="flex flex-wrap items-center gap-3 text-xs pt-2 border-t border-slate-800/80">
          <span className="text-slate-400 text-[11px] uppercase tracking-wider font-semibold flex items-center gap-1.5">
            <Filter className="w-3.5 h-3.5 text-sky-400" /> Filter:
          </span>

          {/* Doc Type */}
          <select
            value={docTypeFilter}
            onChange={(e) => {
              setDocTypeFilter(e.target.value);
              setPage(1);
            }}
            className="bg-slate-800 text-slate-200 border border-slate-700 rounded-md px-2.5 py-1.5 focus:outline-none focus:border-sky-500"
          >
            <option value="">All Types</option>
            <option value="kyc_form">KYC Form</option>
            <option value="bank_statement">Bank Statement</option>
            <option value="medical_report">Medical Report</option>
            <option value="claim_form">Claim Form</option>
            <option value="invoice">Invoice</option>
            <option value="contract">Legal Contract</option>
            <option value="purchase_order">Purchase Order</option>
            <option value="unknown">Unknown</option>
          </select>

          {/* Review Status */}
          <select
            value={statusFilter}
            onChange={(e) => {
              setStatusFilter(e.target.value);
              setPage(1);
            }}
            className="bg-slate-800 text-slate-200 border border-slate-700 rounded-md px-2.5 py-1.5 focus:outline-none focus:border-sky-500"
          >
            <option value="">All Statuses</option>
            <option value="auto_accepted">Auto Accepted</option>
            <option value="human_verified">Human Verified</option>
            <option value="pending_review">Pending Review</option>
            <option value="quarantined">Quarantined</option>
            <option value="rejected">Rejected</option>
          </select>

          {/* PII Type */}
          <select
            value={piiFilter}
            onChange={(e) => {
              setPiiFilter(e.target.value);
              setPage(1);
            }}
            className="bg-slate-800 text-slate-200 border border-slate-700 rounded-md px-2.5 py-1.5 focus:outline-none focus:border-sky-500"
          >
            <option value="">All PII Tags</option>
            <option value="SSN">SSN</option>
            <option value="PASSPORT">Passport</option>
            <option value="NATIONAL_ID">National ID</option>
            <option value="PHONE_NUMBER">Phone</option>
            <option value="EMAIL_ADDRESS">Email</option>
            <option value="PERSON">Person</option>
          </select>

          {/* Min Confidence */}
          <select
            value={minConf}
            onChange={(e) => {
              setMinConf(e.target.value);
              setPage(1);
            }}
            className="bg-slate-800 text-slate-200 border border-slate-700 rounded-md px-2.5 py-1.5 focus:outline-none focus:border-sky-500"
          >
            <option value="">Any Confidence</option>
            <option value="0.95">≥ 95% (High Tier)</option>
            <option value="0.90">≥ 90% (Low Tier)</option>
            <option value="0.75">≥ 75%</option>
          </select>

          <span className="ml-auto text-slate-400 font-mono text-[11px]">
            Found {total} documents
          </span>
        </div>
      </div>

      {/* Documents Table */}
      <div className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden shadow-xl">
        {isLoading ? (
          <div className="p-12 text-center text-slate-400">
            <div className="w-6 h-6 border-2 border-sky-400 border-t-transparent rounded-full animate-spin mx-auto mb-3" />
            Loading documents from database...
          </div>
        ) : error ? (
          <div className="p-8 text-center text-rose-400">
            <AlertTriangle className="w-8 h-8 mx-auto mb-2 text-rose-500" />
            <p className="font-medium">Failed to search documents</p>
            <p className="text-xs text-rose-300 mt-1">{(error as Error).message}</p>
          </div>
        ) : items.length === 0 ? (
          <div className="p-16 text-center text-slate-400">
            <FileText className="w-12 h-12 text-slate-600 mx-auto mb-3" />
            <h3 className="text-base font-semibold text-slate-300">No documents found</h3>
            <p className="text-xs text-slate-500 mt-1">
              Try adjusting your search keywords or clearing filters.
            </p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left border-collapse text-xs">
              <thead>
                <tr className="border-b border-slate-800 bg-slate-950/60 text-slate-400 uppercase text-[10px] tracking-wider font-semibold">
                  <th className="py-3 px-4">File Name</th>
                  <th className="py-3 px-4">Type</th>
                  <th className="py-3 px-4">Confidence</th>
                  <th className="py-3 px-4">Review Status</th>
                  <th className="py-3 px-4">PII Tags</th>
                  <th className="py-3 px-4">Model</th>
                  <th className="py-3 px-4 text-right">Compliance</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/80">
                {items.map((doc) => (
                  <tr
                    key={doc.uid}
                    onClick={() => navigate(`/compliance/${doc.uid}`)}
                    className="hover:bg-slate-800/50 cursor-pointer transition-colors"
                  >
                    <td className="py-3 px-4">
                      <div className="font-semibold text-slate-200">{doc.file_name}</div>
                      <div className="font-mono text-[10px] text-slate-500 mt-0.5">{doc.uid}</div>
                    </td>

                    <td className="py-3 px-4">
                      <span className="font-mono font-medium text-slate-200">{doc.doc_type}</span>
                    </td>

                    <td className="py-3 px-4">
                      <ConfidenceBadge confidence={doc.confidence} />
                    </td>

                    <td className="py-3 px-4">
                      <span
                        className={`inline-block text-[10px] font-bold px-2 py-0.5 rounded uppercase border ${
                          doc.review_status === 'auto_accepted'
                            ? 'bg-emerald-950 text-emerald-300 border-emerald-800'
                            : doc.review_status === 'human_verified'
                            ? 'bg-sky-950 text-sky-300 border-sky-800'
                            : doc.review_status === 'pending_review'
                            ? 'bg-amber-950 text-amber-300 border-amber-800'
                            : 'bg-rose-950 text-rose-300 border-rose-800'
                        }`}
                      >
                        {doc.review_status}
                      </span>
                    </td>

                    <td className="py-3 px-4">
                      {doc.pii_types && doc.pii_types.length > 0 ? (
                        <div className="flex flex-wrap gap-1">
                          {doc.pii_types.map((p, idx) => (
                            <span
                              key={idx}
                              className="font-mono text-[9px] bg-slate-800 text-amber-400 px-1.5 py-0.5 rounded border border-slate-700"
                            >
                              {p}
                            </span>
                          ))}
                        </div>
                      ) : (
                        <span className="text-slate-600 font-mono text-[10px]">none</span>
                      )}
                    </td>

                    <td className="py-3 px-4 font-mono text-slate-400 text-[11px]">
                      {doc.classifier_version}
                    </td>

                    <td className="py-3 px-4 text-right">
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          navigate(`/compliance/${doc.uid}`);
                        }}
                        className="px-2.5 py-1 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded font-medium text-xs transition-colors"
                      >
                        Audit Details
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {/* Pagination Bar */}
        {totalPages > 1 && (
          <div className="p-4 border-t border-slate-800 flex items-center justify-between text-xs text-slate-400">
            <span>
              Page {page} of {totalPages} ({total} documents)
            </span>
            <div className="flex gap-2">
              <button
                disabled={page <= 1}
                onClick={() => setPage((p) => Math.max(p - 1, 1))}
                className="px-3 py-1.5 rounded bg-slate-800 hover:bg-slate-700 text-slate-200 disabled:opacity-40"
              >
                Previous
              </button>
              <button
                disabled={page >= totalPages}
                onClick={() => setPage((p) => Math.min(p + 1, totalPages))}
                className="px-3 py-1.5 rounded bg-slate-800 hover:bg-slate-700 text-slate-200 disabled:opacity-40"
              >
                Next
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};
