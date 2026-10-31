'use client';

import type { ReactNode } from 'react';

export default function StatCard({
  label,
  value,
  sub,
  tone = 'neutral',
  icon,
  trend,
}: {
  label: string;
  value: string;
  sub?: string;
  tone?: 'pos' | 'neg' | 'neutral' | 'brand';
  icon?: ReactNode;
  trend?: { dir: 'up' | 'down'; label: string };
}) {
  const toneText =
    tone === 'pos'
      ? 'text-pos'
      : tone === 'neg'
        ? 'text-neg'
        : tone === 'brand'
          ? 'text-brand'
          : 'text-ink';

  return (
    <div className="group relative overflow-hidden rounded-m border border-line bg-white p-5 transition-shadow duration-200 ease-ketsa hover:shadow-[0_16px_40px_-24px_rgba(12,21,38,.25)]">
      <div className="flex items-start justify-between gap-3">
        <span className="font-mono text-[10.5px] uppercase tracking-[.07em] text-ink-3">
          {label}
        </span>
        {icon && (
          <span className="flex h-[30px] w-[30px] shrink-0 items-center justify-center rounded-[8px] bg-paper-alt text-brand transition-colors duration-200 ease-ketsa group-hover:bg-brand-tint">
            {icon}
          </span>
        )}
      </div>
      <div
        className={`mt-[6px] font-mono text-[clamp(20px,2vw,25px)] font-semibold tracking-[-.02em] tabular-nums ${toneText}`}
      >
        {value}
      </div>
      {(sub || trend) && (
        <div className="mt-[6px] flex items-center gap-[7px]">
          {trend && (
            <span
              className={`inline-flex items-center gap-[3px] rounded-full px-[7px] py-[2px] font-mono text-[10.5px] font-semibold ${
                trend.dir === 'up' ? 'bg-pos-tint text-pos' : 'bg-neg-tint text-neg'
              }`}
            >
              <svg width="9" height="9" viewBox="0 0 24 24" fill="none">
                {trend.dir === 'up' ? (
                  <path d="M18 15l-6-6-6 6" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" />
                ) : (
                  <path d="M6 9l6 6 6-6" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" />
                )}
              </svg>
              {trend.label}
            </span>
          )}
          {sub && !trend && (
            <span className="text-[11.5px] font-medium text-ink-3">{sub}</span>
          )}
        </div>
      )}
    </div>
  );
}
