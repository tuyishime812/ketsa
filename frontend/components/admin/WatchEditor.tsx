'use client';

import { useState } from 'react';
import { adminPut } from '@/lib/api';
import type { WatchItem } from '@/lib/types';
import {
  Card,
  DangerButton,
  NumberInput,
  SaveButton,
  SelectInput,
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

type Row = WatchItem & { key: number };

export default function WatchEditor({
  items,
}: {
  items: WatchItem[];
}) {
  const [rows, setRows] = useState<Row[]>(items.map((it, i) => ({ ...it, key: i })));
  const [error, setError] = useState<string | null>(null);
  const [changed, setChanged] = useState(false);
  const [nextKey, setNextKey] = useState(rows.length);

  function patch(index: number, p: Partial<Row>) {
    setRows((prev) => prev.map((r, i) => (i === index ? { ...r, ...p } : r)));
    setChanged(true);
  }

  function addRow() {
    setRows((prev) => [
      ...prev,
      { name: 'New market', cat: 'politics', price: 50, pts: [20, 22, 24, 23, 26, 28, 30, 32], key: nextKey },
    ]);
    setNextKey((k) => k + 1);
    setChanged(true);
  }

  function removeRow(index: number) {
    setRows((prev) => prev.filter((_, i) => i !== index));
    setChanged(true);
  }

  function moveRow(index: number, dir: -1 | 1) {
    setRows((prev) => {
      const target = index + dir;
      if (target < 0 || target >= prev.length) return prev;
      const next = [...prev];
      const tmp = next[index];
      next[index] = next[target];
      next[target] = tmp;
      return next;
    });
    setChanged(true);
  }

  async function save() {
    setError(null);
    const payload = rows.map(({ name, cat, price, pts }) => ({ name, cat, price, pts }));
    try {
      await adminPut('/watch', payload);
      setChanged(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Save failed');
      throw err;
    }
  }

  return (
    <div className="admin-stack">
      {error && <div className="admin-error">{error}</div>}

      <div className="admin-row-between">
        <p className="admin-muted">
          Items shown in the live &ldquo;Market watch&rdquo; panel in the hero. Prices jitter
          automatically; you set the label, category and starting price.
        </p>
        <button type="button" className="admin-btn admin-btn--primary" onClick={addRow}>
          + Add item
        </button>
      </div>

      <Card>
        <div className="admin-table-wrap">
          <table className="admin-table">
            <thead>
              <tr>
                <th>Name</th>
                <th>Category</th>
                <th>Starting price (¢)</th>
                <th>Order</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {rows.length === 0 && (
                <tr>
                  <td colSpan={5}>
                    <span className="admin-muted">
                      No watch items yet. Add items to fill the hero panel, or leave this empty to
                      hide the panel on the public site.
                    </span>
                  </td>
                </tr>
              )}
              {rows.map((r, i) => (
                <tr key={r.key}>
                  <td>
                    <TextInput value={r.name} onChange={(v) => patch(i, { name: v })} />
                  </td>
                  <td style={{ width: 150 }}>
                    <SelectInput
                      value={r.cat}
                      onChange={(v) => patch(i, { cat: v })}
                      options={CATEGORIES}
                    />
                  </td>
                  <td style={{ width: 120 }}>
                    <NumberInput value={r.price} min={1} max={99} onChange={(v) => patch(i, { price: v })} />
                  </td>
                  <td>
                    <div className="admin-order">
                      <button type="button" className="admin-icon-btn" onClick={() => moveRow(i, -1)} disabled={i === 0}>
                        ↑
                      </button>
                      <button type="button" className="admin-icon-btn" onClick={() => moveRow(i, 1)} disabled={i === rows.length - 1}>
                        ↓
                      </button>
                    </div>
                  </td>
                  <td className="admin-actions">
                    <DangerButton onConfirm={() => removeRow(i)} label="Remove" />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <SaveButton onSave={save} dirty={changed} />
      </Card>

      <p className="admin-hint">
        {rows.length === 0
          ? 'An empty list hides the hero panel on the public site.'
          : 'Keep at least 3 items for a full-looking panel.'}
      </p>
    </div>
  );
}
