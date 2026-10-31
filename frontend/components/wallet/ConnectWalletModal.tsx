'use client';

import { useState } from 'react';
import type { Wallet } from '@/lib/types';

const ADJECTIVES = [
  'brave', 'swift', 'calm', 'bold', 'keen', 'sage', 'nova', 'feral',
  'bright', 'stealth', 'mellow', 'lucky', 'fearless', 'witty', 'quiet',
];
const NOUNS = [
  'otter', 'falcon', 'lynx', 'orca', 'puma', 'raven', 'badger', 'kestrel',
  'heron', 'mako', 'gazelle', 'otter', 'lynx', 'viper', 'heron', 'cobra',
];

function randomName(): string {
  const a = ADJECTIVES[Math.floor(Math.random() * ADJECTIVES.length)];
  const n = NOUNS[Math.floor(Math.random() * NOUNS.length)];
  const num = Math.floor(100 + Math.random() * 900);
  return `${a}-${n}-${num}`;
}

export default function ConnectWalletModal({
  onConnect,
  onClose,
  busy,
}: {
  onConnect: (name: string) => void;
  onClose: () => void;
  busy: boolean;
}) {
  const [name, setName] = useState(() => randomName());

  return (
    <div
      className="fixed inset-0 z-[200] flex items-center justify-center bg-ink/40 p-4 backdrop-blur-[3px]"
      onClick={(e) => {
        if (e.target === e.currentTarget && !busy) onClose();
      }}
    >
      <div className="w-full max-w-[420px] rounded-l border border-line bg-white p-7 shadow-[0_24px_60px_-20px_rgba(12,21,38,.35)]">
        <div className="mb-1 flex items-start justify-between">
          <div>
            <div className="mb-1 font-mono text-[10.5px] uppercase tracking-[.07em] text-brand">
              Simulated wallet
            </div>
            <h2 className="font-serif text-[24px] font-medium text-ink">
              Connect your wallet
            </h2>
          </div>
          <button
            aria-label="Close"
            className="text-ink-3 transition-colors hover:text-ink"
            onClick={busy ? undefined : onClose}
          >
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
              <path d="M6 6L18 18M18 6L6 18" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
            </svg>
          </button>
        </div>

        <p className="mb-5 text-sm text-ink-2">
          Markets run on a simulated wallet — no sign-up needed to explore the
          order books. Create an account to deposit real money 
          and trade with actual MWK.
        </p>

        <label className="mb-1 block font-mono text-[11px] uppercase tracking-[.06em] text-ink-3">
          Display name
        </label>
        <input
          className="field mb-5 w-full"
          value={name}
          maxLength={40}
          onChange={(e) => setName(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !busy) onConnect(name);
          }}
        />

        <div className="flex gap-3">
          <button
            className="w-full rounded-full bg-ink px-5 py-[11px] text-sm font-semibold text-white transition-all duration-200 ease-ketsa hover:-translate-y-[1px] hover:bg-brand-ink disabled:cursor-not-allowed disabled:opacity-60"
            disabled={busy || !name.trim()}
            onClick={() => onConnect(name.trim())}
          >
            {busy ? 'Connecting…' : 'Connect'}
          </button>
          <button
            className="rounded-full border border-line-strong px-4 text-sm font-semibold text-ink-2 transition-colors hover:border-ink"
            onClick={() => setName(randomName())}
            title="Randomize"
          >
            ↻
          </button>
        </div>
      </div>
    </div>
  );
}

export type { Wallet };
