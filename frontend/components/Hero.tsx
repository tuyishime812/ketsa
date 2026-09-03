import Reveal from './Reveal';
import { CountUp } from './CountUp';
import WatchPanel from './WatchPanel';
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
  return (
    <section className="border-b border-line pb-16 pt-20">
      <div className="wrap grid items-start gap-16 md:grid-cols-[1fr_.92fr]">
        <div>
          <Reveal delay={40}>
            <span className="mb-6 inline-flex items-center gap-[7px] rounded-full border border-[#D6E0FB] bg-brand-tint px-[11px] py-[6px] font-mono text-xs tracking-[.03em] text-brand">
              <span className="h-[5px] w-[5px] animate-pulse-dot rounded-full bg-pos" />
              {copy.badge}
            </span>
          </Reveal>

          <Reveal delay={120}>
            <h1 className="font-serif text-[clamp(38px,4.4vw,58px)] font-medium leading-[1.08] tracking-[-.01em] text-ink">
              {copy.headline_1}<em className="italic text-brand">{copy.headline_accent}</em>
            </h1>
          </Reveal>

          <Reveal delay={200}>
            <p className="mt-[22px] max-w-[460px] text-[17px] leading-[1.65] text-ink-2">
              {copy.description}
            </p>
          </Reveal>

          <Reveal delay={280}>
            <div className="mt-8 flex flex-wrap gap-3">
              <a href="#markets" className="btn btn--brand btn--lg">
                Explore markets
              </a>
              <a href="#how" className="btn btn--ghost btn--lg">
                How it works
              </a>
            </div>
          </Reveal>

          <Reveal delay={360}>
            <div className="mt-12 flex flex-wrap gap-y-4 border-t border-line pt-[26px]">
              <ProofStat num={proof.traders_k} suffix="K" label="Traders onboard" />
              <ProofStat num={proof.live_markets} label="Live markets" />
              <ProofStat num={proof.total_volume_m} suffix="M" label="Total volume" decimals={1} />
            </div>
          </Reveal>
        </div>

        <Reveal delay={220}>
          <WatchPanel items={watch} />
        </Reveal>
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
