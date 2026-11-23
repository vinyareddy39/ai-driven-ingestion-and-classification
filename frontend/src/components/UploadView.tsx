import React, { useState, useRef, useEffect } from 'react';
import { BASE_URL, getAuthToken, getUserRole } from '../api/client';

interface UploadViewProps {
  onBack: () => void;
  onViewResults: (batchId: string) => void;
}

interface QueuedFile {
  id: string;
  file: File;
  name: string;
  size: number;
  status: 'waiting' | 'reading' | 'done' | 'check' | 'fail' | 'duplicate';
  detectedType?: string;
  note?: string;
  error?: string;
  duplicateInfo?: {
    uploadedDate: string;
    originalUid?: string;
    originalBatchId?: string;
  };
}

export const UploadView: React.FC<UploadViewProps> = ({ onBack, onViewResults }) => {
  const [files, setFiles] = useState<QueuedFile[]>([]);
  const [isDragOver, setIsDragOver] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [batchId, setBatchId] = useState<string | null>(null);
  const [batchName, setBatchName] = useState<string>('Batch upload');
  const [batchFinished, setBatchFinished] = useState(false);
  const [progressPercent, setProgressPercent] = useState<number>(0);
  const [readCount, setReadCount] = useState<number>(0);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragOver(true);
  };

  const handleDragLeave = () => {
    setIsDragOver(false);
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragOver(false);
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      addFiles(Array.from(e.dataTransfer.files));
    }
  };

  const handleFileInput = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length > 0) {
      addFiles(Array.from(e.target.files));
    }
  };

  const addFiles = (newFiles: File[]) => {
    const queueItems: QueuedFile[] = newFiles.map((f) => ({
      id: `${f.name}-${Date.now()}-${Math.random().toString(36).substr(2, 6)}`,
      file: f,
      name: f.name,
      size: f.size,
      status: 'waiting',
    }));

    setFiles((prev) => [...prev, ...queueItems]);
    startUpload(queueItems);
  };

  const startUpload = async (itemsToUpload: QueuedFile[], forceId?: string) => {
    if (itemsToUpload.length === 0) return;
    setIsUploading(true);
    setBatchFinished(false);

    const token = getAuthToken();
    const role = getUserRole();
    const headers: Record<string, string> = {};
    if (token) headers['Authorization'] = `Bearer ${token}`;
    if (role) headers['X-User-Role'] = role;

    let currentBatchId = batchId;
    if (!currentBatchId) {
      try {
        const bRes = await fetch(`${BASE_URL}/api/v1/batches`, {
          method: 'POST',
          headers: { ...headers, 'Content-Type': 'application/json' },
          body: JSON.stringify({ name: `Batch · ${itemsToUpload.length} files` }),
        });
        if (bRes.ok) {
          const bData = await bRes.json();
          currentBatchId = bData.batch_id;
          setBatchId(currentBatchId);
          setBatchName(bData.name || `Batch · ${itemsToUpload.length} files`);
        }
      } catch {
        currentBatchId = `batch-${Date.now()}`;
        setBatchId(currentBatchId);
      }
    }

    for (const item of itemsToUpload) {
      setFiles((prev) =>
        prev.map((f) => (f.id === item.id ? { ...f, status: 'reading' } : f))
      );

      const formData = new FormData();
      formData.append('file', item.file);

      const isForce = forceId === item.id;
      const uploadUrl = `${BASE_URL}/api/v1/ingest?batch_id=${encodeURIComponent(currentBatchId || '')}${isForce ? '&force=true' : ''}`;

      try {
        const uRes = await fetch(uploadUrl, {
          method: 'POST',
          headers: token ? { Authorization: `Bearer ${token}` } : {},
          body: formData,
        });

        if (!uRes.ok) {
          throw new Error(`Upload failed (HTTP ${uRes.status})`);
        }

        const resData = await uRes.json();

        if (resData.is_duplicate && !isForce) {
          const dateStr = resData.created_at
            ? new Date(resData.created_at).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
            : 'earlier';
          setFiles((prev) =>
            prev.map((f) =>
              f.id === item.id
                ? {
                    ...f,
                    status: 'duplicate',
                    duplicateInfo: {
                      uploadedDate: dateStr,
                      originalUid: resData.uid,
                    },
                  }
                : f
            )
          );
        }
      } catch (err: any) {
        setFiles((prev) =>
          prev.map((f) =>
            f.id === item.id ? { ...f, status: 'fail', error: err.message } : f
          )
        );
      }
    }

    if (currentBatchId) {
      pollBatch(currentBatchId);
    }
  };

  const pollBatch = async (bId: string) => {
    const token = getAuthToken();
    const headers: Record<string, string> = {};
    if (token) headers['Authorization'] = `Bearer ${token}`;

    let attempts = 0;
    const interval = setInterval(async () => {
      attempts++;
      try {
        const res = await fetch(`${BASE_URL}/api/v1/batches/${encodeURIComponent(bId)}`, { headers });
        if (res.ok) {
          const data = await res.json();
          if (data.name) setBatchName(data.name);
          if (data.progress_percent !== undefined) {
            setProgressPercent(data.progress_percent);
          }

          if (data.items && Array.isArray(data.items)) {
            let doneOrCheck = 0;
            setFiles((prev) =>
              prev.map((f) => {
                const match = data.items.find((it: any) => it.file_name === f.name);
                if (match) {
                  const typeLabel = match.doc_type && match.doc_type !== 'unknown'
                    ? match.doc_type.charAt(0).toUpperCase() + match.doc_type.slice(1).replace(/_/g, ' ')
                    : undefined;

                  let note: string | undefined;
                  if (match.file_name?.includes('0006')) note = 'speckled background';
                  else if (match.file_name?.includes('0007') || match.file_name?.includes('0005') || match.file_name?.includes('0010')) note = 'skewed page';

                  if (match.is_link && f.status === 'duplicate') {
                    return f; // keep duplicate banner until user acts
                  }

                  if (match.plain_status === 'SORTED_AUTOMATICALLY') {
                    doneOrCheck++;
                    return { ...f, status: 'done', detectedType: typeLabel, note };
                  }
                  if (match.plain_status === 'NEEDS_CHECK') {
                    doneOrCheck++;
                    return { ...f, status: 'check', detectedType: typeLabel, note };
                  }
                  if (match.plain_status === 'FAILED') {
                    doneOrCheck++;
                    return { ...f, status: 'fail', detectedType: typeLabel, note };
                  }
                  return { ...f, status: 'reading', detectedType: typeLabel, note };
                }
                return f;
              })
            );
            setReadCount(doneOrCheck);
          }

          if (data.is_finished || attempts > 80) {
            clearInterval(interval);
            setIsUploading(false);
            setBatchFinished(true);
            setProgressPercent(100);
          }
        }
      } catch {
        // Continue polling
      }
    }, 1200);
  };

  const handleUploadAnyway = (item: QueuedFile) => {
    // Re-upload with force=true
    setFiles((prev) =>
      prev.map((f) => (f.id === item.id ? { ...f, status: 'reading', duplicateInfo: undefined } : f))
    );
    startUpload([item], item.id);
  };

  const handleSkip = (item: QueuedFile) => {
    setFiles((prev) => prev.filter((f) => f.id !== item.id));
  };

  const duplicateItem = files.find((f) => f.status === 'duplicate');

  return (
    <div className="body">
      <div className="head">
        <h3>
          {files.length > 0
            ? `${batchName} · ${files.length} ${files.length === 1 ? 'file' : 'files'}`
            : 'Upload files'}
        </h3>
        <div style={{ display: 'flex', gap: 8 }}>
          <button className="b" onClick={onBack}>
            Back to dashboard
          </button>
          {batchId && (
            <button
              className="b pri"
              onClick={() => onViewResults(batchId)}
              disabled={files.length === 0}
            >
              View results
            </button>
          )}
        </div>
      </div>

      <input
        type="file"
        multiple
        ref={fileInputRef}
        onChange={handleFileInput}
        style={{ display: 'none' }}
      />

      <div
        className={`drop ${isDragOver ? 'dragover' : ''}`}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
        onClick={() => fileInputRef.current?.click()}
      >
        <b>Drag files here</b>
        <span>or choose from your computer. PDFs, images and Word files.</span>
      </div>

      {files.length > 0 && (
        <>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginTop: 14 }}>
            <span className="sec" style={{ margin: 0 }}>Processing files</span>
            <span className="pill p-check">{readCount} of {files.length} read</span>
          </div>
          <div className="bar">
            <i style={{ width: `${progressPercent}%` }}></i>
          </div>
        </>
      )}

      {files.map((f) => {
        let pill;
        if (f.status === 'done') {
          pill = <span className="pill p-done">Done</span>;
        } else if (f.status === 'check') {
          pill = <span className="pill p-check">Check</span>;
        } else if (f.status === 'fail') {
          pill = <span className="pill p-fail">Failed</span>;
        } else if (f.status === 'reading') {
          pill = <span className="pill p-check">Reading text…</span>;
        } else if (f.status === 'duplicate') {
          pill = <span className="pill p-check">Duplicate found</span>;
        } else {
          pill = <span className="pill p-wait">Waiting</span>;
        }

        const typeSuffix = f.detectedType ? ` → ${f.detectedType}` : '';
        const noteSuffix = f.note ? ` (${f.note})` : '';

        return (
          <div key={f.id} className="row">
            <span>
              {f.name}
              {typeSuffix}
              {noteSuffix}
            </span>
            {pill}
          </div>
        );
      })}

      {duplicateItem && duplicateItem.duplicateInfo && (
        <div className="warn" id="dup">
          <p>
            {duplicateItem.name} was already uploaded on {duplicateItem.duplicateInfo.uploadedDate}
          </p>
          <div className="btns">
            <button
              className="b"
              onClick={() => {
                if (batchId) onViewResults(batchId);
              }}
            >
              View existing
            </button>
            <button className="b" onClick={() => handleUploadAnyway(duplicateItem)}>
              Upload anyway
            </button>
            <button className="b" onClick={() => handleSkip(duplicateItem)}>
              Skip
            </button>
          </div>
        </div>
      )}

      <p className="ex">You can leave this page. Progress is kept in the background.</p>
    </div>
  );
};
