"use client";
import { use } from "react";
import TeamPage from "../../../components/TeamPage";

export default function NBATeamPage({ params }: { params: Promise<{ abbr: string }> }) {
  const { abbr } = use(params);
  return <TeamPage league="nba" team={decodeURIComponent(abbr)} backHref="/" backLabel="Games" />;
}
