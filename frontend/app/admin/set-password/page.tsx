'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { acceptStaffInvite } from '@/lib/api';

const MIN_PASSWORD_LENGTH = 8;

export default function SetPasswordPage() {
  const router = useRouter();
  const [token, setToken] = useState('');
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    // Tokens are emailed in the URL fragment (`#token=...`), which browsers
    // never send to the server, its access logs, or as a Referer. We also
    // accept a legacy `?token=` link and strip it the same way.
    const params = new URLSearchParams(window.location.search);
    const hash = new URLSearchParams(window.location.hash.replace(/^#/, ''));
    const value = hash.get('token') ?? params.get('token') ?? '';
    setToken(value);
    if (!value) {
      setError('This link is missing its token. Ask an admin for a new one.');
    }
    // Strip the single-use token from the address bar/history immediately: it
    // has done its job by being read, and leaving it in history extends its
    // exposure.
    if (value) {
      params.delete('token');
      hash.delete('token');
      const query = params.toString();
      const fragment = hash.toString();
      window.history.replaceState(
        null,
        '',
        `${window.location.pathname}${query ? `?${query}` : ''}${
          fragment ? `#${fragment}` : ''
        }`,
      );
    }
  }, []);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    if (!token) {
      setError('This link is missing its token. Ask an admin for a new one.');
      return;
    }
    if (password.length < MIN_PASSWORD_LENGTH) {
      setError(`Password must be at least ${MIN_PASSWORD_LENGTH} characters.`);
      return;
    }
    if (password !== confirm) {
      setError('The two passwords do not match.');
      return;
    }
    setLoading(true);
    try {
      await acceptStaffInvite(token, password);
      setPassword('');
      setConfirm('');
      setDone(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not set your password');
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
        <h1 className="admin-auth-title">Set your password</h1>

        {done ? (
          <>
            <p className="admin-auth-sub">
              Your password is set. You can now sign in to the admin panel with
              your email and new password.
            </p>
            <button
              type="button"
              className="admin-btn admin-btn--primary"
              onClick={() => router.replace('/admin')}
            >
              Go to sign in
            </button>
          </>
        ) : (
          <>
            <p className="admin-auth-sub">
              Choose a password for your staff admin account. This link can only
              be used once.
            </p>
            <form onSubmit={onSubmit} className="admin-form">
              <label className="admin-label" htmlFor="set-pass">
                New password
              </label>
              <input
                id="set-pass"
                type="password"
                className="admin-input"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="At least 8 characters"
                autoComplete="new-password"
                minLength={MIN_PASSWORD_LENGTH}
                autoFocus
                required
              />
              <label className="admin-label" htmlFor="set-pass-confirm">
                Confirm password
              </label>
              <input
                id="set-pass-confirm"
                type="password"
                className="admin-input"
                value={confirm}
                onChange={(e) => setConfirm(e.target.value)}
                placeholder="Repeat the password"
                autoComplete="new-password"
                minLength={MIN_PASSWORD_LENGTH}
                required
              />
              {error && <div className="admin-error">{error}</div>}
              <button
                type="submit"
                className="admin-btn admin-btn--primary"
                disabled={loading || !token}
              >
                {loading ? 'Saving…' : 'Set password'}
              </button>
            </form>
          </>
        )}
      </div>
    </div>
  );
}
