/**
 * Rendered when the Ketsa API cannot be reached from a server component.
 *
 * Replaces the old behaviour, where a page silently fell back to a bundled
 * demo dataset. That fallback was the more dangerous option: every figure it
 * served (prices, volume, trader counts, the hero badge) was presented to the
 * user as real, so an API outage would have rendered invented market data as
 * live. This fails closed instead.
 *
 * SECURITY: by default this takes no error object and renders no upstream text.
 * API/host/connection detail stays in the server log (CWE-209). A dev-only hint
 * may be shown to help local setup; never enable detailed hints in production.
 */
export default function DataUnavailable({
  what,
  devHint,
}: {
  what: string;
  /** Shown only in non-production builds to aid local troubleshooting. */
  devHint?: string;
}) {
  const showHint = process.env.NODE_ENV !== 'production' && devHint;
  return (
    <div className="flex min-h-[52vh] flex-col items-center justify-center px-6 text-center">
      <div className="max-w-[440px]">
        <h1 className="font-serif text-[26px] font-medium tracking-[-.01em]">
          Temporarily unavailable
        </h1>
        <p className="mt-3 text-[15px] text-ink-2">
          We couldn&rsquo;t load live {what} just now. Please try again in a
          moment.
        </p>
        {showHint ? (
          <p className="mt-3 rounded-[7px] border border-border bg-paper-alt px-3 py-2 text-left text-[12px] text-ink-3">
            <strong className="font-medium text-ink-2">Dev:</strong> {devHint}
          </p>
        ) : null}
        {/* A plain anchor, not a client-side reset: this component renders on
            the server, so a full reload is what actually re-runs the fetch. */}
        <a
          href="."
          className="mt-7 inline-block rounded-[7px] bg-brand px-5 py-2.5 font-mono text-xs font-semibold uppercase tracking-[.06em] text-white transition-opacity hover:opacity-90"
        >
          Retry
        </a>
      </div>
    </div>
  );
}
