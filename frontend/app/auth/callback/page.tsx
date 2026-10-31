'use client';

import { Suspense, useEffect, useState } from 'react';
import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';
import { completeSocialLogin } from '@/lib/api';
import { useWallet } from '@/components/wallet/WalletProvider';

/**
 * Landing page for the Auth0 "Continue with Google" flow.
 *
 * The backend hands the browser a short-lived, single-use ticket in the URL
 * (never the session token itself). This page exchanges it for the Ketsa
 * session — exactly like a password login — then replaces the URL so the
 * ticket does not linger in browser history, and redirects home.
 */
function CallbackInner() {
  const router = useRouter();
  const params = useSearchParams();
  const { applySession } = useWallet();
  const [status, setStatus] = useState<'working' | 'done' | 'error'>('working');
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const ticket = params.get('ticket');
    if (!ticket) {
      setStatus('error');
      setError('This sign-in link is incomplete. Please try again.');
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        const session = await completeSocialLogin(ticket);
        if (cancelled) return;
        applySession(session);
        setStatus('done');
        // replace() removes the ticket from the address bar + history.
        router.replace('/');
      } catch (err) {
        if (cancelled) return;
        setStatus('error');
        setError(
          err instanceof Error ? err.message : 'Sign-in failed, please try again.',
        );
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [params, router, applySession]);

  return (
    <main className="flex min-h-[60vh] flex-col items-center justify-center px-4 py-20 text-center">
      <div className="mb-3 flex h-11 w-11 items-center justify-center rounded-full bg-paper ring-1 ring-line">
        {status === 'working' && (
          <span className="h-4 w-4 animate-spin rounded-full border-2 border-brand border-t-transparent" />
        )}
        {status === 'done' && <span className="text-[16px] text-pos">✓</span>}
        {status === 'error' && <span className="text-[16px] text-neg">✕</span>}
      </div>
      <h1 className="font-serif text-[26px] font-medium text-ink">
        {status === 'working' && 'Finalizing your sign-in…'}
        {status === 'done' && 'Signed in'}
        {status === 'error' && 'Could not sign you in'}
      </h1>
      {status === 'working' && (
        <p className="mt-2 max-w-[380px] text-[13.5px] text-ink-3">
          Exchanging your Google login for your Ketsa session.
        </p>
      )}
      {status === 'error' && (
        <>
          <p className="mt-2 max-w-[380px] text-[13.5px] text-ink-3">{error}</p>
          <Link
            href="/"
            className="mt-6 rounded-[9px] bg-ink px-5 py-[11px] text-sm font-semibold text-white transition-colors hover:bg-brand-ink"
          >
            Back to Ketsa
          </Link>
        </>
      )}
    </main>
  );
}

export default function SocialCallbackPage() {
  return (
    <Suspense
      fallback={
        <main className="flex min-h-[60vh] flex-col items-center justify-center px-4 text-center">
          <span className="h-4 w-4 animate-spin rounded-full border-2 border-brand border-t-transparent" />
        </main>
      }
    >
      <CallbackInner />
    </Suspense>
  );
}
