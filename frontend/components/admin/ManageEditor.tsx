'use client';

import { useState } from 'react';
import { adminPost } from '@/lib/api';
import { Card, DangerButton, Field, TextInput } from './ui';

export default function ManageEditor({ token }: { token: string }) {
  const [current, setCurrent] = useState('');
  const [next, setNext] = useState('');
  const [confirm, setConfirm] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);

  async function changePassword() {
    setError(null);
    setMsg(null);
    if (next.length < 8) {
      setError('New password must be at least 8 characters');
      return;
    }
    if (next !== confirm) {
      setError('New passwords do not match');
      return;
    }
    try {
      await adminPost(token, '/password', { current, new: next });
      setCurrent('');
      setNext('');
      setConfirm('');
      setMsg('Password updated.');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Password change failed');
    }
  }

  async function resetContent() {
    setError(null);
    setMsg(null);
    try {
      await adminPost(token, '/reset', {});
      setMsg('Content reset to the seed defaults.');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Reset failed');
    }
  }

  return (
    <div className="admin-stack">
      {error && <div className="admin-error">{error}</div>}
      {msg && <div className="admin-saved-msg">{msg}</div>}

      <Card title="Change admin password">
        <p className="admin-muted">
          The new password is hashed and stored in the backend, and takes effect
          immediately (replacing the environment value).
        </p>
        <div style={{ marginTop: 14 }} className="admin-grid admin-grid--2">
          <Field label="Current password">
            <TextInput type="password" value={current} onChange={setCurrent} placeholder="••••••••" />
          </Field>
          <div className="admin-field" />
          <Field label="New password" hint="At least 8 characters">
            <TextInput type="password" value={next} onChange={setNext} placeholder="••••••••" />
          </Field>
          <Field label="Confirm new password">
            <TextInput type="password" value={confirm} onChange={setConfirm} placeholder="••••••••" />
          </Field>
        </div>
        <div className="admin-form-actions">
          <button type="button" className="admin-btn admin-btn--primary" onClick={changePassword}>
            Change password
          </button>
        </div>
      </Card>

      <Card title="Danger zone">
        <p className="admin-muted">
          Reset every market, watch, ticker, dashboard series, stats, proof and
          site setting back to the bundled seed defaults. Your stored admin
          password is kept.
        </p>
        <div className="admin-form-actions">
          <DangerButton onConfirm={resetContent} label="Reset content to defaults" />
        </div>
      </Card>
    </div>
  );
}