import Nav from '@/components/Nav';
import Leaderboard from '@/components/leaderboard/Leaderboard';

export const dynamic = 'force-dynamic';

export default function LeaderboardPage() {
  return (
    <>
      <Nav />
      <main>
        <Leaderboard />
      </main>
    </>
  );
}