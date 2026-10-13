import Link from 'next/link';

/**
 * Branded 404. Rendered for unknown routes and for `notFound()` calls from
 * server components (e.g. /markets/[id] with an id that does not exist).
 *
 * Server component on purpose: it must render even when the API is unreachable
 * (a thrown fetch belongs to the error boundary, not here).
 */
export default function NotFound() {
  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-6 px-6 text-center">
      <div className="max-w-[460px]">
        <div className="font-mono text-[11px] uppercase tracking-[.09em] text-ink-3">
          404 — not found
        </div>
        <h1 className="mt-3 font-serif text-[26px] font-medium tracking-[-.01em] text-ink">
          This page isn&rsquo;t on the board
        </h1>
        <p className="mt-3 text-[15px] text-ink-2">
          The market or page you were looking for has moved, resolved, or never
          existed.
        </p>
        <div className="mt-7 flex flex-wrap items-center justify-center gap-3">
          <Link
            href="/"
            className="rounded-[7px] bg-brand px-5 py-2.5 font-mono text-xs font-semibold uppercase tracking-[.06em] text-white transition-opacity hover:opacity-90"
          >
            Back to markets
          </Link>
          <Link
            href="/markets"
            className="rounded-[7px] border border-line bg-white px-5 py-2.5 font-mono text-xs font-semibold uppercase tracking-[.06em] text-ink transition-colors hover:border-ink-3"
          >
            Browse all
          </Link>
        </div>
      </div>
    </main>
  );
}
