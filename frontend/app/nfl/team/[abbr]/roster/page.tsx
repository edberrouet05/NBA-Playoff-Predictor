"use client";
import { use } from "react";
import RosterPage from "../../../../components/RosterPage";

export default function NFLRosterPage({ params }: { params: Promise<{ abbr: string }> }) {
  const { abbr } = use(params);
  return <RosterPage league="nfl" team={decodeURIComponent(abbr)} />;
}
