import Link from 'next/link';
import Reveal from './Reveal';
import { CountUp } from './CountUp';
import WatchPanel from './WatchPanel';
import AuthCta from './auth/AuthCta';
import type { HeroContent, Proof, WatchItem } from '@/lib/types';

export default function Hero({
  watch,
  proof,
  copy,
}: {
  watch: WatchItem[];
  proof: Proof;
  copy: HeroContent;
}) {
  const hasWatch = watch.length > 0;
  const hasProof =
    proof.traders_k > 0 || proof.live_markets > 0 || proof.total_volume_m > 0;

  return (
    <section className="border-b border-line pb-16 pt-16">
      <div className={`wrap grid items-center gap-12 ${hasWatch ? 'lg:grid-cols-[1fr_.95fr]' : ''}`}>
        <div>
          <Reveal delay={40}>
            <span className="mb-6 inline-flex items-center gap-[8px] rounded-full border border-line bg-white px-[12px] py-[6px] font-mono text-xs font-semibold tracking-[.03em] text-ink-2 shadow-[0_1px_2px_rgba(12,21,38,.04)]">
              <span className="h-[6px] w-[6px] animate-pulse-dot rounded-full bg-pos" />
              {copy.badge}<span className="text-ink-3">· live</span>
            </span>
          </Reveal>

          <Reveal delay={120}>
            <h1 className="font-serif text-[clamp(34px,4.2vw,52px)] font-medium leading-[1.08] tracking-[-.01em] text-ink">
              {copy.headline_1}<em className="italic text-brand">{copy.headline_accent}</em>
            </h1>
          </Reveal>

          <Reveal delay={200}>
            <p className="mt-[20px] max-w-[460px] text-[16px] leading-[1.65] text-ink-2">
              {copy.description}
            </p>
          </Reveal>

          <Reveal delay={280}>
            <div className="mt-8 flex flex-wrap items-center gap-3">
              <a href="#markets" className="btn btn--brand btn--lg">
                Explore markets
              </a>
              <AuthCta variant="lg" />
            </div>
          </Reveal>

          <Reveal delay={320}>
            <p className="mt-4 text-[13px] text-ink-3">
              Or keep browsing as a guest with a{' '}
              <Link href="/markets" className="font-semibold text-brand hover:text-ink">
                play wallet
              </Link>{' '}
              — no account needed.
            </p>
          </Reveal>

          {hasProof && (
            <Reveal delay={360}>
              <div className="mt-10 flex flex-wrap gap-x-8 gap-y-4 border-t border-line pt-[24px]">
                <ProofStat num={proof.traders_k} suffix="K" label="Traders onboard" />
                <ProofStat num={proof.live_markets} label="Live markets" />
                <ProofStat num={proof.total_volume_m} suffix="M" label="Total volume" decimals={1} />
              </div>
            </Reveal>
          )}
        </div>

        {hasWatch && (
          <Reveal delay={220}>
            <WatchPanel items={watch} />
          </Reveal>
        )}
      </div>
    </section>
  );
}

function ProofStat({
  num,
  suffix = '',
  label,
  decimals = 0,
}: {
  num: number;
  suffix?: string;
  label: string;
  decimals?: number;
}) {
  return (
    <div className="border-r border-line pr-8 [&:not(:first-child)]:mr-8">
      <div className="font-mono text-[21px] font-semibold text-ink">
        <CountUp target={num} suffix={suffix} decimals={decimals} />
      </div>
      <div className="mt-1 text-xs text-ink-3">{label}</div>
    </div>
  );
}
