'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { adminLogin } from '@/lib/api';

const TOKEN_KEY = 'ketsa_admin_token';

function readStoredToken(): string | null {
  if (typeof window === 'undefined') return null;
  return window.localStorage.getItem(TOKEN_KEY);
}

export function setStoredToken(token: string) {
  if (typeof window === 'undefined') return;
  window.localStorage.setItem(TOKEN_KEY, token);
}

export function clearStoredToken() {
  if (typeof window === 'undefined') return;
  window.localStorage.removeItem(TOKEN_KEY);
}

export function getStoredToken(): string | null {
  return readStoredToken();
}

export default function AdminLogin() {
  const router = useRouter();
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  // If already logged in, go straight to the dashboard.
  useEffect(() => {
    if (readStoredToken()) {
      router.replace('/admin/dashboard');
    }
  }, [router]);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      const token = await adminLogin(password);
      setStoredToken(token);
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
