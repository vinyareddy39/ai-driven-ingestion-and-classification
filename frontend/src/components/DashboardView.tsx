import React, { useState, useEffect } from 'react';
import { BASE_URL, getAuthToken, getUserRole } from '../api/client';

interface DashboardViewProps {
  onNavigateUpload: () => void;
  onNavigateReview: () => void;
  onSelectBatch: (batchId: string) => void;
}

interface BatchSummaryItem {
  batch_id: string;
  number: number;
  name: string;
  created_at: string;
  file_count: number;
  progress_percent: number;
  counts_by_status: Record<string, number>;
  needs_check_count: number;
  is_finished: boolean;
}

export const DashboardView: React.FC<DashboardViewProps> = ({
  onNavigateUpload,
  onNavigateReview,
  onSelectBatch,
}) => {
  const [batches, setBatches] = useState<BatchSummaryItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchData = async () => {
    setLoading(true);
    setError(null);
    try {
      const headers: Record<string, string> = {};
      const token = getAuthToken();
      const role = getUserRole();
      if (token) headers['Authorization'] = `Bearer ${token}`;
      if (role) headers['X-User-Role'] = role;

      const res = await fetch(`${BASE_URL}/api/v1/batches?page=1&page_size=50`, { headers });
      if (!res.ok) {
        throw new Error(`Failed to load documents (HTTP ${res.status})`);
      }

      const bData = await res.json();
      setBatches(bData.items || []);
    } catch (err: any) {
      setError(err.message || 'Could not load your documents.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
  }, []);

  // Compute stat card numbers from real batch data
  const processingCount = batches.filter((b) => !b.is_finished).length;
  const needsCheckCount = batches.reduce((acc, b) => acc + (b.needs_check_count || 0), 0);
  const doneCount = batches.reduce((acc, b) => acc + (b.counts_by_status?.['SORTED_AUTOMATICALLY'] || 0), 0);
  const failedCount = batches.reduce((acc, b) => acc + (b.counts_by_status?.['FAILED'] || 0), 0);

  return (
    <div className="body">
      <div className="head">
        <h3>Your documents</h3>
        <button className="b pri" onClick={onNavigateUpload}>
          Upload files
        </button>
      </div>

      <div className="cards">
        <div className="stat">
          <small>Processing</small>
          <b>{processingCount}</b>
        </div>
        <div className="stat c" onClick={onNavigateReview} title="Open review queue">
          <small>Needs your check</small>
          <b>{needsCheckCount}</b>
        </div>
        <div className="stat d">
          <small>Done</small>
          <b>{doneCount}</b>
        </div>
        <div className="stat f">
          <small>Failed</small>
          <b>{failedCount}</b>
        </div>
      </div>

      <p className="sec">Recent uploads</p>

      {loading ? (
        <div className="empty">Loading recent uploads…</div>
      ) : error ? (
        <div className="empty" style={{ background: 'var(--red-bg)', color: 'var(--red)' }}>
          {error}
        </div>
      ) : batches.length === 0 ? (
        <div className="empty">No documents uploaded yet. Click "Upload files" to begin.</div>
      ) : (
        batches.map((b) => {
          let pill;
          if (b.needs_check_count > 0) {
            pill = <span className="pill p-check">{b.needs_check_count} need a check</span>;
          } else if (b.is_finished) {
            if ((b.counts_by_status?.['FAILED'] || 0) > 0) {
              pill = <span className="pill p-fail">Failed</span>;
            } else {
              pill = <span className="pill p-done">All done</span>;
            }
          } else {
            pill = <span className="pill p-wait">Processing</span>;
          }

          return (
            <div
              key={b.batch_id}
              className="row"
              onClick={() => onSelectBatch(b.batch_id)}
              style={{ cursor: 'pointer' }}
            >
              <span>
                {b.name} · {b.file_count} {b.file_count === 1 ? 'file' : 'files'}
              </span>
              {pill}
            </div>
          );
        })
      )}
    </div>
  );
};
