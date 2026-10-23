'use client';

import { useState } from 'react';
import { adminPut } from '@/lib/api';
import type { DashboardData, PortfolioStats, Proof } from '@/lib/types';
import {
  Card,
  NumberInput,
  SaveButton,
  TextInput,
} from './ui';

const RANGE_KEYS = ['1D', '1W', '1M', '1Y'] as const;

function parsePoints(text: string): number[] {
  return text
    .split(',')
    .map((s) => Number(s.trim()))
    .filter((n) => Number.isFinite(n));
}

export default function DashboardEditor({
  data,
  stats,
  proof,
}: {
  data: DashboardData | null;
  stats: PortfolioStats | null;
  proof: Proof | null;
}) {
  const [dashboard, setDashboard] = useState<DashboardData | null>(data);
  const [statsDraft, setStatsDraft] = useState<PortfolioStats | null>(stats);
  const [error, setError] = useState<string | null>(null);
  const [chartDirty, setChartDirty] = useState(false);
  const [statsDirty, setStatsDirty] = useState(false);

  async function saveDashboardFn() {
    if (!dashboard) return;
    setError(null);
    try {
      await adminPut('/dashboard', dashboard);
      setChartDirty(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Save failed');
    }
  }

  async function saveStatsFn() {
    if (!statsDraft) return;
    setError(null);
    try {
      await adminPut('/stats', statsDraft);
      setStatsDirty(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Save failed');
    }
  }

  if (!dashboard || !statsDraft) {
    return <div className="admin-state">Loading dashboard data…</div>;
  }

  return (
    <div className="admin-stack">
      {error && <div className="admin-error">{error}</div>}

      <Card title="Portfolio chart — balance and price history per time range">
        <div className="admin-stack">
          {RANGE_KEYS.map((key) => {
            const s = dashboard.ranges[key];
            if (!s) return null;
            return (
              <div key={key} className="admin-card">
                <h3 className="admin-card-title">{key} range</h3>
                <div className="admin-grid admin-grid--3">
                  <label className="admin-field">
                    <span className="admin-field-label">Balance ($)</span>
                    <NumberInput
                      value={s.balance}
                      onChange={(v) => {
                        setDashboard((prev) =>
                          prev
                            ? { ...prev, ranges: { ...prev.ranges, [key]: { ...s, balance: v } } }
                            : prev,
                        );
                        setChartDirty(true);
                      }}
                    />
                  </label>
                  <label className="admin-field">
                    <span className="admin-field-label">Change (%)</span>
                    <NumberInput
                      value={s.change}
                      onChange={(v) => {
                        setDashboard((prev) =>
                          prev
                            ? { ...prev, ranges: { ...prev.ranges, [key]: { ...s, change: v } } }
                            : prev,
                        );
                        setChartDirty(true);
                      }}
                    />
                  </label>
                  <label className="admin-field">
                    <span className="admin-field-label">Chart points</span>
                    <TextInput
                      value={s.pts.join(',')}
                      onChange={(v) => {
                        setDashboard((prev) =>
                          prev
                            ? { ...prev, ranges: { ...prev.ranges, [key]: { ...s, pts: parsePoints(v) } } }
                            : prev,
                        );
                        setChartDirty(true);
                      }}
                    />
                  </label>
                </div>
              </div>
            );
          })}
        </div>
        <SaveButton onSave={saveDashboardFn} dirty={chartDirty} label="Save chart data" />
      </Card>

      <Card title="Portfolio stats tiles">
        <div className="admin-grid admin-grid--3">
          <label className="admin-field">
            <span className="admin-field-label">Total P&L ($)</span>
            <NumberInput
              value={statsDraft.pnl}
              onChange={(v) => {
                setStatsDraft((prev) => (prev ? { ...prev, pnl: v } : prev));
                setStatsDirty(true);
              }}
            />
          </label>
          <label className="admin-field">
            <span className="admin-field-label">Open positions</span>
            <NumberInput
              value={statsDraft.open_positions}
              onChange={(v) => {
                setStatsDraft((prev) => (prev ? { ...prev, open_positions: v } : prev));
                setStatsDirty(true);
              }}
            />
          </label>
          <label className="admin-field">
            <span className="admin-field-label">Win rate (%)</span>
            <NumberInput
              value={statsDraft.win_rate}
              onChange={(v) => {
                setStatsDraft((prev) => (prev ? { ...prev, win_rate: v } : prev));
                setStatsDirty(true);
              }}
            />
          </label>
        </div>
        <SaveButton onSave={saveStatsFn} dirty={statsDirty} label="Save stats" />
      </Card>

      {proof && (
        <Card title="Hero proof stats">
          <p className="admin-muted">
            Traders {proof.traders_k}K · Live markets {proof.live_markets} · Volume ${proof.total_volume_m}M.
            Edit these in the <strong>Hero</strong> tab.
          </p>
        </Card>
      )}
    </div>
  );
}
