import Nav from '@/components/Nav';
import Footer from '@/components/Footer';
import TeamDirectory from '@/components/staff/TeamDirectory';
import { fetchHomeData, fetchStaffPublic } from '@/lib/api';
import type { StaffPublic, SiteSettings } from '@/lib/types';

export const dynamic = 'force-dynamic';

export const metadata = {
  title: 'Team — Ketsa',
  description:
    'The people behind Ketsa, the real-time prediction market. Updated live.',
};

export default async function TeamPage() {
  // Live data only, fail soft: an unreachable API shows an empty directory
  // rather than fabricated people. The footer is optional for the same reason.
  let staff: StaffPublic[] = [];
  let settings: SiteSettings | null = null;
  try {
    const [team, home] = await Promise.all([
      fetchStaffPublic(),
      fetchHomeData().catch(() => null),
    ]);
    staff = team;
    settings = home?.settings ?? null;
  } catch (err) {
    console.error('team directory fetch failed:', err);
  }

  return (
    <>
      <Nav />
      <main id="top">
        <TeamDirectory initial={staff} />
      </main>
      {settings && <Footer copy={settings.footer} />}
    </>
  );
}
