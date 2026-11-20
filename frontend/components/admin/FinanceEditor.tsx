'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import { adminGet, getAdminFinanceSummary, listAdminPayments } from '@/lib/api';
import type { AdminFinanceSummary, AdminUserView, Payment } from '@/lib/types';
import { Card } from './ui';

function fmtDate(ts?: number | null): string {
  if (!ts) return '—';
  // payment timestamps are unix seconds; user timestamps may be ms in some views but AdminUserView.created is ms-like in UsersEditor (uses new Date(ts))
  const ms = ts > 1_000_000_000_000 ? ts : ts * 1000;
  return new Date(ms).toLocaleString(undefined, {
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

function paymentLabel(status: string): string {
  if (status === 'pending_approval') return 'Awaiting approval';
  if (status === 'rejected') return 'Rejected';
  if (status === 'pending') return 'Pending/processing';
  if (status === 'completed') return 'Completed';
  if (status === 'failed') return 'Failed';
  return status;
}

function Stat({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="admin-card" style={{ margin: 0 }}>
      <div className="admin-field-label">{label}</div>
      <div style={{ fontSize: 22, fontWeight: 700, marginTop: 4 }}>{value}</div>
      {sub ? <div className="admin-muted" style={{ marginTop: 4 }}>{sub}</div> : null}
    </div>
  );
}

export default function FinanceEditor() {
  const [summary, setSummary] = useState<AdminFinanceSummary | null>(null);
  const [payments, setPayments] = useState<Payment[] | null>(null);
  const [users, setUsers] = useState<AdminUserView[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [kind, setKind] = useState<string>('all');
  const [status, setStatus] = useState<string>('all');
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setError(null);
    setLoading(true);
    try {
      const [s, p, u] = await Promise.all([
        getAdminFinanceSummary(),
        listAdminPayments(kind, status),
        adminGet<AdminUserView[]>('/users'),
      ]);
      setSummary(s);
      setPayments(p);
      setUsers(u);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load finance data');
    } finally {
      setLoading(false);
    }
  }, [kind, status]);

  useEffect(() => {
    void load();
  }, [load]);

  const topUsers = useMemo(() => {
    if (!users) return [];
    return [...users]
      .sort((a, b) => (b.deposits_total || 0) - (a.deposits_total || 0) || (b.wallet_equity || 0) - (a.wallet_equity || 0))
      .slice(0, 25);
  }, [users]);

  return (
    <div className="admin-stack">
      {error && <div className="admin-error">{error}</div>}

      <Card title="Finance overview">
        <p className="admin-muted">
          Deposits, withdrawals, user totals, and net completed cash flow. Net completed flow is
          completed deposits minus completed withdrawals (not including unrealized trading P&amp;L or
          separate platform fees).
        </p>
        <div style={{ marginTop: 12 }}>
          <button type="button" className="admin-btn admin-btn--ghost" onClick={() => void load()} disabled={loading}>
            {loading ? 'Refreshing…' : 'Refresh'}
          </button>
        </div>

        {summary && (
          <div
            style={{
              marginTop: 16,
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))',
              gap: 12,
            }}
          >
            <Stat
              label="Completed deposits"
              value={`MK ${fmtMoney(summary.deposits_completed_total)}`}
              sub={`${summary.deposits_completed_count} completed${summary.deposits_pending_count ? ` · ${summary.deposits_pending_count} pending` : ''}`}
            />
            <Stat
              label="Completed withdrawals"
              value={`MK ${fmtMoney(summary.withdrawals_completed_total)}`}
              sub={`${summary.withdrawals_completed_count} completed`}
            />
            <Stat
              label="Net completed flow"
              value={`MK ${fmtMoney(summary.net_completed_flow)}`}
              sub="Deposits − withdrawals (completed)"
            />
            <Stat
              label="Withdrawals awaiting action"
              value={`MK ${fmtMoney(summary.withdrawals_pending_approval_total + summary.withdrawals_processing_total)}`}
              sub={`${summary.withdrawals_pending_approval_count} awaiting approval · ${summary.withdrawals_processing_count} processing`}
            />
            <Stat
              label="Users"
              value={String(summary.users_total)}
              sub={`${summary.users_with_deposits} user(s) with completed deposits`}
            />
            <Stat
              label="Wallet cash totals"
              value={`MK ${fmtMoney(summary.wallet_cash_balance_total)}`}
              sub={`Withdrawable pool: MK ${fmtMoney(summary.wallet_withdrawable_total)}`}
            />
          </div>
        )}
        {!summary && loading && <div className="admin-muted" style={{ marginTop: 16 }}>Loading summary…</div>}
      </Card>

      <Card title="Deposits & payments">
        <p className="admin-muted">All payment records (deposits and withdrawals) for tracking and reconciliation.</p>
        <div style={{ marginTop: 14, display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
          <span className="admin-field-label">Kind</span>
          <select className="admin-input admin-select" style={{ width: 180 }} value={kind} onChange={(e) => setKind(e.target.value)}>
            <option value="all">All</option>
            <option value="deposit">Deposits</option>
            <option value="withdraw">Withdrawals</option>
          </select>
          <span className="admin-field-label">Status</span>
          <select className="admin-input admin-select" style={{ width: 220 }} value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="all">All</option>
            <option value="completed">Completed</option>
            <option value="pending">Pending/processing</option>
            <option value="pending_approval">Awaiting approval</option>
            <option value="rejected">Rejected</option>
            <option value="failed">Failed</option>
          </select>
        </div>

        <div className="admin-table-wrap" style={{ marginTop: 14 }}>
          <table className="admin-table">
            <thead>
              <tr>
                <th>Date</th>
                <th>Kind</th>
                <th>Wallet</th>
                <th>Amount (MWK)</th>
                <th>Method / Destination</th>
                <th>Status</th>
                <th>Message</th>
              </tr>
            </thead>
            <tbody>
              {payments === null && (
                <tr>
                  <td colSpan={7} className="admin-muted">Loading payments…</td>
                </tr>
              )}
              {payments !== null && payments.length === 0 && (
                <tr>
                  <td colSpan={7} className="admin-muted">No payments in this view.</td>
                </tr>
              )}
              {payments !== null &&
                payments.map((p) => (
                  <tr key={p.id}>
                    <td className="admin-mono">{fmtDate(p.created)}</td>
                    <td>
                      <span className="admin-pill">{p.kind === 'deposit' ? 'Deposit' : 'Withdrawal'}</span>
                    </td>
                    <td className="admin-mono" title={p.wallet_id}>{p.wallet_id.slice(0, 10)}…</td>
                    <td className="admin-mono">{fmtMoney(p.amount)}</td>
                    <td>
                      <div className="admin-td-name">{(p.correspondent || '').replace('_MWI', '') || '—'}</div>
                      <div className="admin-td-sub admin-mono">{p.number || '—'}</div>
                    </td>
                    <td><span className="admin-pill">{paymentLabel(p.status)}</span></td>
                    <td className="admin-td-sub" title={p.message || undefined}>{p.message || '—'}</td>
                  </tr>
                ))}
            </tbody>
          </table>
        </div>
      </Card>

      <Card title="Users & revenue tracking">
        <p className="admin-muted">
          Per-user deposits, withdrawals, and wallet totals (top users by completed deposits). Use the Users tab for full account management.
        </p>
        <div className="admin-table-wrap" style={{ marginTop: 14 }}>
          <table className="admin-table">
            <thead>
              <tr>
                <th>User</th>
                <th>Deposits (MWK)</th>
                <th>Withdrawals (MWK)</th>
                <th>Net (MWK)</th>
                <th>Wallet equity</th>
                <th>Cashable</th>
                <th>Positions</th>
                <th>Pending payments</th>
              </tr>
            </thead>
            <tbody>
              {users === null && (
                <tr>
                  <td colSpan={8} className="admin-muted">Loading users…</td>
                </tr>
              )}
              {users !== null && users.length === 0 && (
                <tr>
                  <td colSpan={8} className="admin-muted">No users found.</td>
                </tr>
              )}
              {users !== null &&
                topUsers.map((u) => {
                  const dep = u.deposits_total || 0;
                  const wd = u.withdrawals_total || 0;
                  return (
                    <tr key={u.id}>
                      <td>
                        <div className="admin-td-name">{u.name || u.id}</div>
                        <div className="admin-td-sub">{u.email || u.phone || '—'}</div>
                      </td>
                      <td className="admin-mono">{fmtMoney(dep)}</td>
                      <td className="admin-mono">{fmtMoney(wd)}</td>
                      <td className="admin-mono">{fmtMoney(dep - wd)}</td>
                      <td className="admin-mono">{u.wallet_equity == null ? '—' : fmtMoney(u.wallet_equity)}</td>
                      <td className="admin-mono">{u.wallet_withdrawable == null ? '—' : fmtMoney(u.wallet_withdrawable)}</td>
                      <td className="admin-mono">{u.positions}</td>
                      <td className="admin-mono">{u.pending_payments}</td>
                    </tr>
                  );
                })}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}
