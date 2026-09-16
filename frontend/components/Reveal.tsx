'use client';

import { useEffect, useRef, useState, type ReactNode } from 'react';

/**
 * Adds a one-time fade/slide-up reveal when the element scrolls into view,
 * mirroring the original `[data-reveal]` behavior.
 */
export default function Reveal({
  children,
  delay = 0,
  className = '',
}: {
  children: ReactNode;
  delay?: number;
  className?: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const [visible, setVisible] = useState(false);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    const el = ref.current;
    setReady(true);
    if (!el) return;
    if (typeof IntersectionObserver === 'undefined') {
      setVisible(true);
      return;
    }
    const io = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            setVisible(true);
            io.unobserve(entry.target);
          }
        });
      },
      { threshold: 0.16 },
    );
    io.observe(el);
    return () => io.disconnect();
  }, []);

  // Content is visible by default (SSR/no-JS safe). We only hide it once the
  // client has mounted so the reveal animation can run; if the observer never
  // fires, the section still stays visible instead of being blank.
  const hidden = ready && !visible;

  return (
    <div
      ref={ref}
      className={`transition-all duration-700 ease-ketsa ${className} ${
        hidden ? 'opacity-0 translate-y-[14px]' : 'opacity-100 translate-y-0'
      }`}
      style={{ transitionDelay: `${delay}ms` }}
    >
      {children}
    </div>
  );
}
