import React, { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  AlertOctagon,
  AlertTriangle,
  CheckCircle2,
  FileUp,
  Link as LinkIcon,
  Loader2,
  ShieldAlert,
  UploadCloud,
  X,
} from 'lucide-react';
import { api, IngestResponse, client } from '../api/client';

interface UploadItem {
  id: string;
  file: File;
  sanitizedName: string;
  status: 'PENDING' | 'UPLOADING' | 'PROCESSING' | 'AUTO_ACCEPTED' | 'PENDING_REVIEW' | 'DUPLICATE' | 'QUARANTINED' | 'ERROR';
  progress: number;
  uid?: string;
  linkedToUid?: string;
  quarantineReason?: string;
  errorMessage?: string;
  docType?: string;
  confidence?: number;
}

export const UploadPage: React.FC = () => {
  const [items, setItems] = useState<UploadItem[]>([]);
  const [isDragging, setIsDragging] = useState(false);
  const [maxUploadMb, setMaxUploadMb] = useState<number>(200);
  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    let cancelled = false;
    async function fetchLimits() {
      try {
        const { data } = await client.GET('/api/v1/system/info');
        if (!cancelled && data) {
          const mb =
            ((data as Record<string, unknown>).max_upload_mb as number) ||
            ((data as Record<string, unknown>).max_upload_size_mb as number) ||
            200;
          setMaxUploadMb(mb);
        }
      } catch {
        // Fallback to 200 MB
      }
    }
    void fetchLimits();
    return () => { cancelled = true; };
  }, []);

  const sanitizeFileName = (name: string): string => {
    return name.replace(/[^a-zA-Z0-9._-]/g, '_');
  };

  const handleFiles = (files: FileList | null) => {
    if (!files) return;
    const newItems: UploadItem[] = [];
    const maxUploadBytes = maxUploadMb * 1024 * 1024;

    Array.from(files).forEach((file) => {
      // Validate file size against dynamic limit
      if (file.size > maxUploadBytes) {
        const fileMb = (file.size / (1024 * 1024)).toFixed(0);
        alert(`File is ${fileMb} MB. Maximum allowed is ${maxUploadMb} MB.`);
        return;
      }

      newItems.push({
        id: `${file.name}-${Date.now()}-${Math.random()}`,
        file,
        sanitizedName: sanitizeFileName(file.name),
        status: 'PENDING',
        progress: 0,
      });
    });

    setItems((prev) => [...prev, ...newItems]);
  };

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(true);
  };

  const handleDragLeave = () => {
    setIsDragging(false);
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
    handleFiles(e.dataTransfer.files);
  };

  const removeItem = (id: string) => {
    setItems((prev) => prev.filter((i) => i.id !== id));
  };

  const pollStatus = async (itemId: string, uid: string) => {
    const interval = setInterval(async () => {
      try {
        const docStatus = await api.getDocumentStatus(uid);
        if (docStatus.review_status === 'auto_accepted') {
          setItems((prev) =>
            prev.map((i) =>
              i.id === itemId
                ? { ...i, status: 'AUTO_ACCEPTED', docType: docStatus.doc_type, confidence: docStatus.confidence }
                : i
            )
          );
          clearInterval(interval);
        } else if (docStatus.review_status === 'pending_review') {
          setItems((prev) =>
            prev.map((i) =>
              i.id === itemId
                ? { ...i, status: 'PENDING_REVIEW', docType: docStatus.doc_type, confidence: docStatus.confidence }
                : i
            )
          );
          clearInterval(interval);
        } else if (docStatus.review_status === 'quarantined') {
          setItems((prev) =>
            prev.map((i) =>
              i.id === itemId
                ? { ...i, status: 'QUARANTINED', quarantineReason: docStatus.quarantine_reason || 'Security Quarantine' }
                : i
            )
          );
          clearInterval(interval);
        }
      } catch {
        // Continue polling
      }
    }, 2000);

    // Timeout after 30s
    setTimeout(() => clearInterval(interval), 30000);
  };

  const uploadAll = async () => {
    for (const item of items) {
      if (item.status !== 'PENDING') continue;

      setItems((prev) =>
        prev.map((i) => (i.id === item.id ? { ...i, status: 'UPLOADING', progress: 40 } : i))
      );

      try {
        const resp = await api.uploadSingleFile(item.file);
        
        if (resp.status === 'DUPLICATE') {
          setItems((prev) =>
            prev.map((i) =>
              i.id === item.id
                ? {
                    ...i,
                    status: 'DUPLICATE',
                    uid: resp.uid,
                    linkedToUid: resp.uid,
                    progress: 100,
                  }
                : i
            )
          );
        } else if (resp.status === 'QUARANTINED') {
          setItems((prev) =>
            prev.map((i) =>
              i.id === item.id
                ? {
                    ...i,
                    status: 'QUARANTINED',
                    uid: resp.uid,
                    quarantineReason: resp.message,
                    progress: 100,
                  }
                : i
            )
          );
        } else {
          setItems((prev) =>
            prev.map((i) =>
              i.id === item.id
                ? { ...i, status: 'PROCESSING', uid: resp.uid, progress: 80 }
                : i
            )
          );
          // Start polling status
          pollStatus(item.id, resp.uid);
        }
      } catch (err: any) {
        setItems((prev) =>
          prev.map((i) =>
            i.id === item.id
              ? { ...i, status: 'ERROR', errorMessage: err.message || 'Upload failed' }
              : i
          )
        );
      }
    }
  };

  return (
    <div className="p-8 max-w-5xl mx-auto w-full">
      <div className="mb-6">
        <h1 className="text-2xl font-bold tracking-tight text-white flex items-center gap-2.5">
          <UploadCloud className="w-6 h-6 text-sky-400" />
          Document Ingestion & Upload
        </h1>
        <p className="text-sm text-slate-400 mt-1">
          Upload documents for automated OCR, classification, PII masking, and ECM routing.
        </p>
      </div>

      {/* Drag & Drop Zone */}
      <div
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
        onClick={() => fileInputRef.current?.click()}
        className={`border-2 border-dashed rounded-2xl p-10 text-center cursor-pointer transition-all ${
          isDragging
            ? 'border-sky-400 bg-sky-950/30'
            : 'border-slate-800 bg-slate-900/60 hover:border-slate-700 hover:bg-slate-900'
        }`}
      >
        <input
          ref={fileInputRef}
          type="file"
          multiple
          onChange={(e) => handleFiles(e.target.files)}
          className="hidden"
          accept=".pdf,.png,.jpg,.jpeg,.tiff,.docx,.eml"
        />

        <div className="w-14 h-14 rounded-2xl bg-sky-600/20 border border-sky-500/30 flex items-center justify-center mx-auto mb-4 text-sky-400 shadow-lg">
          <FileUp className="w-7 h-7" />
        </div>

        <h3 className="text-base font-semibold text-slate-200">
          Click to browse or drag and drop document files
        </h3>
        <p className="text-xs text-slate-400 mt-1.5">
          Supported formats: PDF, TIFF, PNG, JPG, DOCX, EML (Up to {maxUploadMb} MB per file)
        </p>
      </div>

      {/* Upload Queue Actions */}
      {items.length > 0 && (
        <div className="mt-8">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-sm font-bold text-slate-300 uppercase tracking-wider">
              Upload Batch ({items.length} files)
            </h3>
            <button
              onClick={uploadAll}
              className="px-5 py-2 bg-sky-600 hover:bg-sky-500 text-white font-bold text-xs rounded-lg transition-colors shadow-md flex items-center gap-2"
            >
              <UploadCloud className="w-4 h-4" /> Start Ingestion
            </button>
          </div>

          <div className="space-y-3">
            {items.map((item) => (
              <div
                key={item.id}
                className="bg-slate-900 border border-slate-800 rounded-xl p-4 flex items-center justify-between gap-4 text-xs"
              >
                <div className="flex items-center gap-3 min-w-0">
                  <div className="w-8 h-8 rounded bg-slate-800 flex items-center justify-center shrink-0 text-slate-400 font-bold text-[10px]">
                    PDF
                  </div>
                  <div className="truncate">
                    <p className="font-semibold text-slate-200 truncate">{item.sanitizedName}</p>
                    <p className="text-slate-500 text-[11px] font-mono">
                      {(item.file.size / 1024).toFixed(1)} KB • {item.file.type || 'document'}
                    </p>
                  </div>
                </div>

                {/* Status Indicator */}
                <div className="flex items-center gap-3 shrink-0">
                  {item.status === 'PENDING' && (
                    <span className="text-slate-400 font-mono">Ready to upload</span>
                  )}
                  {item.status === 'UPLOADING' && (
                    <span className="text-sky-400 font-mono flex items-center gap-1.5">
                      <Loader2 className="w-3.5 h-3.5 animate-spin" /> Uploading...
                    </span>
                  )}
                  {item.status === 'PROCESSING' && (
                    <span className="text-amber-400 font-mono flex items-center gap-1.5">
                      <Loader2 className="w-3.5 h-3.5 animate-spin" /> Processing AI Pipeline...
                    </span>
                  )}
                  {item.status === 'AUTO_ACCEPTED' && (
                    <span className="text-emerald-400 font-bold flex items-center gap-1.5 bg-emerald-950/80 px-2.5 py-1 rounded border border-emerald-800/80">
                      <CheckCircle2 className="w-3.5 h-3.5" /> Auto Accepted ({item.docType})
                    </span>
                  )}
                  {item.status === 'PENDING_REVIEW' && (
                    <Link
                      to={`/review/${item.uid}`}
                      className="text-amber-300 font-bold flex items-center gap-1.5 bg-amber-950/80 px-2.5 py-1 rounded border border-amber-800/80 hover:bg-amber-900 transition-colors"
                    >
                      <AlertTriangle className="w-3.5 h-3.5 text-amber-400" /> Routed to Review
                    </Link>
                  )}
                  {item.status === 'DUPLICATE' && (
                    <div className="flex items-center gap-1.5 text-sky-300 bg-sky-950/80 px-2.5 py-1 rounded border border-sky-800">
                      <LinkIcon className="w-3.5 h-3.5 text-sky-400" />
                      <span>Duplicate Document</span>
                      {item.linkedToUid && (
                        <Link to={`/documents`} className="underline ml-1 font-mono text-[11px]">
                          View Original
                        </Link>
                      )}
                    </div>
                  )}
                  {item.status === 'QUARANTINED' && (
                    <span
                      title={item.quarantineReason}
                      className="text-rose-300 font-bold flex items-center gap-1.5 bg-rose-950/80 px-2.5 py-1 rounded border border-rose-800"
                    >
                      <ShieldAlert className="w-3.5 h-3.5 text-rose-400" /> Quarantined: {item.quarantineReason}
                    </span>
                  )}
                  {item.status === 'ERROR' && (
                    <span className="text-rose-400 font-semibold">{item.errorMessage}</span>
                  )}

                  {item.status === 'PENDING' && (
                    <button
                      onClick={() => removeItem(item.id)}
                      className="text-slate-500 hover:text-slate-300 p-1"
                    >
                      <X className="w-4 h-4" />
                    </button>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
};
