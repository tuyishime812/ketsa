'use client';

import { useEffect, useState } from 'react';
import { adminPost, getAdminConfig, saveAdminConfig } from '@/lib/api';
import type {
  PaymentsConfig,
  ResolutionConfig,
  SecurityConfig,
} from '@/lib/types';
import {
  Card,
  CheckBox,
  Field,
  NumberInput,
  SaveButton,
  TextArea,
  TextInput,
} from './ui';

function errMsg(err: unknown): string {
  return err instanceof Error ? err.message : 'Request failed';
}

/** Parse the staff-roles textarea: one role per line, or comma-separated. */
function parseRoles(text: string): string[] {
  const out: string[] = [];
  for (const raw of text.split(/[\n,]+/)) {
    const slug = raw.trim().toLowerCase();
    if (slug && !out.includes(slug)) out.push(slug);
  }
  return out;
}

export default function SettingsEditor() {
  const [error, setError] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);

  // Drafts, one per section. null until the first load resolves.
  const [payments, setPayments] = useState<PaymentsConfig | null>(null);
  const [security, setSecurity] = useState<SecurityConfig | null>(null);
  const [rolesText, setRolesText] = useState('');
  const [resolution, setResolution] = useState<ResolutionConfig | null>(null);

  // Password-change sub-form.
  const [current, setCurrent] = useState('');
  const [next, setNext] = useState('');
  const [confirm, setConfirm] = useState('');

  useEffect(() => {
    (async () => {
      try {
        const cfg = await getAdminConfig();
        setPayments(cfg.payments);
        setSecurity(cfg.security);
        setRolesText(cfg.staff_roles.roles.join('\n'));
        setResolution(cfg.resolution);
      } catch (err) {
        setError(errMsg(err));
      }
    })();
  }, []);

  function begin() {
    setError(null);
    setMsg(null);
  }

  async function savePayments() {
    if (!payments) return;
    begin();
    try {
      await saveAdminConfig('payments', payments);
      setMsg('Payment settings saved.');
    } catch (err) {
      setError(errMsg(err));
    }
  }

  async function saveSecurity() {
    if (!security) return;
    begin();
    try {
      await saveAdminConfig('security', security);
      setMsg('Security settings saved.');
    } catch (err) {
      setError(errMsg(err));
    }
  }

  async function saveRoles() {
    begin();
    try {
      await saveAdminConfig('staff_roles', { roles: parseRoles(rolesText) });
      setMsg('Staff roles saved.');
    } catch (err) {
      setError(errMsg(err));
    }
  }

  async function saveResolution() {
    if (!resolution) return;
    begin();
    try {
      await saveAdminConfig('resolution', resolution);
      setMsg('Market resolution settings saved.');
    } catch (err) {
      setError(errMsg(err));
    }
  }

  async function changePassword() {
    begin();
    if (next.length < 8) {
      setError('New password must be at least 8 characters');
      return;
    }
    if (next !== confirm) {
      setError('New passwords do not match');
      return;
    }
    try {
      await adminPost('/password', { current, new: next });
      setCurrent('');
      setNext('');
      setConfirm('');
      setMsg('Password updated.');
    } catch (err) {
      setError(errMsg(err));
    }
  }

  return (
    <div className="admin-stack">
      {error && <div className="admin-error">{error}</div>}
      {msg && <div className="admin-saved-msg">{msg}</div>}

      <Card title="Payments">
        <p className="admin-muted">
          Money-movement limits and switches. Changing these takes effect
          immediately, without a restart. Guests can only ever hold play money —
          real deposits always require an account.
        </p>
        {payments && (
          <>
            <div className="admin-check-group" style={{ marginTop: 14 }}>
              <CheckBox
                label="Deposits enabled"
                value={payments.deposits_enabled}
                onChange={(v) => setPayments({ ...payments, deposits_enabled: v })}
                hint="Turn off to pause all incoming deposits."
              />
              <CheckBox
                label="Withdrawals enabled"
                value={payments.withdrawals_enabled}
                onChange={(v) => setPayments({ ...payments, withdrawals_enabled: v })}
                hint="Turn off to pause all payouts."
              />
            </div>
            <div className="admin-grid admin-grid--2" style={{ marginTop: 14 }}>
              <Field label="Max deposit (MWK)" hint="Per transaction">
                <NumberInput
                  value={payments.max_deposit_mwk}
                  onChange={(v) => setPayments({ ...payments, max_deposit_mwk: v })}
                  min={100}
                />
              </Field>
              <Field label="Max withdrawal (MWK)" hint="Per transaction">
                <NumberInput
                  value={payments.max_withdrawal_mwk}
                  onChange={(v) => setPayments({ ...payments, max_withdrawal_mwk: v })}
                  min={100}
                />
              </Field>
              <Field
                label="Daily withdrawal limit (MWK)"
                hint="Per wallet, rolling 24h — must be ≥ the per-transaction cap"
              >
                <NumberInput
                  value={payments.daily_withdrawal_limit_mwk}
                  onChange={(v) =>
                    setPayments({ ...payments, daily_withdrawal_limit_mwk: v })
                  }
                  min={100}
                />
              </Field>
            </div>
            <SaveButton onSave={savePayments} label="Save payments" />
          </>
        )}
      </Card>

      <Card title="Security">
        <p className="admin-muted">
          Admin login brute-force lockout and the shared admin password.
        </p>
        {security && (
          <>
            <div className="admin-grid admin-grid--2" style={{ marginTop: 14 }}>
              <Field
                label="Max failed logins"
                hint="Failures from one IP before lockout"
              >
                <NumberInput
                  value={security.admin_max_failures}
                  onChange={(v) => setSecurity({ ...security, admin_max_failures: v })}
                  min={1}
                  max={1000}
                />
              </Field>
              <Field label="Lockout duration (seconds)" hint="How long the IP is fenced">
                <NumberInput
                  value={security.admin_lockout_seconds}
                  onChange={(v) =>
                    setSecurity({ ...security, admin_lockout_seconds: v })
                  }
                  min={30}
                  max={86400}
                />
              </Field>
            </div>
            <SaveButton onSave={saveSecurity} label="Save security" />
          </>
        )}

        <hr className="admin-hr" />

        <p className="admin-muted">
          Change the admin password. It is hashed and stored in the backend and
          takes effect immediately, replacing the environment value.
        </p>
        <div className="admin-grid admin-grid--2" style={{ marginTop: 14 }}>
          <Field label="Current password">
            <TextInput
              type="password"
              value={current}
              onChange={setCurrent}
              placeholder="••••••••"
            />
          </Field>
          <div className="admin-field" />
          <Field label="New password" hint="At least 8 characters">
            <TextInput
              type="password"
              value={next}
              onChange={setNext}
              placeholder="••••••••"
            />
          </Field>
          <Field label="Confirm new password">
            <TextInput
              type="password"
              value={confirm}
              onChange={setConfirm}
              placeholder="••••••••"
            />
          </Field>
        </div>
        <div className="admin-form-actions">
          <button
            type="button"
            className="admin-btn admin-btn--primary"
            onClick={() => void changePassword()}
          >
            Change password
          </button>
        </div>
      </Card>

      <Card title="Staff roles">
        <p className="admin-muted">
          The roles available in the Staff directory and shown on the public team
          page. One role per line (or comma-separated). Lowercase letters, digits,
          <code> - </code> or <code>_</code>. Existing staff keep their role even
          if it is removed here.
        </p>
        <div style={{ marginTop: 12 }}>
          <TextArea value={rolesText} onChange={setRolesText} rows={6} />
        </div>
        <SaveButton onSave={saveRoles} label="Save roles" />
      </Card>

      <Card title="Market resolution">
        <p className="admin-muted">
          Guards around settling markets (resolution pays out real balances).
        </p>
        {resolution && (
          <>
            <div className="admin-check-group" style={{ marginTop: 14 }}>
              <CheckBox
                label="Resolution enabled"
                value={resolution.resolution_enabled}
                onChange={(v) =>
                  setResolution({ ...resolution, resolution_enabled: v })
                }
                hint="Turn off to block all market resolution."
              />
              <CheckBox
                label="Require the market's end date to have passed"
                value={resolution.require_end_date}
                onChange={(v) =>
                  setResolution({ ...resolution, require_end_date: v })
                }
                hint="Prevents settling a question ahead of its published close time."
              />
            </div>
            <SaveButton onSave={saveResolution} label="Save resolution" />
          </>
        )}
      </Card>
    </div>
  );
}
