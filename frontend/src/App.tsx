import React, { useState, useEffect } from 'react';
import {
  BASE_URL,
  getAuthToken,
  setAuthToken,
  getUserEmail,
  setUserEmail,
  getUserRole,
  setUserRole,
} from './api/client';
import { LoginView } from './components/LoginView';
import { DashboardView } from './components/DashboardView';
import { UploadView } from './components/UploadView';
import { ReviewQueueView } from './components/ReviewQueueView';
import { BatchResultView } from './components/BatchResultView';

type Screen = 'dashboard' | 'upload' | 'review' | 'results';

export const App: React.FC = () => {
  const [user, setUser] = useState<{ email: string; role: string } | null>(null);
  const [currentScreen, setCurrentScreen] = useState<Screen>('dashboard');
  const [selectedBatchId, setSelectedBatchId] = useState<string | null>(null);
  const [isInitializing, setIsInitializing] = useState(true);

  // Check existing session on mount
  useEffect(() => {
    const initAuth = async () => {
      const token = getAuthToken();
      if (!token) {
        setIsInitializing(false);
        return;
      }

      try {
        const res = await fetch(`${BASE_URL}/api/v1/auth/me`, {
          headers: { Authorization: `Bearer ${token}` },
        });

        if (res.ok) {
          const data = await res.json();
          setUser({ email: data.email || getUserEmail() || 'admin@ecm.local', role: data.role || getUserRole() || 'admin' });
        } else {
          setAuthToken(null);
          setUser(null);
        }
      } catch {
        setUser({ email: getUserEmail() || 'admin@ecm.local', role: getUserRole() || 'admin' });
      } finally {
        setIsInitializing(false);
      }
    };

    initAuth();
  }, []);

  const handleLogout = () => {
    setAuthToken(null);
    setUserRole(null);
    setUserEmail(null);
    setUser(null);
    setCurrentScreen('dashboard');
    setSelectedBatchId(null);
  };

  const handleLoginSuccess = (loggedInUser: { email: string; role: string }) => {
    setUser(loggedInUser);
    setCurrentScreen('dashboard');
  };

  const handleSelectBatch = (batchId: string) => {
    setSelectedBatchId(batchId);
    setCurrentScreen('results');
  };

  if (isInitializing) {
    return (
      <div className="wrap" style={{ maxWidth: 440, marginTop: 40, textAlign: 'center' }}>
        <div className="empty">Loading DocSort…</div>
      </div>
    );
  }

  // Screen 0: Login if not authenticated
  if (!user) {
    return <LoginView onLoginSuccess={handleLoginSuccess} />;
  }

  const roleDisplay = user.role.charAt(0).toUpperCase() + user.role.slice(1);
  const userName = user.email.split('@')[0];

  return (
    <div className="wrap">
      <div className="app">
        {/* Topbar for Dashboard, Upload, Results */}
        {currentScreen !== 'review' && (
          <div className="topbar">
            <span className="logo" onClick={() => setCurrentScreen('dashboard')}>
              DocSort
            </span>
            <span className="who" style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              {currentScreen === 'dashboard' ? (
                <span>
                  {userName} · {roleDisplay}
                </span>
              ) : (
                <button
                  className="link"
                  onClick={() => setCurrentScreen('dashboard')}
                  style={{ textDecoration: 'none', color: 'var(--text2)', padding: 0 }}
                >
                  Back to dashboard
                </button>
              )}
              <button
                className="link"
                onClick={handleLogout}
                style={{ color: 'var(--text3)', fontSize: 13, textDecoration: 'underline', padding: 0 }}
              >
                Sign out
              </button>
            </span>
          </div>
        )}

        {/* Screens */}
        {currentScreen === 'dashboard' && (
          <DashboardView
            onNavigateUpload={() => setCurrentScreen('upload')}
            onNavigateReview={() => setCurrentScreen('review')}
            onSelectBatch={handleSelectBatch}
          />
        )}

        {currentScreen === 'upload' && (
          <UploadView
            onBack={() => setCurrentScreen('dashboard')}
            onViewResults={(bId) => {
              setSelectedBatchId(bId);
              setCurrentScreen('results');
            }}
          />
        )}

        {currentScreen === 'review' && (
          <ReviewQueueView
            onBack={() => setCurrentScreen('dashboard')}
            onFinished={() => setCurrentScreen('dashboard')}
          />
        )}

        {currentScreen === 'results' && selectedBatchId && (
          <BatchResultView
            batchId={selectedBatchId}
            onBack={() => setCurrentScreen('dashboard')}
          />
        )}
      </div>
    </div>
  );
};

export default App;
