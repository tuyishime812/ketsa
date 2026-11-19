'use client';

import { useCallback, useEffect, useState } from 'react';
import {
  approveWithdrawal,
  listAdminWithdrawals,
  rejectWithdrawal,
  AdminApiError,
} from '@/lib/api';
import type { Payment } from '@/lib/types';
import { Card } from './ui';

function fmtDate(ts?: number | null): string {
  if (!ts) return '—';
  return new Date(ts * 1000).toLocaleString(undefined, {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function fmtMoney(n?: number | null): string {
  return (n ?? 0).toLocaleString(undefined, { maximumFractionDigits: 2 });
}

function label(status: string): string {
  if (status === 'pending_approval') return 'Awaiting approval';
  if (status === 'rejected') return 'Rejected';
  if (status === 'pending') return 'Processing';
  if (status === 'completed') return 'Completed';
  if (status === 'failed') return 'Failed';
  return status;
}

export default function WithdrawalsEditor({ canManage }: { canManage: boolean }) {
  const [rows, setRows] = useState<Payment[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [filter, setFilter] = useState<string>('pending_approval');
  const [busyId, setBusyId] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      setRows(await listAdminWithdrawals(filter));
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load withdrawals');
    }
  }, [filter]);

  useEffect(() => {
    void load();
  }, [load]);

  async function onApprove(id: string) {
    setError(null);
    setMsg(null);
    setBusyId(id);
    try {
      await approveWithdrawal(id);
      setMsg('Withdrawal approved and sent for payout.');
      await load();
    } catch (err) {
      setError(err instanceof AdminApiError ? err.message : 'Failed to approve withdrawal');
    } finally {
      setBusyId(null);
    }
  }

  async function onReject(id: string) {
    const reason = window.prompt('Reason for rejection (optional):') || undefined;
    setError(null);
    setMsg(null);
    setBusyId(id);
    try {
      await rejectWithdrawal(id, reason);
      setMsg('Withdrawal rejected and refunded to the user.');
      await load();
    } catch (err) {
      setError(err instanceof AdminApiError ? err.message : 'Failed to reject withdrawal');
    } finally {
      setBusyId(null);
    }
  }

  return (
    <div className="admin-stack">
      {error && <div className="admin-error">{error}</div>}
      {msg && <div className="admin-saved-msg">{msg}</div>}

      <Card title="Withdrawal requests">
        <p className="admin-muted">
          User withdrawal requests are held until an administrator approves them.
          Approving sends the payout to mobile money; rejecting refunds the
          reserved funds to the user&apos;s balance.
        </p>

        <div style={{ marginTop: 14, display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
          <span className="admin-field-label">Show</span>
          <select
            className="admin-input admin-select"
            style={{ width: 220 }}
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
          >
            <option value="pending_approval">Awaiting approval</option>
            <option value="pending">Processing (payout in flight)</option>
            <option value="completed">Completed</option>
            <option value="rejected">Rejected</option>
            <option value="failed">Failed</option>
            <option value="all">All</option>
          </select>
          <button type="button" className="admin-btn admin-btn--ghost" onClick={() => void load()}>
            Refresh
          </button>
        </div>

        <div className="admin-table-wrap" style={{ marginTop: 14 }}>
          <table className="admin-table">
            <thead>
              <tr>
                <th>Requested</th>
                <th>Wallet</th>
                <th>Amount (MWK)</th>
                <th>Destination</th>
                <th>Status</th>
                <th>Message</th>
                <th className="admin-actions">Actions</th>
              </tr>
            </thead>
            <tbody>
              {rows === null && (
                <tr>
                  <td colSpan={7} className="admin-muted">Loading withdrawals…</td>
                </tr>
              )}
              {rows !== null && rows.length === 0 && (
                <tr>
                  <td colSpan={7} className="admin-muted">No withdrawals in this view.</td>
                </tr>
              )}
              {rows !== null &&
                rows.map((p) => (
                  <tr key={p.id}>
                    <td className="admin-mono">{fmtDate(p.created)}</td>
                    <td className="admin-mono" title={p.wallet_id}>
                      {p.wallet_id.slice(0, 10)}…
                    </td>
                    <td className="admin-mono">{fmtMoney(p.amount)}</td>
                    <td>
                      <div className="admin-td-name">{p.correspondent.replace('_MWI', '')}</div>
                      <div className="admin-td-sub admin-mono">{p.number}</div>
                    </td>
                    <td>
                      <span className="admin-pill">{label(p.status)}</span>
                    </td>
                    <td className="admin-td-sub" title={p.message || undefined}>
                      {p.message || '—'}
                    </td>
                    <td className="admin-actions">
                      {p.status === 'pending_approval' && canManage ? (
                        <>
                          <button
                            type="button"
                            className="admin-btn admin-btn--primary"
                            disabled={busyId === p.id}
                            onClick={() => void onApprove(p.id)}
                          >
                            {busyId === p.id ? 'Working…' : 'Approve'}
                          </button>
                          <button
                            type="button"
                            className="admin-btn admin-btn--ghost"
                            disabled={busyId === p.id}
                            onClick={() => void onReject(p.id)}
                          >
                            Reject
                          </button>
                        </>
                      ) : (
                        <span className="admin-muted">—</span>
                      )}
                    </td>
                  </tr>
                ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}
