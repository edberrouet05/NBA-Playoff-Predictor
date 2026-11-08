"use client";
import { use } from "react";
import TeamPage from "../../../components/TeamPage";

export default function NHLTeamPage({ params }: { params: Promise<{ abbr: string }> }) {
  const { abbr } = use(params);
  return <TeamPage league="nhl" team={decodeURIComponent(abbr)} backHref="/nhl" backLabel="Games" />;
}
