'use client';

import { useWallet } from '@/components/wallet/WalletProvider';
import type { CtaContent } from '@/lib/types';

export default function CtaBand({ copy }: { copy: CtaContent }) {
  const { user, wallet, loading, openAuth } = useWallet();

  return (
    <section className="mb-24 px-8">
      <div className="mx-auto flex max-w-[1220px] flex-col items-start justify-between gap-8 rounded-l bg-ink p-[36px] text-white sm:flex-row sm:items-center sm:px-[52px] sm:py-[60px]">
        <div>
          <h2 className="max-w-[440px] font-serif text-[clamp(24px,3vw,32px)] font-medium tracking-[-.01em]">
            {copy.title}
          </h2>
          <p className="mt-[10px] max-w-[400px] text-[15px] text-[#AEB8CC]">
            {copy.description}
          </p>
        </div>

        {/* The CTA label stays admin-editable; the action opens the auth modal
            instead of the old dead `href="#top"` scroll-to-top anchor. */}
        <div className="flex flex-wrap items-center gap-3">
          {loading ? (
            <span
              className="btn btn--lg animate-pulse border-transparent bg-white text-ink opacity-60"
              aria-hidden
            >
              {copy.button}
            </span>
          ) : user || wallet ? (
            <a
              href="/dashboard"
              className="btn btn--lg border-transparent bg-white text-ink hover:bg-[#E9ECF4]"
            >
              Go to dashboard
            </a>
          ) : (
            <>
              <button
                type="button"
                className="btn btn--lg border-transparent bg-white text-ink hover:bg-[#E9ECF4]"
                onClick={() => openAuth('register')}
              >
                {copy.button}
              </button>
              <button
                type="button"
                className="btn btn--lg border-white/25 text-white hover:border-white hover:bg-white/10"
                onClick={() => openAuth('login')}
              >
                Log in
              </button>
            </>
          )}
        </div>
      </div>
    </section>
  );
}
