import type { CtaContent } from '@/lib/types';

export default function CtaBand({ copy }: { copy: CtaContent }) {
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
        <a
          href="#top"
          className="btn btn--lg border-transparent bg-white text-ink hover:bg-[#E9ECF4]"
        >
          {copy.button}
        </a>
      </div>
    </section>
  );
}
