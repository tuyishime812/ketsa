'use client';

import { useWallet } from '@/components/wallet/WalletProvider';

/**
 * Shown in place of the deposit/withdraw form when the visitor only holds a
 * guest (play-money) wallet.
 *
 * Real-money movements are account-gated on the server: `/api/payments/*`
 * calls `require_user` before anything else, so an anonymous request always
 * fails with 401. Rendering the form to a guest would therefore guarantee a
 * confusing "Not authenticated" error on submit; instead we explain the rule
 * and route the visitor into the account flow.
 */
export default function AccountGate({
  title,
  description,
}: {
  title: string;
  description: string;
}) {
  const { openAuth } = useWallet();

  return (
    <div className="rounded-m border border-line bg-white p-5">
      <div className="mb-3 flex items-center gap-[9px]">
        <span className="flex h-[30px] w-[30px] shrink-0 items-center justify-center rounded-[8px] bg-brand-tint text-brand">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
            <rect
              x="4"
              y="10"
              width="16"
              height="10"
              rx="2"
              stroke="currentColor"
              strokeWidth="1.7"
            />
            <path
              d="M8 10V7a4 4 0 0 1 8 0v3"
              stroke="currentColor"
              strokeWidth="1.7"
              strokeLinecap="round"
            />
          </svg>
        </span>
        <h3 className="font-serif text-[17px] font-medium">
          {title} <span className="text-ink-3">· PayChangu</span>
        </h3>
      </div>

      <p className="text-[12.5px] leading-snug text-ink-2">{description}</p>

      <ul className="mt-4 flex flex-col gap-[6px] text-[12px] text-ink-2">
        <li className="flex items-start gap-2">
          <span className="mt-[6px] h-[5px] w-[5px] shrink-0 rounded-full bg-brand" />
          Deposits, withdrawals and payment history need a Ketsa account.
        </li>
        <li className="flex items-start gap-2">
          <span className="mt-[6px] h-[5px] w-[5px] shrink-0 rounded-full bg-brand" />
          Your play-money wallet &amp; positions stay right where they are.
        </li>
      </ul>

      <div className="mt-4 flex flex-wrap gap-3">
        <button
          className="btn btn--brand"
          onClick={() => openAuth('register')}
        >
          Create an account
        </button>
        <button className="btn btn--ghost" onClick={() => openAuth('login')}>
          Sign in
        </button>
      </div>
    </div>
  );
}
