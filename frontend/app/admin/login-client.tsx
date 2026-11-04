'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { adminLogin, adminMe, requestStaffPasswordReset } from '@/lib/api';

type Mode = 'staff' | 'owner';

export default function AdminLogin() {
  const router = useRouter();
  const [mode, setMode] = useState<Mode>('staff');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  // Forgot-password (staff accounts only).
  const [forgotOpen, setForgotOpen] = useState(false);
  const [forgotEmail, setForgotEmail] = useState('');
  const [forgotMsg, setForgotMsg] = useState<string | null>(null);
  const [forgotBusy, setForgotBusy] = useState(false);

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

  function switchMode(next: Mode) {
    setMode(next);
    setError(null);
    setPassword('');
    setForgotOpen(false);
    setForgotMsg(null);
  }

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      await adminLogin(password, mode === 'staff' ? email : undefined);
      router.replace('/admin/dashboard');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Login failed');
    } finally {
      setLoading(false);
    }
  }

  async function onForgot(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setForgotMsg(null);
    const address = (forgotEmail || email).trim();
    if (!address) {
      setError('Enter your staff email address first.');
      return;
    }
    setForgotBusy(true);
    try {
      // The backend answers identically for known and unknown addresses, so we
      // can only truthfully say "if that account exists".
      await requestStaffPasswordReset(address);
      setForgotMsg(
        'If that email belongs to a staff account, a reset link has been sent. Check your inbox.',
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not request a reset link');
    } finally {
      setForgotBusy(false);
    }
  }

  const isStaff = mode === 'staff';

  return (
    <div className="admin-auth">
      <div className="admin-auth-card">
        <div className="admin-logo">
          <span className="admin-logo-dot" />
          Ketsa
        </div>
        <h1 className="admin-auth-title">Admin login</h1>
        <p className="admin-auth-sub">
          {isStaff
            ? 'Sign in with your staff email and password.'
            : 'Enter the owner password to manage the site.'}
        </p>

        <div className="admin-auth-tabs" role="tablist" aria-label="Login type">
          <button
            type="button"
            role="tab"
            aria-selected={isStaff}
            className={`admin-auth-tab ${isStaff ? 'is-active' : ''}`}
            onClick={() => switchMode('staff')}
          >
            Staff account
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={!isStaff}
            className={`admin-auth-tab ${!isStaff ? 'is-active' : ''}`}
            onClick={() => switchMode('owner')}
          >
            Owner
          </button>
        </div>

        <form onSubmit={onSubmit} className="admin-form">
          {isStaff && (
            <>
              <label className="admin-label" htmlFor="admin-email">
                Email
              </label>
              <input
                id="admin-email"
                type="email"
                className="admin-input"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="you@ketsa.io"
                autoComplete="username"
                autoFocus
                required
              />
            </>
          )}

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
            autoComplete={isStaff ? 'current-password' : 'current-password'}
            autoFocus={!isStaff}
            required
          />
          {error && <div className="admin-error">{error}</div>}
          <button type="submit" className="admin-btn admin-btn--primary" disabled={loading}>
            {loading ? 'Signing in…' : 'Sign in'}
          </button>
        </form>

        {isStaff && (
          <div className="admin-auth-help">
            {!forgotOpen ? (
              <button
                type="button"
                className="admin-link-btn"
                onClick={() => {
                  setForgotOpen(true);
                  setForgotEmail(email);
                  setForgotMsg(null);
                }}
              >
                Forgot your password?
              </button>
            ) : (
              <form onSubmit={onForgot} className="admin-form admin-form--compact">
                <label className="admin-label" htmlFor="admin-forgot-email">
                  Staff email
                </label>
                <input
                  id="admin-forgot-email"
                  type="email"
                  className="admin-input"
                  value={forgotEmail}
                  onChange={(e) => setForgotEmail(e.target.value)}
                  placeholder="you@ketsa.io"
                  autoComplete="username"
                  required
                />
                {forgotMsg && <div className="admin-muted">{forgotMsg}</div>}
                <div className="admin-auth-help-row">
                  <button
                    type="submit"
                    className="admin-btn admin-btn--ghost"
                    disabled={forgotBusy}
                  >
                    {forgotBusy ? 'Sending…' : 'Email reset link'}
                  </button>
                  <button
                    type="button"
                    className="admin-link-btn"
                    onClick={() => {
                      setForgotOpen(false);
                      setForgotMsg(null);
                    }}
                  >
                    Cancel
                  </button>
                </div>
              </form>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
