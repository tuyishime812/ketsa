'use client';

import { Fragment, useState } from 'react';
import { adminDelete, adminPost, adminPut } from '@/lib/api';
import type { Market } from '@/lib/types';
import {
  Card,
  DangerButton,
  Field,
  NumberInput,
  SaveButton,
  SelectInput,
  TextArea,
  TextInput,
} from './ui';

const CATEGORIES: { value: string; label: string }[] = [
  { value: 'politics', label: 'Politics' },
  { value: 'crypto', label: 'Crypto' },
  { value: 'sports', label: 'Sports' },
  { value: 'culture', label: 'Culture' },
  { value: 'tech', label: 'Tech' },
  { value: 'climate', label: 'Climate' },
];

const TRENDS = [
  { value: 'up', label: 'Up ▲' },
  { value: 'down', label: 'Down ▼' },
];

type Draft = Omit<Market, 'meta'> & {
  meta: [string, string];
  isNew?: boolean;
};

/** Convert an ISO string to the `datetime-local` input format (local time). */
function toLocalInput(iso?: string | null): string {
  if (!iso) return '';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '';
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(
    d.getHours(),
  )}:${pad(d.getMinutes())}`;
}

function emptyDraft(): Draft {
  const now = new Date();
  const future = new Date(now.getTime() + 30 * 24 * 3600 * 1000);
  return {
    id: '',
    cat: 'politics',
    tag: 'Politics',
    q: '',
    yes: 50,
    no: 50,
    meta: ['', ''],
    trend: 'up',
    pts: [10, 14, 12, 18, 16, 22, 20, 26],
    description: '',
    end_date: future.toISOString(),
    created: now.toISOString(),
    volume: 0,
    liquidity: 500,
    status: 'open',
    last_price: 50,
    isNew: true,
  };
}

export default function MarketsEditor({
  markets,
}: {
  markets: Market[];
}) {
  const [list, setList] = useState<Market[]>(markets);
  const [editing, setEditing] = useState<Draft | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [resolveId, setResolveId] = useState<string | null>(null);

  const dirty = editing !== null;

  function startCreate() {
    setEditing(emptyDraft());
    setError(null);
  }

  function startEdit(m: Market) {
    setEditing({ ...m, meta: [m.meta[0], m.meta[1]] });
    setError(null);
  }

  function patch(partial: Partial<Draft>) {
    if (!editing) return;
    setEditing({ ...editing, ...partial });
  }

  function computeNo(yes: number) {
    return 100 - yes;
  }

  async function saveCurrent() {
    if (!editing) return;
    setError(null);

    // Validate in the browser first so the admin gets a precise message
    // instead of a generic 422 from the API. The server re-checks everything.
    const id = editing.id.trim().toLowerCase();
    if (!/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(id)) {
      setError(
        'Market ID must be a lowercase slug: letters, numbers and single hyphens (e.g. btc-120k).',
      );
      throw new Error('validation');
    }
    if (!editing.q.trim()) {
      setError('Question is required.');
      throw new Error('validation');
    }
    if (!editing.tag.trim()) {
      setError('Tag is required.');
      throw new Error('validation');
    }

    const no = editing.isNew ? computeNo(editing.yes) : editing.no;
    if (!Number.isInteger(editing.yes) || !Number.isInteger(no)) {
      setError('YES and NO prices must be whole cents.');
      throw new Error('validation');
    }
    if (editing.yes + no !== 100) {
      setError('YES and NO prices must add up to 100.');
      throw new Error('validation');
    }
    if (editing.pts.length < 2) {
      setError('Add at least two sparkline points.');
      throw new Error('validation');
    }
    if (editing.pts.some((point) => !Number.isInteger(point))) {
      setError('Sparkline points must be whole numbers.');
      throw new Error('validation');
    }
    if (editing.pts.some((point) => point < 0 || point > 100)) {
      setError('Sparkline points must be between 0 and 100.');
      throw new Error('validation');
    }

    let endDate: string | null = null;
    if (editing.end_date) {
      const parsed = new Date(editing.end_date);
      if (Number.isNaN(parsed.getTime())) {
        setError('End date is invalid.');
        throw new Error('validation');
      }
      endDate = parsed.toISOString();
    }

    const volume = Number(editing.volume ?? 0);
    const liquidity = Number(editing.liquidity ?? 0);
    if (!Number.isFinite(volume) || volume < 0 || !Number.isFinite(liquidity) || liquidity < 0) {
      setError('Volume and liquidity must be zero or positive.');
      throw new Error('validation');
    }

    const payload: Market = {
      id,
      cat: editing.cat as Market['cat'],
      tag: editing.tag.trim(),
      q: editing.q.trim(),
      yes: editing.yes,
      no,
      meta: editing.meta,
      trend: editing.trend as Market['trend'],
      pts: editing.pts,
      description: editing.description ?? '',
      end_date: endDate,
      created: editing.created ?? new Date().toISOString(),
      volume,
      liquidity,
      status: (editing.status ?? 'open') as Market['status'],
    };

    try {
      // Use POST for a new market so the server can reject a duplicate id
      // instead of silently overwriting an existing market.
      const save = editing.isNew ? adminPost : adminPut;
      await save('/markets', payload);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Save failed');
      throw err instanceof Error ? err : new Error('Save failed');
    }

    setList((prev) => {
      const exists = prev.some((m) => m.id === payload.id);
      return exists
        ? prev.map((m) => (m.id === payload.id ? payload : m))
        : [payload, ...prev];
    });
    setEditing(null);
  }

  async function removeMarket(id: string) {
    try {
      await adminDelete(`/markets/${encodeURIComponent(id)}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Delete failed');
      return;
    }
    setList((prev) => prev.filter((m) => m.id !== id));
  }

  async function resolveMarket(m: Market, outcome: 'yes' | 'no') {
    setError(null);
    try {
      await adminPost(
        `/markets/${encodeURIComponent(m.id)}/resolve`,
        { outcome },
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Resolve failed');
      return;
    }
    setList((prev) =>
      prev.map((it) =>
        it.id === m.id
          ? {
              ...it,
              status: 'resolved' as const,
              resolved_outcome: outcome,
              resolved_price: outcome === 'yes' ? 100 : 0,
            }
          : it,
      ),
    );
    setResolveId(null);
  }

  return (
    <div className="admin-stack">
      <div className="admin-row-between">
        <p className="admin-muted">
          {list.length} markets — click <strong>Edit</strong> to change one, or
          <strong> Add market</strong> to create a new prediction market.
        </p>
        <button type="button" className="admin-btn admin-btn--primary" onClick={startCreate}>
          + Add market
        </button>
      </div>

      {error && <div className="admin-error">{error}</div>}

      <Card>
        {list.length === 0 ? (
          <p className="admin-muted" style={{ padding: '18px 4px', margin: 0 }}>
            No markets yet. Click <strong>+ Add market</strong> above to create
            your first real market.
          </p>
        ) : (
        <div className="admin-table-wrap">
          <table className="admin-table">
            <thead>
              <tr>
                <th>ID</th>
                <th>Question</th>
                <th>Category</th>
                <th>YES</th>
                <th>NO</th>
                <th>Trend</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {list.map((m) => (
                <Fragment key={m.id}>
                  <tr>
                    <td className="admin-mono">{m.id}</td>
                    <td className="admin-strong">{m.q}</td>
                    <td>{m.cat}</td>
                    <td className="admin-mono">{m.yes}¢</td>
                    <td className="admin-mono">{m.no}¢</td>
                    <td
                      className={
                        m.status === 'resolved'
                          ? 'admin-pos'
                          : m.trend === 'up'
                            ? 'admin-pos'
                            : 'admin-neg'
                      }
                    >
                      {m.status === 'resolved'
                        ? `RESOLVED · ${(m.resolved_outcome ?? '').toUpperCase()}`
                        : m.trend === 'up'
                          ? '▲'
                          : '▼'}
                    </td>
                    <td className="admin-actions">
                      <button
                        type="button"
                        className="admin-btn admin-btn--ghost"
                        onClick={() => startEdit(m)}
                      >
                        Edit
                      </button>
                      {m.status !== 'resolved' && (
                        <button
                          type="button"
                          className="admin-btn admin-btn--ghost"
                          onClick={() => setResolveId((id) => (id === m.id ? null : m.id))}
                        >
                          Resolve
                        </button>
                      )}
                      <DangerButton onConfirm={() => removeMarket(m.id)} label="Delete" />
                    </td>
                  </tr>
                  {resolveId === m.id && (
                    <tr className="admin-reset-row">
                      <td colSpan={7} className="admin-resolve-actions">
                        <span>Resolve “{m.q}” as:</span>
                        <button
                          type="button"
                          className="admin-btn admin-btn--primary"
                          onClick={() => void resolveMarket(m, 'yes')}
                        >
                          YES won · 100¢
                        </button>
                        <button
                          type="button"
                          className="admin-btn admin-btn--primary"
                          onClick={() => void resolveMarket(m, 'no')}
                        >
                          NO won · 100¢
                        </button>
                        <button
                          type="button"
                          className="admin-btn admin-btn--ghost"
                          onClick={() => setResolveId(null)}
                        >
                          Cancel
                        </button>
                      </td>
                    </tr>
                  )}
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
        )}
      </Card>

      {editing && (
        <Card title={editing.isNew ? 'New market' : `Edit: ${editing.id}`}>
          <div className="admin-grid admin-grid--2">
            <Field
              label="Market ID (URL slug)"
              hint={
                editing.isNew
                  ? 'Lowercase letters, numbers and single hyphens.'
                  : 'The ID is permanent; delete and recreate the market if it must change.'
              }
            >
              <TextInput
                value={editing.id}
                onChange={(v) =>
                  patch({
                    id: v
                      .toLowerCase()
                      .replace(/[^a-z0-9-]+/g, '-')
                      .replace(/-{2,}/g, '-')
                      .replace(/^-+|-+$/g, ''),
                  })
                }
                placeholder="btc-120k"
                disabled={!editing.isNew}
              />
            </Field>
            <Field label="Tag (shown on card)">
              <TextInput value={editing.tag} onChange={(v) => patch({ tag: v })} placeholder="Crypto" />
            </Field>
          </div>

          <Field label="Question">
            <TextArea
              value={editing.q}
              onChange={(v) => patch({ q: v })}
              rows={2}
            />
          </Field>

          <Field
            label="Description / resolution rules"
            hint="Shown on the market detail page. Include the exact resolution source and criteria."
          >
            <TextArea
              value={editing.description ?? ''}
              onChange={(v) => patch({ description: v })}
              rows={3}
            />
          </Field>

          <div className="admin-grid admin-grid--3">
            <Field label="Category">
              <SelectInput
                value={editing.cat}
                onChange={(v) => {
                  const tag = CATEGORIES.find((c) => c.value === v)?.label ?? v;
                  patch({ cat: v as Market['cat'], tag });
                }}
                options={CATEGORIES}
              />
            </Field>
            <Field label="YES price (¢)">
              <NumberInput
                value={editing.yes}
                min={1}
                max={99}
                onChange={(v) => patch({ yes: v })}
              />
            </Field>
            <Field label="NO price (¢)" hint={editing.isNew ? 'Auto = 100 − YES' : undefined}>
              <NumberInput
                value={editing.no}
                min={1}
                max={99}
                onChange={(v) => patch({ no: v })}
              />
            </Field>
          </div>

          <div className="admin-grid admin-grid--2">
            <Field label="End date" hint="When the market resolves">
              <TextInput
                type="datetime-local"
                value={toLocalInput(editing.end_date)}
                onChange={(v) => patch({ end_date: v || null })}
              />
            </Field>
            <Field
              label="Status"
              hint={
                editing.status === 'resolved'
                  ? 'Settled markets cannot be reopened here.'
                  : 'Resolve a market with the Resolve action so the winning outcome is recorded.'
              }
            >
              <SelectInput
                value={editing.status ?? 'open'}
                onChange={(v) => patch({ status: v as Market['status'] })}
                options={
                  editing.status === 'resolved'
                    ? [{ value: 'resolved', label: 'Resolved' }]
                    : [
                        { value: 'open', label: 'Open' },
                        { value: 'closed', label: 'Closed (stop trading)' },
                      ]
                }
              />
            </Field>
          </div>

          <div className="admin-grid admin-grid--2">
            <Field label="Volume (USDC)">
              <NumberInput
                value={editing.volume ?? 0}
                min={0}
                onChange={(v) => patch({ volume: v })}
              />
            </Field>
            <Field label="Liquidity (USDC)" hint="Resting book value; seeds the depth">
              <NumberInput
                value={editing.liquidity ?? 0}
                min={0}
                onChange={(v) => patch({ liquidity: v })}
              />
            </Field>
          </div>

          <div className="admin-grid admin-grid--2">
            <Field label="Trend">
              <SelectInput
                value={editing.trend}
                onChange={(v) => patch({ trend: v as Market['trend'] })}
                options={TRENDS}
              />
            </Field>
            <Field label="Sparkline points" hint="Comma-separated numbers, e.g. 10,14,12,18">
              <TextInput
                value={editing.pts.join(',')}
                onChange={(v) =>
                  patch({
                    pts: v
                      .split(',')
                      .map((s) => Number(s.trim()))
                      .filter((n) => Number.isFinite(n)),
                  })
                }
              />
            </Field>
          </div>

          <div className="admin-grid admin-grid--2">
            <Field label="Meta 1 (e.g. volume)">
              <TextInput value={editing.meta[0]} onChange={(v) => patch({ meta: [v, editing.meta[1]] })} />
            </Field>
            <Field label="Meta 2 (e.g. traders)">
              <TextInput value={editing.meta[1]} onChange={(v) => patch({ meta: [editing.meta[0], v] })} />
            </Field>
          </div>

          <div className="admin-form-actions">
            <SaveButton
              onSave={saveCurrent}
              label={editing.isNew ? 'Create market' : 'Save market'}
              dirty={dirty}
            />
            <button
              type="button"
              className="admin-btn admin-btn--ghost"
              onClick={() => setEditing(null)}
            >
              Cancel
            </button>
          </div>
        </Card>
      )}

      <p className="admin-hint">Changes are saved to the database and appear on the site immediately.</p>
    </div>
  );
}
