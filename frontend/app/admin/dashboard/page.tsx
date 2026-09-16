'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { adminGet, adminPost } from '@/lib/api';
import { getStoredToken, clearStoredToken } from '../login-client';
import type {
  HomeData,
  PortfolioStats,
  Proof,
  SiteSettings,
} from '@/lib/types';
import MarketsEditor from '@/components/admin/MarketsEditor';
import HeroEditor from '@/components/admin/HeroEditor';
import TickerEditor from '@/components/admin/TickerEditor';
import WatchEditor from '@/components/admin/WatchEditor';
import DashboardEditor from '@/components/admin/DashboardEditor';
import FooterEditor from '@/components/admin/FooterEditor';
import ManageEditor from '@/components/admin/ManageEditor';
import UsersEditor from '@/components/admin/UsersEditor';

type TabKey =
  | 'markets'
  | 'hero'
  | 'ticker'
  | 'watch'
  | 'dashboard'
  | 'content'
  | 'users'
  | 'manage';

const TABS: { key: TabKey; label: string }[] = [
  { key: 'markets', label: 'Markets' },
  { key: 'hero', label: 'Hero' },
  { key: 'ticker', label: 'Ticker' },
  { key: 'watch', label: 'Watch' },
  { key: 'dashboard', label: 'Dashboard' },
  { key: 'content', label: 'Content' },
  { key: 'users', label: 'Users' },
  { key: 'manage', label: 'Manage' },
];

export default function AdminDashboard() {
  const router = useRouter();
  const [token, setToken] = useState<string | null>(null);
  const [tab, setTab] = useState<TabKey>('markets');

  // Public data (read via same-origin /api proxy, no auth needed).
  const [home, setHome] = useState<HomeData | null>(null);
  const [stats, setStats] = useState<PortfolioStats | null>(null);
  const [proof, setProof] = useState<Proof | null>(null);

  // Admin settings (protected).
  const [settings, setSettings] = useState<SiteSettings | null>(null);

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const stored = getStoredToken();
    if (!stored) {
      router.replace('/admin');
      return;
    }
    setToken(stored);

    (async () => {
      try {
        // Public data is read from the same-origin /api proxy (no auth).
        const [homeData, statsRes, proofRes, settingsData] = await Promise.all([
          fetch('/api/home').then((r) => r.json() as Promise<HomeData>),
          fetch('/api/stats').then((r) => r.json() as Promise<PortfolioStats>),
          fetch('/api/proof').then((r) => r.json() as Promise<Proof>),
          adminGet<SiteSettings>(stored, '/settings'),
        ]);
        setHome(homeData);
        setStats(statsRes);
        setProof(proofRes);
        setSettings(settingsData);
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to load data');
      } finally {
        setLoading(false);
      }
    })();
  }, [router]);

  async function handleLogout() {
    if (token) {
      try {
        await adminPost(token, '/logout', {});
      } catch {
        // Token already invalid locally is fine — clear it regardless.
      }
    }
    clearStoredToken();
    router.replace('/admin');
  }

  if (!token) return null;

  return (
    <div className="admin-shell">
      <aside className="admin-sidebar">
        <div className="admin-logo">
          <span className="admin-logo-dot" />
          Ketsa
        </div>
        <div className="admin-sidebar-label">Admin</div>
        <nav className="admin-nav">
          {TABS.map((t) => (
            <button
              key={t.key}
              className={`admin-nav-item ${tab === t.key ? 'is-active' : ''}`}
              onClick={() => setTab(t.key)}
            >
              {t.label}
            </button>
          ))}
        </nav>
        <div className="admin-sidebar-footer">
          <a className="admin-nav-link" href="/" target="_blank" rel="noreferrer">
            View site ↗
          </a>
          <button className="admin-nav-link admin-logout" onClick={handleLogout}>
            Log out
          </button>
        </div>
      </aside>

      <main className="admin-main">
        <header className="admin-topbar">
          <h1 className="admin-page-title">
            {TABS.find((t) => t.key === tab)?.label}
          </h1>
        </header>

        <div className="admin-content">
          {loading && <div className="admin-state">Loading…</div>}
          {error && !loading && (
            <div className="admin-state admin-state--error">{error}</div>
          )}
          {!loading && home && settings && tab === 'markets' && (
            <MarketsEditor token={token} markets={home.markets.all} />
          )}
          {!loading && settings && tab === 'hero' && (
            <HeroEditor token={token} proof={proof ?? null} settings={settings} />
          )}
          {!loading && home && tab === 'ticker' && (
            <TickerEditor token={token} items={home.ticker} />
          )}
          {!loading && home && tab === 'watch' && (
            <WatchEditor token={token} items={home.watch} />
          )}
          {!loading && tab === 'dashboard' && (
            <DashboardEditor
              token={token}
              data={home?.dashboard ?? null}
              stats={stats}
              proof={proof}
            />
          )}
          {!loading && settings && tab === 'content' && (
            <FooterEditor token={token} settings={settings} />
          )}
          {!loading && tab === 'users' && <UsersEditor token={token} />}
          {!loading && tab === 'manage' && <ManageEditor token={token} />}
        </div>
      </main>
    </div>
  );
}
