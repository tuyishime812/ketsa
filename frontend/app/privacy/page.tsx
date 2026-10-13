import type { Metadata } from 'next';
import Link from 'next/link';

/**
 * Privacy Policy.
 *
 * REVIEW REQUIRED BEFORE LAUNCH: a good-faith baseline describing what Ketsa
 * collects and why, not legal advice. Have counsel review it against the data
 * protection law that applies to you (e.g. Malawi's Data Protection Act) and
 * fill in the operator entity and contact channel before going live. See
 * RUNBOOK.md.
 */
export const metadata: Metadata = {
  title: 'Privacy Policy — Ketsa',
  description:
    'What Ketsa collects, why, who it is shared with, how long it is kept, and the choices you have.',
};

const CONTACT = process.env.NEXT_PUBLIC_KETSA_CONTACT_EMAIL?.trim();

function H2({ children }: { children: React.ReactNode }) {
  return (
    <h2 className="mt-9 font-serif text-[19px] font-medium text-ink">{children}</h2>
  );
}

export default function PrivacyPage() {
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
          Privacy Policy
        </h1>
        <p className="mt-3 text-[13px] text-ink-3">Last updated: 13 October 2026</p>

        <div className="mt-6 space-y-4 text-[14.5px] leading-relaxed text-ink-2">
          <p>
            This policy explains what Ketsa collects when you use the platform,
            why we collect it, and the choices you have. Ketsa handles personal
            data as a controller.
          </p>

          <H2>1. What we collect</H2>
          <ul className="list-disc space-y-2 pl-5">
            <li>
              <strong className="font-medium text-ink">Account details</strong> —
              your name and either an email address or a phone number, plus a
              hashed password. Passwords are hashed; we never store the original.
            </li>
            <li>
              <strong className="font-medium text-ink">
                Wallet and transaction data
              </strong>{' '}
              — balances, deposits, withdrawals, trades, positions and holds,
              needed to run the market and keep a correct ledger.
            </li>
            <li>
              <strong className="font-medium text-ink">Session data</strong> —
              a session token so you stay signed in, and basic security signals
              used to detect abuse.
            </li>
          </ul>

          <H2>2. Why we use it</H2>
          <p>
            To create and secure your account, process deposits, withdrawals and
            trades, resolve markets and pay out positions, provide support, meet
            legal and anti-fraud obligations, and keep the service working.
          </p>

          <H2>3. Who we share it with</H2>
          <p>
            We share only what is needed, with service providers acting on our
            instructions:
          </p>
          <ul className="list-disc space-y-2 pl-5">
            <li>
              <strong className="font-medium text-ink">Payment provider</strong> —
              to move funds for deposits and withdrawals.
            </li>
            <li>
              <strong className="font-medium text-ink">Email provider</strong> — to
              deliver verification and account emails.
            </li>
            <li>
              <strong className="font-medium text-ink">Hosting and database</strong>{' '}
              — to store account and market data.
            </li>
          </ul>
          <p>
            We do not sell your personal data.
          </p>

          <H2>4. How long we keep it</H2>
          <p>
            We keep account and transaction records for as long as your account is
            active and afterwards only as long as needed for legal, tax, security
            and dispute-resolution purposes. Session tokens expire automatically.
          </p>

          <H2>5. Security</H2>
          <p>
            We protect data with encryption in transit, hashed passwords and
            access controls, and we log security-relevant events without recording
            secrets. No system is perfectly secure; keep your password private and
            contact us if you suspect unauthorised access.
          </p>

          <H2>6. Your choices</H2>
          <p>
            You can access and update your account details in the app and ask us
            to correct or delete data we are not required to keep. Some records
            must be retained to satisfy legal obligations.
          </p>

          <H2>7. Contact</H2>
          <p>
            {CONTACT
              ? `Privacy questions or requests: ${CONTACT}.`
              : 'Privacy questions or requests can be raised through the support channel in the app.'}
          </p>
        </div>
      </div>
    </main>
  );
}
