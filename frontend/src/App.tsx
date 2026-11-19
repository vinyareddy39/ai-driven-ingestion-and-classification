import React, { useState, useEffect, useCallback } from 'react';
import { Navbar } from './components/Navbar';
import { DashboardView } from './components/DashboardView';
import { UploadDesk } from './components/UploadDesk';
import { ReviewQueue } from './components/ReviewQueue';
import { ReviewDetail } from './components/ReviewDetail';
import { AuditSearch } from './components/AuditSearch';
import { ReprocessHub } from './components/ReprocessHub';
import { client, setUserRole } from './api/client';
import type { DashboardStats } from './types';

// LOCAL MODE: set role header for all requests
// In production this would be replaced by a real auth token from the IdP.
setUserRole('admin');

type Tab = 'dashboard' | 'ingest' | 'review' | 'audit' | 'reprocess';

const App: React.FC = () => {
  const [activeTab, setActiveTab] = useState<Tab>('dashboard');
  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [statsError, setStatsError] = useState<string | null>(null);
  const [isRefreshing, setIsRefreshing] = useState(false);

  // For drill-down navigation: Review Queue → Review Detail
  const [reviewDetailUid, setReviewDetailUid] = useState<string | null>(null);

  // For drill-down navigation: Dashboard recent doc → Audit detail
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
    const interval = setInterval(() => { void fetchStats(); }, 30_000);
    return () => clearInterval(interval);
  }, [fetchStats]);

  const handleNavigateTab = (tab: string) => {
    setReviewDetailUid(null);
    setAuditInitialUid(null);
    setActiveTab(tab as Tab);
  };

  const handleSelectDocument = (uid: string) => {
    setAuditInitialUid(uid);
    setActiveTab('audit');
  };

  const handleOpenReviewDetail = (uid: string) => {
    setReviewDetailUid(uid);
  };

  const handleReviewBack = () => {
    setReviewDetailUid(null);
  };

  const handleReviewActionComplete = () => {
    setReviewDetailUid(null);
    // Re-fetch stats so the pending_review badge updates
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
      />

      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
        {/* Dashboard stats load error — non-blocking banner */}
        {statsError && (
          <div
            role="alert"
            className="mb-4 px-4 py-3 rounded-lg bg-rose-500/10 border border-rose-500/30 text-rose-300 text-sm"
          >
            Dashboard metrics unavailable: {statsError}
          </div>
        )}

        {activeTab === 'dashboard' && (
          <DashboardView
            stats={stats}
            onNavigateTab={handleNavigateTab}
            onSelectDocument={handleSelectDocument}
          />
        )}

        {activeTab === 'ingest' && <UploadDesk />}

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

        {activeTab === 'audit' && (
          <AuditSearch initialUid={auditInitialUid} />
        )}

        {activeTab === 'reprocess' && <ReprocessHub />}
      </main>
    </div>
  );
};

export default App;
