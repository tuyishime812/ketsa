'use client';

import { useState } from 'react';
import { adminDelete, adminPut } from '@/lib/api';
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

function emptyDraft(): Draft {
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
    isNew: true,
  };
}

export default function MarketsEditor({
  token,
  markets,
}: {
  token: string;
  markets: Market[];
}) {
  const [list, setList] = useState<Market[]>(markets);
  const [editing, setEditing] = useState<Draft | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [savedTick, setSavedTick] = useState(0);

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
    // Build a list of pts from the textarea if provided.
    const payload: Market = {
      id: editing.id,
      cat: editing.cat as Market['cat'],
      tag: editing.tag,
      q: editing.q,
      yes: editing.yes,
      no: editing.isNew ? computeNo(editing.yes) : editing.no,
      meta: editing.meta,
      trend: editing.trend as Market['trend'],
      pts: editing.pts,
    };

    try {
      await adminPut(token, '/markets', payload);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Save failed');
      return;
    }

    setList((prev) => {
      const exists = prev.some((m) => m.id === payload.id);
      return exists
        ? prev.map((m) => (m.id === payload.id ? payload : m))
        : [payload, ...prev];
    });
    setEditing(null);
    setSavedTick((t) => t + 1);
  }

  async function removeMarket(id: string) {
    try {
      await adminDelete(token, `/markets/${encodeURIComponent(id)}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Delete failed');
      return;
    }
    setList((prev) => prev.filter((m) => m.id !== id));
    setSavedTick((t) => t + 1);
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
                <tr key={m.id}>
                  <td className="admin-mono">{m.id}</td>
                  <td className="admin-strong">{m.q}</td>
                  <td>{m.cat}</td>
                  <td className="admin-mono">{m.yes}¢</td>
                  <td className="admin-mono">{m.no}¢</td>
                  <td className={m.trend === 'up' ? 'admin-pos' : 'admin-neg'}>
                    {m.trend === 'up' ? '▲' : '▼'}
                  </td>
                  <td className="admin-actions">
                    <button
                      type="button"
                      className="admin-btn admin-btn--ghost"
                      onClick={() => startEdit(m)}
                    >
                      Edit
                    </button>
                    <DangerButton onConfirm={() => removeMarket(m.id)} label="Delete" />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      {editing && (
        <Card title={editing.isNew ? 'New market' : `Edit: ${editing.id}`}>
          <div className="admin-grid admin-grid--2">
            <Field label="Market ID (URL slug)">
              <TextInput
                value={editing.id}
                onChange={(v) => patch({ id: v.replace(/\s+/g, '-').toLowerCase() })}
                placeholder="btc-120k"
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
