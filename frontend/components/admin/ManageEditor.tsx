'use client';

import { useState } from 'react';
import { adminPost } from '@/lib/api';
import { Card, DangerButton } from './ui';

export default function ManageEditor() {
  const [error, setError] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);

  async function resetContent() {
    setError(null);
    setMsg(null);
    try {
      await adminPost('/reset', {});
      setMsg('Content reset to the backend defaults.');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Reset failed');
    }
  }

  return (
    <div className="admin-stack">
      {error && <div className="admin-error">{error}</div>}
      {msg && <div className="admin-saved-msg">{msg}</div>}

      <Card title="Danger zone">
        <p className="admin-muted">
          Reset every market, watch, ticker, dashboard series, stats, proof and
          site setting back to the default content held by the backend. Your
          stored admin password is kept.
        </p>
        <div className="admin-form-actions">
          <DangerButton onConfirm={resetContent} label="Reset content to defaults" />
        </div>
      </Card>

      <Card title="Admin password">
        <p className="admin-muted">
          The admin password now lives under{' '}
          <strong>Settings → Security</strong>, alongside the login lockout
          controls.
        </p>
      </Card>
    </div>
  );
}
