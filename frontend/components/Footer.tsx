import Link from 'next/link';
import type { FooterContent } from '@/lib/types';

export default function Footer({ copy }: { copy: FooterContent }) {
  return (
    <footer className="border-t border-line pb-[30px] pt-[52px]">
      <div className="wrap">
        <div className="mb-10 grid grid-cols-1 gap-8 sm:grid-cols-2 lg:grid-cols-[1.4fr_repeat(3,1fr)]">
          <div className="foot__brand">
            <div className="flex items-center gap-[9px] font-serif text-[22px] font-semibold italic text-ink">
              <span className="h-2 w-2 rounded-full bg-brand" />
              Ketsa
            </div>
            <p className="mt-[14px] max-w-[250px] text-[13px] leading-[1.6] text-ink-3">
              {copy.tagline}
            </p>
          </div>

          {copy.columns.map((col) => (
            <div key={col.title}>
              <h4 className="mb-[15px] text-[11.5px] uppercase tracking-[.05em] text-ink-3">
                {col.title}
              </h4>
              <ul className="space-y-[10px]">
                {col.links.map((l) => (
                  <li key={l.label}>
                    <a
                      href={l.href}
                      className="text-[13.5px] text-ink-2 transition-colors duration-200 hover:text-ink"
                    >
                      {l.label}
                    </a>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>

        <div className="flex flex-wrap items-center justify-between gap-[10px] border-t border-line pt-[22px] text-xs text-ink-3">
          <span>{copy.copyright}</span>
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
            {/* Structural, not admin content: the legal links must always be
                present, regardless of what the editable footer columns say. */}
            <Link href="/terms" className="transition-colors hover:text-ink">
              Terms
            </Link>
            <Link href="/privacy" className="transition-colors hover:text-ink">
              Privacy
            </Link>
            <span>{copy.disclaimer}</span>
          </div>
        </div>
      </div>
    </footer>
  );
}
