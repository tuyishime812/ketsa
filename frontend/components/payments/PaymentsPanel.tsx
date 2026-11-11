'use client';

import { useEffect, useState } from 'react';
import {
  createDepositSession,
  createWithdrawalSession,
  fetchPaymentsSession,
  refreshPaymentSession,
} from '@/lib/api';
import { useWallet } from '@/components/wallet/WalletProvider';
import type { Correspondent, Payment } from '@/lib/types';
import { fmtBalance, timeAgo } from '@/lib/utils';
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

function statusTone(status: Payment['status']) {
  if (status === 'completed') return 'bg-pos/10 text-pos';
  if (status === 'failed') return 'bg-neg/10 text-neg';
  return 'bg-paper-alt text-ink-2';
}

export default function PaymentsPanel() {
  const { wallet, user, refreshWallet } = useWallet();
  const [mode, setMode] = useState<'deposit' | 'withdraw'>('deposit');
  const [correspondent, setCorrespondent] = useState<Correspondent>('AIRTEL_MWI');
  const [amount, setAmount] = useState('');
  const [number, setNumber] = useState('');
  const [payments, setPayments] = useState<Payment[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [activeInvoice, setActiveInvoice] = useState<Payment | null>(null);

  const widgetId = wallet?.id;
  const isCrypto = correspondent === 'USDT';

  async function loadHistory() {
    if (!wallet) return;
    try {
      setPayments(await fetchPaymentsSession(wallet.id));
    } catch {
      /* history is best-effort */
    }
  }

  useEffect(() => {
    void loadHistory();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [widgetId]);

  // Account-gated by the server (`require_user` on every /api/payments route).
  // A guest would only ever get a 401, so show the account CTA instead. This
  // sits after the hooks above so the hook order stays unconditional.
  if (!user) {
    return (
      <AccountGate
        title="Fund wallet"
        description="Deposit and cash out with real MWK over Airtel Money, TNM Mpamba, or USDT. Real-money movements need a Ketsa account — play money stays on your guest wallet."
      />
    );
  }

  function validMobile(raw: string): boolean {
    const digits = raw.replace(/\s/g, '');
    const n = digits.replace(/^0/, '');
    return /^\d{9,10}$/.test(n);
  }

  async function submit() {
    if (!wallet) return;
    const amt = parseFloat(amount);
    if (!Number.isFinite(amt) || amt < 100) {
      setError('Minimum payment is 100 MWK.');
      return;
    }
    if (mode === 'withdraw' && amt > wallet.withdrawable) {
      // Catch it here too: the server enforces the same ceiling, but telling
      // the user before they hit a 400 saves a round trip.
      setError(
        `You can withdraw up to ${fmtBalance(wallet.withdrawable, wallet.currency)} — ` +
          'only real money you deposited is cashable out.',
      );
      return;
    }
    if (!isCrypto && !validMobile(number)) {
      setError('Enter a valid 10-digit mobile number (e.g. 0998 123 456).');
      return;
    }

    // Crypto (USDT): show coming soon only when the user clicks.
    if (isCrypto) {
      setError(null);
      setNotice('Coming soon');
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
        if (last.status === 'failed') setNotice(last.message || 'The deposit failed — nothing was charged.');
        else setNotice('Deposit completed. Your balance has been updated.');
      } else {
        setNotice('Withdrawal queued for payout to your mobile money.');
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
        } else if (last.status === 'failed') {
          setNotice(last.message || 'The withdrawal failed — funds were refunded to your balance.');
        } else {
          setNotice(`Still ${last.status}. You can check the status below — this may take a minute.`);
        }
      }

      setPayments(await fetchPaymentsSession(wallet.id));
      await refreshWallet();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Payment failed — please try again.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="rounded-m border border-line bg-white p-5">
      <div className="mb-4 flex items-center justify-between gap-3">
        <h3 className="font-serif text-[17px] font-medium">
          {mode === 'deposit' ? 'Fund wallet' : 'Withdraw'}
        </h3>
        <div className="segment">
          <button
            className={`segment-btn ${mode === 'deposit' ? 'is-active' : ''}`}
            onClick={() => { setMode('deposit'); setError(null); setNotice(null); }}
          >
            Deposit
          </button>
          <button
            className={`segment-btn ${mode === 'withdraw' ? 'is-active' : ''}`}
            onClick={() => { setMode('withdraw'); setError(null); setNotice(null); }}
          >
            Withdraw
          </button>
        </div>
      </div>

      <p className="mb-4 text-[12.5px] text-ink-2">
        {mode === 'deposit'
          ? 'Top up your balance with real money via Airtel Money, TNM Mpamba, or USDT.'
          : 'Payout real money you deposited back to your mobile money (min 100 MWK). Play balance and trading winnings are not cashable out.'}
      </p>

      <div className="grid gap-4 sm:grid-cols-2">
        <label className="block">
          <span className="mb-2 block font-mono text-[10.5px] uppercase tracking-[.07em] text-ink-3">
            Amount (MWK)
          </span>
          <input
            className="field w-full"
            type="number"
            inputMode="decimal"
            min="100"
            step="1"
            max={mode === 'withdraw' ? wallet?.withdrawable : undefined}
            placeholder="500"
            value={amount}
            onChange={(e) => setAmount(e.target.value)}
          />
          {mode === 'withdraw' && wallet && wallet.withdrawable > 0 && (
            <button
              type="button"
              className="mt-2 font-mono text-[10.5px] uppercase tracking-[.07em] text-ink-3 underline hover:text-ink-2"
              onClick={() => setAmount(String(Math.floor(wallet.withdrawable)))}
            >
              Max {fmtBalance(wallet.withdrawable, wallet.currency)}
            </button>
          )}
        </label>
        {!isCrypto ? (
          <label className="block">
            <span className="mb-2 block font-mono text-[10.5px] uppercase tracking-[.07em] text-ink-3">
              Mobile number
            </span>
            <input
              className="field w-full"
              type="tel"
              inputMode="tel"
              placeholder="0998 123 456"
              value={number}
              onChange={(e) => setNumber(e.target.value)}
            />
          </label>
        ) : (
          <div className="block">
            <span className="mb-2 block font-mono text-[10.5px] uppercase tracking-[.07em] text-ink-3">
              USDT deposit
            </span>
            <p className="text-[12.5px] text-ink-2">
              {mode === 'deposit'
                ? 'Deposit with USDT. Your balance will be credited after processing.'
                : 'Crypto withdrawals are coming soon.'}
            </p>
          </div>
        )}
      </div>

      <div className="segment mt-4 flex-wrap">
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
        className={`btn mt-4 w-full ${mode === 'deposit' ? 'btn--brand' : 'btn--ghost'}`}
        disabled={busy}
        onClick={() => void submit()}
      >
        {busy ? 'Processing…' : mode === 'deposit' ? 'Deposit' : 'Withdraw'}
      </button>

      {notice && <p className="mt-3 text-[12.5px] text-pos">{notice}</p>}
      {error && <p className="mt-3 text-[12.5px] text-neg">{error}</p>}
      {activeInvoice && activeInvoice.correspondent === 'USDT' && activeInvoice.kind === 'deposit' && (
        <div className="mt-4 rounded-m border border-line bg-paper-alt p-4 text-[12.5px]">
          <div className="mb-2 font-mono text-[10px] uppercase tracking-[.06em] text-ink-3">Crypto deposit invoice (Binance Pay)</div>
          <div className="grid gap-1 text-ink-2">
            {activeInvoice.crypto_amount != null && <div>Pay: <span className="font-semibold text-ink">{activeInvoice.crypto_amount} {activeInvoice.crypto_currency || 'USDT'}</span> {activeInvoice.crypto_network ? `(${activeInvoice.crypto_network})` : ''}</div>}
            {activeInvoice.invoice_url && <div>Payment link: <a className="text-brand underline" href={activeInvoice.invoice_url} target="_blank" rel="noreferrer">Open invoice</a></div>}
            {activeInvoice.qr_code && <div>QR: <span className="break-all">{activeInvoice.qr_code}</span></div>}
            {activeInvoice.deposit_address && <div>Deposit address: <span className="break-all font-mono">{activeInvoice.deposit_address}</span></div>}
            {activeInvoice.expires_at && <div>Expires: {new Date(activeInvoice.expires_at * 1000).toLocaleString()}</div>}
            <div>Status: <span className="font-semibold uppercase">{activeInvoice.status}</span></div>
          </div>
          <p className="mt-2 text-[11.5px] text-ink-3">Your in-app balance is credited only after verified payment confirmation.</p>
        </div>
      )}

      {payments.length > 0 && (
        <div className="mt-5 border-t border-line pt-4">
          <div className="mb-2 font-mono text-[10px] uppercase tracking-[.06em] text-ink-3">
            Payment history
          </div>
          <ul className="flex flex-col gap-[6px]">
            {payments.slice(0, 15).map((p) => (
              <li
                key={p.id}
                className="grid grid-cols-[70px_88px_1fr_auto] items-center gap-3 font-mono text-[11.5px]"
              >
                <span className="text-ink-3">{timeAgo(p.updated)}</span>
                <span
                  className={`rounded-[4px] px-[6px] py-[2px] text-center text-[10px] font-semibold uppercase ${
                    p.kind === 'deposit' ? 'bg-pos/10 text-pos' : 'bg-paper-alt text-ink-2'
                  }`}
                >
                  {p.kind}
                </span>
                <span className="truncate text-ink-2">
                  {fmtBalance(p.amount, wallet?.currency)} · {p.correspondent.replace('_MWI', '')}
                </span>
                <span
                  className={`rounded-[4px] px-[6px] py-[2px] text-[10px] font-semibold uppercase ${statusTone(p.status)}`}
                >
                  {p.status}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
