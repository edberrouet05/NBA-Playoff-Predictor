"use client";
import { use } from "react";
import RosterPage from "../../../../components/RosterPage";

export default function NBARosterPage({ params }: { params: Promise<{ abbr: string }> }) {
  const { abbr } = use(params);
  return <RosterPage league="nba" team={decodeURIComponent(abbr)} />;
}
