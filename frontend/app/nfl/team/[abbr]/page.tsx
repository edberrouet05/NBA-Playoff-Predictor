"use client";
import { use } from "react";
import TeamPage from "../../../components/TeamPage";

export default function NFLTeamPage({ params }: { params: Promise<{ abbr: string }> }) {
  const { abbr } = use(params);
  return <TeamPage league="nfl" team={decodeURIComponent(abbr)} backHref="/nfl" backLabel="Games" />;
}
