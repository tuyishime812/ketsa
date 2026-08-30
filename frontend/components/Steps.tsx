const STEPS = [
  {
    num: '01',
    title: 'Pick a market',
    body: 'Browse thousands of questions on politics, crypto, sport, and culture — each priced by real trading, not a bookmaker\u2019s line.',
  },
  {
    num: '02',
    title: 'Buy Yes or No',
    body: 'Shares cost between 1¢ and 99¢. If you\u2019re right, each share resolves to $1. If you\u2019re wrong, it resolves to zero.',
  },
  {
    num: '03',
    title: 'Cash out anytime',
    body: 'Sell your position the moment the odds move your way — you don\u2019t have to wait for the market to resolve.',
  },
];

export default function Steps() {
  return (
    <section className="section" id="how">
      <div className="wrap">
        <div className="mb-[38px] flex flex-wrap items-end justify-between gap-6">
          <div>
            <div className="mb-[9px] font-mono text-[11.5px] uppercase tracking-[.06em] text-brand">
              Mechanics
            </div>
            <h2 className="font-serif text-[clamp(26px,3vw,34px)] font-medium tracking-[-.01em]">
              Three steps, one price
            </h2>
          </div>
          <p className="max-w-[420px] text-[15px] text-ink-2">
            No order forms, no fine print. Shares trade between 1¢ and 99¢ based
            on what the market believes.
          </p>
        </div>

        <div className="border-t border-line">
          {STEPS.map((s) => (
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
