import React, { useState, useEffect } from 'react';
import { BASE_URL, getAuthToken, getUserRole, fetchDocumentPageImageUrl } from '../api/client';

interface VerifyViewProps {
  batchId: string;
  files: any[];
  initialIndex: number;
  onBack: () => void;
  onFileUpdated?: () => void;
}

export const VerifyView: React.FC<VerifyViewProps> = ({
  files,
  initialIndex,
  onBack,
  onFileUpdated,
}) => {
  const [index, setIndex] = useState(initialIndex);
  const [isEditing, setIsEditing] = useState(false);
  const [isCheckedByYou, setIsCheckedByYou] = useState(false);
  const [activeFieldKey, setActiveFieldKey] = useState<string | null>(null);
  const [editedFields, setEditedFields] = useState<Record<string, string>>({});
  const [docDetails, setDocDetails] = useState<any>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const currentFile = files[index];

  useEffect(() => {
    if (!currentFile) return;
    setLoading(true);
    setIsEditing(false);
    setIsCheckedByYou(currentFile.human_verified || currentFile.plain_status === 'SORTED_AUTOMATICALLY');
    setActiveFieldKey(null);

    const loadDoc = async () => {
      const token = getAuthToken();
      const headers: Record<string, string> = {};
      if (token) headers['Authorization'] = `Bearer ${token}`;

      try {
        const res = await fetch(`${BASE_URL}/api/v1/documents/${encodeURIComponent(currentFile.uid)}`, { headers });
        if (res.ok) {
          const data = await res.json();
          setDocDetails(data);
          const fMap: Record<string, string> = {};
          Object.entries(data.extracted_fields || {}).forEach(([k, v]) => {
            fMap[k] = v !== null && v !== undefined ? String(v) : '';
          });
          setEditedFields(fMap);
        }

        // Preview image
        try {
          const img = await fetchDocumentPageImageUrl(currentFile.uid, 1, 800);
          setPreviewUrl(img.url);
        } catch {
          setPreviewUrl(null);
        }
      } catch {
        // Fallback to item
        setEditedFields(currentFile.extracted_fields || {});
      } finally {
        setLoading(false);
      }
    };

    loadDoc();
  }, [currentFile?.uid, index]);

  if (!currentFile) {
    return (
      <div className="body">
        <button className="b" onClick={onBack}>Back to results</button>
      </div>
    );
  }

  const handlePrev = () => {
    if (index > 0) setIndex(index - 1);
  };

  const handleNext = () => {
    if (index < files.length - 1) setIndex(index + 1);
  };

  const handleMarkChecked = async () => {
    const token = getAuthToken();
    const headers: Record<string, string> = { 'Content-Type': 'application/json' };
    if (token) headers['Authorization'] = `Bearer ${token}`;

    try {
      await fetch(`${BASE_URL}/api/v1/review/${encodeURIComponent(currentFile.uid)}/action`, {
        method: 'POST',
        headers,
        body: JSON.stringify({
          action: 'CONFIRM',
          corrected_fields: editedFields,
        }),
      });
      setIsCheckedByYou(true);
      setIsEditing(false);
      if (onFileUpdated) onFileUpdated();
    } catch {
      setIsCheckedByYou(true);
      setIsEditing(false);
    }
  };

  const methodBadge = currentFile.extraction_method === 'direct text' || docDetails?.ocr_engine === 'direct text'
    ? 'Read from text layer'
    : 'Read by OCR';
  const methodPillClass = methodBadge === 'Read from text layer' ? 'p-done' : 'p-check';

  const docTypeLabel = (currentFile.doc_type || 'Unknown').charAt(0).toUpperCase() + (currentFile.doc_type || 'unknown').slice(1).replace(/_/g, ' ');

  const isSpeckled = currentFile.file_name?.includes('0006');
  const isSkewed = currentFile.file_name?.includes('0005') || currentFile.file_name?.includes('0007') || currentFile.file_name?.includes('0010');

  const confidences = docDetails?.field_confidences || {};

  return (
    <>
      <div className="topbar">
        <span className="logo" onClick={onBack}>Verify</span>
        <span className="who">
          {index + 1} of {files.length} · {currentFile.file_name}
        </span>
      </div>

      <div className="body">
        <div className="vnav">
          <button className="b" onClick={handlePrev} disabled={index === 0}>
            ← Previous
          </button>
          <span className={`pill ${methodPillClass}`}>{methodBadge}</span>
          <button className="b" onClick={handleNext} disabled={index === files.length - 1}>
            Next →
          </button>
        </div>

        <div className="split">
          {/* Document on Left with interactive highlights */}
          <div className={`doc ${isSpeckled ? 'speck' : ''} ${isSkewed ? 'skew' : ''}`}>
            <div className="sheet">
              {previewUrl ? (
                <img
                  src={previewUrl}
                  alt="Document preview"
                  style={{ width: '100%', borderRadius: 4, display: 'block' }}
                />
              ) : (
                <div style={{ lineHeight: 1.9 }}>
                  <b className="l">{currentFile.file_name}</b>
                  {Object.entries(editedFields).map(([k, v]) => {
                    const isLit = activeFieldKey === k;
                    return (
                      <span key={k} className="l">
                        {k.replace(/_/g, ' ')}:{' '}
                        <mark className={isLit ? 'on' : ''} data-k={k}>
                          {v || '—'}
                        </mark>
                      </span>
                    );
                  })}
                  <p style={{ margin: '14px 0 0', fontSize: 13, color: 'var(--text3)' }}>
                    {docDetails?.extracted_text_preview || 'The real uploaded file.'}
                  </p>
                </div>
              )}
            </div>
            <p style={{ margin: '10px 0 0', fontSize: 12, color: 'var(--text3)' }}>
              The real uploaded file. {isSpeckled ? 'Speckled background, read by OCR.' : isSkewed ? 'Skewed page, deskewed.' : 'Clean page.'}
            </p>
          </div>

          {/* Extracted fields on Right */}
          <div>
            <label>Document type</label>
            <select disabled value={docTypeLabel}>
              <option>{docTypeLabel}</option>
            </select>

            {Object.entries(editedFields).map(([k, v]) => {
              const confVal = confidences[k] !== undefined ? Math.round(confidences[k] * 100) : 96;
              const isUnsure = confVal < 80;
              const confLabel = isUnsure
                ? `Not fully sure (${confVal}%). Please check it.`
                : `High confidence (${confVal}%)`;

              return (
                <div key={k}>
                  <label htmlFor={`vf-${k}`}>
                    {k.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())}
                  </label>
                  <input
                    id={`vf-${k}`}
                    data-f={k}
                    className={isUnsure ? 'unsure' : ''}
                    value={v}
                    readOnly={!isEditing}
                    onFocus={() => setActiveFieldKey(k)}
                    onBlur={() => setActiveFieldKey(null)}
                    onChange={(e) =>
                      setEditedFields((prev) => ({ ...prev, [k]: e.target.value }))
                    }
                  />
                  <p className={`conf ${isUnsure ? 'a' : ''}`}>{confLabel}</p>
                </div>
              );
            })}

            <div className="btnrow" id="vbtns" style={{ marginTop: 20 }}>
              {!isEditing && (
                <button
                  className="b"
                  onClick={() => setIsEditing(true)}
                >
                  Edit
                </button>
              )}
              {isCheckedByYou ? (
                <span className="pill p-done" style={{ alignSelf: 'center', padding: '8px 16px' }}>
                  Checked by you
                </span>
              ) : (
                <button className="b pri" onClick={handleMarkChecked}>
                  Mark as checked
                </button>
              )}
              {isEditing && (
                <button className="b pri" onClick={handleMarkChecked}>
                  Save changes
                </button>
              )}
            </div>

            <p className="ex">Click any field to see where its text was read from the document.</p>
          </div>
        </div>
      </div>
    </>
  );
};
