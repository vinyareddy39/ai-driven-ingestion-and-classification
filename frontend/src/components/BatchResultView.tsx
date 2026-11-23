import React, { useState, useEffect } from 'react';
import { BASE_URL, getAuthToken, getUserRole } from '../api/client';
import { VerifyView } from './VerifyView';

interface BatchResultViewProps {
  batchId: string;
  onBack: () => void;
}

export const BatchResultView: React.FC<BatchResultViewProps> = ({ batchId, onBack }) => {
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [downloading, setDownloading] = useState(false);
  const [downloadError, setDownloadError] = useState<string | null>(null);
  const [showTree, setShowTree] = useState(false);
  const [verifyIndex, setVerifyIndex] = useState<number | null>(null);

  const fetchBatch = async () => {
    setLoading(true);
    setError(null);
    try {
      const headers: Record<string, string> = {};
      const token = getAuthToken();
      const role = getUserRole();
      if (token) headers['Authorization'] = `Bearer ${token}`;
      if (role) headers['X-User-Role'] = role;

      const res = await fetch(`${BASE_URL}/api/v1/batches/${encodeURIComponent(batchId)}?page=1&page_size=200`, {
        headers,
      });

      if (!res.ok) {
        throw new Error(`Failed to load batch results (HTTP ${res.status})`);
      }

      const resData = await res.json();
      setData(resData);
    } catch (err: any) {
      setError(err.message || 'Could not load batch results.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchBatch();
  }, [batchId]);

  const handleDownloadZip = async () => {
    setDownloading(true);
    setDownloadError(null);
    try {
      const headers: Record<string, string> = {};
      const token = getAuthToken();
      const role = getUserRole();
      if (token) headers['Authorization'] = `Bearer ${token}`;
      if (role) headers['X-User-Role'] = role;

      const res = await fetch(`${BASE_URL}/api/v1/batches/${encodeURIComponent(batchId)}/export`, {
        headers,
      });

      if (!res.ok) {
        const errJson = await res.json().catch(() => null);
        throw new Error(errJson?.detail || `Export failed with status ${res.status}`);
      }

      const blob = await res.blob();
      const blobUrl = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = blobUrl;
      const bName = data?.name ? data.name.toLowerCase().replace(/\s+/g, '_') : 'sorted_batch';
      a.download = `${bName}.zip`;
      document.body.appendChild(a);
      a.click();
      window.URL.revokeObjectURL(blobUrl);
      document.body.removeChild(a);
      setShowTree(true);
    } catch (err: any) {
      setDownloadError(err.message || 'Could not download ZIP file.');
    } finally {
      setDownloading(false);
    }
  };

  if (loading) {
    return (
      <div className="body">
        <div className="empty">Loading batch results…</div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="body">
        <div className="empty" style={{ background: 'var(--red-bg)', color: 'var(--red)' }}>
          {error}
        </div>
        <div style={{ marginTop: 12 }}>
          <button className="b" onClick={fetchBatch}>Try again</button>
          <button className="b" onClick={onBack} style={{ marginLeft: 8 }}>Back to dashboard</button>
        </div>
      </div>
    );
  }

  const items: any[] = data?.items || [];
  const totalFiles = data?.progress?.total || items.length;
  const batchName = data?.name || `Upload #${data?.number || 1}`;

  // If in Verify mode (Step 9)
  if (verifyIndex !== null) {
    return (
      <VerifyView
        batchId={batchId}
        files={items}
        initialIndex={verifyIndex}
        onBack={() => {
          setVerifyIndex(null);
          fetchBatch();
        }}
        onFileUpdated={fetchBatch}
      />
    );
  }

  // Group items by doc_type
  const groups: Record<string, any[]> = {};
  items.forEach((it) => {
    const t = it.doc_type || 'unknown';
    if (!groups[t]) groups[t] = [];
    groups[t].push(it);
  });

  const hasAnyExtractedFields = items.some(
    (it) => it.extracted_fields && Object.keys(it.extracted_fields).length > 0
  );

  return (
    <div className="body">
      <div className="head">
        <h3>
          {batchName} · {totalFiles} {totalFiles === 1 ? 'file' : 'files'}
        </h3>
        <div style={{ display: 'flex', gap: 8 }}>
          <button className="b" onClick={onBack}>
            Back to dashboard
          </button>
          <button
            className="b pri"
            onClick={handleDownloadZip}
            disabled={downloading || !hasAnyExtractedFields}
            title={!hasAnyExtractedFields ? 'Waiting for extraction to finish before enabling ZIP download' : ''}
          >
            {downloading ? 'Downloading…' : 'Download all as ZIP'}
          </button>
        </div>
      </div>

      {downloadError && (
        <div className="warn" style={{ background: 'var(--red-bg)', color: 'var(--red)', marginBottom: 14 }}>
          {downloadError}
        </div>
      )}

      {items.length === 0 ? (
        <div className="empty">No documents found in this batch.</div>
      ) : (
        Object.entries(groups).map(([typeKey, typeItems]) => {
          const typeTitle =
            typeKey === 'invoice'
              ? 'Invoices'
              : typeKey === 'letter'
                ? 'Letters'
                : typeKey === 'purchase_order'
                  ? 'Purchase Orders'
                  : typeKey.charAt(0).toUpperCase() + typeKey.slice(1).replace(/_/g, ' ') + 's';

          return (
            <div key={typeKey} style={{ marginBottom: 24 }}>
              <div className="grp">
                <b>{typeTitle}</b>
                <span className="pill p-done">{typeItems.length}</span>
              </div>

              <div className="tbl">
                {typeKey === 'letter' ? (
                  <>
                    <div className="thead" style={{ gridTemplateColumns: 'minmax(140px, 2fr) minmax(130px, 2fr) minmax(100px, 1.2fr) 110px' }}>
                      <span>File</span>
                      <span>Sender</span>
                      <span>Date</span>
                      <span>Status</span>
                    </div>
                    {typeItems.map((it) => {
                      const gIdx = items.findIndex((x) => x.uid === it.uid);
                      const f = it.extracted_fields || {};
                      const sender = f.sender_name || f.sender || '—';
                      const date = f.date || f.letter_date || '—';
                      const pCls = it.plain_status === 'SORTED_AUTOMATICALLY' ? 'p-done' : it.plain_status === 'NEEDS_CHECK' ? 'p-check' : 'p-fail';
                      const pTxt = it.plain_status === 'SORTED_AUTOMATICALLY' ? 'Done' : it.plain_status === 'NEEDS_CHECK' ? 'Check' : 'Failed';

                      return (
                        <div key={it.uid} className="trow" style={{ gridTemplateColumns: 'minmax(140px, 2fr) minmax(130px, 2fr) minmax(100px, 1.2fr) 110px' }}>
                          <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={it.file_name}>
                            {it.file_name}
                          </span>
                          <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                            {sender}
                          </span>
                          <span>{date}</span>
                          <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                            <span className={`pill ${pCls}`}>{pTxt}</span>
                            <button className="link" onClick={() => setVerifyIndex(gIdx >= 0 ? gIdx : 0)}>
                              View
                            </button>
                          </span>
                        </div>
                      );
                    })}
                  </>
                ) : typeKey === 'contract' ? (
                  <>
                    <div className="thead" style={{ gridTemplateColumns: 'minmax(130px, 1.6fr) minmax(100px, 1fr) minmax(90px, 0.9fr) minmax(120px, 1.4fr) minmax(120px, 1.4fr) minmax(105px, 1fr) 95px 105px' }}>
                      <span>File</span>
                      <span>Contract ID</span>
                      <span>Date</span>
                      <span>First Party</span>
                      <span>Second Party</span>
                      <span>Signatory</span>
                      <span>Condition</span>
                      <span>Status</span>
                    </div>
                    {typeItems.map((it) => {
                      const gIdx = items.findIndex((x) => x.uid === it.uid);
                      const f = it.extracted_fields || {};
                      const cid = f.contract_id || '—';
                      const date = f.effective_date || f.date || '—';
                      const firstParty = f.first_party || f.party_one || '—';
                      const secondParty = f.second_party || f.party_two || '—';
                      const signatory = f.authorized_signatory || '—';
                      const condition = f.page_condition || 'clean';
                      const pCls = it.plain_status === 'SORTED_AUTOMATICALLY' || it.plain_status === 'ALREADY_UPLOADED' ? 'p-done' : it.plain_status === 'NEEDS_CHECK' ? 'p-check' : 'p-fail';
                      const pTxt = it.plain_status === 'SORTED_AUTOMATICALLY' ? 'Done' : it.plain_status === 'ALREADY_UPLOADED' ? 'Done' : it.plain_status === 'NEEDS_CHECK' ? 'Check' : 'Failed';

                      return (
                        <div key={it.uid} className="trow" style={{ gridTemplateColumns: 'minmax(130px, 1.6fr) minmax(100px, 1fr) minmax(90px, 0.9fr) minmax(120px, 1.4fr) minmax(120px, 1.4fr) minmax(105px, 1fr) 95px 105px' }}>
                          <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={it.file_name}>
                            {it.file_name}
                          </span>
                          <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                            {cid}
                          </span>
                          <span>{date}</span>
                          <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={firstParty}>
                            {firstParty}
                          </span>
                          <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={secondParty}>
                            {secondParty}
                          </span>
                          <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={signatory}>
                            {signatory}
                          </span>
                          <span style={{ fontSize: 12, color: 'var(--text2)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={condition}>
                            {condition}
                          </span>
                          <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                            <span className={`pill ${pCls}`}>{pTxt}</span>
                            <button className="link" onClick={() => setVerifyIndex(gIdx >= 0 ? gIdx : 0)}>
                              View
                            </button>
                          </span>
                        </div>
                      );
                    })}
                  </>
                ) : typeKey === 'purchase_order' ? (
                  <>
                    <div className="thead" style={{ gridTemplateColumns: 'minmax(140px, 2fr) minmax(130px, 2fr) minmax(100px, 1.2fr) 110px' }}>
                      <span>File</span>
                      <span>Vendor</span>
                      <span>Order Total</span>
                      <span>Status</span>
                    </div>
                    {typeItems.map((it) => {
                      const gIdx = items.findIndex((x) => x.uid === it.uid);
                      const f = it.extracted_fields || {};
                      const vendor = f.vendor_name || it.vendor || '—';
                      const amt = f.order_total || f.total_amount || it.amount || '—';
                      const amtStr = typeof amt === 'number' ? `$${amt.toLocaleString('en-US', { minimumFractionDigits: 2 })}` : String(amt);
                      const pCls = it.plain_status === 'SORTED_AUTOMATICALLY' || it.plain_status === 'ALREADY_UPLOADED' ? 'p-done' : it.plain_status === 'NEEDS_CHECK' ? 'p-check' : 'p-fail';
                      const pTxt = it.plain_status === 'SORTED_AUTOMATICALLY' ? 'Done' : it.plain_status === 'ALREADY_UPLOADED' ? 'Done' : it.plain_status === 'NEEDS_CHECK' ? 'Check' : 'Failed';

                      return (
                        <div key={it.uid} className="trow" style={{ gridTemplateColumns: 'minmax(140px, 2fr) minmax(130px, 2fr) minmax(100px, 1.2fr) 110px' }}>
                          <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={it.file_name}>
                            {it.file_name}
                          </span>
                          <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                            {vendor}
                          </span>
                          <span>{amtStr}</span>
                          <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                            <span className={`pill ${pCls}`}>{pTxt}</span>
                            <button className="link" onClick={() => setVerifyIndex(gIdx >= 0 ? gIdx : 0)}>
                              View
                            </button>
                          </span>
                        </div>
                      );
                    })}
                  </>
                ) : (
                  <>
                    <div className="thead" style={{ gridTemplateColumns: 'minmax(140px, 2fr) minmax(130px, 2fr) minmax(100px, 1.2fr) 110px' }}>
                      <span>File</span>
                      <span>Vendor</span>
                      <span>Amount</span>
                      <span>Status</span>
                    </div>
                    {typeItems.map((it) => {
                      const gIdx = items.findIndex((x) => x.uid === it.uid);
                      const f = it.extracted_fields || {};
                      const vendor = it.vendor || f.vendor_name || f.vendor || '—';
                      const amt = it.amount || (f.total_amount ? `$${Number(f.total_amount).toLocaleString('en-US', { minimumFractionDigits: 2 })}` : '—');
                      const pCls = it.plain_status === 'SORTED_AUTOMATICALLY' || it.plain_status === 'ALREADY_UPLOADED' ? 'p-done' : it.plain_status === 'NEEDS_CHECK' ? 'p-check' : 'p-fail';
                      const pTxt = it.plain_status === 'SORTED_AUTOMATICALLY' ? 'Done' : it.plain_status === 'ALREADY_UPLOADED' ? 'Done' : it.plain_status === 'NEEDS_CHECK' ? 'Check' : 'Failed';

                      return (
                        <div key={it.uid} className="trow" style={{ gridTemplateColumns: 'minmax(140px, 2fr) minmax(130px, 2fr) minmax(100px, 1.2fr) 110px' }}>
                          <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={it.file_name}>
                            {it.file_name}
                          </span>
                          <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                            {vendor}
                          </span>
                          <span>{amt}</span>
                          <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                            <span className={`pill ${pCls}`}>{pTxt}</span>
                            <button className="link" onClick={() => setVerifyIndex(gIdx >= 0 ? gIdx : 0)}>
                              View
                            </button>
                          </span>
                        </div>
                      );
                    })}
                  </>
                )}
              </div>
            </div>
          );
        })
      )}

      {showTree && (
        <div className="tree">
          {batchName.toLowerCase().replace(/\s+/g, '_')}.zip
          {Object.keys(groups).map((k) => `\n├─ ${k}/    ${groups[k].length} files`)}
          {'\n└─ index.csv   one row per file, columns that fit each type'}
        </div>
      )}

      <p className="ex">
        Click View on any row to open the split screen and check it against the original, or Download all as ZIP.
      </p>
    </div>
  );
};
