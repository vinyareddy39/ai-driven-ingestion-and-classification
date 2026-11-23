import React, { useState } from 'react';
import { BASE_URL, setAuthToken, setUserRole, setUserEmail } from '../api/client';

interface LoginViewProps {
  onLoginSuccess: (user: { email: string; role: string }) => void;
}

export const LoginView: React.FC<LoginViewProps> = ({ onLoginSuccess }) => {
  const [email, setEmail] = useState('admin@example.com');
  const [password, setPassword] = useState('AdminPass123!');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setLoading(true);

    try {
      const res = await fetch(`${BASE_URL}/api/v1/auth/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: jsonBody({ email, password }),
      });

      if (!res.ok) {
        throw new Error("That email or password isn't right. Try again.");
      }

      const data = await res.json();
      setAuthToken(data.access_token);

      // Fetch user profile
      const meRes = await fetch(`${BASE_URL}/api/v1/auth/me`, {
        headers: { Authorization: `Bearer ${data.access_token}` },
      });

      let role = 'admin';
      let userEmail = email;
      if (meRes.ok) {
        const meData = await meRes.json();
        role = meData.role || 'admin';
        userEmail = meData.email || email;
      }

      setUserRole(role);
      setUserEmail(userEmail);
      onLoginSuccess({ email: userEmail, role });
    } catch (err: any) {
      setError(err.message || "That email or password isn't right. Try again.");
    } finally {
      setLoading(false);
    }
  };

  function jsonBody(obj: any) {
    return JSON.stringify(obj);
  }

  return (
    <div className="wrap" style={{ maxWidth: 440, marginTop: 40 }}>
      <div className="app">
        <div className="topbar">
          <span className="logo">DocSort</span>
          <span style={{ color: 'var(--text2)', fontSize: 13 }}>Sign in</span>
        </div>
        <div className="body">
          <div className="head" style={{ marginBottom: 20 }}>
            <h1>Sign in to DocSort</h1>
          </div>

          <form onSubmit={handleSubmit}>
            <div style={{ marginBottom: 14 }}>
              <label>Email address</label>
              <input
                type="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="name@example.com"
                disabled={loading}
              />
            </div>

            <div style={{ marginBottom: 16 }}>
              <label>Password</label>
              <input
                type="password"
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="••••••••"
                disabled={loading}
              />
              {error && <p className="hint red" style={{ marginTop: 6 }}>{error}</p>}
            </div>

            <button type="submit" className="primary" style={{ width: '100%' }} disabled={loading}>
              {loading ? 'Signing in…' : 'Sign in'}
            </button>
          </form>
        </div>
      </div>
    </div>
  );
};
