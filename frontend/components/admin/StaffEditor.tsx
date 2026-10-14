'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import {
  AdminApiError,
  createStaff,
  deleteStaff,
  inviteStaff,
  listStaff,
  updateStaff,
  uploadStaff,
} from '@/lib/api';
import { useStaffStream } from '@/lib/useStaffStream';
import { STAFF_ROLES, type StaffMember, type StaffUploadResult } from '@/lib/types';
import { Card, DangerButton, Field, SelectInput, TextInput } from './ui';

function fmtDate(ts?: number | null): string {
  if (!ts) return '—';
  return new Date(ts * 1000).toLocaleString(undefined, {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function apiError(err: unknown): string {
  if (err instanceof AdminApiError) return err.message;
  return err instanceof Error ? err.message : 'Request failed';
}

const ROLE_OPTIONS = STAFF_ROLES.map((r) => ({
  value: r,
  label: r.charAt(0).toUpperCase() + r.slice(1),
}));

export default function StaffEditor({ token }: { token: string }) {
  const [staff, setStaff] = useState<StaffMember[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  // Non-fatal notices that are neither success nor failure (e.g. an invite the
  // backend accepted but could not actually deliver in log mode).
  const [warn, setWarn] = useState<string | null>(null);

  // Add-one form.
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [phone, setPhone] = useState('');
  const [role, setRole] = useState('support');
  const [adding, setAdding] = useState(false);

  // Bulk upload.
  const [bulkText, setBulkText] = useState('');
  const [uploading, setUploading] = useState(false);
  const [uploadResult, setUploadResult] = useState<StaffUploadResult | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const load = useCallback(async () => {
    try {
      setStaff(await listStaff(token));
    } catch (err) {
      setError(apiError(err));
    }
  }, [token]);

  useEffect(() => {
    void load();
  }, [load]);

  // Realtime: any staff change (from this panel or another admin) re-fetches
  // the authoritative list, so the table is never stale.
  const onEvent = useCallback(() => {
    void load();
  }, [load]);
  const { connected } = useStaffStream(onEvent);

  async function addOne() {
    setError(null);
    setMsg(null);
    setWarn(null);
    setAdding(true);
    try {
      const member = await createStaff(token, {
        name: name.trim(),
        email: email.trim(),
        phone: phone.trim() || null,
        role,
      });
      setName('');
      setEmail('');
      setPhone('');
      setRole('support');
      setMsg(`Added ${member.name}.`);
      await load();
    } catch (err) {
      setError(apiError(err));
    } finally {
      setAdding(false);
    }
  }

  async function runUpload(text: string) {
    setError(null);
    setMsg(null);
    setWarn(null);
    setUploadResult(null);
    if (!text.trim()) {
      setError('Paste CSV/JSON or choose a file first.');
      return;
    }
    setUploading(true);
    try {
      const result = await uploadStaff(token, { text });
      setUploadResult(result);
      if (result.added || result.updated) {
        setMsg(`Upload applied: ${result.added} added, ${result.updated} updated.`);
      }
      await load();
    } catch (err) {
      setError(apiError(err));
    } finally {
      setUploading(false);
    }
  }

  async function onFile(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    // Cap the read so a mistakenly-selected huge file can't hang the tab; the
    // backend enforces a 1000-row limit anyway.
    if (file.size > 2_000_000) {
      setError('File is too large (max 2 MB).');
      e.target.value = '';
      return;
    }
    const text = await file.text();
    setBulkText(text);
    await runUpload(text);
    e.target.value = '';
  }

  async function toggleActive(member: StaffMember) {
    setError(null);
    setMsg(null);
    setWarn(null);
    try {
      await updateStaff(token, member.id, { active: !member.active });
      await load();
    } catch (err) {
      setError(apiError(err));
    }
  }

  async function remove(member: StaffMember) {
    setError(null);
    setMsg(null);
    setWarn(null);
    try {
      await deleteStaff(token, member.id);
      setMsg(`Removed ${member.name}.`);
      await load();
    } catch (err) {
      setError(apiError(err));
    }
  }

  async function invite(member: StaffMember) {
    setError(null);
    setMsg(null);
    setWarn(null);
    try {
      const res = await inviteStaff(token, member.id);
      // Honest feedback: only a really-delivered invite is a success. In log
      // mode (or with Resend unconfigured) the backend reports delivered=false,
      // so say so plainly instead of implying an email left the building.
      if (res.delivered) setMsg(res.detail);
      else setWarn(res.detail);
      await load();
    } catch (err) {
      setError(apiError(err));
    }
  }

  return (
    <div className="admin-stack">
      {error && <div className="admin-error">{error}</div>}
      {warn && <div className="admin-warn">{warn}</div>}
      {msg && <div className="admin-saved-msg">{msg}</div>}

      <Card title="Add a staff member">
        <p className="admin-muted">
          Staff are platform operators (support, finance, …), separate from trader
          accounts. Every change appears instantly on this page and on the public
          team directory.{' '}
          <span className={connected ? 'admin-live' : 'admin-live admin-live--off'}>
            {connected ? 'Live' : 'Reconnecting…'}
          </span>
        </p>
        <div className="admin-grid admin-grid--2" style={{ marginTop: 14 }}>
          <Field label="Full name">
            <TextInput value={name} onChange={setName} placeholder="Maya Banda" />
          </Field>
          <Field label="Email">
            <TextInput value={email} onChange={setEmail} placeholder="maya@ketsa.io" />
          </Field>
          <Field label="Phone" hint="Optional">
            <TextInput value={phone} onChange={setPhone} placeholder="0991 234 567" />
          </Field>
          <Field label="Role">
            <SelectInput value={role} onChange={setRole} options={ROLE_OPTIONS} />
          </Field>
        </div>
        <div className="admin-save-row">
          <button
            type="button"
            className="admin-btn admin-btn--primary"
            disabled={adding || !name.trim() || !email.trim()}
            onClick={() => void addOne()}
          >
            {adding ? 'Adding…' : 'Add staff'}
          </button>
        </div>
      </Card>

      <Card title="Bulk upload">
        <p className="admin-muted">
          Upload a CSV or JSON file, or paste the text. Columns:{' '}
          <code>name, email, phone, role</code>. Existing staff (matched by email
          or phone) are updated; invalid rows are skipped and listed below.
        </p>
        <div style={{ marginTop: 12, display: 'flex', gap: 10, flexWrap: 'wrap' }}>
          <input
            ref={fileRef}
            type="file"
            accept=".csv,.json,.txt,text/csv,application/json"
            style={{ display: 'none' }}
            onChange={(e) => void onFile(e)}
          />
          <button
            type="button"
            className="admin-btn admin-btn--ghost"
            onClick={() => fileRef.current?.click()}
            disabled={uploading}
          >
            {uploading ? 'Uploading…' : 'Choose file'}
          </button>
        </div>
        <div style={{ marginTop: 12 }}>
          <textarea
            className="admin-input admin-textarea"
            rows={6}
            value={bulkText}
            onChange={(e) => setBulkText(e.target.value)}
            placeholder={
              'name,email,phone,role\nMaya Banda,maya@ketsa.io,0991234567,support'
            }
          />
        </div>
        <div className="admin-save-row">
          <button
            type="button"
            className="admin-btn admin-btn--primary"
            disabled={uploading}
            onClick={() => void runUpload(bulkText)}
          >
            {uploading ? 'Uploading…' : 'Upload pasted text'}
          </button>
        </div>
        {uploadResult && (
          <div className="admin-upload-result" style={{ marginTop: 12 }}>
            <strong>
              {uploadResult.added} added · {uploadResult.updated} updated ·{' '}
              {uploadResult.skipped} skipped
            </strong>
            {uploadResult.errors.length > 0 && (
              <ul className="admin-upload-errors">
                {uploadResult.errors.map((e, i) => (
                  <li key={i}>{e}</li>
                ))}
              </ul>
            )}
          </div>
        )}
      </Card>

      <Card title="Team directory">
        <div className="admin-table-wrap">
          <table className="admin-table">
            <thead>
              <tr>
                <th>Member</th>
                <th>Role</th>
                <th>Status</th>
                <th>Added</th>
                <th className="admin-actions">Actions</th>
              </tr>
            </thead>
            <tbody>
              {staff === null && (
                <tr>
                  <td colSpan={5} className="admin-muted">
                    Loading staff…
                  </td>
                </tr>
              )}
              {staff !== null && staff.length === 0 && (
                <tr>
                  <td colSpan={5} className="admin-muted">
                    No staff yet.
                  </td>
                </tr>
              )}
              {staff?.map((m) => (
                <tr key={m.id}>
                  <td>
                    <div className="admin-td-name">{m.name}</div>
                    <div className="admin-td-sub">
                      {m.email}
                      {m.phone ? ` · ${m.phone}` : ''}
                    </div>
                  </td>
                  <td className="admin-mono">
                    {m.role.charAt(0).toUpperCase() + m.role.slice(1)}
                  </td>
                  <td>
                    <span
                      className={`admin-pill ${m.active ? 'admin-pill--on' : 'admin-pill--off'}`}
                    >
                      {m.active ? 'Active' : 'Disabled'}
                    </span>
                  </td>
                  <td className="admin-mono">{fmtDate(m.created)}</td>
                  <td className="admin-actions">
                    <button
                      type="button"
                      className="admin-btn admin-btn--ghost"
                      onClick={() => void invite(m)}
                    >
                      Resend invite
                    </button>
                    <button
                      type="button"
                      className="admin-btn admin-btn--ghost"
                      onClick={() => void toggleActive(m)}
                    >
                      {m.active ? 'Disable' : 'Enable'}
                    </button>
                    <DangerButton onConfirm={() => remove(m)} label="Remove" />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}
