'use client';

import { useState } from 'react';

// Shared admin UI primitives. Colours/styles are defined in admin.css.

export function Field({
  label,
  children,
  hint,
}: {
  label: string;
  children: React.ReactNode;
  hint?: string;
}) {
  return (
    <label className="admin-field">
      <span className="admin-field-label">{label}</span>
      {children}
      {hint && <span className="admin-field-hint">{hint}</span>}
    </label>
  );
}

export function TextInput({
  value,
  onChange,
  placeholder,
  type = 'text',
}: {
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  type?: string;
}) {
  return (
    <input
      type={type}
      className="admin-input"
      value={value}
      onChange={(e) => onChange(e.target.value)}
      placeholder={placeholder}
    />
  );
}

export function TextArea({
  value,
  onChange,
  rows = 3,
}: {
  value: string;
  onChange: (v: string) => void;
  rows?: number;
}) {
  return (
    <textarea
      className="admin-input admin-textarea"
      rows={rows}
      value={value}
      onChange={(e) => onChange(e.target.value)}
    />
  );
}

export function NumberInput({
  value,
  onChange,
  min,
  max,
}: {
  value: number;
  onChange: (v: number) => void;
  min?: number;
  max?: number;
}) {
  return (
    <input
      type="number"
      className="admin-input"
      value={Number.isFinite(value) ? value : ''}
      min={min}
      max={max}
      onChange={(e) => onChange(Number(e.target.value))}
    />
  );
}

export function SelectInput({
  value,
  onChange,
  options,
}: {
  value: string;
  onChange: (v: string) => void;
  options: { value: string; label: string }[];
}) {
  return (
    <select
      className="admin-input admin-select"
      value={value}
      onChange={(e) => onChange(e.target.value)}
    >
      {options.map((o) => (
        <option key={o.value} value={o.value}>
          {o.label}
        </option>
      ))}
    </select>
  );
}

export function SaveButton({
  onSave,
  label = 'Save changes',
  dirty = true,
}: {
  onSave: () => Promise<void> | void;
  label?: string;
  dirty?: boolean;
}) {
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  async function handle() {
    setSaving(true);
    setSaved(false);
    try {
      await onSave();
      setSaved(true);
      window.setTimeout(() => setSaved(false), 2000);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="admin-save-row">
      <button
        type="button"
        className="admin-btn admin-btn--primary"
        onClick={handle}
        disabled={saving || !dirty}
      >
        {saving ? 'Saving…' : label}
      </button>
      {saved && <span className="admin-saved-msg">Saved ✓</span>}
    </div>
  );
}

export function DangerButton({
  onConfirm,
  label = 'Delete',
}: {
  onConfirm: () => Promise<void> | void;
  label?: string;
}) {
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);

  async function handleClick() {
    if (!confirming) {
      setConfirming(true);
      window.setTimeout(() => setConfirming(false), 2500);
      return;
    }
    setBusy(true);
    try {
      await onConfirm();
    } finally {
      setBusy(false);
      setConfirming(false);
    }
  }

  return (
    <button
      type="button"
      className={`admin-btn admin-btn--danger ${confirming ? 'is-confirming' : ''}`}
      onClick={handleClick}
      disabled={busy}
    >
      {busy ? '…' : confirming ? 'Confirm?' : label}
    </button>
  );
}

export function Card({
  title,
  children,
}: {
  title?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="admin-card">
      {title && <h2 className="admin-card-title">{title}</h2>}
      {children}
    </div>
  );
}
