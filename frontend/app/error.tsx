'use client';

/**
 * Root error boundary.
 *
 * Reached when a server component throws — which, now that the bundled demo
 * data is gone, includes "the API is unreachable". It renders a neutral
 * unavailable state instead.
 *
 * SECURITY: `error.message` / `error.digest` are deliberately NOT rendered.
 * Upstream error strings can carry upstream hostnames, SQL/Auth0 detail or
 * request paths (CWE-209). The real message goes to the server log via
 * Next's own reporting; the browser only ever sees the copy below.
 */
export default function Error({
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <main
      className="flex min-h-screen flex-col items-center justify-center gap-6 px-6 text-center"
      role="alert"
    >
      <div className="max-w-[440px]">
        <h1 className="font-serif text-[26px] font-medium tracking-[-.01em]">
          Temporarily unavailable
        </h1>
        <p className="mt-3 text-[15px] text-ink-2">
          We couldn&rsquo;t load live market data just now. Please try again in a
          moment.
        </p>
        <button
          type="button"
          onClick={() => reset()}
          className="mt-7 rounded-[7px] bg-brand px-5 py-2.5 font-mono text-xs font-semibold uppercase tracking-[.06em] text-white transition-opacity hover:opacity-90"
        >
          Retry
        </button>
      </div>
    </main>
  );
}