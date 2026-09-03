import type { StepsContent } from '@/lib/types';

export default function Steps({ copy }: { copy: StepsContent }) {
  return (
    <section className="section" id="how">
      <div className="wrap">
        <div className="mb-[38px] flex flex-wrap items-end justify-between gap-6">
          <div>
            <div className="mb-[9px] font-mono text-[11.5px] uppercase tracking-[.06em] text-brand">
              {copy.kicker}
            </div>
            <h2 className="font-serif text-[clamp(26px,3vw,34px)] font-medium tracking-[-.01em]">
              {copy.title}
            </h2>
          </div>
          <p className="max-w-[420px] text-[15px] text-ink-2">
            {copy.description}
          </p>
        </div>

        <div className="border-t border-line">
          {copy.items.map((s) => (
            <div
              key={s.num}
              className="grid items-baseline gap-6 border-b border-line py-8 md:grid-cols-[80px_1fr_1.4fr]"
            >
              <div className="font-mono text-[13px] text-brand">{s.num}</div>
              <h3 className="font-serif text-xl font-medium">{s.title}</h3>
              <p className="text-[14.5px] leading-[1.65] text-ink-2">{s.body}</p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
