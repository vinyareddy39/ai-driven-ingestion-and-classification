import React from 'react';
import { BrowserRouter, Route, Routes } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { Shell } from './components/Shell';
import { DashboardPage } from './pages/DashboardPage';
import { ReviewQueuePage } from './pages/ReviewQueuePage';
import { ReviewDetailPage } from './pages/ReviewDetailPage';
import { UploadPage } from './pages/UploadPage';
import { DocumentsListPage } from './pages/DocumentsListPage';
import { DocumentCompliancePage } from './pages/DocumentCompliancePage';
import { ReprocessPage } from './pages/ReprocessPage';
import { AdminPage } from './pages/AdminPage';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      refetchOnWindowFocus: false,
    },
  },
});

export const App: React.FC = () => {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<Shell />}>
            <Route index element={<DashboardPage />} />
            <Route path="review" element={<ReviewQueuePage />} />
            <Route path="review/:documentUid" element={<ReviewDetailPage />} />
            <Route path="upload" element={<UploadPage />} />
            <Route path="documents" element={<DocumentsListPage />} />
            <Route path="compliance/:documentUid" element={<DocumentCompliancePage />} />
            <Route path="reprocess" element={<ReprocessPage />} />
            <Route path="admin" element={<AdminPage />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  );
};
