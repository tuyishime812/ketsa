'use client';

import { useCallback, useEffect, useState } from 'react';
import { adminDelete, adminGet, adminPost, AdminApiError } from '@/lib/api';
import type { AdminUserView } from '@/lib/types';
import { Card, DangerButton, Field, TextInput } from './ui';

function fmtDate(ts?: number | null): string {
  if (!ts) return '—';
  return new Date(ts).toLocaleString(undefined, {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

export default function UsersEditor({ token }: { token: string }) {
  const [users, setUsers] = useState<AdminUserView[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [sortBy, setSortBy] = useState<keyof Pick<
    AdminUserView,
    'wallet_equity' | 'created' | 'name'
  >>('wallet_equity');

  const load = useCallback(async () => {
    setError(null);
    try {
      const rows = await adminGet<AdminUserView[]>(token, '/users');
      setUsers(rows);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load users');
    }
  }, [token]);

  useEffect(() => {
    void load();
  }, [load]);

  const sorted = useSorted(users, sortBy);

  async function resetPassword(email: string, newPassword: string) {
    setError(null);
    setMsg(null);
    if (newPassword.length < 8) {
      setError('New password must be at least 8 characters');
      return;
    }
    try {
      await adminPost(token, '/users/reset-password', {
        email,
        new_password: newPassword,
      });
      setMsg(`Password reset for ${email}. Previous sessions were revoked.`);
    } catch (err) {
      setError(apiError(err));
    }
  }

  async function deleteUser(email: string) {
    setError(null);
    setMsg(null);
    try {
      await adminDelete(token, `/users/${encodeURIComponent(email)}`);
      setUsers((prev) => (prev ?? []).filter((u) => u.email !== email));
      setMsg(`Deleted account ${email}.`);
    } catch (err) {
      setError(apiError(err));
    }
  }

  return (
    <div className="admin-stack">
      {error && <div className="admin-error">{error}</div>}
      {msg && <div className="admin-saved-msg">{msg}</div>}

      <Card title="User accounts">
        <p className="admin-muted">
          All wallet equities are priced live through the matching engine.
          Resetting a password signs the account out everywhere; deleting an
          account permanently removes it and its wallet history.
        </p>

        <div style={{ marginTop: 14 }}>
          <span className="admin-field-label">Sort by</span>{' '}
          <select
            className="admin-input admin-select"
            style={{ width: 180, marginLeft: 8 }}
            value={sortBy}
            onChange={(e) =>
              setSortBy(
                e.target.value as
                  | 'wallet_equity'
                  | 'created'
                  | 'name',
              )
            }
          >
            <option value="wallet_equity">Equity</option>
            <option value="created">Newest</option>
            <option value="name">Name</option>
          </select>
        </div>

        <div className="admin-table-wrap" style={{ marginTop: 14 }}>
          <table className="admin-table">
            <thead>
              <tr>
                <th>User</th>
                <th>Wallet</th>
                <th>Equity</th>
                <th>Positions</th>
                <th>Trades</th>
                <th>Member since</th>
                <th className="admin-actions">Actions</th>
              </tr>
            </thead>
            <tbody>
              {sorted === null && (
                <tr>
                  <td colSpan={7} className="admin-muted">
                    Loading users…
                  </td>
                </tr>
              )}
              {sorted !== null && sorted.length === 0 && (
                <tr>
                  <td colSpan={7} className="admin-muted">
                    No accounts yet.
                  </td>
                </tr>
              )}
              {sorted !== null &&
                sorted.map((u) => (
                  <UserRow
                    key={u.id}
                    user={u}
                    onReset={(pw) => resetPassword(u.email, pw)}
                    onDelete={() => deleteUser(u.email)}
                  />
                ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}

function UserRow({
  user,
  onReset,
  onDelete,
}: {
  user: AdminUserView;
  onReset: (newPassword: string) => Promise<void>;
  onDelete: () => Promise<void>;
}) {
  const [editing, setEditing] = useState(false);
  const [pw, setPw] = useState('');
  const [busy, setBusy] = useState(false);

  async function submit() {
    setBusy(true);
    try {
      await onReset(pw);
      setEditing(false);
      setPw('');
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <tr>
        <td>
          <div className="admin-td-name">{user.name}</div>
          <div className="admin-td-sub">{user.email}</div>
        </td>
        <td className="admin-mono">{user.wallet_id}</td>
        <td className="admin-mono">
          {(user.wallet_equity ?? 0).toLocaleString(undefined, {
            maximumFractionDigits: 2,
          })}{' '}
          MWK
        </td>
        <td className="admin-mono">{user.positions}</td>
        <td className="admin-mono">{user.trades}</td>
        <td className="admin-mono">{fmtDate(user.created)}</td>
        <td className="admin-actions">
          <button
            type="button"
            className="admin-btn admin-btn--ghost"
            onClick={() => setEditing((v) => !v)}
          >
            {editing ? 'Cancel' : 'Reset password'}
          </button>
          <DangerButton onConfirm={onDelete} label="Delete" />
        </td>
      </tr>
      {editing && (
        <tr>
          <td colSpan={7} className="admin-reset-row">
            <div className="admin-grid admin-grid--2">
              <Field label="New password" hint="At least 8 characters">
                <TextInput
                  type="password"
                  value={pw}
                  onChange={setPw}
                  placeholder="••••••••"
                />
              </Field>
              <div className="admin-reset-actions">
                <button
                  type="button"
                  className="admin-btn admin-btn--primary"
                  disabled={busy || pw.length < 8}
                  onClick={() => void submit()}
                >
                  {busy ? 'Resetting…' : 'Set new password'}
                </button>
              </div>
            </div>
          </td>
        </tr>
      )}
    </>
  );
}

function useSorted(
  users: AdminUserView[] | null,
  by: 'wallet_equity' | 'created' | 'name',
): AdminUserView[] | null {
  if (users === null) return null;
  const copy = [...users];
  if (by === 'name') {
    copy.sort((a, b) => a.name.localeCompare(b.name));
  } else {
    copy.sort((a, b) => {
      const av = a[by] ?? 0;
      const bv = b[by] ?? 0;
      return (bv as number) - (av as number);
    });
  }
  return copy;
}

function apiError(err: unknown): string {
  if (err instanceof AdminApiError) return err.message;
  return err instanceof Error ? err.message : 'Request failed';
}