'use client';

import { useState } from 'react';

const NAV_LINKS = [
  { href: '#markets', label: 'Markets' },
  { href: '#dashboard', label: 'Dashboard' },
  { href: '#how', label: 'How it works' },
  { href: '#top', label: 'Docs' },
];

export default function Nav() {
  const [open, setOpen] = useState(false);

  return (
    <header className="sticky top-0 z-[100] border-b border-line bg-[rgba(255,255,255,.92)] backdrop-blur-[10px]">
      <div className="wrap flex h-[68px] items-center justify-between">
        <a href="#top" className="flex items-center gap-[9px] font-serif text-[22px] font-semibold italic text-ink">
          <span className="h-2 w-2 rounded-full bg-brand" />
          Ketsa
        </a>

        <nav
          className={`${
            open
              ? 'absolute left-0 right-0 top-[68px] flex flex-col gap-4 border-b border-line bg-white px-5 pb-6 pt-[18px]'
              : 'hidden items-center gap-[34px] md:flex'
          }`}
        >
          {NAV_LINKS.map((l) => (
            <a
              key={l.label}
              href={l.href}
              className="text-sm font-medium text-ink-2 transition-colors duration-200 ease-ketsa hover:text-ink"
              onClick={() => setOpen(false)}
            >
              {l.label}
            </a>
          ))}
        </nav>

        <div className="flex items-center gap-[10px]">
          <a href="#top" className="btn btn--ghost">
            Log in
          </a>
          <a href="#top" className="btn btn--brand">
            Get started
          </a>
          <button
            className="md:hidden"
            aria-label="Menu"
            aria-expanded={open}
            onClick={() => setOpen((v) => !v)}
          >
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none">
              <path
                d={open ? 'M6 6L18 18M18 6L6 18' : 'M4 7H20M4 12H20M4 17H20'}
                stroke="#0C1526"
                strokeWidth="1.8"
                strokeLinecap="round"
              />
            </svg>
          </button>
        </div>
      </div>
    </header>
  );
}
