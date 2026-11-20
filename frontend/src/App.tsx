import React, { useState, useEffect, useCallback } from 'react';
import { BrowserRouter, Routes, Route, useParams, useNavigate } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { Navbar } from './components/Navbar';
import { DashboardView } from './components/DashboardView';
import { UploadDesk } from './components/UploadDesk';
import { MyUploadsView } from './components/MyUploadsView';
import { BatchResultView } from './components/BatchResultView';
import { ReviewQueue } from './components/ReviewQueue';
import { ReviewDetail } from './components/ReviewDetail';
import { AuditSearch } from './components/AuditSearch';
import { ReprocessHub } from './components/ReprocessHub';
import { client, setUserRole, setAuthToken } from './api/client';
import type { DashboardStats } from './types';

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: false } },
});

// LOCAL MODE: set role header and token for local development session
setUserRole('admin');
setAuthToken('7v0xX3WljSa89vceTyNKmhDpPO4_NIJ63jIC3mkAKbo');

type Tab =
  | 'ingest'
  | 'my_uploads'
  | 'batch_detail'
  | 'review'
  | 'audit'
  | 'dashboard'
  | 'reprocess'
  | 'file_history';

// Component for /uploads/:id direct URL route
const BatchPageRoute: React.FC = () => {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();

  if (!id) return <div>No batch specified</div>;

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100">
      <header className="sticky top-0 z-50 border-b border-slate-800 bg-slate-900/90 backdrop-blur-md px-6 py-4 flex items-center justify-between">
        <button
          onClick={() => navigate('/')}
          className="text-sm font-semibold text-teal-400 hover:text-teal-300 flex items-center space-x-2"
        >
          <span>← Back to all uploads</span>
        </button>
        <span className="text-xs px-2 py-0.5 rounded-full bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 font-mono">
          LOCAL MODE
        </span>
      </header>
      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
        <BatchResultView
          batchId={id}
          onReset={() => navigate('/')}
          onNavigateTab={(tab) => navigate(`/?tab=${tab}`)}
        />
      </main>
    </div>
  );
};

const MainShell: React.FC = () => {
  // Default to Upload page for ordinary users
  const [activeTab, setActiveTab] = useState<Tab>('ingest');
  const [activeBatchId, setActiveBatchId] = useState<string | null>(null);
  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [statsError, setStatsError] = useState<string | null>(null);
  const [isRefreshing, setIsRefreshing] = useState(false);

  // Drill-downs
  const [reviewDetailUid, setReviewDetailUid] = useState<string | null>(null);
  const [auditInitialUid, setAuditInitialUid] = useState<string | null>(null);

  const fetchStats = useCallback(async () => {
    setIsRefreshing(true);
    setStatsError(null);
    try {
      const { data, error } = await client.GET('/api/v1/dashboard/metrics');
      if (error) {
        setStatsError(
          typeof error === 'object' && error !== null && 'detail' in error
            ? String((error as { detail: unknown }).detail)
            : 'Failed to load dashboard metrics'
        );
      } else {
        setStats(data as unknown as DashboardStats);
      }
    } catch (e) {
      setStatsError(e instanceof Error ? e.message : 'Network error');
    } finally {
      setIsRefreshing(false);
    }
  }, []);

  // Initial load + 30-second auto-refresh
  useEffect(() => {
    void fetchStats();
    const interval = setInterval(() => {
      void fetchStats();
    }, 30_000);
    return () => clearInterval(interval);
  }, [fetchStats]);

  const handleNavigateTab = (tab: string) => {
    setReviewDetailUid(null);
    setAuditInitialUid(null);
    setActiveTab(tab as Tab);
  };

  const handleSelectBatch = (batchId: string) => {
    setActiveBatchId(batchId);
    setActiveTab('batch_detail');
  };

  const handleOpenReviewDetail = (uid: string) => {
    setReviewDetailUid(uid);
  };

  const handleReviewBack = () => {
    setReviewDetailUid(null);
  };

  const handleReviewActionComplete = () => {
    setReviewDetailUid(null);
    void fetchStats();
  };

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100">
      <Navbar
        activeTab={activeTab}
        setActiveTab={handleNavigateTab}
        stats={stats}
        onRefresh={fetchStats}
        isRefreshing={isRefreshing}
        onSelectBatch={handleSelectBatch}
      />

      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
        {statsError && (
          <div
            role="alert"
            className="mb-4 px-4 py-3 rounded-lg bg-rose-500/10 border border-rose-500/30 text-rose-300 text-sm"
          >
            Dashboard metrics unavailable: {statsError}
          </div>
        )}

        {/* 1. Upload Desk */}
        {activeTab === 'ingest' && (
          <UploadDesk
            onNavigateBatch={(batchId) => handleSelectBatch(batchId)}
            onNavigateTab={handleNavigateTab}
          />
        )}

        {/* 2. My Uploads List */}
        {activeTab === 'my_uploads' && (
          <MyUploadsView
            onSelectBatch={handleSelectBatch}
            onNavigateUpload={() => setActiveTab('ingest')}
          />
        )}

        {/* 3. Batch Detail Page */}
        {activeTab === 'batch_detail' && activeBatchId && (
          <BatchResultView
            batchId={activeBatchId}
            onReset={() => setActiveTab('ingest')}
            onNavigateTab={handleNavigateTab}
            onOpenReviewQueue={() => setActiveTab('review')}
          />
        )}

        {/* 4. Needs a check (Review & Triage) */}
        {activeTab === 'review' && (
          reviewDetailUid ? (
            <ReviewDetail
              uid={reviewDetailUid}
              onBack={handleReviewBack}
              onActionComplete={handleReviewActionComplete}
            />
          ) : (
            <ReviewQueue onOpenDetail={handleOpenReviewDetail} />
          )
        )}

        {/* 5. Find a File (Search) */}
        {activeTab === 'audit' && (
          <AuditSearch initialUid={auditInitialUid} />
        )}

        {/* Admin tools */}
        {activeTab === 'dashboard' && (
          <DashboardView
            stats={stats}
            onNavigateTab={handleNavigateTab}
            onSelectBatch={handleSelectBatch}
          />
        )}

        {activeTab === 'reprocess' && <ReprocessHub />}

        {activeTab === 'file_history' && (
          <AuditSearch initialUid={auditInitialUid} />
        )}
      </main>
    </div>
  );
};

const App: React.FC = () => {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          <Route path="/uploads/:id" element={<BatchPageRoute />} />
          <Route path="*" element={<MainShell />} />
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  );
};

export default App;
