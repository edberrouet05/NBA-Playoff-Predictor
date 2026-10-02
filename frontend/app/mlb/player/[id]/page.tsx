"use client";
import { use } from "react";
import PlayerPage from "../../../components/PlayerPage";

export default function MLBPlayerPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  return <PlayerPage league="mlb" id={id} />;
}
