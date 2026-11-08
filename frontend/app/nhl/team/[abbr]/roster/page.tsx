"use client";
import { use } from "react";
import RosterPage from "../../../../components/RosterPage";

export default function NHLRosterPage({ params }: { params: Promise<{ abbr: string }> }) {
  const { abbr } = use(params);
  return <RosterPage league="nhl" team={decodeURIComponent(abbr)} />;
}
