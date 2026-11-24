import React, { useEffect, useRef, useState } from 'react';
import { api, BatchItem, FieldItem, FileItem, User } from './api/client';

type ViewMode = 'auth' | 'dash' | 'proc' | 'results' | 'view';

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
  const [savedToast, setSavedToast] = useState('');

  // Initial auth check
  useEffect(() => {
    const token = localStorage.getItem('token');
    if (token) {
      api
        .getMe()
        .then((u) => {
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
          setUser(null);
          setView('auth');
        });
    } else {
      setUser(null);
      setView('auth');
    }
  }, []);

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
    setView('auth');
  };

  // Upload Handlers
  const handleFilesSelected = async (fileList: FileList | null) => {
    if (!fileList || fileList.length === 0) return;
    setIsUploading(true);
    try {
      const filesArray = Array.from(fileList);
      const res = await api.uploadBatch(filesArray);
      setCurrentBatchId(res.id);

      // Immediately fetch batch state and switch to proc
      const initialBatch = await api.getBatch(res.id);
      setBatch(initialBatch);
      setView('proc');
    } catch (err: any) {
      alert(`Upload error: ${err.message}`);
    } finally {
      setIsUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = '';
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

  // Open View Screen
  const openView = (index: number) => {
    if (!batch || !batch.files[index]) return;
    setActiveFileIndex(index);
    const f = batch.files[index];
    setDraftFields(f.fields.map((x) => ({ ...x })));
    setSavedToast('');
    setView('view');
  };

  // View Screen Field operations
  const updateDraft = (i: number, key: 'label' | 'value', val: string) => {
    setDraftFields((prev) => {
      const copy = [...prev];
      copy[i] = { ...copy[i], [key]: val };
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
      { label: '', value: '', orig: '', conf: 1.0, src: 'added' },
    ]);
    setSavedToast('');
  };

  const saveChanges = async () => {
    if (!batch || !batch.files[activeFileIndex]) return;
    const file = batch.files[activeFileIndex];

    const cleanFields = draftFields.filter(
      (x) => x.label.trim() || x.value.trim()
    );
    const updated = cleanFields.map((x) => {
      const orig = x.orig !== undefined ? x.orig : x.value;
      let src = x.src || 'read';
      if (src === 'read' && x.value !== orig) src = 'edited';
      else if (src === 'edited' && x.value === orig) src = 'read';
      return { ...x, orig, src };
    });

    try {
      const res = await api.updateFields(file.id, updated);
      // Refresh batch data
      const refreshedBatch = await api.getBatch(batch.id);
      setBatch(refreshedBatch);
      setDraftFields(updated);
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
    setDraftFields(f.fields.map((x) => ({ ...x })));
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
      // Immediately switch back to processing screen to watch it re-scan live
      setView('proc');
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
      {/* Header bar matching demo */}
      <header className="bar">
        <b>Document Reader</b>
        <span className="sp"></span>
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
              Add one or more files. Each one is read from scratch.
            </p>
            <div
              className={`drop ${isDragOver ? 'drag-over' : ''}`}
              onDragOver={(e) => {
                e.preventDefault();
                setIsDragOver(true);
              }}
              onDragLeave={() => setIsDragOver(false)}
              onDrop={(e) => {
                e.preventDefault();
                setIsDragOver(false);
                handleFilesSelected(e.dataTransfer.files);
              }}
            >
              <p>Drop files here, or choose them from your computer.</p>
              <input
                type="file"
                multiple
                ref={fileInputRef}
                style={{ display: 'none' }}
                onChange={(e) => handleFilesSelected(e.target.files)}
              />
              <button
                id="up"
                className="pri"
                type="button"
                disabled={isUploading}
                onClick={() => fileInputRef.current?.click()}
              >
                {isUploading ? 'Uploading...' : 'Choose files'}
              </button>
            </div>
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
              {batch.done_count} of {batch.files.length} files finished
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
                      {f.dup && f.stage !== 'Waiting' && (
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
                const t = f.type || 'Document';
                if (!groups[t]) groups[t] = [];
                groups[t].push(i);
              });

              return Object.keys(groups).map((g) => {
                const idxs = groups[g];
                // Columns are ONLY the union of labels found in this group
                const cols: string[] = [];
                idxs.forEach((i) => {
                  batch.files[i].fields.forEach((x) => {
                    if (!cols.includes(x.label)) cols.push(x.label);
                  });
                });

                return (
                  <div className="grp" key={g}>
                    <h2>
                      {g}
                      <span>{idxs.length}</span>
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
                            <th></th>
                          </tr>
                        </thead>
                        <tbody>
                          {idxs.map((i) => {
                            const f = batch.files[i];
                            const isLow = f.fields.some(
                              (x) => (x.conf ?? 1.0) < 0.85
                            );
                            const pillClass =
                              f.status === 'Done'
                                ? 'ok'
                                : f.status === 'Done, check'
                                ? 'warn'
                                : 'bad';
                            return (
                              <tr key={f.id}>
                                <td>
                                  {f.name}
                                  {f.dup && (
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
                                      —
                                    </td>
                                  );
                                })}
                                <td>
                                  <span className={`pill ${pillClass}`}>
                                    {f.status}
                                  </span>
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
                    {f.dup
                      ? `. Same content as ${f.dup}, read again.`
                      : ''}
                  </p>

                  {f.fields.some((x) => x.value?.toLowerCase().includes('rate limit')) && (
                    <div
                      style={{
                        margin: '14px 0 18px 0',
                        padding: '12px 16px',
                        backgroundColor: 'rgba(234, 179, 8, 0.12)',
                        border: '1px solid #eab308',
                        borderRadius: '8px',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'space-between',
                      }}
                    >
                      <div style={{ color: '#fef08a' }}>
                        ⚠️ <strong>Rate limit reached during scan.</strong> Click to edit details manually below, or click <strong>Do again</strong> to re-run AI extraction automatically.
                      </div>
                      <button
                        className="btn"
                        style={{
                          backgroundColor: '#eab308',
                          color: '#000000',
                          fontWeight: 600,
                          padding: '6px 14px',
                          marginLeft: '12px',
                          whiteSpace: 'nowrap',
                        }}
                        onClick={() => handleDoAgain(f.id)}
                      >
                        Do again
                      </button>
                    </div>
                  )}

                  <div className="split">
                    {/* Left Panel: Real Document Page Image */}
                    <div className="paperbox">
                      <div className="paper-viewer">
                        <img
                          src={api.getPageImageUrl(f.id, 1)}
                          alt={`Original document ${f.name}`}
                        />
                      </div>
                      <div className="cap">
                        Original page. Page condition detected: {f.cond}.
                      </div>
                    </div>

                    {/* Right Panel: Editable Details Found */}
                    <div className="card">
                      <h2>Details found</h2>
                      {draftFields.length === 0 && (
                        <p className="sub">No details extracted.</p>
                      )}
                      {draftFields.map((x, i) => {
                        const confPct = Math.round((x.conf ?? 1.0) * 100);
                        const isLow = (x.conf ?? 1.0) < 0.85;
                        return (
                          <div className="fr" key={i}>
                            <input
                              value={x.label}
                              onChange={(e) =>
                                updateDraft(i, 'label', e.target.value)
                              }
                              placeholder="Detail name"
                              aria-label="Detail name"
                            />
                            <input
                              value={x.value}
                              onChange={(e) =>
                                updateDraft(i, 'value', e.target.value)
                              }
                              placeholder="Value"
                              aria-label="Value"
                            />
                            <button
                              type="button"
                              onClick={() => removeDraftRow(i)}
                              aria-label={`Remove ${x.label || 'detail'}`}
                            >
                              Remove
                            </button>
                            <div className="meta">
                              {x.src !== 'added' && (
                                <span>Read with {confPct}% confidence</span>
                              )}
                              {isLow && (
                                <span className="pill warn">check this</span>
                              )}
                              {x.src === 'edited' && (
                                <span className="pill warn">edited</span>
                              )}
                              {x.src === 'added' && (
                                <span className="pill warn">added</span>
                              )}
                            </div>
                          </div>
                        );
                      })}

                      <div className="toolbar" style={{ marginTop: '12px' }}>
                        <button id="add" type="button" onClick={addDetailRow}>
                          Add a detail
                        </button>
                        <button
                          id="sv"
                          type="button"
                          className="pri"
                          onClick={saveChanges}
                        >
                          Save changes
                        </button>
                        {savedToast && (
                          <span className="toast">{savedToast}</span>
                        )}
                      </div>
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
