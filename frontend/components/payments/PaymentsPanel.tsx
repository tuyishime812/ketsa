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

const sleep = (ms: number) => new Promise<void>((res) => setTimeout(res, ms));

function statusTone(status: Payment['status']) {
  if (status === 'completed') return 'bg-pos/10 text-pos';
  if (status === 'failed') return 'bg-neg/10 text-neg';
  return 'bg-paper-alt text-ink-2';
}

export default function PaymentsPanel() {
  const { wallet, refreshWallet } = useWallet();
  const [mode, setMode] = useState<'deposit' | 'withdraw'>('deposit');
  const [correspondent, setCorrespondent] = useState<Correspondent>('AIRTEL_MWI');
  const [amount, setAmount] = useState('');
  const [number, setNumber] = useState('');
  const [payments, setPayments] = useState<Payment[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const widgetId = wallet?.id;

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

  function validNumber(raw: string): boolean {
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
    if (!validNumber(number)) {
      setError('Enter a valid 10-digit mobile number (e.g. 0998 123 456).');
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
      setNotice(
        mode === 'deposit'
          ? 'Deposit started — approve the prompt on your phone if you receive one.'
          : 'Withdrawal queued for payout to your mobile money.',
      );
      setAmount('');

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
          last.message ||
            (mode === 'deposit'
              ? 'The deposit failed — nothing was charged.'
              : 'The withdrawal failed — funds were refunded to your balance.'),
        );
      } else {
        setNotice(
          `Still ${last.status}. You can check the status below — this may take a minute.`,
        );
      }
      setPayments(await fetchPaymentsSession(wallet.id));
      await refreshWallet();
    } catch (e) {
      setError(
        e instanceof Error ? e.message : 'Payment failed — please try again.',
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="rounded-m border border-line bg-white p-5">
      <div className="mb-4 flex items-center justify-between gap-3">
        <h3 className="font-serif text-[17px] font-medium">
          Payments <span className="text-ink-3">· wandePay</span>
        </h3>
        <div className="segment">
          <button
            className={`segment-btn ${mode === 'deposit' ? 'is-active' : ''}`}
            onClick={() => setMode('deposit')}
          >
            Deposit
          </button>
          <button
            className={`segment-btn ${mode === 'withdraw' ? 'is-active' : ''}`}
            onClick={() => setMode('withdraw')}
          >
            Withdraw
          </button>
        </div>
      </div>

      <p className="mb-4 text-[12.5px] text-ink-2">
        {mode === 'deposit'
          ? `Top up your balance with real money via Airtel Money or TNM Mpamba.`
          : `Payout real money you deposited back to your mobile money (min 100 MWK). ` +
            `Play balance and trading winnings are not cashable out.`}
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
      </div>

      <div className="segment mt-4">
        <button
          className={`segment-btn ${correspondent === 'AIRTEL_MWI' ? 'is-active' : ''}`}
          onClick={() => setCorrespondent('AIRTEL_MWI')}
        >
          Airtel
        </button>
        <button
          className={`segment-btn ${correspondent === 'TNM_MWI' ? 'is-active' : ''}`}
          onClick={() => setCorrespondent('TNM_MWI')}
        >
          TNM
        </button>
      </div>

      <button
        className={`btn mt-4 w-full ${mode === 'deposit' ? 'btn--brand' : 'btn--ghost'}`}
        disabled={busy}
        onClick={() => void submit()}
      >
        {busy
          ? 'Processing…'
          : mode === 'deposit'
            ? 'Deposit via wandePay'
            : `Withdraw ${wallet ? fmtBalance(wallet.withdrawable, wallet.currency) : ''} withdrawable`}
      </button>

      {notice && <p className="mt-3 text-[12.5px] text-pos">{notice}</p>}
      {error && <p className="mt-3 text-[12.5px] text-neg">{error}</p>}

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