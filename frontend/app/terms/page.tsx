import type { Metadata } from 'next';
import Link from 'next/link';

/**
 * Terms of Service.
 *
 * REVIEW REQUIRED BEFORE LAUNCH: this is a good-faith baseline for a
 * real-money prediction market, not legal advice. Have counsel review it and
 * fill in the operator entity, governing jurisdiction and contact channel
 * (`NEXT_PUBLIC_KETSA_CONTACT_EMAIL`) for your jurisdiction before going live.
 * See RUNBOOK.md.
 */
export const metadata: Metadata = {
  title: 'Terms of Service — Ketsa',
  description:
    'The rules for using Ketsa: eligibility, your account, deposits and withdrawals, trading risk, and how markets resolve.',
};

const CONTACT = process.env.NEXT_PUBLIC_KETSA_CONTACT_EMAIL?.trim();

function H2({ children }: { children: React.ReactNode }) {
  return (
    <h2 className="mt-9 font-serif text-[19px] font-medium text-ink">{children}</h2>
  );
}

export default function TermsPage() {
  return (
    <main className="wrap py-[56px]">
      <div className="mx-auto max-w-[720px]">
        <Link
          href="/"
          className="font-mono text-[12px] text-ink-2 transition-colors hover:text-ink"
        >
          ← Back to Ketsa
        </Link>
        <h1 className="mt-5 font-serif text-[clamp(26px,3vw,34px)] font-medium tracking-[-.01em]">
          Terms of Service
        </h1>
        <p className="mt-3 text-[13px] text-ink-3">Last updated: 13 October 2026</p>

        <div className="mt-6 space-y-4 text-[14.5px] leading-relaxed text-ink-2">
          <p>
            These terms govern your use of Ketsa (the &ldquo;platform&rdquo;), a
            market where participants trade on the outcome of real-world events.
            By creating an account, funding a wallet, or placing a trade you agree
            to them. If you do not agree, do not use the platform.
          </p>

          <H2>1. Eligibility</H2>
          <p>
            You must be at least 18 years old and legally able to enter into this
            agreement. You are responsible for ensuring that using the platform is
            lawful where you are located.
          </p>

          <H2>2. Your account</H2>
          <p>
            You must give accurate registration details and keep your password
            confidential. You are responsible for all activity under your account.
            One account per person; accounts are not transferable.
          </p>

          <H2>3. Deposits, balances and withdrawals</H2>
          <p>
            Wallets are funded in Malawian Kwacha (MWK) through our payment
            partner. Balances shown are held for trading on the platform and are
            not a bank deposit. Withdrawal caps and verification requirements may
            apply. You are responsible for sending funds to the correct
            destination.
          </p>

          <H2>4. Trading and risk</H2>
          <p>
            Prices reflect what participants are willing to pay, not a
            bookmaker&rsquo;s odds. Prices can move against you and a position can
            become worthless if it does not resolve in your favour. Trade only
            what you can afford to lose. We do not provide investment advice.
          </p>

          <H2>5. Market resolution</H2>
          <p>
            Each market has published rules describing the outcome and the source
            used to decide it. We resolve markets in line with those rules and may
            correct an obvious error. Resolution decisions are final once a market
            is settled and positions are paid out.
          </p>

          <H2>6. Prohibited conduct</H2>
          <p>
            Do not manipulate prices or markets, use multiple accounts to evade
            limits, attempt to defraud the platform or other users, or interfere
            with the platform&rsquo;s operation or security. We may suspend or
            close accounts that breach these terms.
          </p>

          <H2>7. Availability and changes</H2>
          <p>
            The platform is provided &ldquo;as is&rdquo; and may be unavailable
            from time to time for maintenance or because of events outside our
            control. We may update these terms; material changes will be announced
            in the app, and continued use means you accept them.
          </p>

          <H2>8. Limitation of liability</H2>
          <p>
            To the fullest extent permitted by law, the platform is not liable for
            indirect or consequential losses, or for losses arising from market
            movements, third-party services, or your own account security.
          </p>

          <H2>9. Contact</H2>
          <p>
            {CONTACT
              ? `Questions about these terms: ${CONTACT}.`
              : 'Questions about these terms can be raised through the support channel in the app.'}
          </p>
        </div>
      </div>
    </main>
  );
}
