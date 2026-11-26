import React, { useEffect, useRef, useState } from 'react';
import { api, pingBackendWithColdStartRetry, BatchItem, FieldItem, FileItem, TableItem, User } from './api/client';

type ViewMode = 'auth' | 'dash' | 'proc' | 'results' | 'view';

interface StagedFile {
  id: string;
  file: File;
  relativePath: string;
  folder: string;
}

interface SkippedFile {
  name: string;
  relativePath: string;
  reason: string;
}

const STRUCTURE_TYPES = [
  { value: 'label_value_pair', label: 'Label-Value' },
  { value: 'form_row', label: 'Form Row' },
  { value: 'heading', label: 'Heading' },
  { value: 'paragraph', label: 'Paragraph' },
  { value: 'table', label: 'Table' },
  { value: 'list', label: 'List' },
  { value: 'checkbox_group', label: 'Checkbox/Radio' },
  { value: 'signature_stamp', label: 'Signature/Stamp' },
  { value: 'handwriting', label: 'Handwriting' },
  { value: 'image_logo', label: 'Image/Logo' },
  { value: 'chart_diagram', label: 'Chart/Diagram' },
  { value: 'barcode_qr', label: 'Barcode/QR' },
  { value: 'header_footer', label: 'Header/Footer' },
  { value: 'footnote', label: 'Footnote' },
  { value: 'watermark', label: 'Watermark' },
  { value: 'side_by_side', label: 'Side-by-Side' },
  { value: 'other', label: 'Other' },
];

export default function App() {
  const [user, setUser] = useState<User | null>(null);
  const [view, setView] = useState<ViewMode>('auth');
  const [authMode, setAuthMode] = useState<'in' | 'reg'>('in');
  const [authName, setAuthName] = useState('');
  const [authEmail, setAuthEmail] = useState('');
  const [authPassword, setAuthPassword] = useState('');
  const [authError, setAuthError] = useState('');
  const [authSuccess, setAuthSuccess] = useState('');

  // Batches & Processing
  const [currentBatchId, setCurrentBatchId] = useState<string | null>(null);
  const [batch, setBatch] = useState<BatchItem | null>(null);
  const [pastBatches, setPastBatches] = useState<any[]>([]);
  const [isUploading, setIsUploading] = useState(false);
  const [isDragOver, setIsDragOver] = useState(false);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  // View / Edit Screen
  const [activeFileIndex, setActiveFileIndex] = useState(0);
  const [draftFields, setDraftFields] = useState<FieldItem[]>([]);
  const [draftTables, setDraftTables] = useState<TableItem[]>([]);
  const [savedToast, setSavedToast] = useState('');
  const [highlightedBbox, setHighlightedBbox] = useState<number[] | null>(null);
  const [activeDetailIdx, setActiveDetailIdx] = useState<number | null>(null);
  const [unlockPassword, setUnlockPassword] = useState('');
  const [unlockError, setUnlockError] = useState('');
  const [isUnlocking, setIsUnlocking] = useState(false);
  const [zoomLevel, setZoomLevel] = useState(1.0);
  const [labelSuggestions, setLabelSuggestions] = useState<string[]>([]);
  const [activeTab, setActiveTab] = useState<'details' | 'raw_text'>('details');
  const [showMoreDetails, setShowMoreDetails] = useState(false);
  const [workerStatus, setWorkerStatus] = useState<string>('Ready');
  const [isWakingUp, setIsWakingUp] = useState(false);
  const [wakingElapsed, setWakingElapsed] = useState(0);
  const [isExportingAccount, setIsExportingAccount] = useState(false);

  // Staged Files & Folder Upload Preview
  const [stagedFiles, setStagedFiles] = useState<StagedFile[]>([]);
  const [skippedFiles, setSkippedFiles] = useState<SkippedFile[]>([]);
  const [showPreview, setShowPreview] = useState(false);
  const [uploadProgress, setUploadProgress] = useState<{ current: number; total: number } | null>(null);
  const [folderFilter, setFolderFilter] = useState('');
  const folderInputRef = useRef<HTMLInputElement | null>(null);

  // Initial auth check, cold start wake-up, & worker health check
  useEffect(() => {
    let isMounted = true;

    const initApp = async () => {
      // Check backend availability with friendly cold-start wake-up message
      await pingBackendWithColdStartRetry((waking, elapsed) => {
        if (isMounted) {
          setIsWakingUp(waking);
          setWakingElapsed(elapsed);
        }
      });

      if (!isMounted) return;
      setIsWakingUp(false);

      api.getWorkerHealth().then((h) => {
        if (isMounted) setWorkerStatus(h.status === 'healthy' ? 'Ready' : 'Degraded');
      }).catch(() => {
        if (isMounted) setWorkerStatus('Offline');
      });

      const token = localStorage.getItem('token');
      if (token) {
        api
          .getMe()
          .then((u) => {
            if (!isMounted) return;
            if (u) {
              setUser(u);
              setView('dash');
              loadPastBatches();
            } else {
              setUser(null);
              setView('auth');
            }
          })
          .catch(() => {
            if (!isMounted) return;
            setUser(null);
            setView('auth');
          });
      } else {
        if (!isMounted) return;
        setUser(null);
        setView('auth');
      }
    };

    initApp();
    return () => {
      isMounted = false;
    };
  }, []);

  const handleExportAccount = async () => {
    try {
      setIsExportingAccount(true);
      const blob = await api.exportAccountData();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `account_backup_${new Date().toISOString().replace(/[:.]/g, '-')}.zip`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.URL.revokeObjectURL(url);
    } catch (err: any) {
      alert(`Account export failed: ${err.message || 'Unknown error'}`);
    } finally {
      setIsExportingAccount(false);
    }
  };

  const loadPastBatches = async () => {
    try {
      const list = await api.listBatches();
      setPastBatches(list);
    } catch {
      // Ignored
    }
  };

  // Polling during processing
  useEffect(() => {
    if (view !== 'proc' || !currentBatchId) return;

    let isMounted = true;
    const interval = setInterval(async () => {
      try {
        const b = await api.getBatch(currentBatchId);
        if (!isMounted) return;
        setBatch(b);

        // Check if all files are Done or Failed
        const allFinished =
          b.files.length > 0 &&
          b.files.every((f) => f.stage === 'Done' || f.stage === 'Failed');
        if (allFinished) {
          clearInterval(interval);
          setTimeout(() => {
            if (isMounted) setView('results');
          }, 800);
        }
      } catch (err: any) {
        if (err?.status === 404 || err?.message?.includes('404')) {
          clearInterval(interval);
          setBatch(null);
          setCurrentBatchId(null);
          setView('dash');
          return;
        }
      }
    }, 1000);

    return () => {
      isMounted = false;
      clearInterval(interval);
    };
  }, [view, currentBatchId]);

  // Auth Handlers
  const handleAuthSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setAuthError('');
    setAuthSuccess('');

    const email = authEmail.trim();
    const pw = authPassword;

    if (authMode === 'reg' && !authName.trim()) {
      setAuthError('Enter your name.');
      return;
    }
    if (!/^\S+@\S+\.\S+$/.test(email)) {
      setAuthError('Enter a valid email address.');
      return;
    }
    if (pw.length < 6) {
      setAuthError('Password needs at least 6 characters.');
      return;
    }

    try {
      if (authMode === 'reg') {
        await api.register(authName, email, pw);
        setAuthMode('in');
        setAuthSuccess('Registered. Now sign in.');
        setAuthPassword('');
      } else {
        const res = await api.login(email, pw);
        setUser(res.user);
        setView('dash');
        loadPastBatches();
      }
    } catch (err: any) {
      setAuthError(err.message || 'Authentication failed');
    }
  };

  const handleLogout = async () => {
    await api.logout();
    setUser(null);
    setBatch(null);
    setCurrentBatchId(null);
    setDraftFields([]);
    setDraftTables([]);
    setView('auth');
  };

  // Supported File Extensions: Accept PDF, PNG, JPG and JPEG. Skip everything else.
  const SUPPORTED_EXTS = ['.pdf', '.png', '.jpg', '.jpeg'];

  // Recursive folder traversal via webkitGetAsEntry
  const traverseFileSystemEntry = async (
    entry: any,
    parentPath: string = ''
  ): Promise<{ file: File; relativePath: string }[]> => {
    const results: { file: File; relativePath: string }[] = [];
    if (!entry) return results;

    if (entry.isFile) {
      const file = await new Promise<File>((resolve, reject) => {
        entry.file(resolve, reject);
      });
      const relativePath = parentPath ? `${parentPath}/${file.name}` : file.name;
      results.push({ file, relativePath });
    } else if (entry.isDirectory) {
      const currentPath = parentPath ? `${parentPath}/${entry.name}` : entry.name;
      const dirReader = entry.createReader();

      // Read entries in batches until empty
      const readAllEntries = async (): Promise<any[]> => {
        const all: any[] = [];
        while (true) {
          const batch = await new Promise<any[]>((resolve, reject) => {
            dirReader.readEntries(resolve, reject);
          });
          if (!batch || batch.length === 0) break;
          all.push(...batch);
        }
        return all;
      };

      try {
        const entries = await readAllEntries();
        for (const child of entries) {
          const subResults = await traverseFileSystemEntry(child, currentPath);
          results.push(...subResults);
        }
      } catch (err) {
        console.warn('Error reading directory entry:', err);
      }
    }

    return results;
  };

  const processStagedFiles = (items: { file: File; relativePath: string }[]) => {
    const valid: StagedFile[] = [];
    const skipped: SkippedFile[] = [];

    items.forEach((item, idx) => {
      const name = item.file.name;
      const ext = '.' + name.split('.').pop()?.toLowerCase();
      // Skip hidden files, system files, or unsupported formats
      if (
        name.startsWith('.') ||
        name.toLowerCase() === 'thumbs.db' ||
        name.toLowerCase() === 'desktop.ini' ||
        !SUPPORTED_EXTS.includes(ext)
      ) {
        skipped.push({
          name: name,
          relativePath: item.relativePath,
          reason: !SUPPORTED_EXTS.includes(ext) ? 'not supported' : 'system/hidden file',
        });
      } else {
        const folder = item.relativePath.includes('/')
          ? item.relativePath.substring(0, item.relativePath.lastIndexOf('/'))
          : 'Root / No folder';
        valid.push({
          id: `${item.relativePath}_${idx}_${Date.now()}_${Math.random()}`,
          file: item.file,
          relativePath: item.relativePath,
          folder: folder,
        });
      }
    });

    if (valid.length === 0 && skipped.length === 0) return;

    setStagedFiles((prev) => [...prev, ...valid]);
    setSkippedFiles((prev) => [...prev, ...skipped]);
    setShowPreview(true);
  };

  const removeStagedFile = (id: string) => {
    setStagedFiles((prev) => prev.filter((f) => f.id !== id));
  };

  const removeStagedFolder = (folderName: string) => {
    setStagedFiles((prev) => prev.filter((f) => f.folder !== folderName));
  };

  const clearStagedFiles = () => {
    setStagedFiles([]);
    setSkippedFiles([]);
    setShowPreview(false);
  };

  const handleStartReading = async () => {
    if (stagedFiles.length === 0) return;
    setIsUploading(true);
    setUploadProgress({ current: 0, total: stagedFiles.length });

    try {
      const batchName = `Batch · ${stagedFiles.length} files`;
      const batchRes = await api.initBatch(batchName);
      const batchId = batchRes.id;
      setCurrentBatchId(batchId);

      // Upload in chunks of 5 with retry
      const CHUNK_SIZE = 5;
      let uploadedCount = 0;

      for (let i = 0; i < stagedFiles.length; i += CHUNK_SIZE) {
        const chunk = stagedFiles.slice(i, i + CHUNK_SIZE);
        const chunkFiles = chunk.map((c) => c.file);
        const chunkPaths = chunk.map((c) => c.relativePath);

        await api.appendBatchFiles(batchId, chunkFiles, chunkPaths);
        uploadedCount += chunk.length;
        setUploadProgress({ current: uploadedCount, total: stagedFiles.length });
      }

      await api.startBatch(batchId);
      const initialBatch = await api.getBatch(batchId);
      setBatch(initialBatch);
      clearStagedFiles();
      setView('proc');
    } catch (err: any) {
      alert(err.message || 'Upload failed');
    } finally {
      setIsUploading(false);
      setUploadProgress(null);
    }
  };

  // Open an existing batch from history
  const openBatch = async (batchId: string) => {
    try {
      const b = await api.getBatch(batchId);
      setBatch(b);
      setCurrentBatchId(b.id);
      const allFinished =
        b.files.length > 0 &&
        b.files.every((f) => f.stage === 'Done' || f.stage === 'Failed');
      setView(allFinished ? 'results' : 'proc');
    } catch (err: any) {
      alert(`Could not open batch: ${err.message}`);
    }
  };

  const fetchSuggestions = (docType?: string) => {
    api.getLabelSuggestions(docType).then((sugs) => {
      if (Array.isArray(sugs) && sugs.length > 0) {
        setLabelSuggestions(sugs);
      }
    }).catch(() => {});
  };

  // Open View Screen
  const openView = (index: number) => {
    if (!batch || !batch.files[index]) return;
    setActiveFileIndex(index);
    const f = batch.files[index];
    const mapped = f.fields.map((x) => ({
      ...x,
      orig_label: x.orig_label !== undefined ? x.orig_label : x.label,
      orig: x.orig !== undefined ? x.orig : x.value,
      is_edited: Boolean(x.is_edited || x.src === 'edited'),
    }));
    mapped.sort((a, b) => {
      const aEmpty = !a.label || !a.label.trim();
      const bEmpty = !b.label || !b.label.trim();
      if (aEmpty !== bEmpty) return aEmpty ? 1 : -1;
      return (a.page || 1) - (b.page || 1);
    });
    setDraftFields(mapped);
    setDraftTables(f.tables ? JSON.parse(JSON.stringify(f.tables)) : []);
    fetchSuggestions(f.type);
    setSavedToast('');
    setHighlightedBbox(null);
    setActiveDetailIdx(null);
    setUnlockPassword('');
    setUnlockError('');
    setView('view');
  };

  const handleDetailClick = (idx: number, bbox?: number[] | null) => {
    setActiveDetailIdx(idx);
    if (bbox && Array.isArray(bbox) && bbox.length === 4) {
      setHighlightedBbox(bbox);
    } else {
      setHighlightedBbox(null);
    }
  };

  const handleUnlockFile = async (fileId: string) => {
    if (!unlockPassword) return;
    setIsUnlocking(true);
    setUnlockError('');
    try {
      await api.unlockFile(fileId, unlockPassword);
      if (currentBatchId) {
        const refreshed = await api.getBatch(currentBatchId);
        setBatch(refreshed);
        const f = refreshed.files[activeFileIndex];
        if (f) {
          const mapped = f.fields.map((x) => ({
            ...x,
            orig_label: x.orig_label !== undefined ? x.orig_label : x.label,
            orig: x.orig !== undefined ? x.orig : x.value,
            is_edited: Boolean(x.is_edited || x.src === 'edited'),
          }));
          mapped.sort((a, b) => {
            const aEmpty = !a.label || !a.label.trim();
            const bEmpty = !b.label || !b.label.trim();
            if (aEmpty !== bEmpty) return aEmpty ? 1 : -1;
            return (a.page || 1) - (b.page || 1);
          });
          setDraftFields(mapped);
          setDraftTables(f.tables ? JSON.parse(JSON.stringify(f.tables)) : []);
        }
      }
      setUnlockPassword('');
    } catch (err: any) {
      setUnlockError(err.message || 'Incorrect password.');
    } finally {
      setIsUnlocking(false);
    }
  };

  // View Screen Field operations
  const updateDraft = (i: number, key: 'label' | 'value', val: string) => {
    setDraftFields((prev) => {
      const copy = [...prev];
      const item = { ...copy[i], [key]: val };
      const origVal = item.orig !== undefined ? item.orig : item.value;
      const origLbl = item.orig_label !== undefined ? item.orig_label : item.label;
      if (item.src !== 'added') {
        if (item.value !== origVal || item.label !== origLbl) {
          item.src = 'edited';
          item.is_edited = true;
        } else {
          item.src = 'read';
          item.is_edited = false;
        }
      }
      copy[i] = item;
      return copy;
    });
    setSavedToast('');
  };

  const removeDraftRow = (i: number) => {
    setDraftFields((prev) => prev.filter((_, idx) => idx !== i));
    setSavedToast('');
  };

  const addDetailRow = () => {
    setDraftFields((prev) => [
      ...prev,
      { label: '', orig_label: '', value: '', orig: '', conf: 1.0, src: 'added', is_edited: false },
    ]);
    setSavedToast('');
  };

  const handleAcceptSuggestion = (i: number) => {
    setDraftFields((prev) => {
      const copy = [...prev];
      if (!copy[i]) return prev;
      const item = { ...copy[i] };
      item.label = item.suggested_label || item.label;
      item.src = 'verified';
      item.is_edited = true;
      copy[i] = item;
      return copy;
    });
    setSavedToast('Suggestion accepted as verified.');
    setTimeout(() => setSavedToast(''), 3000);
  };

  const handleSelectAlternative = (i: number, altLabel: string) => {
    setDraftFields((prev) => {
      const copy = [...prev];
      if (!copy[i]) return prev;
      const item = { ...copy[i] };
      item.label = altLabel;
      item.src = 'verified';
      item.is_edited = true;
      copy[i] = item;
      return copy;
    });
    setSavedToast(`Selected alternative label: ${altLabel}`);
    setTimeout(() => setSavedToast(''), 3000);
  };

  const handleAcceptAllSuggestions = async (fileId: string) => {
    try {
      await api.acceptAllSuggestions(fileId);
      setDraftFields((prev) =>
        prev.map((item) =>
          item.suggested_label || item.src === 'generated'
            ? {
                ...item,
                label: item.suggested_label || item.label,
                src: 'verified',
                is_edited: true,
              }
            : item
        )
      );
      setSavedToast('All suggestions accepted as verified.');
      setTimeout(() => setSavedToast(''), 3000);
    } catch (err: any) {
      alert(err.message || 'Failed to accept suggestions');
    }
  };

  const handlePromoteDetail = async (fileId: string, fieldId?: string, i?: number) => {
    if (!fieldId) return;
    try {
      await api.promoteDetail(fileId, fieldId);
      setDraftFields((prev) => {
        const copy = [...prev];
        if (i !== undefined && copy[i]) {
          copy[i] = { ...copy[i], is_promoted: true, in_more_details: false };
        }
        return copy;
      });
      setSavedToast('Detail promoted to key details.');
      setTimeout(() => setSavedToast(''), 3000);
    } catch (err: any) {
      alert(err.message || 'Failed to promote detail');
    }
  };

  const handleAcceptSplit = async (fileId: string, fieldId?: string, i?: number) => {
    if (!fieldId) return;
    try {
      await api.acceptSplit(fileId, fieldId);
      if (currentBatchId) {
        const refreshed = await api.getBatch(currentBatchId);
        setBatch(refreshed);
        const f = refreshed.files[activeFileIndex];
        if (f) {
          setDraftFields(f.fields.map((x) => ({ ...x })));
        }
      }
      setSavedToast('Split suggestion accepted.');
      setTimeout(() => setSavedToast(''), 3000);
    } catch (err: any) {
      alert(err.message || 'Failed to accept split');
    }
  };

  const handleDismissSplit = (i: number) => {
    setDraftFields((prev) => {
      const copy = [...prev];
      if (copy[i]) copy[i] = { ...copy[i], split_suggestion: null };
      return copy;
    });
  };

  const handleReclassifyRegion = async (fileId: string, regionId: string, newType: string, fieldIdx?: number) => {
    try {
      await api.reclassifyRegion(fileId, regionId, newType);
      const GROUP_MAP: Record<string, string> = {
        label_value_pair: 'fields', form_row: 'fields', heading: 'fields',
        paragraph: 'fields', footnote: 'fields', header_footer: 'fields',
        watermark: 'fields', side_by_side: 'fields', other: 'fields',
        table: 'tables', list: 'lists', checkbox_group: 'checkboxes',
        signature_stamp: 'signatures_and_stamps', handwriting: 'signatures_and_stamps',
        image_logo: 'images_and_charts', chart_diagram: 'images_and_charts',
        barcode_qr: 'codes',
      };
      setDraftFields((prev) =>
        prev.map((item, idx) => {
          if (item.region_id === regionId || (fieldIdx !== undefined && idx === fieldIdx)) {
            return {
              ...item,
              structure_type: newType,
              structure_group: GROUP_MAP[newType] || 'fields',
              structure_confidence: 1.0,
              src: 'edited',
              is_edited: true,
            };
          }
          return item;
        })
      );
      setSavedToast(`Reclassified region to ${newType}. Correction stored.`);
      setTimeout(() => setSavedToast(''), 3500);
    } catch (err: any) {
      setSavedToast(`Reclassification failed: ${err.message}`);
      setTimeout(() => setSavedToast(''), 3500);
    }
  };

  const handleBulkVerifyClean = async (batchId: string) => {
    try {
      const res = await api.bulkVerifyClean(batchId);
      const refreshed = await api.getBatch(batchId);
      setBatch(refreshed);
      setSavedToast(`Bulk verified ${res.verified_count} clean documents.`);
      setTimeout(() => setSavedToast(''), 4000);
    } catch (err: any) {
      alert(err.message || 'Bulk verify failed');
    }
  };

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (view !== 'view' || !batch) return;
      const target = e.target as HTMLElement | null;
      const tagName = target?.tagName?.toLowerCase();
      const isInput = tagName === 'input' || tagName === 'textarea' || target?.isContentEditable;

      if (!isInput) {
        if (e.key === '[') {
          e.preventDefault();
          if (activeFileIndex > 0) navFile(activeFileIndex - 1);
        } else if (e.key === ']') {
          e.preventDefault();
          if (activeFileIndex < batch.files.length - 1) navFile(activeFileIndex + 1);
        } else if (e.key === 'Delete' && activeDetailIdx !== null) {
          e.preventDefault();
          removeDraftRow(activeDetailIdx);
        }
      } else if (e.key === 'Enter' && activeDetailIdx !== null) {
        const cur = draftFields[activeDetailIdx];
        if (cur && (cur.suggested_label || cur.src === 'generated')) {
          handleAcceptSuggestion(activeDetailIdx);
        }
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [view, batch, activeFileIndex, activeDetailIdx, draftFields]);

  const saveChanges = async () => {
    if (!batch || !batch.files[activeFileIndex]) return;
    const file = batch.files[activeFileIndex];

    const cleanFields = draftFields.filter(
      (x) => x.label.trim() || x.value.trim()
    );

    // Prevent duplicate labels in one document unless defined as a list
    const seen = new Set<string>();
    const listAllowed = new Set(['line_items', 'items', 'notes', 'entries', 'diagnoses', 'medications', 'procedures']);
    for (const item of cleanFields) {
      const lbl = item.label.trim().toLowerCase();
      if (!lbl) continue;
      const isList = lbl.endsWith('[]') || lbl.endsWith('_list') || listAllowed.has(lbl);
      if (!isList && seen.has(lbl)) {
        alert(`Duplicate label "${item.label.trim()}" is not allowed in this document unless defined as a list.`);
        return;
      }
      seen.add(lbl);
    }

    // Sort: labelled rows first, unlabelled rows below
    cleanFields.sort((a, b) => {
      const aEmpty = !a.label || !a.label.trim();
      const bEmpty = !b.label || !b.label.trim();
      if (aEmpty !== bEmpty) return aEmpty ? 1 : -1;
      return (a.page || 1) - (b.page || 1);
    });

    const updated = cleanFields.map((x) => {
      const orig = x.orig !== undefined ? x.orig : x.value;
      const orig_label = x.orig_label !== undefined ? x.orig_label : x.label;
      let src = x.src || 'read';
      let is_edited = Boolean(x.is_edited);
      if (src !== 'added') {
        if (x.value !== orig || x.label !== orig_label) {
          src = 'edited';
          is_edited = true;
        } else if (src === 'edited' && x.value === orig && x.label === orig_label) {
          src = 'read';
          is_edited = false;
        }
      }
      return { ...x, orig, orig_label, src, is_edited };
    });

    try {
      const res = await api.updateFields(file.id, updated);
      if (draftTables) {
        await api.updateTables(file.id, draftTables);
      }
      // Refresh batch data
      const refreshedBatch = await api.getBatch(batch.id);
      setBatch(refreshedBatch);
      setDraftFields(updated);
      fetchSuggestions(file.type);
      const timeStr = new Date().toLocaleTimeString([], {
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
      });
      setSavedToast(`Saved at ${timeStr}. It stays after a refresh.`);
    } catch (err: any) {
      alert(`Save error: ${err.message}`);
    }
  };

  // Navigate between files in view screen
  const navFile = (newIdx: number) => {
    if (!batch || newIdx < 0 || newIdx >= batch.files.length) return;
    setActiveFileIndex(newIdx);
    const f = batch.files[newIdx];
    const mapped = f.fields.map((x) => ({
      ...x,
      orig_label: x.orig_label !== undefined ? x.orig_label : x.label,
      orig: x.orig !== undefined ? x.orig : x.value,
      is_edited: Boolean(x.is_edited || x.src === 'edited'),
    }));
    mapped.sort((a, b) => {
      const aEmpty = !a.label || !a.label.trim();
      const bEmpty = !b.label || !b.label.trim();
      if (aEmpty !== bEmpty) return aEmpty ? 1 : -1;
      return (a.page || 1) - (b.page || 1);
    });
    setDraftFields(mapped);
    setDraftTables(f.tables ? JSON.parse(JSON.stringify(f.tables)) : []);
    fetchSuggestions(f.type);
    setSavedToast('');
  };

  // Table manipulation functions
  const updateTableHeader = (tableIdx: number, headerIdx: number, newHeader: string) => {
    setDraftTables((prev) => {
      const copy = JSON.parse(JSON.stringify(prev));
      const tbl = copy[tableIdx];
      if (!tbl) return prev;
      const oldHeader = tbl.headers[headerIdx];
      tbl.headers[headerIdx] = newHeader;
      for (const row of tbl.rows) {
        if (oldHeader in row) {
          row[newHeader] = row[oldHeader];
          delete row[oldHeader];
        }
      }
      return copy;
    });
    setSavedToast('');
  };

  const updateTableCell = (tableIdx: number, rowIdx: number, header: string, value: string) => {
    setDraftTables((prev) => {
      const copy = JSON.parse(JSON.stringify(prev));
      const tbl = copy[tableIdx];
      if (!tbl || !tbl.rows[rowIdx]) return prev;
      tbl.rows[rowIdx][header] = value;
      return copy;
    });
    setSavedToast('');
  };

  const addTableRow = (tableIdx: number) => {
    setDraftTables((prev) => {
      const copy = JSON.parse(JSON.stringify(prev));
      const tbl = copy[tableIdx];
      if (!tbl) return prev;
      const newRow: Record<string, string> = {};
      for (const h of tbl.headers) {
        newRow[h] = '';
      }
      tbl.rows.push(newRow);
      return copy;
    });
    setSavedToast('');
  };

  const removeTableRow = (tableIdx: number, rowIdx: number) => {
    setDraftTables((prev) => {
      const copy = JSON.parse(JSON.stringify(prev));
      const tbl = copy[tableIdx];
      if (!tbl) return prev;
      tbl.rows.splice(rowIdx, 1);
      return copy;
    });
    setSavedToast('');
  };

  const addTableColumn = (tableIdx: number) => {
    const colName = prompt('Enter new column name:');
    if (!colName || !colName.trim()) return;
    const cleanName = colName.trim();
    setDraftTables((prev) => {
      const copy = JSON.parse(JSON.stringify(prev));
      const tbl = copy[tableIdx];
      if (!tbl) return prev;
      if (!tbl.headers.includes(cleanName)) {
        tbl.headers.push(cleanName);
        for (const row of tbl.rows) {
          row[cleanName] = '';
        }
      }
      return copy;
    });
    setSavedToast('');
  };

  const removeTableColumn = (tableIdx: number, headerIdx: number) => {
    setDraftTables((prev) => {
      const copy = JSON.parse(JSON.stringify(prev));
      const tbl = copy[tableIdx];
      if (!tbl) return prev;
      const headerToRemove = tbl.headers[headerIdx];
      tbl.headers.splice(headerIdx, 1);
      for (const row of tbl.rows) {
        delete row[headerToRemove];
      }
      return copy;
    });
    setSavedToast('');
  };

  const handleClearBatch = async () => {
    if (currentBatchId) {
      try {
        await api.deleteBatch(currentBatchId);
      } catch (err) {
        console.error('Delete error:', err);
      }
    }
    setBatch(null);
    setCurrentBatchId(null);
    loadPastBatches();
    setView('dash');
  };

  // Re-run scanning / extraction ("Do again")
  const handleDoAgain = async (fileId: string) => {
    try {
      await api.retryFile(fileId);
      // Immediately refresh batch to show updated result in UI
      if (currentBatchId) {
        const b = await api.getBatch(currentBatchId);
        setBatch(b);
        const allFinished =
          b.files.length > 0 &&
          b.files.every((f) => f.stage === 'Done' || f.stage === 'Failed');
        setView(allFinished ? 'results' : 'proc');
      }
    } catch (err: any) {
      alert(`Could not retry extraction: ${err.message}`);
    }
  };

  const handleDoAllAgain = async () => {
    if (!currentBatchId) return;
    try {
      await api.retryBatchRateLimited(currentBatchId);
      setView('proc');
    } catch (err: any) {
      alert(`Could not retry rate-limited files: ${err.message}`);
    }
  };

  // Step indicator rendering
  const stepNames: Record<ViewMode, string> = {
    auth: '1 Sign in',
    dash: '2 Upload',
    proc: '3 Reading',
    results: '4 Results',
    view: '5 Check and edit',
  };

  return (
    <div className="wrap">
      {/* Cold start waking up alert banner */}
      {isWakingUp && (
        <div
          id="cold-start-banner"
          style={{
            backgroundColor: '#fef3c7',
            borderBottom: '1px solid #fcd34d',
            color: '#92400e',
            padding: '10px 16px',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            fontSize: '13px',
            fontWeight: 500,
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <span style={{ fontSize: '16px' }}>⏳</span>
            <span>
              <strong>Waking up the server...</strong> Free tier instances sleep after 15 minutes of inactivity. Connecting now ({wakingElapsed}s / ~60s)...
            </span>
          </div>
          <span style={{ fontSize: '11px', color: '#b45309' }}>Retrying automatically</span>
        </div>
      )}

      {/* Header bar matching demo */}
      <header className="bar">
        <b>Document Reader</b>
        <span className="sp"></span>
        <span
          className="worker-status-badge"
          title="Background worker and pipeline engine status"
          style={{
            fontSize: '12px',
            display: 'inline-flex',
            alignItems: 'center',
            gap: '6px',
            marginRight: '16px',
            padding: '2px 8px',
            borderRadius: '12px',
            backgroundColor: workerStatus === 'Ready' ? '#ecfdf5' : '#fffbeb',
            color: workerStatus === 'Ready' ? '#047857' : '#b45309',
            border: `1px solid ${workerStatus === 'Ready' ? '#a7f3d0' : '#fde68a'}`,
            fontWeight: 500,
          }}
        >
          <span
            style={{
              width: '7px',
              height: '7px',
              borderRadius: '50%',
              backgroundColor: workerStatus === 'Ready' ? '#10b981' : '#f59e0b',
            }}
          />
          Worker: {workerStatus}
        </span>
        <span className="who">{user ? user.email : ''}</span>
        {user && (
          <button id="out" onClick={handleLogout}>
            Sign out
          </button>
        )}
      </header>

      {/* Step indicator matching demo */}
      <ol className="steps">
        {(Object.keys(stepNames) as ViewMode[]).map((k) => (
          <li key={k} className={view === k ? 'on' : ''}>
            {stepNames[k]}
          </li>
        ))}
      </ol>

      <main id="main">
        {/* 1. AUTH SCREEN */}
        {view === 'auth' && (
          <div className="card auth">
            <h1>{authMode === 'reg' ? 'Create your account' : 'Sign in'}</h1>
            <p className="sub">
              {authMode === 'reg'
                ? 'Register once, then sign in.'
                : 'Sign in to upload and check documents.'}
            </p>
            <form onSubmit={handleAuthSubmit}>
              {authMode === 'reg' && (
                <>
                  <label className="f" htmlFor="nm">
                    Name
                  </label>
                  <input
                    id="nm"
                    autoComplete="name"
                    value={authName}
                    onChange={(e) => setAuthName(e.target.value)}
                  />
                </>
              )}
              <label className="f" htmlFor="em">
                Email
              </label>
              <input
                id="em"
                type="email"
                autoComplete="email"
                value={authEmail}
                onChange={(e) => setAuthEmail(e.target.value)}
              />
              <label className="f" htmlFor="pw">
                Password
              </label>
              <input
                id="pw"
                type="password"
                autoComplete={
                  authMode === 'reg' ? 'new-password' : 'current-password'
                }
                value={authPassword}
                onChange={(e) => setAuthPassword(e.target.value)}
              />
              {authError && <div className="err">{authError}</div>}
              {authSuccess && (
                <div className="err" style={{ color: 'var(--ok-fg)' }}>
                  {authSuccess}
                </div>
              )}
              <button
                className="pri"
                style={{ width: '100%', marginTop: '6px' }}
                type="submit"
              >
                {authMode === 'reg' ? 'Register' : 'Sign in'}
              </button>
            </form>
            <p className="sub" style={{ margin: '14px 0 0', textAlign: 'center' }}>
              {authMode === 'reg' ? 'Already registered?' : 'New here?'}{' '}
              <button
                id="sw"
                className="link"
                type="button"
                onClick={() => {
                  setAuthMode(authMode === 'reg' ? 'in' : 'reg');
                  setAuthError('');
                  setAuthSuccess('');
                }}
              >
                {authMode === 'reg' ? 'Sign in' : 'Register'}
              </button>
            </p>
          </div>
        )}

        {/* 2. UPLOAD SCREEN */}
        {view === 'dash' && (
          <div>
            <h1>Upload documents</h1>
            <p className="sub">
              Add folders or files. Folders are read recursively. Each file is read from scratch.
            </p>
            <div
              className={`drop ${isDragOver ? 'drag-over' : ''}`}
              onDragOver={(e) => {
                e.preventDefault();
                setIsDragOver(true);
              }}
              onDragLeave={() => setIsDragOver(false)}
              onDrop={async (e) => {
                e.preventDefault();
                setIsDragOver(false);

                const items = e.dataTransfer.items;
                let extracted: { file: File; relativePath: string }[] = [];

                if (items && items.length > 0 && (items[0] as any).webkitGetAsEntry) {
                  for (let i = 0; i < items.length; i++) {
                    const item = items[i];
                    const entry = (item as any).webkitGetAsEntry();
                    if (entry) {
                      const res = await traverseFileSystemEntry(entry);
                      extracted.push(...res);
                    }
                  }
                } else if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
                  extracted = Array.from(e.dataTransfer.files).map((f) => ({
                    file: f,
                    relativePath: (f as any).webkitRelativePath || f.name,
                  }));
                }

                processStagedFiles(extracted);
              }}
            >
              <p>Drop folders or files here, or choose them below.</p>
              <input
                type="file"
                multiple
                ref={fileInputRef}
                style={{ display: 'none' }}
                onChange={(e) => {
                  if (e.target.files && e.target.files.length > 0) {
                    const extracted = Array.from(e.target.files).map((f) => ({
                      file: f,
                      relativePath: f.webkitRelativePath || f.name,
                    }));
                    processStagedFiles(extracted);
                  }
                  e.target.value = '';
                }}
              />
              <input
                type="file"
                ref={folderInputRef}
                style={{ display: 'none' }}
                {...({ webkitdirectory: '', directory: '', multiple: true } as any)}
                onChange={(e) => {
                  if (e.target.files && e.target.files.length > 0) {
                    const extracted = Array.from(e.target.files).map((f) => ({
                      file: f,
                      relativePath: f.webkitRelativePath || f.name,
                    }));
                    processStagedFiles(extracted);
                  }
                  e.target.value = '';
                }}
              />
              <div style={{ display: 'flex', gap: '12px', justifyContent: 'center', marginTop: '12px' }}>
                <button
                  id="up"
                  className="pri"
                  type="button"
                  disabled={isUploading}
                  onClick={() => fileInputRef.current?.click()}
                >
                  Choose files
                </button>
                <button
                  id="choose-folder-btn"
                  className="sec"
                  type="button"
                  disabled={isUploading}
                  onClick={() => folderInputRef.current?.click()}
                >
                  Choose a folder
                </button>
              </div>
            </div>

            {/* PREVIEW BEFORE UPLOAD (Requirements 4 & 5) */}
            {showPreview && stagedFiles.length > 0 && (() => {
              const foldersCount = new Set(stagedFiles.map((f) => f.folder)).size;
              return (
                <div className="card" style={{ marginTop: '1.5rem', marginBottom: '1.5rem' }}>
                  <h2 style={{ marginTop: 0, fontSize: '1.1rem' }}>
                    {stagedFiles.length} file{stagedFiles.length === 1 ? '' : 's'} found in {foldersCount} folder{foldersCount === 1 ? '' : 's'}
                    {skippedFiles.length > 0 ? `, ${skippedFiles.length} skipped (not supported)` : ''}
                  </h2>
                  {skippedFiles.length > 0 && (
                    <div
                      className="note"
                      style={{
                        color: 'var(--warn-fg, #b45309)',
                        marginBottom: '1rem',
                        background: 'var(--warn-bg, #fef3c7)',
                        padding: '8px 12px',
                        borderRadius: '4px',
                        fontSize: '12px',
                      }}
                    >
                      <strong>Skipped files ({skippedFiles.length}):</strong>{' '}
                      {skippedFiles.map((s) => s.name).join(', ')}
                    </div>
                  )}

                  {/* Folders and their files */}
                  {Array.from(new Set(stagedFiles.map((f) => f.folder))).map((folder) => {
                    const filesInFolder = stagedFiles.filter((f) => f.folder === folder);
                    return (
                      <div
                        key={folder}
                        style={{
                          border: '1px solid var(--line)',
                          borderRadius: '6px',
                          padding: '10px 12px',
                          marginBottom: '10px',
                          background: 'var(--panel)',
                        }}
                      >
                        <div
                          style={{
                            display: 'flex',
                            justifyContent: 'space-between',
                            alignItems: 'center',
                            marginBottom: '6px',
                          }}
                        >
                          <span style={{ fontWeight: 600, fontSize: '13px' }}>
                            📁 {folder}{' '}
                            <span className="pill" style={{ fontSize: '11px', marginLeft: '6px' }}>
                              {filesInFolder.length} file{filesInFolder.length === 1 ? '' : 's'}
                            </span>
                          </span>
                          <button
                            type="button"
                            className="sec"
                            style={{ padding: '2px 8px', fontSize: '12px', color: 'var(--bad-fg, #dc2626)' }}
                            onClick={() => removeStagedFolder(folder)}
                          >
                            Remove folder
                          </button>
                        </div>
                        <div
                          style={{
                            display: 'flex',
                            flexDirection: 'column',
                            gap: '4px',
                            maxHeight: '140px',
                            overflowY: 'auto',
                          }}
                        >
                          {filesInFolder.map((item) => (
                            <div
                              key={item.id}
                              style={{
                                display: 'flex',
                                justifyContent: 'space-between',
                                alignItems: 'center',
                                fontSize: '12px',
                                padding: '3px 6px',
                                background: 'var(--bg)',
                                borderRadius: '4px',
                              }}
                            >
                              <span
                                style={{
                                  overflow: 'hidden',
                                  textOverflow: 'ellipsis',
                                  whiteSpace: 'nowrap',
                                  maxWidth: '75%',
                                }}
                              >
                                📄 {item.file.name}{' '}
                                <span style={{ color: 'var(--muted)', fontSize: '11px' }}>
                                  ({(item.file.size / 1024).toFixed(1)} KB)
                                </span>
                              </span>
                              <button
                                type="button"
                                className="link"
                                style={{ fontSize: '12px', color: 'var(--bad-fg, #dc2626)' }}
                                onClick={() => removeStagedFile(item.id)}
                              >
                                Remove
                              </button>
                            </div>
                          ))}
                        </div>
                      </div>
                    );
                  })}

                  <div
                    style={{
                      display: 'flex',
                      gap: '12px',
                      justifyContent: 'flex-end',
                      alignItems: 'center',
                      marginTop: '16px',
                    }}
                  >
                    <button
                      type="button"
                      className="sec"
                      onClick={clearStagedFiles}
                      disabled={isUploading}
                    >
                      Cancel
                    </button>
                    <button
                      type="button"
                      id="start-reading-btn"
                      className="pri"
                      onClick={handleStartReading}
                      disabled={isUploading || stagedFiles.length === 0}
                      style={{ fontWeight: 600, padding: '8px 20px' }}
                    >
                      {isUploading
                        ? `Uploading ${uploadProgress?.current || 0} of ${uploadProgress?.total || stagedFiles.length}...`
                        : 'Start reading'}
                    </button>
                  </div>
                  {isUploading && uploadProgress && (
                    <div style={{ marginTop: '12px' }}>
                      <div className="prog">
                        <i
                          style={{
                            width: `${Math.round((uploadProgress.current / uploadProgress.total) * 100)}%`,
                          }}
                        ></i>
                      </div>
                      <div className="sub" style={{ marginTop: '4px' }}>
                        Uploading {uploadProgress.current} of {uploadProgress.total} ({Math.round((uploadProgress.current / uploadProgress.total) * 100)}%)
                      </div>
                    </div>
                  )}
                </div>
              );
            })()}
            <ul className="rules">
              <li>
                Every upload is read again, even if the filename or content
                matches an earlier one.
              </li>
              <li>
                The app decides the document type and finds every detail that is
                on the page.
              </li>
              <li>
                Nothing is filled in. If a detail is not on the page, it stays
                empty.
              </li>
            </ul>

            {/* Past Batches */}
            {pastBatches.length > 0 && (
              <div className="grp">
                <h2>
                  Past uploads<span>{pastBatches.length}</span>
                </h2>
                <div className="tw">
                  <table>
                    <thead>
                      <tr>
                        <th>Batch</th>
                        <th>Files</th>
                        <th>Created</th>
                        <th></th>
                      </tr>
                    </thead>
                    <tbody>
                      {pastBatches.map((pb) => (
                        <tr key={pb.id}>
                          <td>{pb.name}</td>
                          <td>{pb.file_count} files</td>
                          <td>
                            {pb.created_at
                              ? new Date(pb.created_at).toLocaleString()
                              : '—'}
                          </td>
                          <td>
                            <button
                              className="link"
                              onClick={() => openBatch(pb.id)}
                            >
                              Open
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}

            {/* Account Backup & Render Free-Tier 30-Day Expiry Notice */}
            <div
              style={{
                marginTop: '32px',
                padding: '16px 20px',
                borderRadius: '8px',
                backgroundColor: '#f8fafc',
                border: '1px solid #e2e8f0',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                flexWrap: 'wrap',
                gap: '16px',
              }}
            >
              <div style={{ maxWidth: '680px' }}>
                <div style={{ fontWeight: 600, fontSize: '14px', color: '#0f172a', display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <span>💾</span>
                  <span>Account Backup & Free PostgreSQL 30-Day Notice</span>
                </div>
                <div style={{ fontSize: '13px', color: '#64748b', marginTop: '4px', lineHeight: 1.4 }}>
                  Render free PostgreSQL databases expire and reset 30 days after creation. Export all your batches, documents, and reviewed fields in structured JSON and tabular CSV to keep a permanent local backup.
                </div>
              </div>
              <button
                className="sec"
                onClick={handleExportAccount}
                disabled={isExportingAccount}
                style={{
                  whiteSpace: 'nowrap',
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: '6px',
                  fontWeight: 500,
                  fontSize: '13px',
                }}
              >
                {isExportingAccount ? 'Exporting...' : 'Export Account Data (JSON & CSV)'}
              </button>
            </div>
          </div>
        )}

        {/* 3. READING / PROGRESS SCREEN */}
        {view === 'proc' && batch && (
          <div>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', flexWrap: 'wrap', gap: '0.5rem' }}>
              <h1>Reading your files</h1>
              <button
                id="clr"
                className="sec"
                type="button"
                onClick={handleClearBatch}
                style={{ padding: '0.4rem 0.85rem', fontSize: '0.85rem' }}
              >
                Clear this batch
              </button>
            </div>
            <p className="sub">
              Reading {batch.done_count} of {batch.files.length} finished
            </p>
            <div className="prog">
              <i style={{ width: `${batch.progress_pct}%` }}></i>
            </div>
            <div className="sub" style={{ margin: 0 }}>
              {batch.progress_pct}% complete
            </div>

            <div className="rows">
              {batch.files.map((f) => {
                const pillClass =
                  f.stage === 'Done'
                    ? 'ok'
                    : f.stage === 'Failed'
                    ? 'bad'
                    : f.stage === 'Waiting'
                    ? ''
                    : 'warn';
                return (
                  <div className="row" key={f.id}>
                    <span className="nm">
                      {f.name}
                      {f.dup && f.dup !== f.name && f.stage !== 'Waiting' && (
                        <div className="note">
                          Same content as {f.dup}. Read again anyway.
                        </div>
                      )}
                      {f.error && !f.error.includes('Fast Lane') && !f.error.includes('connect to text LLMs') && (
                        <div
                          className="note"
                          style={{ color: 'var(--bad-fg)' }}
                        >
                          Error: {f.error}
                        </div>
                      )}
                    </span>
                    <span className={`pill ${pillClass}`}>{f.stage}</span>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* 4. RESULTS SCREEN */}
        {view === 'results' && batch && (
          <div>
            <div className="toolbar">
              <h1 style={{ margin: 0 }}>Results</h1>
              <span className="sp"></span>
              {(() => {
                const allFolders = Array.from(
                  new Set(
                    batch.files
                      .map((f) =>
                        f.relative_path && f.relative_path.includes('/')
                          ? f.relative_path.substring(0, f.relative_path.lastIndexOf('/'))
                          : ''
                      )
                      .filter(Boolean)
                  )
                ).sort();

                if (allFolders.length === 0) return null;
                return (
                  <div style={{ display: 'flex', alignItems: 'center', gap: '6px', marginRight: '8px' }}>
                    <label htmlFor="folder-filter" style={{ fontSize: '12px', fontWeight: 600, color: 'var(--muted)' }}>
                      Folder:
                    </label>
                    <select
                      id="folder-filter"
                      value={folderFilter}
                      onChange={(e) => setFolderFilter(e.target.value)}
                      style={{
                        fontSize: '12px',
                        padding: '5px 8px',
                        borderRadius: '6px',
                        border: '1px solid var(--line)',
                        background: 'var(--panel)',
                        color: 'var(--fg)',
                      }}
                    >
                      <option value="">All folders ({batch.files.length})</option>
                      {allFolders.map((fld) => {
                        const count = batch.files.filter(
                          (f) => f.relative_path?.startsWith(fld + '/') || f.relative_path === fld
                        ).length;
                        return (
                          <option key={fld} value={fld}>
                            📁 {fld} ({count})
                          </option>
                        );
                      })}
                    </select>
                  </div>
                );
              })()}
              <button
                id="do-again-all"
                style={{
                  backgroundColor: '#0284c7',
                  color: '#ffffff',
                  fontWeight: 600,
                  marginRight: '8px',
                  padding: '7px 14px',
                  borderRadius: '6px',
                  cursor: 'pointer',
                  border: 'none',
                }}
                onClick={handleDoAllAgain}
                title="Re-run AI extraction for all documents in this batch"
              >
                🔄 Do again
              </button>
              <button id="clr" onClick={handleClearBatch}>
                Clear this batch
              </button>
              <a
                href={api.getDownloadUrl(batch.id)}
                download
                style={{ textDecoration: 'none' }}
              >
                <button className="pri">Download all as ZIP</button>
              </a>
              <button
                id="again"
                onClick={() => {
                  loadPastBatches();
                  setView('dash');
                }}
              >
                Upload more
              </button>
            </div>
            <p className="sub">
              {batch.files.length} files, grouped by the type the app found.
              Each table shows only the details found in that group.
              {batch.corrections_count > 0 && (
                <span>
                  {' '}
                  · Learned from {batch.corrections_count} correction
                  {batch.corrections_count > 1 ? 's' : ''}
                </span>
              )}
            </p>

            {/* Render groups dynamically */}
            {(() => {
              const groups: Record<string, number[]> = {};
              batch.files.forEach((f, i) => {
                const isFailed =
                  f.stage === 'Failed' ||
                  f.status === 'Failed' ||
                  f.status === 'Damaged' ||
                  f.status === 'Empty' ||
                  f.status === 'Locked' ||
                  f.status === 'check' ||
                  f.type === 'Could not read';
                const t = isFailed ? 'Could not read' : (f.type || 'Document');
                if (!groups[t]) groups[t] = [];
                groups[t].push(i);
              });

              return Object.keys(groups).map((g) => {
                const idxs = groups[g];
                const filteredIdxs = idxs.filter((i) => {
                  if (!folderFilter) return true;
                  const rel = batch.files[i].relative_path || '';
                  return rel.startsWith(folderFilter + '/') || rel === folderFilter;
                });
                if (filteredIdxs.length === 0) return null;

                // Columns are ONLY the union of labels found in this group
                const cols: string[] = [];
                filteredIdxs.forEach((i) => {
                  batch.files[i].fields.forEach((x) => {
                    if (!cols.includes(x.label)) cols.push(x.label);
                  });
                });

                return (
                  <div className="grp" key={g}>
                    <h2>
                      {g}
                      <span>{filteredIdxs.length}</span>
                    </h2>
                    <div className="tw">
                      <table>
                        <thead>
                          <tr>
                            <th>File</th>
                            {cols.map((c) => (
                              <th key={c}>{c}</th>
                            ))}
                            <th>Status</th>
                            <th>Check reasons</th>
                            <th></th>
                          </tr>
                        </thead>
                        <tbody>
                          {filteredIdxs.map((i) => {
                            const f = batch.files[i];
                            const isLow = f.fields.some(
                              (x) => (x.conf ?? 1.0) < 0.85
                            );
                            const pillClass =
                              f.status === 'Done'
                                ? 'ok'
                                : f.status === 'Done, check' || f.status === 'Needs check'
                                ? 'warn'
                                : 'bad';
                            return (
                              <tr key={f.id}>
                                <td>
                                  {f.name}
                                  {f.relative_path && f.relative_path.includes('/') && (
                                    <div
                                      className="note"
                                      style={{ color: 'var(--muted)', fontSize: '11px', marginTop: '2px' }}
                                    >
                                      📁 {f.relative_path.substring(0, f.relative_path.lastIndexOf('/'))}
                                    </div>
                                  )}
                                  {f.dup && f.dup !== f.name && (
                                    <div className="note">
                                      Same content as {f.dup}
                                    </div>
                                  )}
                                  {f.error && !f.error.includes('Fast Lane') && !f.error.includes('connect to text LLMs') && (
                                    <div
                                      className="note"
                                      style={{ color: 'var(--bad-fg)' }}
                                    >
                                      {f.error}
                                    </div>
                                  )}
                                </td>
                                {cols.map((c) => {
                                  const match = f.fields.find(
                                    (y) => y.label === c
                                  );
                                  return match ? (
                                    <td key={c}>
                                      {match.value}
                                      {match.src !== 'read' && (
                                        <span
                                          className="pill"
                                          style={{
                                            fontSize: '10px',
                                            marginLeft: '4px',
                                          }}
                                        >
                                          {match.src}
                                        </span>
                                      )}
                                    </td>
                                  ) : (
                                    <td key={c} className="empty">
                                      "-"
                                    </td>
                                  );
                                })}
                                <td>
                                  <span className={`pill ${pillClass}`}>
                                    {f.status}
                                  </span>
                                </td>
                                <td>
                                  {f.check_reasons ||
                                    (f.status === 'Done, check' || f.status === 'Needs check'
                                      ? f.error || 'Low confidence details require verification'
                                      : f.status === 'Failed' || f.stage === 'Failed'
                                      ? f.error || 'Reading failed'
                                      : '-')}
                                </td>
                                <td style={{ whiteSpace: 'nowrap' }}>
                                  <button
                                    className="link"
                                    onClick={() => openView(i)}
                                  >
                                    View
                                  </button>
                                  <button
                                    className="btn"
                                    style={{
                                      marginLeft: '8px',
                                      padding: '4px 10px',
                                      fontSize: '12px',
                                      backgroundColor: '#0284c7',
                                      color: '#ffffff',
                                      border: 'none',
                                      borderRadius: '4px',
                                      cursor: 'pointer',
                                      fontWeight: 600,
                                    }}
                                    onClick={() => handleDoAgain(f.id)}
                                    title="Re-run AI extraction for this document"
                                  >
                                    🔄 Do again
                                  </button>
                                </td>
                              </tr>
                            );
                          })}
                        </tbody>
                      </table>
                    </div>
                  </div>
                );
              });
            })()}

            <p className="cap">
              "Done, check" means at least one value was read with low
              confidence. Click View to compare it with the original page.
            </p>
          </div>
        )}

        {/* 5. VIEW / EDIT SCREEN */}
        {view === 'view' && batch && batch.files[activeFileIndex] && (
          <div>
            {(() => {
              const f = batch.files[activeFileIndex];
              return (
                <div>
                  <div className="toolbar">
                    <button id="bk" onClick={() => setView('results')}>
                      Back to results
                    </button>
                    <button
                      id="do-again-view"
                      style={{
                        marginLeft: '8px',
                        backgroundColor: '#0284c7',
                        color: '#ffffff',
                        fontWeight: 600,
                      }}
                      onClick={() => handleDoAgain(f.id)}
                      title="Re-run AI extraction for this document"
                    >
                      🔄 Do again
                    </button>
                    <span className="sp"></span>
                    <button
                      id="pv"
                      disabled={activeFileIndex === 0}
                      onClick={() => navFile(activeFileIndex - 1)}
                    >
                      Previous
                    </button>
                    <span>
                      {activeFileIndex + 1} of {batch.files.length}
                    </span>
                    <button
                      id="nx"
                      disabled={activeFileIndex === batch.files.length - 1}
                      onClick={() => navFile(activeFileIndex + 1)}
                    >
                      Next
                    </button>
                  </div>

                  <h1 style={{ overflowWrap: 'anywhere' }}>{f.name}</h1>
                  <p className="sub">
                    Type found: {f.type}
                    {f.dup && f.dup !== f.name
                      ? `. Same content as ${f.dup}, read again.`
                      : ''}
                  </p>

                  {f.error && f.error.includes('password') && (
                    <div className="card" style={{ marginBottom: '16px', background: 'var(--warn-bg)', borderColor: 'var(--warn-fg)' }}>
                      <h2 style={{ color: 'var(--warn-fg)', margin: '0 0 6px 0' }}>This file is password protected.</h2>
                      <p className="sub" style={{ margin: '0 0 10px 0' }}>Enter the document password to unlock and read all pages.</p>
                      <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
                        <input
                          type="password"
                          placeholder="Password"
                          value={unlockPassword}
                          onChange={(e) => setUnlockPassword(e.target.value)}
                          style={{ maxWidth: '280px' }}
                        />
                        <button
                          className="pri"
                          type="button"
                          disabled={isUnlocking}
                          onClick={() => handleUnlockFile(f.id)}
                        >
                          {isUnlocking ? 'Unlocking...' : 'Unlock'}
                        </button>
                      </div>
                      {unlockError && <div className="err" style={{ marginTop: '8px' }}>{unlockError}</div>}
                    </div>
                  )}

                  <div className="split">
                    {/* Left Panel: Real Document Page Image with BBox Highlight and Zoom Controls */}
                    <div className="paperbox">
                      <div style={{ display: 'flex', gap: '8px', alignItems: 'center', marginBottom: '8px' }}>
                        <span style={{ fontSize: '12px', fontWeight: 600, color: 'var(--muted)' }}>Zoom:</span>
                        <button
                          type="button"
                          className="btn"
                          style={{ padding: '2px 8px', fontSize: '13px' }}
                          onClick={() => setZoomLevel((z) => Math.max(0.5, Number((z - 0.25).toFixed(2))))}
                          title="Zoom out"
                        >
                          −
                        </button>
                        <span style={{ fontSize: '12px', minWidth: '40px', textAlign: 'center' }}>
                          {Math.round(zoomLevel * 100)}%
                        </span>
                        <button
                          type="button"
                          className="btn"
                          style={{ padding: '2px 8px', fontSize: '13px' }}
                          onClick={() => setZoomLevel((z) => Math.min(3.0, Number((z + 0.25).toFixed(2))))}
                          title="Zoom in"
                        >
                          +
                        </button>
                        <button
                          type="button"
                          className="btn"
                          style={{ padding: '2px 8px', fontSize: '12px' }}
                          onClick={() => setZoomLevel(1.0)}
                        >
                          Reset
                        </button>
                      </div>
                      <div
                        className="paper-viewer"
                        style={{ position: 'relative', overflow: 'auto', maxHeight: '75vh' }}
                        onMouseUp={() => {
                          const sel = window.getSelection()?.toString().trim();
                          if (sel && activeDetailIdx !== null) {
                            updateDraft(activeDetailIdx, 'value', sel);
                            setSavedToast(`Filled selected text into active detail.`);
                            setTimeout(() => setSavedToast(''), 3000);
                          }
                        }}
                      >
                        <div style={{ position: 'relative', transform: `scale(${zoomLevel})`, transformOrigin: 'top left', display: 'inline-block', width: '100%' }}>
                          <img
                            src={api.getPageImageUrl(f.id, 1)}
                            alt={`Original document ${f.name}`}
                            style={{ display: 'block', width: '100%', height: 'auto' }}
                          />
                          {highlightedBbox && (
                            <div
                              className="highlight-box"
                              style={{
                                top: `${highlightedBbox[0] / 10}%`,
                                left: `${highlightedBbox[1] / 10}%`,
                                height: `${Math.max(2, (highlightedBbox[2] - highlightedBbox[0]) / 10)}%`,
                                width: `${Math.max(3, (highlightedBbox[3] - highlightedBbox[1]) / 10)}%`,
                              }}
                              title="Detail location on page"
                            />
                          )}
                        </div>
                      </div>
                      <div className="cap">
                        Original page. Page condition detected: {f.cond}.
                        {highlightedBbox && <span> · Highlighting selected detail</span>}
                        <span style={{ display: 'block', fontSize: '11px', color: 'var(--muted)', marginTop: '2px' }}>
                          💡 Tip: Select any text on page to fill into the active field. Use `[` and `]` to navigate files, `Enter` to accept suggestions, `Delete` to remove.
                        </span>
                      </div>
                    </div>

                    {/* Right Panel: Review Screen with Details and Raw Text Tab */}
                    <div className="card">
                      {/* Section 7: Tab Navigation (Details found vs Raw text per page) */}
                      <div style={{ display: 'flex', gap: '8px', marginBottom: '16px', borderBottom: '1px solid var(--border)', paddingBottom: '8px' }}>
                        <button
                          type="button"
                          className={`btn ${activeTab === 'details' ? 'pri' : ''}`}
                          onClick={() => setActiveTab('details')}
                        >
                          Details found ({draftFields.length})
                        </button>
                        <button
                          type="button"
                          className={`btn ${activeTab === 'raw_text' ? 'pri' : ''}`}
                          onClick={() => setActiveTab('raw_text')}
                        >
                          Raw text per page
                        </button>
                      </div>

                      {activeTab === 'raw_text' ? (
                        <div className="raw-text-container">
                          <p className="sub" style={{ fontStyle: 'italic', marginBottom: '12px' }}>
                            Full text is preserved per page as raw text. Raw text is never turned into candidate fields.
                          </p>
                          {f.raw_text_by_page && Object.keys(f.raw_text_by_page).length > 0 ? (
                            Object.entries(f.raw_text_by_page).map(([pg, txt]) => (
                              <div key={pg} style={{ marginBottom: '16px' }}>
                                <h4 style={{ margin: '0 0 6px 0', color: 'var(--muted)' }}>Page {pg}</h4>
                                <pre style={{ background: 'rgba(0,0,0,0.25)', padding: '12px', borderRadius: '6px', whiteSpace: 'pre-wrap', wordBreak: 'break-word', fontSize: '12px', lineHeight: '1.4' }}>
                                  {txt}
                                </pre>
                              </div>
                            ))
                          ) : (
                            <pre style={{ background: 'rgba(0,0,0,0.25)', padding: '12px', borderRadius: '6px', whiteSpace: 'pre-wrap', fontSize: '12px' }}>
                              No raw text recorded for this document.
                            </pre>
                          )}
                        </div>
                      ) : (
                        <div>
                          {(() => {
                            const renderFieldRow = (x: FieldItem, i: number, isMore: boolean = false) => {
                              const confPct = Math.round((x.conf ?? 1.0) * 100);
                              const isLow = (x.conf ?? 1.0) < 0.85;
                              const isRowEdited = Boolean(
                                x.is_edited ||
                                x.src === 'edited' ||
                                (x.orig !== undefined && x.value !== x.orig) ||
                                (x.orig_label !== undefined && x.label !== x.orig_label)
                              );
                              const needsLabel = !x.label && (x.hint === 'needs label' || (x.lbl_conf ?? 1.0) < 0.85);

                              return (
                                <div
                                  className={`fr ${activeDetailIdx === i ? 'active-detail' : ''}`}
                                  key={i}
                                  onClick={() => handleDetailClick(i, x.bbox)}
                                >
                                  {/* Left Column: Editable label input with suggestions & alternative picker */}
                                  <div className="fr-label-container" style={{ width: '100%' }}>
                                    <div style={{ display: 'flex', gap: '6px', alignItems: 'center', flexWrap: 'wrap' }}>
                                      <select
                                        value={x.structure_type || 'label_value_pair'}
                                        onChange={(e) => {
                                          e.stopPropagation();
                                          handleReclassifyRegion(f.id, x.region_id || `region_${i}`, e.target.value, i);
                                        }}
                                        style={{
                                          fontSize: '11px',
                                          padding: '2px 4px',
                                          borderRadius: '4px',
                                          border: '1px solid var(--border)',
                                          background: 'var(--card-hover)',
                                          color: 'var(--fg)',
                                          fontWeight: 600,
                                        }}
                                        title="Structure type (1-click correction)"
                                        aria-label={`Structure type for row ${i + 1}`}
                                      >
                                        {STRUCTURE_TYPES.map((st) => (
                                          <option key={st.value} value={st.value}>{st.label}</option>
                                        ))}
                                      </select>
                                      <input
                                        type="text"
                                        className="fr-label-input"
                                        list="doc-label-suggestions"
                                        value={x.label}
                                        onChange={(e) => updateDraft(i, 'label', e.target.value)}
                                        placeholder={needsLabel ? 'needs label' : 'Add label'}
                                        aria-label={`Label for row ${i + 1}`}
                                        style={{ flex: 1, minWidth: '120px' }}
                                      />
                                      {!x.label && x.suggested_label && (
                                        <button
                                          type="button"
                                          className="btn"
                                          style={{ fontSize: '11px', padding: '2px 8px', background: '#0284c7', color: '#fff', border: 'none', borderRadius: '4px' }}
                                          onClick={(e) => {
                                            e.stopPropagation();
                                            handleAcceptSuggestion(i);
                                          }}
                                          title="Accept suggested label"
                                        >
                                          Suggested: "{x.suggested_label}" ✓
                                        </button>
                                      )}
                                      {x.label && (x.suggested_label || x.src === 'generated') && x.src !== 'verified' && (
                                        <span
                                          className="pill"
                                          title={x.reason || 'Learned suggestion (click or press Enter to accept)'}
                                          onClick={(e) => {
                                            e.stopPropagation();
                                            handleAcceptSuggestion(i);
                                          }}
                                          style={{ cursor: 'pointer', background: '#0284c7', color: '#ffffff', fontWeight: 600, fontSize: '11px' }}
                                        >
                                          suggested ✓
                                        </span>
                                      )}
                                      {x.src === 'verified' && (
                                        <span className="pill" style={{ background: '#166534', color: '#bbf7d0', fontSize: '11px', fontWeight: 600 }}>
                                          verified by reviewer
                                        </span>
                                      )}
                                      {x.alternatives && x.alternatives.length > 0 && (
                                        <select
                                          style={{ fontSize: '11px', padding: '2px 4px', background: 'var(--card)', color: 'var(--fg)', border: '1px solid var(--border)', borderRadius: '4px' }}
                                          value=""
                                          onChange={(e) => {
                                            e.stopPropagation();
                                            handleSelectAlternative(i, e.target.value);
                                          }}
                                          title="Choose alternative learned label"
                                        >
                                          <option value="" disabled>Alternatives...</option>
                                          {x.alternatives.map((alt, aidx) => (
                                            <option key={aidx} value={alt}>{alt}</option>
                                          ))}
                                        </select>
                                      )}
                                      {isMore && (
                                        <button
                                          type="button"
                                          className="btn"
                                          style={{ fontSize: '11px', padding: '2px 8px' }}
                                          onClick={(e) => {
                                            e.stopPropagation();
                                            handlePromoteDetail(f.id, x.id, i);
                                          }}
                                          title="Promote this candidate to key details"
                                        >
                                          ⬆ Promote
                                        </button>
                                      )}
                                    </div>
                                  </div>

                                  {/* Right Column: Editable wrapping value */}
                                  <div style={{ width: '100%' }}>
                                    <textarea
                                      className="fr-value-area"
                                      rows={Math.max(1, Math.ceil(x.value.length / 55))}
                                      value={x.value}
                                      onChange={(e) =>
                                        updateDraft(i, 'value', e.target.value)
                                      }
                                      placeholder="Value"
                                      aria-label={`Value for ${x.label || 'detail'}`}
                                    />
                                    {/* Split suggestion banner */}
                                    {x.split_suggestion && Array.isArray(x.split_suggestion) && x.split_suggestion.length > 0 && (
                                      <div style={{ marginTop: '6px', padding: '6px 10px', background: 'rgba(56, 189, 248, 0.1)', border: '1px dashed #38bdf8', borderRadius: '4px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                                        <span style={{ fontSize: '12px' }}>
                                          💡 Suggested split: {x.split_suggestion.map((s: any) => `${s.label}: "${s.value}"`).join(' & ')}
                                        </span>
                                        <div style={{ display: 'flex', gap: '6px' }}>
                                          <button
                                            type="button"
                                            className="btn"
                                            style={{ fontSize: '11px', padding: '2px 8px' }}
                                            onClick={(e) => {
                                              e.stopPropagation();
                                              handleAcceptSplit(f.id, x.id, i);
                                            }}
                                          >
                                            Accept split
                                          </button>
                                          <button
                                            type="button"
                                            className="btn"
                                            style={{ fontSize: '11px', padding: '2px 8px' }}
                                            onClick={(e) => {
                                              e.stopPropagation();
                                              handleDismissSplit(i);
                                            }}
                                          >
                                            Dismiss
                                          </button>
                                        </div>
                                      </div>
                                    )}
                                  </div>

                                  {/* Option to mark as not a field (remove noise line) */}
                                  <div style={{ display: 'flex', alignItems: 'center' }}>
                                    <button
                                      type="button"
                                      className="btn-not-field"
                                      onClick={(e) => {
                                        e.stopPropagation();
                                        removeDraftRow(i);
                                      }}
                                      title="Mark as not a field (remove noise)"
                                      aria-label={`Mark as not a field: ${x.label || 'row'}`}
                                    >
                                      ✕ Not a field
                                    </button>
                                  </div>

                                  <div className="meta">
                                    <span>
                                      Val: {Math.round((x.val_conf ?? x.conf ?? 0.985) * 100)}% · Lbl: {x.label && x.label.trim() && x.lbl_conf !== undefined && x.lbl_conf !== null ? `${Math.round(x.lbl_conf * 100)}%` : '-'} · Struct: {Math.round((x.structure_confidence ?? 1.0) * 100)}%
                                    </span>
                                    <span className="pill" style={{ fontSize: '10px', background: 'rgba(255,255,255,0.06)' }}>
                                      {x.structure_type || 'label_value_pair'}
                                    </span>
                                    {isLow && (
                                      <span className="pill warn">check this</span>
                                    )}
                                    {isRowEdited && (
                                      <span className="pill warn" style={{ background: '#fef08a', color: '#854d0e', fontWeight: 600 }}>
                                        edited
                                      </span>
                                    )}
                                    {x.src === 'added' && (
                                      <span className="pill warn">added</span>
                                    )}
                                    {x.page && (
                                      <span>Page {x.page}</span>
                                    )}
                                    {x.grounding_span && (
                                      <span style={{ fontSize: '10px', color: 'var(--muted)' }}>📍 Grounded</span>
                                    )}
                                  </div>
                                </div>
                              );
                            };

                            const handleCopyJson = () => {
                              const jsonOutput = {
                                document_kind: f.type || 'Unknown',
                                type: f.type || 'Unknown',
                                type_confidence: (f as any).type_confidence ?? 0.92,
                                top_candidates: (f as any).top_candidates || [{ type: f.type || 'Unknown', score: 0.92 }],
                                summary: f.document_summary || null,
                                tags: f.tags || [],
                                page_conditions: (f as any).page_conditions || [{ page: 1, condition: f.cond || 'clean' }],
                                logical_documents: (f as any).logical_documents || [{ document_index: 1, start_page: 1, end_page: 1, type: f.type || 'Unknown', confidence: 0.92 }],
                                fields: draftFields.map((d) => ({
                                  label: d.label,
                                  value: d.value,
                                  confidence: d.conf ?? 1.0,
                                  val_conf: d.val_conf,
                                  lbl_conf: d.lbl_conf,
                                  page: d.page ?? 1,
                                  source: d.src,
                                  grounding_span: d.grounding_span,
                                })),
                                table_rows: (f as any).table_rows || [],
                                sensitive_findings: (f as any).sensitive_findings || [],
                                detectors_run: 11,
                                routing: {
                                  destination: (f as any).destination || (f.type ? `${f.type.toUpperCase()}_PROCESSING_SYSTEM` : 'MANUAL_TRIAGE_QUEUE'),
                                  is_restricted: (f as any).is_restricted || false,
                                },
                                needs_review: draftFields.some((x) => (x.conf ?? 1.0) < 0.85) || f.type === 'Unknown' || f.type === 'unknown',
                                review_reasons: (f as any).review_reasons || [],
                                pipeline_version: (f as any).pipeline_version || '2.3.0',
                                registry_version: (f as any).registry_version || '2.3.0',
                              };

                              navigator.clipboard.writeText(JSON.stringify(jsonOutput, null, 2));
                              setSavedToast('JSON Copied!');
                              setTimeout(() => setSavedToast(''), 3000);
                            };

                            const sensitiveFindings = (f as any).sensitive_findings || [];
                            const detectorsRunCount = 11;
                            const findingsCount = sensitiveFindings.length;

                            // Separate details by region group
                            const fieldsGroup = draftFields.map((item, idx) => ({ item, idx })).filter(({ item }) => !item.structure_group || item.structure_group === 'fields');
                            const listsGroup = draftFields.map((item, idx) => ({ item, idx })).filter(({ item }) => item.structure_group === 'lists');
                            const checkboxesGroup = draftFields.map((item, idx) => ({ item, idx })).filter(({ item }) => item.structure_group === 'checkboxes');
                            const signaturesGroup = draftFields.map((item, idx) => ({ item, idx })).filter(({ item }) => item.structure_group === 'signatures_and_stamps');
                            const imagesGroup = draftFields.map((item, idx) => ({ item, idx })).filter(({ item }) => item.structure_group === 'images_and_charts');
                            const codesGroup = draftFields.map((item, idx) => ({ item, idx })).filter(({ item }) => item.structure_group === 'codes');
                            const tableTotalsGroup = draftFields.map((item, idx) => ({ item, idx })).filter(({ item }) => item.structure_group === 'tables');

                            // Separate key details (at most 8) and more details inside fieldsGroup
                            const keyDetailsWithIdx = fieldsGroup.filter(({ item }) => !item.in_more_details || item.is_promoted);
                            const moreDetailsWithIdx = fieldsGroup.filter(({ item }) => item.in_more_details && !item.is_promoted);

                            return (
                              <div>
                                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
                                  <h2 style={{ margin: 0 }}>Details found</h2>
                                  <button
                                    type="button"
                                    className="btn"
                                    style={{ padding: '4px 10px', fontSize: '13px' }}
                                    onClick={handleCopyJson}
                                  >
                                    📋 Copy JSON
                                  </button>
                                </div>

                                {f.document_summary && (
                                  <div style={{ padding: '8px 12px', background: 'rgba(255, 255, 255, 0.03)', border: '1px solid var(--border)', borderRadius: '6px', marginBottom: '12px' }}>
                                    <div style={{ fontSize: '11px', color: 'var(--muted)', fontWeight: 600, textTransform: 'uppercase' }}>Summary</div>
                                    <div style={{ fontSize: '13px', marginTop: '3px' }}>{f.document_summary}</div>
                                    {f.tags && f.tags.length > 0 && (
                                      <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap', marginTop: '6px' }}>
                                        {f.tags.map((t, tidx) => (
                                          <span key={tidx} className="pill" style={{ fontSize: '11px' }}>#{t}</span>
                                        ))}
                                      </div>
                                    )}
                                  </div>
                                )}

                                {/* Findings Panel: Always show 'detectors run: N, findings: M' */}
                                <div
                                  className="findings-panel"
                                  style={{
                                    background: 'rgba(255, 255, 255, 0.04)',
                                    border: '1px solid var(--border)',
                                    borderRadius: '6px',
                                    padding: '10px 14px',
                                    marginBottom: '16px',
                                  }}
                                >
                                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                                    <span style={{ fontSize: '13px', fontWeight: 600 }}>
                                      🛡️ Sensitive Data Panel: detectors run: {detectorsRunCount}, findings: {findingsCount}
                                    </span>
                                    {(f as any).is_restricted && (
                                      <span className="pill warn" style={{ background: '#7f1d1d', color: '#fca5a5' }}>
                                        RESTRICTED
                                      </span>
                                    )}
                                  </div>
                                </div>

                                {/* Tables Section */}
                                {draftTables && draftTables.length > 0 && (
                                  <div style={{ marginBottom: '20px' }}>
                                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
                                      <h3 style={{ margin: 0, fontSize: '15px' }}>Structured Tables ({draftTables.length})</h3>
                                    </div>
                                    {draftTables.map((tbl, tIdx) => (
                                      <div key={tIdx} style={{ marginBottom: '16px', border: '1px solid var(--border)', borderRadius: '6px', padding: '12px', background: 'var(--card)' }}>
                                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
                                          <span style={{ fontWeight: 600, fontSize: '13px' }}>Table {tIdx + 1} (Page {tbl.page || 1}) · {tbl.rows.length} rows</span>
                                          <div style={{ display: 'flex', gap: '6px' }}>
                                            <button type="button" className="btn" style={{ fontSize: '11px', padding: '2px 8px' }} onClick={() => addTableColumn(tIdx)}>+ Column</button>
                                            <button type="button" className="btn" style={{ fontSize: '11px', padding: '2px 8px' }} onClick={() => addTableRow(tIdx)}>+ Row</button>
                                          </div>
                                        </div>

                                        {/* Arithmetic check status badges */}
                                        {tbl.arithmetic_checks && tbl.arithmetic_checks.length > 0 && (
                                          <div style={{ marginBottom: '8px', display: 'flex', flexDirection: 'column', gap: '4px' }}>
                                            {tbl.arithmetic_checks.map((chk, cIdx) => (
                                              <div
                                                key={cIdx}
                                                style={{
                                                  fontSize: '11px',
                                                  padding: '3px 6px',
                                                  borderRadius: '4px',
                                                  background: chk.status === 'verified' ? '#f0fdf4' : '#fef2f2',
                                                  color: chk.status === 'verified' ? '#166534' : '#991b1b',
                                                  border: `1px solid ${chk.status === 'verified' ? '#bbf7d0' : '#fecaca'}`,
                                                }}
                                              >
                                                <span>{chk.status === 'verified' ? '✓ ' : '⚠️ '}</span>
                                                <span><strong>{chk.type.toUpperCase()}:</strong> {chk.message}</span>
                                              </div>
                                            ))}
                                          </div>
                                        )}

                                        {/* Grid Table */}
                                        <div style={{ overflowX: 'auto' }}>
                                          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '12px' }}>
                                            <thead>
                                              <tr style={{ background: 'var(--card-hover)', borderBottom: '1px solid var(--border)' }}>
                                                <th style={{ width: '28px', padding: '4px', textAlign: 'center' }}>#</th>
                                                {tbl.headers.map((h, hIdx) => (
                                                  <th key={hIdx} style={{ padding: '6px', textAlign: 'left' }}>
                                                    <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                                                      <input
                                                        type="text"
                                                        value={h}
                                                        onChange={(e) => updateTableHeader(tIdx, hIdx, e.target.value)}
                                                        style={{ fontWeight: 600, padding: '2px 4px', width: '100%', fontSize: '11px' }}
                                                      />
                                                      <button
                                                        type="button"
                                                        onClick={() => removeTableColumn(tIdx, hIdx)}
                                                        title="Delete column"
                                                        style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--muted)', fontSize: '11px' }}
                                                      >
                                                        ✕
                                                     </button>
                                                    </div>
                                                  </th>
                                                ))}
                                                <th style={{ width: '32px', padding: '4px' }}></th>
                                              </tr>
                                            </thead>
                                            <tbody>
                                              {tbl.rows.map((row, rIdx) => (
                                                <tr key={rIdx} style={{ borderBottom: '1px solid var(--border)' }}>
                                                  <td style={{ textAlign: 'center', color: 'var(--muted)', fontSize: '11px' }}>{rIdx + 1}</td>
                                                  {tbl.headers.map((h, hIdx) => (
                                                    <td key={hIdx} style={{ padding: '3px' }}>
                                                      <input
                                                        type="text"
                                                        value={row[h] || ''}
                                                        onChange={(e) => updateTableCell(tIdx, rIdx, h, e.target.value)}
                                                        style={{ width: '100%', padding: '3px 5px', fontSize: '12px' }}
                                                      />
                                                    </td>
                                                  ))}
                                                  <td style={{ textAlign: 'center', padding: '3px' }}>
                                                    <button
                                                      type="button"
                                                      onClick={() => removeTableRow(tIdx, rIdx)}
                                                      title="Delete row"
                                                      style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#ef4444', fontSize: '12px' }}
                                                    >
                                                      🗑️
                                                    </button>
                                                  </td>
                                                </tr>
                                              ))}
                                            </tbody>
                                          </table>
                                        </div>
                                      </div>
                                    ))}
                                  </div>
                                )}

                                <datalist id="doc-label-suggestions">
                                  {labelSuggestions.map((sug, sIdx) => (
                                    <option key={sIdx} value={sug} />
                                  ))}
                                </datalist>

                                {draftFields.length === 0 && (
                                  <p className="sub">No details extracted.</p>
                                )}

                                {/* 1. Fields & Details */}
                                {fieldsGroup.length > 0 && (
                                  <div style={{ marginBottom: '16px' }}>
                                    <h3 style={{ margin: '14px 0 8px 0', fontSize: '15px' }}>📝 Fields & Details ({fieldsGroup.length})</h3>
                                    {keyDetailsWithIdx.map(({ item, idx }) =>
                                      renderFieldRow(item, idx, false)
                                    )}
                                  </div>
                                )}

                                {/* 2. Lists */}
                                {listsGroup.length > 0 && (
                                  <div style={{ marginBottom: '16px' }}>
                                    <h3 style={{ margin: '16px 0 8px 0', fontSize: '15px' }}>📋 Lists ({listsGroup.length})</h3>
                                    {listsGroup.map(({ item, idx }) =>
                                      renderFieldRow(item, idx, false)
                                    )}
                                  </div>
                                )}

                                {/* 3. Checkboxes & Options */}
                                {checkboxesGroup.length > 0 && (
                                  <div style={{ marginBottom: '16px' }}>
                                    <h3 style={{ margin: '16px 0 8px 0', fontSize: '15px' }}>☑️ Checkboxes & Options ({checkboxesGroup.length})</h3>
                                    {checkboxesGroup.map(({ item, idx }) =>
                                      renderFieldRow(item, idx, false)
                                    )}
                                  </div>
                                )}

                                {/* 4. Signatures & Stamps */}
                                {signaturesGroup.length > 0 && (
                                  <div style={{ marginBottom: '16px' }}>
                                    <h3 style={{ margin: '16px 0 8px 0', fontSize: '15px' }}>✍️ Signatures & Stamps ({signaturesGroup.length})</h3>
                                    {signaturesGroup.map(({ item, idx }) =>
                                      renderFieldRow(item, idx, false)
                                    )}
                                  </div>
                                )}

                                {/* 5. Images & Charts */}
                                {imagesGroup.length > 0 && (
                                  <div style={{ marginBottom: '16px' }}>
                                    <h3 style={{ margin: '16px 0 8px 0', fontSize: '15px' }}>🖼️ Images & Charts ({imagesGroup.length})</h3>
                                    {imagesGroup.map(({ item, idx }) =>
                                      renderFieldRow(item, idx, false)
                                    )}
                                  </div>
                                )}

                                {/* 6. Barcodes & Codes */}
                                {codesGroup.length > 0 && (
                                  <div style={{ marginBottom: '16px' }}>
                                    <h3 style={{ margin: '16px 0 8px 0', fontSize: '15px' }}>📱 Barcodes & Codes ({codesGroup.length})</h3>
                                    {codesGroup.map(({ item, idx }) =>
                                      renderFieldRow(item, idx, false)
                                    )}
                                  </div>
                                )}

                                {/* 7. Attached Table Totals */}
                                {tableTotalsGroup.length > 0 && (
                                  <div style={{ marginBottom: '16px' }}>
                                    <h3 style={{ margin: '16px 0 8px 0', fontSize: '15px' }}>Attached Table Totals ({tableTotalsGroup.length})</h3>
                                    {tableTotalsGroup.map(({ item, idx }) =>
                                      renderFieldRow(item, idx, false)
                                    )}
                                  </div>
                                )}

                                {/* Render Collapsible More Details if present */}
                                {moreDetailsWithIdx.length > 0 && (
                                  <div style={{ marginTop: '16px', borderTop: '1px solid var(--border)', paddingTop: '12px' }}>
                                    <button
                                      type="button"
                                      className="btn"
                                      style={{ width: '100%', textAlign: 'left', display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '8px 12px' }}
                                      onClick={() => setShowMoreDetails((prev) => !prev)}
                                    >
                                      <span>More details ({moreDetailsWithIdx.length})</span>
                                      <span>{showMoreDetails ? '▲ Collapse' : '▼ Expand'}</span>
                                    </button>
                                    {showMoreDetails && (
                                      <div style={{ marginTop: '10px' }}>
                                        {moreDetailsWithIdx.map(({ item, idx }) =>
                                          renderFieldRow(item, idx, true)
                                        )}
                                      </div>
                                    )}
                                  </div>
                                )}
                              </div>
                            );
                          })()}

                          <div className="toolbar" style={{ marginTop: '16px', display: 'flex', gap: '8px', flexWrap: 'wrap', alignItems: 'center' }}>
                            <button id="add" type="button" onClick={addDetailRow}>
                              Add another field
                            </button>
                            <button
                              type="button"
                              className="btn"
                              onClick={() => handleAcceptAllSuggestions(f.id)}
                              title="Accept all generated suggestions into verified"
                            >
                              ✓ Accept all suggestions
                            </button>
                            <button
                              id="sv"
                              type="button"
                              className="pri"
                              onClick={saveChanges}
                            >
                              Save changes
                            </button>
                            <button
                              type="button"
                              className="btn"
                              onClick={() => handleBulkVerifyClean(batch.id)}
                              title="Bulk verify all clean documents in this batch"
                            >
                              ✓ Bulk verify clean documents
                            </button>
                            <button
                              type="button"
                              className="btn"
                              onClick={() => {
                                window.open(api.getCorrectionsExportUrl('csv'), '_blank');
                              }}
                              title="Export all user-reviewed corrections as CSV"
                            >
                              📥 Corrections (CSV)
                            </button>
                            <button
                              type="button"
                              className="btn"
                              onClick={() => {
                                window.open(api.getCorrectionsExportUrl('json'), '_blank');
                              }}
                              title="Export all user-reviewed corrections as JSON"
                            >
                              📥 Corrections (JSON)
                            </button>
                            {savedToast && (
                              <span className="toast">{savedToast}</span>
                            )}
                          </div>
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              );
            })()}
          </div>
        )}
      </main>
    </div>
  );
}
