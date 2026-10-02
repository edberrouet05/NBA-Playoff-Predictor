import { redirect } from "next/navigation";

// Old NBA team URL (/team/<name>) → shared team page
export default async function LegacyTeamPage({ params }: { params: Promise<{ team: string }> }) {
  const { team } = await params;
  redirect(`/nba/team/${team}`);
}
