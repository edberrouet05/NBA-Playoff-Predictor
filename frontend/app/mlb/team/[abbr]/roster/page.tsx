"use client";
import { use } from "react";
import RosterPage from "../../../../components/RosterPage";

export default function MLBRosterPage({ params }: { params: Promise<{ abbr: string }> }) {
  const { abbr } = use(params);
  return <RosterPage league="mlb" team={decodeURIComponent(abbr)} />;
}
