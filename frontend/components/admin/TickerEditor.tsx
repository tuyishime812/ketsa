'use client';

import { useState } from 'react';
import { adminPut } from '@/lib/api';
import type { TickerItem } from '@/lib/types';
import {
  Card,
  DangerButton,
  SaveButton,
  SelectInput,
  TextInput,
} from './ui';

type Row = TickerItem & { key: number };

export default function TickerEditor({
  items,
}: {
  items: TickerItem[];
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
    setRows((prev) => [...prev, { t: 'NEW MARKET', v: '50¢', d: 'up', key: nextKey }]);
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
    const payload = rows.map(({ t, v, d }) => ({ t, v, d }));
    try {
      await adminPut('/ticker', payload);
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
        <p className="admin-muted">Items shown in the scrolling marquee at the top of the site.</p>
        <button type="button" className="admin-btn admin-btn--primary" onClick={addRow}>
          + Add item
        </button>
      </div>

      <Card>
        <div className="admin-table-wrap">
          <table className="admin-table">
            <thead>
              <tr>
                <th>Market</th>
                <th>Price</th>
                <th>Direction</th>
                <th>Order</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {rows.length === 0 && (
                <tr>
                  <td colSpan={5}>
                    <span className="admin-muted">
                      No ticker items yet. Add items to fill the marquee, or leave this empty to
                      hide the ticker on the public site.
                    </span>
                  </td>
                </tr>
              )}
              {rows.map((r, i) => (
                <tr key={r.key}>
                  <td>
                    <TextInput value={r.t} onChange={(v) => patch(i, { t: v })} />
                  </td>
                  <td style={{ width: 120 }}>
                    <TextInput value={r.v} onChange={(v) => patch(i, { v: v })} placeholder="41¢" />
                  </td>
                  <td style={{ width: 140 }}>
                    <SelectInput
                      value={r.d}
                      onChange={(v) => patch(i, { d: v as TickerItem['d'] })}
                      options={[
                        { value: 'up', label: 'Up ▲' },
                        { value: 'down', label: 'Down ▼' },
                      ]}
                    />
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
          ? 'An empty list hides the scrolling ticker on the public site.'
          : 'The ticker is duplicated for a seamless scrolling loop — keep at least 4 items.'}
      </p>
    </div>
  );
}
