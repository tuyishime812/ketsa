'use client';

import { FormEvent, useState } from 'react';
import { useWallet } from '@/components/wallet/WalletProvider';
import { changePasswordSession } from '@/lib/api';

export default function AccountSettings() {
  const { user, applySession } = useWallet();
  const [current, setCurrent] = useState('');
  const [next, setNext] = useState('');
  const [confirm, setConfirm] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  if (!user) return null;

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (next.length < 8) {
      setError('New password must be at least 8 characters.');
      return;
    }
    if (next !== confirm) {
      setError('New password does not match confirmation.');
      return;
    }
    setBusy(true);
    try {
      const session = await changePasswordSession(current, next);
      applySession(session);
      setCurrent('');
      setNext('');
      setConfirm('');
      setDone(true);
      setTimeout(() => setDone(false), 4000);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Password change failed');
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="rounded-m border border-line bg-white p-5">
      <h3 className="mb-3 font-serif text-[17px] font-medium">Account</h3>
      <p className="mb-4 text-[12.5px] leading-snug text-ink-2">
        Signed in as <span className="font-medium text-ink">{user.email || user.phone}</span>
      </p>

      <form className="flex flex-col gap-3" onSubmit={(e) => void submit(e)}>
        <label className="flex flex-col gap-[5px]">
          <span className="font-mono text-[10px] uppercase tracking-[.06em] text-ink-3">
            Current password
          </span>
          <input
            type="password"
            required
            value={current}
            onChange={(e) => setCurrent(e.target.value)}
            className="input"
            autoComplete="current-password"
          />
        </label>

        <label className="flex flex-col gap-[5px]">
          <span className="font-mono text-[10px] uppercase tracking-[.06em] text-ink-3">
            New password
          </span>
          <input
            type="password"
            required
            minLength={8}
            value={next}
            onChange={(e) => setNext(e.target.value)}
            className="input"
            autoComplete="new-password"
          />
        </label>

        <label className="flex flex-col gap-[5px]">
          <span className="font-mono text-[10px] uppercase tracking-[.06em] text-ink-3">
            Confirm new password
          </span>
          <input
            type="password"
            required
            minLength={8}
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
            className="input"
            autoComplete="new-password"
          />
        </label>

        {error && (
          <p className="rounded bg-neg/10 px-3 py-2 text-[12px] font-medium text-neg">
            {error}
          </p>
        )}

        {done && (
          <p className="rounded bg-pos/10 px-3 py-2 text-[12px] font-medium text-pos">
            Password changed successfully. You&apos;ll stay signed in with the same account.
          </p>
        )}

        <button
          type="submit"
          disabled={busy}
          className="btn btn--brand mt-1 w-full"
        >
          {busy ? 'Changing…' : 'Change password'}
        </button>
      </form>
    </div>
  );
}
