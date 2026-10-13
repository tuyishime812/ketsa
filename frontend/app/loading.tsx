/**
 * Route-segment loading UI. Next renders this instantly while a server
 * component resolves, so navigating to /markets or a market page shows a
 * deliberate loading state instead of a frozen or blank screen (the market
 * pages fetch live data on every request).
 *
 * `aria-busy` + a screen-reader status keep it honest for assistive tech
 * rather than a purely decorative spinner.
 */
export default function Loading() {
  return (
    <main
      aria-busy="true"
      aria-live="polite"
      className="flex min-h-screen flex-col items-center justify-center gap-4 px-6"
    >
      <span
        aria-hidden="true"
        className="h-8 w-8 animate-spin rounded-full border-2 border-line border-t-brand"
      />
      <span className="sr-only">Loading live market data…</span>
      <span className="font-mono text-[11px] uppercase tracking-[.08em] text-ink-3">
        Loading live markets…
      </span>
    </main>
  );
}
