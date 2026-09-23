'use client';

import { useState } from 'react';

type Mode = 'login' | 'register';
type IdKind = 'email' | 'phone';

interface AuthModalProps {
  initialMode?: Mode;
  busy: boolean;
  error: string | null;
  onLogin: (identifier: string, password: string) => void;
  onRegister: (name: string, identifier: string, password: string) => void;
  onGoogle: () => void;
  onClose: () => void;
  onGuest: () => void;
}

const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;
// Malawi mobile: optional +265 / 265 / leading-0, then 9 digits starting 8|9.
// Mirrors backend normalize_phone() (spaces/dashes ignored client-side).
const PHONE_RE = /^(\+?265)?0?[89]\d{8}$/;

function normalizePhoneInput(v: string): string {
  return v.replace(/[\s\-()]/g, '');
}

function Field({
  label,
  type = 'text',
  value,
  onChange,
  placeholder,
  autoComplete,
  error,
}: {
  label: string;
  type?: string;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  autoComplete?: string;
  error?: string | null;
}) {
  return (
    <label className="block">
      <span className="mb-1.5 block font-mono text-[11px] font-semibold uppercase tracking-[.07em] text-ink-3">
        {label}
      </span>
      <input
        type={type}
        className="field w-full"
        value={value}
        placeholder={placeholder}
        autoComplete={autoComplete}
        spellCheck={false}
        onChange={(e) => onChange(e.target.value)}
      />
      {error && <span className="mt-1 block text-[12px] font-medium text-neg">{error}</span>}
    </label>
  );
}

function GoogleG() {
  return (
    <svg width="18" height="18" viewBox="0 0 48 48" aria-hidden focusable="false">
      <path
        fill="#EA4335"
        d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z"
      />
      <path
        fill="#4285F4"
        d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z"
      />
      <path
        fill="#FBBC05"
        d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z"
      />
      <path
        fill="#34A853"
        d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z"
      />
    </svg>
  );
}

export default function AuthModal({
  initialMode = 'login',
  busy,
  error,
  onLogin,
  onRegister,
  onGoogle,
  onClose,
  onGuest,
}: AuthModalProps) {
  const [mode, setMode] = useState<Mode>(initialMode);
  const [name, setName] = useState('');
  const [identifier, setIdentifier] = useState('');
  const [idKind, setIdKind] = useState<IdKind>('email');
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [showPw, setShowPw] = useState(false);
  const [localErrors, setLocalErrors] = useState<Record<string, string>>({});

  function switchMode(next: Mode) {
    setMode(next);
    setLocalErrors({});
  }

  function validate(): boolean {
    const errs: Record<string, string> = {};
    if (mode === 'register' && !name.trim()) errs.name = 'Enter your name';
    const raw = identifier.trim();
    if (idKind === 'email') {
      if (!EMAIL_RE.test(raw)) errs.identifier = 'Enter a valid email address';
    } else if (!PHONE_RE.test(normalizePhoneInput(raw))) {
      errs.identifier = 'Enter a valid Malawian phone number (e.g. 0991 234 567)';
    }
    if (password.length < 8) errs.password = 'Must be at least 8 characters';
    if (mode === 'register' && confirm !== password) errs.confirm = 'Passwords do not match';
    setLocalErrors(errs);
    return Object.keys(errs).length === 0;
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (busy || !validate()) return;
    if (mode === 'login') onLogin(identifier.trim(), password);
    else onRegister(name.trim(), identifier.trim(), password);
  }

  const tab =
    'flex-1 rounded-[9px] py-[10px] text-sm font-semibold transition-all duration-200 ease-ketsa';
  const activeTab = 'bg-ink text-white shadow-[0_6px_16px_-8px_rgba(12,21,38,.55)]';
  const idleTab = 'text-ink-2 hover:bg-paper hover:text-ink';

  return (
    <div
      className="fixed inset-0 z-[200] flex items-center justify-center bg-ink/40 p-4 backdrop-blur-[3px]"
      onClick={(e) => {
        if (e.target === e.currentTarget && !busy) onClose();
      }}
    >
      <div className="grid w-full max-w-[880px] overflow-hidden rounded-l border border-line bg-white shadow-[0_24px_60px_-20px_rgba(12,21,38,.35)] md:grid-cols-[0.9fr_1fr]">
        {/* Brand panel */}
        <aside className="relative hidden flex-col justify-between bg-ink p-8 text-white md:flex">
          <div className="flex items-center gap-[9px] font-serif text-[20px] font-semibold italic">
            <span className="h-2 w-2 rounded-full bg-brand" />
            Ketsa
          </div>
          <div>
            <div className="mb-4 inline-flex items-center gap-[6px] rounded-full bg-white/10 px-[10px] py-[4px] font-mono text-[10.5px] font-semibold uppercase tracking-[.07em] text-white/70">
              <span className="h-[5px] w-[5px] animate-pulse-dot rounded-full bg-pos" />
              Live markets
            </div>
            <h2 className="font-serif text-[28px] font-medium leading-[1.15]">
              Trade on what
              <em className="italic text-brand-tint"> happens next.</em>
            </h2>
            <ul className="mt-6 space-y-3 text-[13px] text-white/70">
              {[
                'Start with a play wallet funded with MK 1,000',
                'Buy Yes or No and cash out the instant odds move',
                'Top up with real money through wandePay',
              ].map((t) => (
                <li key={t} className="flex items-start gap-2.5">
                  <span className="mt-[1px] flex h-[18px] w-[18px] shrink-0 items-center justify-center rounded-full bg-brand text-[10px]">
                    ✓
                  </span>
                  {t}
                </li>
              ))}
            </ul>
          </div>
          <p className="font-mono text-[10.5px] uppercase tracking-[.08em] text-white/40">
            Prices move with the crowd
          </p>
        </aside>

        {/* Form panel */}
        <div className="flex flex-col p-7 md:p-8">
          <div className="mb-1 flex items-start justify-between">
            <div>
              <div className="mb-1 font-mono text-[10.5px] uppercase tracking-[.07em] text-brand">
                {mode === 'login' ? 'Welcome back' : 'Create your account'}
              </div>
              <h3 className="font-serif text-[24px] font-medium text-ink">
                {mode === 'login' ? 'Log in to Ketsa' : 'Start trading in minutes'}
              </h3>
            </div>
            <button
              aria-label="Close"
              className="rounded-full border border-transparent p-[6px] text-ink-3 transition-colors hover:border-line hover:text-ink"
              onClick={busy ? undefined : onClose}
            >
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
                <path d="M6 6L18 18M18 6L6 18" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
              </svg>
            </button>
          </div>

          <div className="mt-5 flex rounded-[10px] border border-line bg-paper-alt p-[4px]">
            <button
              type="button"
              className={`${tab} ${mode === 'login' ? activeTab : idleTab}`}
              onClick={() => switchMode('login')}
            >
              Log in
            </button>
            <button
              type="button"
              className={`${tab} ${mode === 'register' ? activeTab : idleTab}`}
              onClick={() => switchMode('register')}
            >
              Create account
            </button>
          </div>

          <div className="mt-6">
            <button
              type="button"
              onClick={busy ? undefined : onGoogle}
              disabled={busy}
              className="flex w-full items-center justify-center gap-2.5 rounded-[9px] border border-line bg-white px-5 py-[12px] text-sm font-semibold text-ink transition-all duration-200 ease-ketsa hover:-translate-y-[1px] hover:border-ink hover:bg-paper disabled:cursor-not-allowed disabled:opacity-60"
            >
              <GoogleG />
              Continue with Google
            </button>
          </div>

          <div className="my-5 flex items-center gap-3" aria-hidden>
            <span className="h-px flex-1 bg-line" />
            <span className="font-mono text-[10px] font-semibold uppercase tracking-[.08em] text-ink-3">
              or
            </span>
            <span className="h-px flex-1 bg-line" />
          </div>

          <form onSubmit={submit} className="space-y-4" noValidate>
            {mode === 'register' && (
              <Field
                label="Name"
                value={name}
                onChange={setName}
                placeholder="Ada Okafor"
                autoComplete="name"
                error={localErrors.name}
              />
            )}
            <div>
              <div className="mb-1.5 flex items-center justify-between">
                <span className="font-mono text-[11px] font-semibold uppercase tracking-[.07em] text-ink-3">
                  Email or phone
                </span>
                <div className="flex gap-[3px] rounded-full border border-line bg-paper-alt p-[3px]">
                  <button
                    type="button"
                    className={`rounded-full px-[11px] py-[3px] font-mono text-[10px] font-semibold uppercase tracking-[.06em] transition-colors ${
                      idKind === 'email' ? 'bg-ink text-white' : 'text-ink-3 hover:text-ink'
                    }`}
                    onClick={() => setIdKind('email')}
                  >
                    Email
                  </button>
                  <button
                    type="button"
                    className={`rounded-full px-[11px] py-[3px] font-mono text-[10px] font-semibold uppercase tracking-[.06em] transition-colors ${
                      idKind === 'phone' ? 'bg-ink text-white' : 'text-ink-3 hover:text-ink'
                    }`}
                    onClick={() => setIdKind('phone')}
                  >
                    Phone
                  </button>
                </div>
              </div>
              <input
                type={idKind === 'email' ? 'email' : 'tel'}
                className="field w-full"
                value={identifier}
                placeholder={idKind === 'email' ? 'you@example.com' : '0991 234 567'}
                autoComplete={idKind === 'email' ? 'email' : 'tel'}
                inputMode={idKind === 'email' ? 'email' : 'tel'}
                spellCheck={false}
                onChange={(e) => setIdentifier(e.target.value)}
              />
              {localErrors.identifier && (
                <span className="mt-1 block text-[12px] font-medium text-neg">
                  {localErrors.identifier}
                </span>
              )}
            </div>
            <div>
              <div className="mb-1.5 flex items-center justify-between">
                <span className="font-mono text-[11px] font-semibold uppercase tracking-[.07em] text-ink-3">
                  Password
                </span>
                {mode === 'login' && (
                  <span className="text-[11px] text-ink-3">8+ characters</span>
                )}
              </div>
              <div className="relative">
                <input
                  type={showPw ? 'text' : 'password'}
                  className="field w-full pr-[42px]"
                  value={password}
                  placeholder="••••••••"
                  autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
                  onChange={(e) => setPassword(e.target.value)}
                />
                <button
                  type="button"
                  aria-label={showPw ? 'Hide password' : 'Show password'}
                  className="absolute right-[12px] top-1/2 -translate-y-1/2 text-ink-3 transition-colors hover:text-ink"
                  onClick={() => setShowPw((v) => !v)}
                >
                  {showPw ? (
                    <svg width="17" height="17" viewBox="0 0 24 24" fill="none">
                      <path d="M2 12s3.5-6 10-6 10 6 10 6-3.5 6-10 6-10-6-10-6Z" stroke="currentColor" strokeWidth="1.6" />
                      <path d="M2 2l20 20" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
                    </svg>
                  ) : (
                    <svg width="17" height="17" viewBox="0 0 24 24" fill="none">
                      <path d="M2 12s3.5-6 10-6 10 6 10 6-3.5 6-10 6-10-6-10-6Z" stroke="currentColor" strokeWidth="1.6" />
                      <circle cx="12" cy="12" r="3" stroke="currentColor" strokeWidth="1.6" />
                    </svg>
                  )}
                </button>
              </div>
              {localErrors.password && (
                <span className="mt-1 block text-[12px] font-medium text-neg">{localErrors.password}</span>
              )}
            </div>
            {mode === 'register' && (
              <Field
                label="Confirm password"
                type="password"
                value={confirm}
                onChange={setConfirm}
                placeholder="••••••••"
                autoComplete="new-password"
                error={localErrors.confirm}
              />
            )}

            {error && (
              <div className="rounded-[8px] border border-neg/25 bg-neg-tint px-[13px] py-[10px] text-[13px] font-medium text-neg">
                {error}
              </div>
            )}

            <button
              type="submit"
              className="w-full rounded-[9px] bg-ink px-5 py-[12px] text-sm font-semibold text-white transition-all duration-200 ease-ketsa hover:-translate-y-[1px] hover:bg-brand-ink disabled:cursor-not-allowed disabled:opacity-60"
              disabled={busy}
            >
              {busy
                ? mode === 'login'
                  ? 'Logging in…'
                  : 'Creating account…'
                : mode === 'login'
                  ? 'Log in'
                  : 'Create account'}
            </button>
          </form>

          <div className="mt-5 border-t border-line pt-4 text-center">
            <button
              type="button"
              className="text-[12.5px] font-medium text-ink-3 transition-colors hover:text-ink"
              onClick={busy ? undefined : onGuest}
            >
              Skip — continue with a play wallet instead
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}