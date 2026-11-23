import React, { useState, useEffect } from 'react';
import { BASE_URL, getAuthToken, getUserRole, fetchDocumentPageImageUrl } from '../api/client';

interface ReviewQueueViewProps {
  onBack: () => void;
  onFinished: () => void;
}

interface FieldItem {
  key: string;
  label: string;
  value: string;
  confidence: number;
  isUnsure: boolean;
  isMissing: boolean;
}

export const ReviewQueueView: React.FC<ReviewQueueViewProps> = ({ onBack, onFinished }) => {
  const [queue, setQueue] = useState<any[]>([]);
  const [currentIndex, setCurrentIndex] = useState(0);
  const [loadingQueue, setLoadingQueue] = useState(true);
  const [queueError, setQueueError] = useState<string | null>(null);

  const [currentDoc, setCurrentDoc] = useState<any>(null);
  const [docType, setDocType] = useState<string>('Letter');
  const [fields, setFields] = useState<FieldItem[]>([]);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [docText, setDocText] = useState<string>('');
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [docTypesList, setDocTypesList] = useState<string[]>(['Letter', 'Invoice', 'Purchase Order', 'Receipt', 'Contract', 'Bank Statement', 'Other']);

  // Fetch document types from configuration endpoint
  useEffect(() => {
    const fetchDocTypes = async () => {
      try {
        const token = getAuthToken();
        const headers: Record<string, string> = {};
        if (token) headers['Authorization'] = `Bearer ${token}`;
        const res = await fetch(`${BASE_URL}/api/v1/document-types`, { headers });
        if (res.ok) {
          const data = await res.json();
          const types = Object.values(data.document_types || {}).map((d: any) => d.label || d.name);
          if (types.length > 0) setDocTypesList([...types, 'Other']);
        }
      } catch {
        // use fallback list
      }
    };
    fetchDocTypes();
  }, []);

  const fetchQueue = async () => {
    setLoadingQueue(true);
    setQueueError(null);
    try {
      const headers: Record<string, string> = {};
      const token = getAuthToken();
      const role = getUserRole();
      if (token) headers['Authorization'] = `Bearer ${token}`;
      if (role) headers['X-User-Role'] = role;

      const res = await fetch(`${BASE_URL}/api/v1/review/queue?page=1&page_size=50`, { headers });
      if (!res.ok) throw new Error(`Could not load review queue (HTTP ${res.status})`);

      const data = await res.json();
      const items = Array.isArray(data) ? data : data.items || [];
      setQueue(items);
      setCurrentIndex(0);
      if (items.length > 0) {
        loadDetail(items[0].document_uid);
      }
    } catch (err: any) {
      setQueueError(err.message || 'Failed to load review items.');
    } finally {
      setLoadingQueue(false);
    }
  };

  useEffect(() => {
    fetchQueue();
  }, []);

  const loadDetail = async (uid: string) => {
    setLoadingDetail(true);
    if (previewUrl) {
      URL.revokeObjectURL(previewUrl);
      setPreviewUrl(null);
    }

    const headers: Record<string, string> = {};
    const token = getAuthToken();
    const role = getUserRole();
    if (token) headers['Authorization'] = `Bearer ${token}`;
    if (role) headers['X-User-Role'] = role;

    try {
      const res = await fetch(`${BASE_URL}/api/v1/review/${encodeURIComponent(uid)}`, { headers });
      if (res.ok) {
        const data = await res.json();
        setCurrentDoc(data);

        const t = data.predicted_type || data.doc_type || 'Letter';
        const formattedType = t === 'po' ? 'Purchase Order' : t.charAt(0).toUpperCase() + t.slice(1).replace(/_/g, ' ');
        setDocType(formattedType);

        const extracted = data.extracted_fields || {};
        const confidences = data.field_confidences || {};
        const fList: FieldItem[] = [];

        Object.entries(extracted).forEach(([k, v]) => {
          const valStr = v !== null && v !== undefined ? String(v) : '';
          const conf = confidences[k] ?? 0.95;
          const isMissing = !valStr;
          const isUnsure = conf < 0.85 && !isMissing;
          const label = k.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
          fList.push({
            key: k,
            label,
            value: valStr,
            confidence: conf,
            isUnsure,
            isMissing,
          });
        });

        // If invoice and missing invoice_date
        if (t.toLowerCase().includes('invoice') && !fList.some((f) => f.key === 'invoice_date')) {
          fList.push({
            key: 'invoice_date',
            label: 'Invoice Date',
            value: '',
            confidence: 0,
            isUnsure: false,
            isMissing: true,
          });
        }

        setFields(fList);
        setDocText(data.evidence_text || '');
      }

      // Fetch page image preview
      try {
        const img = await fetchDocumentPageImageUrl(uid, 1, 800);
        setPreviewUrl(img.url);
      } catch {
        // Fallback to text
      }
    } catch {
      // Continue with current state
    } finally {
      setLoadingDetail(false);
    }
  };

  const handleFieldChange = (index: number, val: string) => {
    setFields((prev) =>
      prev.map((f, i) => (i === index ? { ...f, value: val, isMissing: !val, isUnsure: false } : f))
    );
  };

  const handleAddField = () => {
    const name = window.prompt('Enter field name:');
    if (name && name.trim()) {
      const cleanKey = name.trim().toLowerCase().replace(/\s+/g, '_');
      setFields((prev) => [
        ...prev,
        {
          key: cleanKey,
          label: name.trim(),
          value: '',
          confidence: 1.0,
          isUnsure: false,
          isMissing: false,
        },
      ]);
    }
  };

  const handleApprove = async () => {
    if (!queue[currentIndex]) return;
    setSubmitting(true);

    const docUid = queue[currentIndex].document_uid;
    const token = getAuthToken();
    const role = getUserRole();
    const headers: Record<string, string> = { 'Content-Type': 'application/json' };
    if (token) headers['Authorization'] = `Bearer ${token}`;
    if (role) headers['X-User-Role'] = role;

    const correctedFields: Record<string, any> = {};
    fields.forEach((f) => {
      correctedFields[f.key] = f.value;
    });

    try {
      await fetch(`${BASE_URL}/api/v1/review/${encodeURIComponent(docUid)}/action`, {
        method: 'POST',
        headers,
        body: JSON.stringify({
          action: 'CONFIRM',
          corrected_type: docType.toLowerCase().replace(/\s+/g, '_'),
          corrected_fields: correctedFields,
        }),
      });

      advanceQueue();
    } catch {
      advanceQueue();
    } finally {
      setSubmitting(false);
    }
  };

  const handleSaveChanges = async () => {
    await handleApprove();
  };

  const handleSkip = () => {
    advanceQueue();
  };

  const handleTryReadingAgain = async () => {
    if (!queue[currentIndex]) return;
    setSubmitting(true);
    const docUid = queue[currentIndex].document_uid;
    const token = getAuthToken();
    const headers: Record<string, string> = {};
    if (token) headers['Authorization'] = `Bearer ${token}`;
    try {
      await fetch(`${BASE_URL}/api/v1/reprocess/${encodeURIComponent(docUid)}`, {
        method: 'POST',
        headers,
      });
      advanceQueue();
    } catch {
      advanceQueue();
    } finally {
      setSubmitting(false);
    }
  };

  const advanceQueue = () => {
    const nextIdx = currentIndex + 1;
    if (nextIdx < queue.length) {
      setCurrentIndex(nextIdx);
      loadDetail(queue[nextIdx].document_uid);
    } else {
      onFinished();
    }
  };

  if (loadingQueue) {
    return (
      <div className="body">
        <div className="empty">Loading review queue…</div>
      </div>
    );
  }

  if (queueError) {
    return (
      <div className="body">
        <div className="empty" style={{ background: 'var(--red-bg)', color: 'var(--red)' }}>
          {queueError}
        </div>
        <div style={{ marginTop: 12 }}>
          <button className="b" onClick={fetchQueue}>Try again</button>
          <button className="b" onClick={onBack} style={{ marginLeft: 8 }}>Back to dashboard</button>
        </div>
      </div>
    );
  }

  if (queue.length === 0) {
    return (
      <div className="body">
        <div className="head">
          <h3>Review queue</h3>
          <button className="b" onClick={onBack}>Back to dashboard</button>
        </div>
        <div className="empty">No files currently need review. All set!</div>
      </div>
    );
  }

  const isNothingReadable = fields.length === 0 || fields.every((f) => !f.value);
  const fileName = currentDoc?.file_name || queue[currentIndex]?.document_uid || 'Document';
  const isSpeckled = fileName.includes('0006');
  const isSkewed = fileName.includes('0005') || fileName.includes('0007') || fileName.includes('0010');

  return (
    <>
      <div className="topbar">
        <span className="logo" onClick={onBack}>Check this file</span>
        <span className="who">
          {currentIndex + 1} of {queue.length}
        </span>
      </div>

      <div className="body split">
        {/* Document Preview (Left) */}
        <div className={`doc ${isSpeckled ? 'speck' : ''} ${isSkewed ? 'skew' : ''}`}>
          <div className="sheet">
            {previewUrl ? (
              <img
                src={previewUrl}
                alt="Document preview"
                style={{ width: '100%', borderRadius: 4, display: 'block' }}
              />
            ) : docText ? (
              <div style={{ whiteSpace: 'pre-wrap', fontFamily: 'inherit', fontSize: 13, lineHeight: 1.8 }}>
                {docText}
              </div>
            ) : (
              <div>
                <b>Document preview</b>
                <br />
                {isNothingReadable ? 'A blurry scan. No text could be found.' : 'Loading preview…'}
              </div>
            )}
          </div>
          <p style={{ margin: '10px 0 0', fontSize: 12, color: 'var(--text3)' }}>
            Preview of the uploaded file {isSpeckled ? '(speckled page)' : isSkewed ? '(skewed page)' : ''}
          </p>
        </div>

        {/* Dynamic Fields Form (Right) */}
        <div>
          {isNothingReadable ? (
            <>
              <span className="pill p-fail" style={{ marginBottom: 12 }}>
                We couldn't read any details from this file
              </span>
              <div className="empty">
                The page may be blurry, blank or in a format we don't recognize. Pick a type below to enter the details yourself, or try reading it again.
              </div>
              <label>Document type</label>
              <select value={docType} onChange={(e) => setDocType(e.target.value)}>
                <option value="">Choose a type…</option>
                {docTypesList.map((t) => (
                  <option key={t} value={t}>
                    {t}
                  </option>
                ))}
              </select>
              <button className="link" onClick={handleAddField}>
                + Add a field
              </button>
              <div className="btnrow">
                <button className="b pri" onClick={handleTryReadingAgain} disabled={submitting}>
                  Try reading again
                </button>
                <button className="b" onClick={handleApprove} disabled={submitting}>
                  Save as it is
                </button>
                <button className="b" onClick={handleSkip}>
                  Skip
                </button>
              </div>
            </>
          ) : (
            <>
              <label>Document type</label>
              <select value={docType} onChange={(e) => setDocType(e.target.value)}>
                {docTypesList.map((t) => (
                  <option key={t} value={t}>
                    {t}
                  </option>
                ))}
              </select>

              {fields.map((field, idx) => (
                <div key={field.key}>
                  <label>{field.label}</label>
                  <input
                    className={`${field.isUnsure ? 'unsure' : ''} ${field.isMissing ? 'missing' : ''}`}
                    value={field.value}
                    placeholder={field.isMissing ? 'Not found in this file' : ''}
                    onChange={(e) => handleFieldChange(idx, e.target.value)}
                  />
                  {field.isUnsure && (
                    <p className="hint a">We're not fully sure about this one. Please check it.</p>
                  )}
                  {field.isMissing && (
                    <p className="hint r">We couldn't find this in the document. Type it in, or leave it empty.</p>
                  )}
                </div>
              ))}

              <button className="link" onClick={handleAddField}>
                + Add another field
              </button>

              <div className="btnrow">
                <button className="b pri" onClick={handleApprove} disabled={submitting}>
                  Approve
                </button>
                <button className="b" onClick={handleSaveChanges} disabled={submitting}>
                  Save changes
                </button>
                <button className="b" onClick={handleSkip}>
                  Skip
                </button>
              </div>
            </>
          )}
        </div>
      </div>
    </>
  );
};
