"use client";
import { use } from "react";
import TeamPage from "../../../components/TeamPage";

export default function MLBTeamPage({ params }: { params: Promise<{ abbr: string }> }) {
  const { abbr } = use(params);
  return <TeamPage league="mlb" team={decodeURIComponent(abbr)} backHref="/mlb" backLabel="Games" />;
}
