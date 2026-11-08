import { SectionTabs } from "../../components/SectionTabs";

export default function Layout({ children }: { children: React.ReactNode }) {
  return (
    <>
      <SectionTabs sport="mlb" section="model" />
      {children}
    </>
  );
}
