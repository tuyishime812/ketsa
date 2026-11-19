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

function AirtelLogo() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" aria-hidden="true" className="shrink-0">
      <circle cx="12" cy="12" r="11" fill="#E60000" />
      <path d="M7 15c1.4-3.8 3.1-5.7 5-5.7S15.6 11.2 17 15" stroke="#fff" strokeWidth="2.2" strokeLinecap="round" fill="none" />
      <circle cx="12" cy="8.2" r="1.4" fill="#fff" />
    </svg>
  );
}

function MpambaLogo() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" aria-hidden="true" className="shrink-0">
      <rect x="2" y="2" width="20" height="20" rx="5" fill="#009640" />
      <path d="M7 16V8h3.2l1.8 4 1.8-4H17v8h-2.4v-4.2L13 16h-2l-1.6-4.2V16H7z" fill="#fff" />
    </svg>
  );
}

function UsdtLogo() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" aria-hidden="true" className="shrink-0">
      <circle cx="12" cy="12" r="11" fill="#26A17B" />
      <path d="M13.4 11.3v-1.6h3V7.8H7.6v1.9h3v1.6c-2.4.1-4.2.6-4.2 1.2s1.8 1.1 4.2 1.2v4.1h2.8v-4.1c2.4-.1 4.2-.6 4.2-1.2s-1.8-1.1-4.2-1.2zm0 2c-.4 0-1 .1-1.4.1s-1 0-1.4-.1v-.5c.4 0 1-.1 1.4-.1s1 0 1.4.1v.5z" fill="#fff" />
    </svg>
  );
}

function validMobile(raw: string): boolean {
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
        description="Top up and cash out with real MWK over Airtel Money, TNM Mpamba, or USDT. Real-money movements need a Ketsa account — your play-money wallet is unaffected."
      />
    );
  }

  const isCrypto = correspondent === 'USDT';

  async function submit() {
    if (!wallet) return;
    const amt = parseFloat(amount);
    if (!Number.isFinite(amt) || amt < 100) {
      setError('Minimum is 100 MWK.');
      return;
    }
    if (!isCrypto && !validMobile(number)) {
      setError('Enter a valid 10-digit mobile number (e.g. 0991 513 401).');
      return;
    }

    // Crypto (USDT): show coming soon only when the user clicks.
    if (isCrypto) {
      setError(null);
      setNotice('Coming soon');
      return;
    }

    if (mode === 'withdraw' && amt > wallet.withdrawable) {
      setError('Insufficient withdrawable funds for this withdrawal.');
      return;
    }

    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const created =
        mode === 'deposit'
          ? await createDepositSession(wallet.id, amt, number || 'USDT', correspondent)
          : await createWithdrawalSession(wallet.id, amt, number, correspondent);
      setAmount('');

      if (mode === 'deposit') {
        setNotice('Processing deposit…');
        const started = Date.now();
        let last = created;
        while (Date.now() - started < 8000) {
          if (last.status === 'completed' || last.status === 'failed') break;
          await sleep(2000);
          if (Date.now() - started >= 8000) break;
          try { last = await refreshPaymentSession(created.id); } catch { break; }
        }
        if (last.status === 'failed') setNotice(last.message || 'Payment failed.');
        else setNotice('Deposit completed. Your balance has been updated.');
        await refreshWallet();
      } else {
        if (created.status === 'pending_approval') {
          setNotice('Withdrawal requested. It will be processed after administrator approval.');
        } else {
          setNotice('Withdrawal queued for payout.');
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
            setNotice('Withdrawal completed.');
          } else if (last.status === 'failed' || last.status === 'rejected') {
            setNotice(last.message || (last.rolled_back ? 'Failed — funds refunded.' : 'Payment failed.'));
          } else if (last.status === 'pending_approval') {
            setNotice('Withdrawal requested. It will be processed after administrator approval.');
          } else {
            setNotice(`Still ${last.status} — check Portfolio for the latest status.`);
          }
        }
        await refreshWallet();
      }
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
        {!isCrypto && (
          <input
            className="field w-full"
            type="tel"
            inputMode="tel"
            placeholder="Mobile number (e.g. 0991 513 401)"
            value={number}
            onChange={(e) => setNumber(e.target.value)}
          />
        )}
        {isCrypto && mode === 'deposit' && (
          <p className="text-[12px] leading-snug text-ink-2">
            Deposit with USDT. Your balance will be credited after processing.
          </p>
        )}
        <div className="segment flex-wrap">
          <button
            className={`segment-btn flex items-center gap-2 ${correspondent === 'AIRTEL_MWI' ? 'is-active' : ''}`}
            onClick={() => { setCorrespondent('AIRTEL_MWI'); setNotice(null); setError(null); }}
          >
            <AirtelLogo /> Airtel
          </button>
          <button
            className={`segment-btn flex items-center gap-2 ${correspondent === 'TNM_MWI' ? 'is-active' : ''}`}
            onClick={() => { setCorrespondent('TNM_MWI'); setNotice(null); setError(null); }}
          >
            <MpambaLogo /> Mpamba
          </button>
          <button
            className={`segment-btn flex items-center gap-2 ${correspondent === 'USDT' ? 'is-active' : ''}`}
            onClick={() => { setCorrespondent('USDT'); setNotice(null); setError(null); }}
          >
            <UsdtLogo /> USDT
          </button>
        </div>
        <button
          className={`btn w-full ${mode === 'deposit' ? 'btn--brand' : 'btn--ghost'}`}
          disabled={busy || !wallet}
          onClick={() => void submit()}
        >
          {busy ? 'Processing…' : mode === 'deposit' ? 'Deposit' : 'Withdraw'}
        </button>
        {notice && <p className="text-[12px] leading-snug text-pos">{notice}</p>}
        {error && <p className="text-[12px] leading-snug text-neg">{error}</p>}
      </div>
    </div>
  );
}
