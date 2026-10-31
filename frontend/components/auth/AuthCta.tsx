'use client';

import { useWallet } from '@/components/wallet/WalletProvider';

/**
 * Landing-page entry points into the existing auth modal.
 *
 * Hero and CtaBand are server components, so they cannot call `openAuth`
 * directly. This client island renders the buttons and delegates to the
 * WalletProvider, which already owns the AuthModal instance.
 *
 * When a session is already active the buttons are swapped for a link to the
 * dashboard, so a logged-in visitor never sees a "Log in" CTA.
 */
export default function AuthCta({
  variant = 'default',
  className = '',
}: {
  /** 'lg' for the hero (larger buttons), 'default' for the CTA band. */
  variant?: 'lg' | 'default';
  className?: string;
}) {
  const { user, wallet, loading, openAuth } = useWallet();

  if (loading) {
    // Match the button box so the row does not reflow once auth state resolves.
    return (
      <div className={`flex flex-wrap items-center gap-3 ${className}`} aria-hidden>
        <span
          className={`btn btn--ghost ${
            variant === 'lg' ? 'btn--lg' : ''
          } animate-pulse opacity-60`}
        >
          Log in
        </span>
        <span
          className={`btn btn--brand ${
            variant === 'lg' ? 'btn--lg' : ''
          } animate-pulse opacity-60`}
        >
          Create account
        </span>
      </div>
    );
  }

  if (user || wallet) {
    return (
      <a href="/dashboard" className={`btn btn--brand ${className}`}>
        Go to dashboard
      </a>
    );
  }

  const size = variant === 'lg' ? 'btn--lg' : '';

  return (
    <div className={`flex flex-wrap items-center gap-3 ${className}`}>
      <button
        type="button"
        className={`btn btn--ghost ${size}`}
        onClick={() => openAuth('login')}
      >
        Log in
      </button>
      <button
        type="button"
        className={`btn btn--brand ${size}`}
        onClick={() => openAuth('register')}
      >
        Create account
      </button>
    </div>
  );
}
