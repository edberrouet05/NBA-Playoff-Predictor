import { SectionTabs } from "../../components/SectionTabs";

export default function Layout({ children }: { children: React.ReactNode }) {
  return (
    <>
      <SectionTabs sport="nfl" section="model" />
      {children}
    </>
  );
}
