'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { adminGet, adminLogout, adminMe, AdminApiError } from '@/lib/api';
import type {
  AdminPrincipal,
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
import StaffEditor from '@/components/admin/StaffEditor';
import BroadcastEditor from '@/components/admin/BroadcastEditor';
import WithdrawalsEditor from '@/components/admin/WithdrawalsEditor';
import SettingsEditor from '@/components/admin/SettingsEditor';

type TabKey =
  | 'markets'
  | 'hero'
  | 'ticker'
  | 'watch'
  | 'dashboard'
  | 'content'
  | 'users'
  | 'withdrawals'
  | 'staff'
  | 'broadcast'
  | 'settings'
  | 'manage';

interface TabDef {
  key: TabKey;
  label: string;
  /** Capability the server requires for this area to be useful. */
  capability: string;
}

// Tabs are hidden when the signed-in role lacks the capability. This is only a
// convenience: every route re-checks the capability server-side, so hiding a
// tab is not what stops an unauthorised write.
const TABS: TabDef[] = [
  { key: 'markets', label: 'Markets', capability: 'markets:write' },
  { key: 'hero', label: 'Hero', capability: 'content:write' },
  { key: 'ticker', label: 'Ticker', capability: 'content:write' },
  { key: 'watch', label: 'Watch', capability: 'content:write' },
  { key: 'dashboard', label: 'Dashboard', capability: 'content:write' },
  { key: 'content', label: 'Content', capability: 'content:write' },
  { key: 'users', label: 'Users', capability: 'users:read' },
  { key: 'withdrawals', label: 'Withdrawals', capability: 'withdrawals:read' },
  { key: 'staff', label: 'Staff', capability: 'staff:read' },
  { key: 'broadcast', label: 'Broadcast', capability: 'broadcast:write' },
  { key: 'settings', label: 'Settings', capability: 'config:write' },
  { key: 'manage', label: 'Manage', capability: 'config:write' },
];

export default function AdminDashboard() {
  const router = useRouter();
  const [ready, setReady] = useState(false);
  const [tab, setTab] = useState<TabKey>('markets');
  const [principal, setPrincipal] = useState<AdminPrincipal | null>(null);
  // Off-canvas navigation on narrow screens. On desktop the sidebar is always
  // visible and this state is ignored by CSS.
  const [navOpen, setNavOpen] = useState(false);

  // Public data (read via same-origin /api proxy, no auth needed).
  const [home, setHome] = useState<HomeData | null>(null);
  const [stats, setStats] = useState<PortfolioStats | null>(null);
  const [proof, setProof] = useState<Proof | null>(null);

  // Admin settings (protected).
  const [settings, setSettings] = useState<SiteSettings | null>(null);

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      try {
        // Resolve the principal first: it decides which protected data we may
        // fetch and which tabs we may show.
        const who = await adminMe();

        // Public data is read from the same-origin /api proxy (no auth).
        // `/settings` is protected: it both proves the HttpOnly admin session
        // is still valid and supplies the settings the editors need.
        const [homeData, statsRes, proofRes, settingsData] = await Promise.all([
          fetch('/api/home').then((r) => r.json() as Promise<HomeData>),
          fetch('/api/stats').then((r) => r.json() as Promise<PortfolioStats>),
          fetch('/api/proof').then((r) => r.json() as Promise<Proof>),
          who.capabilities.includes('content:read')
            ? adminGet<SiteSettings>('/settings')
            : Promise.resolve({} as SiteSettings),
        ]);
        setPrincipal(who);
        setHome(homeData);
        setStats(statsRes);
        setProof(proofRes);
        setSettings(settingsData);
        setReady(true);
      } catch (err) {
        if (err instanceof AdminApiError && err.status === 401) {
          router.replace('/admin');
          return;
        }
        setError(err instanceof Error ? err.message : 'Failed to load data');
      } finally {
        setLoading(false);
      }
    })();
  }, [router]);

  async function handleLogout() {
    setNavOpen(false);
    try {
      await adminLogout();
    } catch {
      // Session already invalid is fine — the proxy clears the cookie anyway.
    }
    router.replace('/admin');
  }

  if (!ready) return null;

  const allowedTabs = TABS.filter((t) =>
    (principal?.capabilities ?? []).includes(t.capability),
  );
  const activeTab: TabKey | undefined = allowedTabs.some((t) => t.key === tab)
    ? tab
    : allowedTabs[0]?.key;
  const can = (capability: string) =>
    (principal?.capabilities ?? []).includes(capability);

  return (
    <div className={`admin-shell ${navOpen ? 'is-nav-open' : ''}`}>
      <aside className={`admin-sidebar ${navOpen ? 'is-open' : ''}`}>
        <div className="admin-logo">
          <span className="admin-logo-dot" />
          Ketsa
        </div>
        <div className="admin-sidebar-label">Admin</div>
        <nav className="admin-nav">
          {allowedTabs.map((t) => (
            <button
              key={t.key}
              className={`admin-nav-item ${activeTab === t.key ? 'is-active' : ''}`}
              onClick={() => {
                setTab(t.key);
                setNavOpen(false);
              }}
            >
              {t.label}
            </button>
          ))}
        </nav>
        <div className="admin-sidebar-footer">
          {principal && (
            <div className="admin-identity">
              <div className="admin-identity-name">{principal.name || principal.email}</div>
              <div className="admin-identity-role">{principal.role}</div>
            </div>
          )}
          <a className="admin-nav-link" href="/" target="_blank" rel="noreferrer">
            View site ↗
          </a>
          <button className="admin-nav-link admin-logout" onClick={handleLogout}>
            Log out
          </button>
        </div>
      </aside>

      {navOpen && (
        <button
          type="button"
          className="admin-nav-backdrop"
          aria-label="Close navigation"
          onClick={() => setNavOpen(false)}
        />
      )}

      <main className="admin-main">
        <header className="admin-topbar">
          <button
            type="button"
            className="admin-menu-btn"
            aria-label="Toggle navigation"
            aria-expanded={navOpen}
            onClick={() => setNavOpen((open) => !open)}
          >
            <span />
            <span />
            <span />
          </button>
          <h1 className="admin-page-title">
            {allowedTabs.find((t) => t.key === activeTab)?.label ?? 'Admin'}
          </h1>
        </header>

        <div className="admin-content">
          {loading && <div className="admin-state">Loading…</div>}
          {error && !loading && (
            <div className="admin-state admin-state--error">{error}</div>
          )}
          {!loading && home && settings && activeTab === 'markets' && (
            <MarketsEditor markets={home.markets.all} />
          )}
          {!loading && settings && activeTab === 'hero' && (
            <HeroEditor proof={proof ?? null} settings={settings} />
          )}
          {!loading && home && activeTab === 'ticker' && (
            <TickerEditor items={home.ticker} />
          )}
          {!loading && home && activeTab === 'watch' && (
            <WatchEditor items={home.watch} />
          )}
          {!loading && activeTab === 'dashboard' && (
            <DashboardEditor
              data={home?.dashboard ?? null}
              stats={stats}
              proof={proof}
            />
          )}
          {!loading && settings && activeTab === 'content' && (
            <FooterEditor settings={settings} />
          )}
          {!loading && activeTab === 'users' && <UsersEditor />}
          {!loading && activeTab === 'withdrawals' && (
            <WithdrawalsEditor canManage={can('withdrawals:manage')} />
          )}
          {!loading && activeTab === 'staff' && <StaffEditor canWrite={can('staff:write')} />}
          {!loading && activeTab === 'broadcast' && <BroadcastEditor />}
          {!loading && activeTab === 'settings' && (
            <SettingsEditor isMaster={principal?.kind === 'master'} />
          )}
          {!loading && activeTab === 'manage' && <ManageEditor />}
        </div>
      </main>
    </div>
  );
}
