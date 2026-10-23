'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { adminLogin, adminMe } from '@/lib/api';

export default function AdminLogin() {
  const router = useRouter();
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  // If an HttpOnly admin session already exists, go straight to the dashboard.
  // The cookie is invisible to JavaScript by design, so ask the API instead of
  // reading a token from localStorage (there no longer is one).
  useEffect(() => {
    let cancelled = false;
    adminMe()
      .then(() => {
        if (!cancelled) router.replace('/admin/dashboard');
      })
      .catch(() => {
        /* no session - stay on the login form */
      });
    return () => {
      cancelled = true;
    };
  }, [router]);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      await adminLogin(password);
      router.replace('/admin/dashboard');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Login failed');
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="admin-auth">
      <div className="admin-auth-card">
        <div className="admin-logo">
          <span className="admin-logo-dot" />
          Ketsa
        </div>
        <h1 className="admin-auth-title">Admin login</h1>
        <p className="admin-auth-sub">Enter your admin password to manage the site.</p>

        <form onSubmit={onSubmit} className="admin-form">
          <label className="admin-label" htmlFor="admin-pass">
            Password
          </label>
          <input
            id="admin-pass"
            type="password"
            className="admin-input"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="••••••••"
            autoFocus
            required
          />
          {error && <div className="admin-error">{error}</div>}
          <button type="submit" className="admin-btn admin-btn--primary" disabled={loading}>
            {loading ? 'Signing in…' : 'Sign in'}
          </button>
        </form>
      </div>
    </div>
  );
}
