'use client';

import { useEffect, useRef, useState } from 'react';

type Mode = 'login' | 'register';
type IdKind = 'email' | 'phone';
type Step = 'auth' | 'verify' | 'forgot' | 'logincode';

interface AuthModalProps {
  initialMode?: Mode;
  busy: boolean;
  error: string | null;
  /** Email awaiting OTP verification, when a signup is in flight. */
  pendingEmail: string | null;
  onLogin: (identifier: string, password: string) => void;
  /**
   * Ask for a sign-in code to be emailed. Resolves true when the backend
   * accepted the request — which is NOT confirmation that the address has an
   * account, so the caller must show the code step either way.
   */
  onRequestLoginCode: (identifier: string) => Promise<boolean>;
  /** Complete a passwordless sign-in with the emailed code. */
  onLoginWithCode: (email: string, otp: string) => Promise<void>;
  /**
   * Register. Resolves 'pending' when the backend answered 202 (email OTP
   * emailed — the modal moves to the verify step) or null otherwise.
   */
  onRegister: (
    name: string,
    identifier: string,
    password: string,
  ) => Promise<'pending' | null>;
  /** Complete an email signup with the emailed code. */
  onVerify: (email: string, otp: string) => Promise<void>;
  /** Re-send the signup code; true when a fresh code was emailed. */
  onResendOtp: (email: string) => Promise<boolean>;
  /** Request a password-reset code; resolves true when the request was sent. */
  onForgot: (identifier: string) => Promise<boolean>;
  /** Set a new password with the emailed code; true on success. */
  onReset: (
    email: string,
    otp: string,
    newPassword: string,
  ) => Promise<boolean>;
  onGoogle: () => void;
  onClose: () => void;
  onGuest: () => void;
}

const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;
// Malawi mobile: optional +265 / 265 / leading-0, then 9 digits starting 8|9.
// Mirrors backend normalize_phone() (spaces/dashes ignored client-side).
const PHONE_RE = /^(\+?265)?0?[89]\d{8}$/;
const OTP_RE = /^\d{6}$/;

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
  inputMode,
  error,
}: {
  label: string;
  type?: string;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  autoComplete?: string;
  inputMode?: 'text' | 'email' | 'tel' | 'numeric';
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
        inputMode={inputMode}
        spellCheck={false}
        onChange={(e) => onChange(e.target.value)}
      />
      {error && <span role="alert" className="mt-1 block text-[12px] font-medium text-neg">{error}</span>}
    </label>
  );
}

/** Email-or-phone identifier input with an Email/Phone kind toggle. */
function IdentifierField({
  kind,
  onKindChange,
  value,
  onChange,
  error,
}: {
  kind: IdKind;
  onKindChange: (k: IdKind) => void;
  value: string;
  onChange: (v: string) => void;
  error?: string | null;
}) {
  const chip = (k: IdKind, label: string) => (
    <button
      type="button"
      className={`rounded-full px-[11px] py-[3px] font-mono text-[10px] font-semibold uppercase tracking-[.06em] transition-colors ${
        kind === k ? 'bg-ink text-white' : 'text-ink-3 hover:text-ink'
      }`}
      onClick={() => onKindChange(k)}
    >
      {label}
    </button>
  );
  return (
    <div>
      <div className="mb-1.5 flex items-center justify-between">
        <span className="font-mono text-[11px] font-semibold uppercase tracking-[.07em] text-ink-3">
          Email or phone
        </span>
        <div className="flex gap-[3px] rounded-full border border-line bg-paper-alt p-[3px]">
          {chip('email', 'Email')}
          {chip('phone', 'Phone')}
        </div>
      </div>
      <input
        type={kind === 'email' ? 'email' : 'tel'}
        className="field w-full"
        value={value}
        placeholder={kind === 'email' ? 'you@example.com' : '0991 234 567'}
        autoComplete={kind === 'email' ? 'email' : 'tel'}
        inputMode={kind === 'email' ? 'email' : 'tel'}
        spellCheck={false}
        onChange={(e) => onChange(e.target.value)}
      />
      {error && (
        <span role="alert" className="mt-1 block text-[12px] font-medium text-neg">{error}</span>
      )}
    </div>
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
  pendingEmail,
  onLogin,
  onRequestLoginCode,
  onLoginWithCode,
  onRegister,
  onVerify,
  onResendOtp,
  onForgot,
  onReset,
  onGoogle,
  onClose,
  onGuest,
}: AuthModalProps) {
  const [mode, setMode] = useState<Mode>(initialMode);
  const [step, setStep] = useState<Step>('auth');
  const [name, setName] = useState('');
  const [identifier, setIdentifier] = useState('');
  const [idKind, setIdKind] = useState<IdKind>('email');
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [showPw, setShowPw] = useState(false);
  const [localErrors, setLocalErrors] = useState<Record<string, string>>({});
  // Verify step (email signup)
  const [otp, setOtp] = useState('');
  const [resent, setResent] = useState(false);
  // Forgot-password step
  const [forgotId, setForgotId] = useState('');
  const [forgotKind, setForgotKind] = useState<IdKind>('email');
  const [forgotEmail, setForgotEmail] = useState('');
  const [forgotSent, setForgotSent] = useState(false);
  const [newPw, setNewPw] = useState('');
  const [newPw2, setNewPw2] = useState('');
  const [resetDone, setResetDone] = useState(false);
  // Passwordless sign-in step
  const [codeEmail, setCodeEmail] = useState('');
  const [codeSent, setCodeSent] = useState(false);
  const [codeResent, setCodeResent] = useState(false);

  // A pending email signup flips the modal to the verify step.
  useEffect(() => {
    if (pendingEmail) {
      setStep('verify');
      setOtp('');
      setResent(false);
    }
  }, [pendingEmail]);

  // --- Dialog accessibility ---------------------------------------------
  // The modal is exclusive: focus moves into it, Tab cycles within it, and
  // Escape closes it (unless a request is in flight). Without the trap, Tab
  // walks the page behind the overlay and screen readers never leave the
  // page context. `busy`/`onClose` are read through refs so this effect runs
  // once on open — re-running it on every `busy` flip would yank focus back
  // to the first field mid-submit.
  const dialogRef = useRef<HTMLDivElement>(null);
  const busyRef = useRef(busy);
  busyRef.current = busy;
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;

  useEffect(() => {
    const node = dialogRef.current;
    if (!node) return;
    const previouslyFocused = document.activeElement as HTMLElement | null;
    const focusables = () =>
      Array.from(
        node.querySelectorAll<HTMLElement>(
          'button:not([disabled]), a[href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
        ),
      ).filter((el) => el.getAttribute('aria-hidden') !== 'true');

    focusables()[0]?.focus();

    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        if (!busyRef.current) onCloseRef.current();
        return;
      }
      if (e.key !== 'Tab') return;
      const items = focusables();
      if (items.length === 0) return;
      const first = items[0];
      const last = items[items.length - 1];
      const active = document.activeElement;
      if (e.shiftKey && active === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && active === last) {
        e.preventDefault();
        first.focus();
      }
    };
    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('keydown', onKeyDown);
      previouslyFocused?.focus?.();
    };
  }, []);

  const verifyEmailTarget = pendingEmail || identifier.trim();

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
    setResetDone(false);
    if (mode === 'login') onLogin(identifier.trim(), password);
    else {
      const outcome = await onRegister(name.trim(), identifier.trim(), password);
      if (outcome === 'pending') {
        setStep('verify');
        setOtp('');
        setResent(false);
        setLocalErrors({});
      }
    }
  }

  async function submitVerify(e: React.FormEvent) {
    e.preventDefault();
    if (busy) return;
    const code = otp.trim();
    if (!OTP_RE.test(code)) {
      setLocalErrors({ otp: 'Enter the 6-digit code from the email' });
      return;
    }
    setLocalErrors({});
    await onVerify(verifyEmailTarget, code);
  }

  async function resend() {
    if (busy) return;
    const ok = await onResendOtp(verifyEmailTarget);
    if (ok) {
      setResent(true);
      setOtp('');
      setLocalErrors({});
    }
  }

  function backToForm() {
    setStep('auth');
    setOtp('');
    setResent(false);
    setLocalErrors({});
  }

  /** Switch from the password form to "email me a sign-in code". */
  function startLoginCode() {
    setMode('login');
    setCodeEmail(identifier.trim());
    setCodeSent(false);
    setCodeResent(false);
    setOtp('');
    setStep('logincode');
    setLocalErrors({});
  }

  /**
   * Request the sign-in code. Note we advance to the code step whenever the
   * request is accepted, whether or not the address actually has an account —
   * the backend replies identically in both cases on purpose, so the UI must
   * not reveal the difference.
   */
  async function submitLoginCode(e: React.FormEvent) {
    e.preventDefault();
    if (busy) return;
    const address = codeEmail.trim();
    if (!EMAIL_RE.test(address)) {
      setLocalErrors({ codeEmail: 'Enter a valid email address' });
      return;
    }
    setLocalErrors({});
    const ok = await onRequestLoginCode(address);
    if (ok) {
      setCodeSent(true);
      setCodeResent(false);
      setOtp('');
    }
  }

  async function submitVerifyLoginCode(e: React.FormEvent) {
    e.preventDefault();
    if (busy) return;
    const code = otp.trim();
    if (!OTP_RE.test(code)) {
      setLocalErrors({ otp: 'Enter the 6-digit code from the email' });
      return;
    }
    setLocalErrors({});
    await onLoginWithCode(codeEmail.trim(), code);
  }

  /** Re-send the sign-in code (backend enforces a 60s cooldown). */
  async function resendLoginCode() {
    if (busy) return;
    const ok = await onRequestLoginCode(codeEmail.trim());
    if (ok) {
      setCodeSent(true);
      setCodeResent(true);
      setOtp('');
      setLocalErrors({});
    }
  }

  async function submitForgot(e: React.FormEvent) {
    e.preventDefault();
    if (busy) return;
    const raw = forgotId.trim();
    const valid =
      forgotKind === 'email'
        ? EMAIL_RE.test(raw)
        : PHONE_RE.test(normalizePhoneInput(raw));
    if (!valid) {
      setLocalErrors({
        forgotId: 'Enter a valid email address or Malawian phone number',
      });
      return;
    }
    setLocalErrors({});
    const sent = await onForgot(raw);
    if (!sent) return;
    if (forgotKind === 'email') {
      setForgotEmail(raw);
      setForgotSent(true);
      setOtp('');
      setNewPw('');
      setNewPw2('');
    } else {
      // The endpoint answers 200 for anything (no user oracle) — phone-only
      // accounts can't self-reset until an SMS provider is wired in.
      setLocalErrors({
        forgotId:
          'Phone-only accounts can\u2019t reset online yet — an admin can reset your password.',
      });
    }
  }

  async function submitReset(e: React.FormEvent) {
    e.preventDefault();
    if (busy) return;
    const errs: Record<string, string> = {};
    if (!OTP_RE.test(otp.trim())) errs.otp = 'Enter the 6-digit code from the email';
    if (newPw.length < 8) errs.newPw = 'Must be at least 8 characters';
    if (newPw !== newPw2) errs.newPw2 = 'Passwords do not match';
    if (Object.keys(errs).length) {
      setLocalErrors(errs);
      return;
    }
    setLocalErrors({});
    const done = await onReset(forgotEmail, otp.trim(), newPw);
    if (!done) return;
    setStep('auth');
    setMode('login');
    setResetDone(true);
    setForgotSent(false);
    setForgotEmail('');
    setForgotId('');
    setOtp('');
    setNewPw('');
    setNewPw2('');
  }

  const tab =
    'flex-1 rounded-[9px] py-[10px] text-sm font-semibold transition-all duration-200 ease-ketsa';
  const activeTab = 'bg-ink text-white shadow-[0_6px_16px_-8px_rgba(12,21,38,.55)]';
  const idleTab = 'text-ink-2 hover:bg-paper hover:text-ink';
  const submitBtn =
    'w-full rounded-[9px] bg-ink px-5 py-[12px] text-sm font-semibold text-white transition-all duration-200 ease-ketsa hover:-translate-y-[1px] hover:bg-brand-ink disabled:cursor-not-allowed disabled:opacity-60';
  const linkBtn =
    'text-[12.5px] font-medium text-ink-3 transition-colors hover:text-ink disabled:cursor-not-allowed disabled:opacity-60';

  const kicker =
    step === 'verify'
      ? 'Check your email'
      : step === 'forgot'
        ? 'Password reset'
        : mode === 'login'
          ? 'Welcome back'
          : 'Create your account';
  const heading =
    step === 'verify'
      ? 'Enter your code'
      : step === 'forgot'
        ? 'Recover your account'
        : mode === 'login'
          ? 'Log in to Ketsa'
          : 'Start trading in minutes';

  return (
    <div
      className="fixed inset-0 z-[200] flex items-center justify-center bg-ink/40 p-4 backdrop-blur-[3px]"
      onClick={(e) => {
        if (e.target === e.currentTarget && !busy) onClose();
      }}
    >
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="auth-modal-heading"
        aria-describedby="auth-modal-kicker"
        className="grid w-full max-w-[880px] overflow-hidden rounded-l border border-line bg-white shadow-[0_24px_60px_-20px_rgba(12,21,38,.35)] md:grid-cols-[0.9fr_1fr]"
      >
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
                'Create an account and fund your wallet with real MWK via wandePay',
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
              <div
                id="auth-modal-kicker"
                className="mb-1 font-mono text-[10.5px] uppercase tracking-[.07em] text-brand"
              >
                {kicker}
              </div>
              <h3
                id="auth-modal-heading"
                className="font-serif text-[24px] font-medium text-ink"
              >
                {heading}
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

          {step === 'auth' && (
            <>
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
                <IdentifierField
                  kind={idKind}
                  onKindChange={setIdKind}
                  value={identifier}
                  onChange={setIdentifier}
                  error={localErrors.identifier}
                />
                {mode === 'register' && idKind === 'email' && !localErrors.identifier && (
                  <p className="-mt-2 text-[11.5px] text-ink-3">
                    Email signups are verified with a code we email to your inbox.
                  </p>
                )}
                <div>
                  <div className="mb-1.5 flex items-center justify-between">
                    <span className="font-mono text-[11px] font-semibold uppercase tracking-[.07em] text-ink-3">
                      Password
                    </span>
                    {mode === 'register' ? (
                      <span className="text-[11px] text-ink-3">8+ characters</span>
                    ) : (
                      <button
                        type="button"
                        className="text-[11px] font-semibold text-brand transition-colors hover:text-ink"
                        onClick={() => {
                          setForgotId(identifier);
                          setForgotKind(idKind);
                          setStep('forgot');
                          setLocalErrors({});
                        }}
                      >
                        Forgot password?
                      </button>
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
                    <span role="alert" className="mt-1 block text-[12px] font-medium text-neg">{localErrors.password}</span>
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

                {resetDone && (
                  <div className="rounded-[8px] border border-pos/25 bg-pos-tint px-[13px] py-[10px] text-[13px] font-medium text-pos">
                    Password reset — log in with your new password.
                  </div>
                )}
                {error && (
                  <div role="alert" className="rounded-[8px] border border-neg/25 bg-neg-tint px-[13px] py-[10px] text-[13px] font-medium text-neg">
                    {error}
                  </div>
                )}

                <button type="submit" className={submitBtn} disabled={busy}>
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
                  className={linkBtn}
                  onClick={busy ? undefined : onGuest}
                >
                  Skip — continue with a play wallet instead
                </button>
                {mode === 'login' && idKind === 'email' && (
                  <button
                    type="button"
                    className={`${linkBtn} mt-2`}
                    onClick={busy ? undefined : startLoginCode}
                  >
                    Sign in with a code instead of a password
                  </button>
                )}
              </div>
            </>
          )}

          {step === 'verify' && (
            <form onSubmit={submitVerify} className="mt-6 space-y-4" noValidate>
              <p className="text-[13.5px] leading-relaxed text-ink-2">
                We emailed a 6-digit code to{' '}
                <span className="font-semibold text-ink">{verifyEmailTarget}</span>.
                Enter it to activate your account — your Ketsa wallet is created
                the moment the code checks out.
              </p>
              <Field
                label="Verification code"
                value={otp}
                onChange={(v) => setOtp(v.replace(/\D/g, '').slice(0, 6))}
                placeholder="••••••"
                inputMode="numeric"
                error={localErrors.otp}
              />
              {error && (
                <div role="alert" className="rounded-[8px] border border-neg/25 bg-neg-tint px-[13px] py-[10px] text-[13px] font-medium text-neg">
                  {error}
                </div>
              )}
              <button type="submit" className={submitBtn} disabled={busy}>
                {busy ? 'Verifying…' : 'Verify & continue'}
              </button>
              <div className="flex items-center justify-between pt-1">
                <button
                  type="button"
                  className={linkBtn}
                  onClick={busy ? undefined : backToForm}
                >
                  ← Back
                </button>
                <button
                  type="button"
                  className={linkBtn}
                  onClick={busy ? undefined : resend}
                  disabled={busy}
                >
                  {resent ? 'Code resent — check your inbox' : 'Resend code'}
                </button>
              </div>
            </form>
          )}

          {step === 'logincode' && (
            <div className="mt-6">
              {!codeSent ? (
                <form onSubmit={submitLoginCode} className="space-y-4" noValidate>
                  <p className="text-[13.5px] leading-relaxed text-ink-2">
                    Enter your email and we&apos;ll send a 6-digit code to sign
                    in — no password needed.
                  </p>
                  <Field
                    label="Email"
                    type="email"
                    value={codeEmail}
                    onChange={setCodeEmail}
                    placeholder="you@example.com"
                    autoComplete="email"
                    inputMode="email"
                    error={localErrors.codeEmail}
                  />
                  {error && (
                    <div role="alert" className="rounded-[8px] border border-neg/25 bg-neg-tint px-[13px] py-[10px] text-[13px] font-medium text-neg">
                      {error}
                    </div>
                  )}
                  <button type="submit" className={submitBtn} disabled={busy}>
                    {busy ? 'Sending…' : 'Email me a sign-in code'}
                  </button>
                  <div className="flex items-center justify-between pt-1">
                    <button
                      type="button"
                      className={linkBtn}
                      onClick={busy ? undefined : backToForm}
                    >
                      ← Back
                    </button>
                  </div>
                </form>
              ) : (
                <form
                  onSubmit={submitVerifyLoginCode}
                  className="space-y-4"
                  noValidate
                >
                  <p className="text-[13.5px] leading-relaxed text-ink-2">
                    We emailed a 6-digit sign-in code to{' '}
                    <span className="font-semibold text-ink">{codeEmail.trim()}</span>.
                    Enter it below to sign in.
                  </p>
                  <Field
                    label="Sign-in code"
                    value={otp}
                    onChange={(v) => setOtp(v.replace(/\D/g, '').slice(0, 6))}
                    placeholder="••••••"
                    inputMode="numeric"
                    error={localErrors.otp}
                  />
                  {error && (
                    <div role="alert" className="rounded-[8px] border border-neg/25 bg-neg-tint px-[13px] py-[10px] text-[13px] font-medium text-neg">
                      {error}
                    </div>
                  )}
                  <button type="submit" className={submitBtn} disabled={busy}>
                    {busy ? 'Signing in…' : 'Sign in'}
                  </button>
                  <div className="flex items-center justify-between pt-1">
                    <button
                      type="button"
                      className={linkBtn}
                      onClick={busy ? undefined : backToForm}
                    >
                      ← Back
                    </button>
                    <button
                      type="button"
                      className={linkBtn}
                      onClick={busy ? undefined : resendLoginCode}
                      disabled={busy}
                    >
                      {codeResent
                        ? 'Code resent — check your inbox'
                        : 'Resend code'}
                    </button>
                  </div>
                </form>
              )}
            </div>
          )}

          {step === 'forgot' && (
            <div className="mt-6">
              {!forgotSent ? (
                <form onSubmit={submitForgot} className="space-y-4" noValidate>
                  <p className="text-[13.5px] leading-relaxed text-ink-2">
                    Enter the email on your Ketsa account and we&apos;ll email a
                    6-digit reset code. Phone-only accounts can&apos;t self-reset
                    yet — an admin can reset your password from the dashboard.
                  </p>
                  <IdentifierField
                    kind={forgotKind}
                    onKindChange={setForgotKind}
                    value={forgotId}
                    onChange={setForgotId}
                    error={localErrors.forgotId}
                  />
                  {error && (
                    <div role="alert" className="rounded-[8px] border border-neg/25 bg-neg-tint px-[13px] py-[10px] text-[13px] font-medium text-neg">
                      {error}
                    </div>
                  )}
                  <button type="submit" className={submitBtn} disabled={busy}>
                    {busy ? 'Sending…' : 'Email reset code'}
                  </button>
                  <button
                    type="button"
                    className={`${linkBtn} w-full text-center`}
                    onClick={busy ? undefined : backToForm}
                  >
                    ← Back to log in
                  </button>
                </form>
              ) : (
                <form onSubmit={submitReset} className="space-y-4" noValidate>
                  <p className="text-[13.5px] leading-relaxed text-ink-2">
                    Enter the 6-digit code we emailed to{' '}
                    <span className="font-semibold text-ink">{forgotEmail}</span>,
                    then choose a new password.
                  </p>
                  <Field
                    label="Reset code"
                    value={otp}
                    onChange={(v) => setOtp(v.replace(/\D/g, '').slice(0, 6))}
                    placeholder="••••••"
                    inputMode="numeric"
                    error={localErrors.otp}
                  />
                  <Field
                    label="New password"
                    type="password"
                    value={newPw}
                    onChange={setNewPw}
                    placeholder="••••••••"
                    autoComplete="new-password"
                    error={localErrors.newPw}
                  />
                  <Field
                    label="Confirm new password"
                    type="password"
                    value={newPw2}
                    onChange={setNewPw2}
                    placeholder="••••••••"
                    autoComplete="new-password"
                    error={localErrors.newPw2}
                  />
                  {error && (
                    <div role="alert" className="rounded-[8px] border border-neg/25 bg-neg-tint px-[13px] py-[10px] text-[13px] font-medium text-neg">
                      {error}
                    </div>
                  )}
                  <button type="submit" className={submitBtn} disabled={busy}>
                    {busy ? 'Resetting…' : 'Set new password'}
                  </button>
                  <button
                    type="button"
                    className={`${linkBtn} w-full text-center`}
                    onClick={busy ? undefined : () => {
                      setForgotSent(false);
                      setLocalErrors({});
                    }}
                  >
                    ← Back
                  </button>
                </form>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}