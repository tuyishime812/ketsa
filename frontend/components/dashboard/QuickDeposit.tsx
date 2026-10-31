'use client';

import { useState } from 'react';
import { useWallet } from '@/components/wallet/WalletProvider';
import {
  createDepositSession,
  createWithdrawalSession,
  refreshPaymentSession,
} from '@/lib/api';
import type { Correspondent } from '@/lib/types';
import AccountGate from '@/components/payments/AccountGate';

const sleep = (ms: number) => new Promise<void>((res) => setTimeout(res, ms));

function validNumber(raw: string): boolean {
  const n = raw.replace(/\s/g, '').replace(/^0/, '');
  return /^\d{9,10}$/.test(n);
}

export default function QuickDeposit() {
  const { wallet, user, refreshWallet } = useWallet();
  const [mode, setMode] = useState<'deposit' | 'withdraw'>('deposit');
  const [correspondent, setCorrespondent] = useState<Correspondent>('AIRTEL_MWI');
  const [amount, setAmount] = useState('');
  const [number, setNumber] = useState('');
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Real money requires an account (server-side `require_user`). Guests hold
  // only a play-money wallet, so show the account CTA rather than a form that
  // can only ever fail with a 401.
  if (!user) {
    return (
      <AccountGate
        title={mode === 'deposit' ? 'Fund wallet' : 'Withdraw'}
        description="Top up and cash out with real MWK over Airtel Money or TNM Mpamba — that needs a Ketsa account. Your play-money wallet is unaffected."
      />
    );
  }

  async function submit() {
    if (!wallet) return;
    const amt = parseFloat(amount);
    if (!Number.isFinite(amt) || amt < 100) {
      setError('Minimum is 100 MWK.');
      return;
    }
    if (!validNumber(number)) {
      setError('Enter a valid 10-digit mobile number (e.g. 0991 513 401).');
      return;
    }
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const created =
        mode === 'deposit'
          ? await createDepositSession(wallet.id, amt, number, correspondent)
          : await createWithdrawalSession(wallet.id, amt, number, correspondent);
      setAmount('');
      setNotice(
        mode === 'deposit'
          ? 'Deposit started — approve the prompt on your phone if you receive one.'
          : 'Withdrawal queued for payout.',
      );
      let last = created;
      for (let i = 0; i < 30 && last.status === 'pending'; i++) {
        await sleep(2000);
        try {
          last = await refreshPaymentSession(created.id);
        } catch {
          break;
        }
      }
      if (last.status === 'completed') {
        setNotice(
          mode === 'deposit'
            ? 'Deposit confirmed — your balance has been updated.'
            : 'Withdrawal completed.',
        );
      } else if (last.status === 'failed') {
        setNotice(
          last.message || (last.rolled_back ? 'Failed — funds refunded.' : 'Payment failed.'),
        );
      } else {
        setNotice(`Still ${last.status} — check Portfolio for the latest status.`);
      }
      await refreshWallet();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Payment failed — please try again.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="rounded-m border border-line bg-white p-5">
      <div className="mb-4 flex items-center justify-between">
        <h3 className="font-serif text-[17px] font-medium">
          {mode === 'deposit' ? 'Fund wallet' : 'Withdraw'}
          <span className="text-ink-3"> · PayChangu</span>
        </h3>
        <div className="segment">
          <button
            className={`segment-btn ${mode === 'deposit' ? 'is-active' : ''}`}
            onClick={() => {
              setMode('deposit');
              setError(null);
              setNotice(null);
            }}
          >
            Top up
          </button>
          <button
            className={`segment-btn ${mode === 'withdraw' ? 'is-active' : ''}`}
            onClick={() => {
              setMode('withdraw');
              setError(null);
              setNotice(null);
            }}
          >
            Cash out
          </button>
        </div>
      </div>

      <div className="flex flex-col gap-[10px]">
        <input
          className="field w-full"
          type="number"
          inputMode="decimal"
          min="100"
          placeholder="Amount (MWK) — min 100"
          value={amount}
          onChange={(e) => setAmount(e.target.value)}
        />
        <input
          className="field w-full"
          type="tel"
          inputMode="tel"
          placeholder="Mobile number (e.g. 0991 513 401)"
          value={number}
          onChange={(e) => setNumber(e.target.value)}
        />
        <div className="segment">
          <button
            className={`segment-btn ${correspondent === 'AIRTEL_MWI' ? 'is-active' : ''}`}
            onClick={() => setCorrespondent('AIRTEL_MWI')}
          >
            Airtel Money
          </button>
          <button
            className={`segment-btn ${correspondent === 'TNM_MWI' ? 'is-active' : ''}`}
            onClick={() => setCorrespondent('TNM_MWI')}
          >
            TNM Mpamba
          </button>
        </div>
        <button
          className={`btn w-full ${mode === 'deposit' ? 'btn--brand' : 'btn--ghost'}`}
          disabled={busy || !wallet}
          onClick={() => void submit()}
        >
          {busy
            ? 'Processing…'
            : mode === 'deposit'
              ? 'Deposit with PayChangu'
              : 'Withdraw to mobile money'}
        </button>
        {notice && <p className="text-[12px] leading-snug text-pos">{notice}</p>}
        {error && <p className="text-[12px] leading-snug text-neg">{error}</p>}
      </div>
    </div>
  );
}
