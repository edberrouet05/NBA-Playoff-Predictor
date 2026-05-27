import type { Metadata } from "next";
import { Geist } from "next/font/google";
import "./globals.css";
import Navbar from "./components/Navbar";
import ThemeToggle from "./components/ThemeToggle";
import TopNav from "./components/TopNav";

const geist = Geist({ variable: "--font-geist-sans", subsets: ["latin"] });

export const metadata: Metadata = {
  title: "CourtEdge",
  description: "Live schedule · Game-by-game simulation · 2025–26 stats",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${geist.variable} antialiased`} suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: `(function(){var t=localStorage.getItem('theme');if(t==='dark'||(!t&&matchMedia('(prefers-color-scheme: dark)').matches)){document.documentElement.classList.add('dark');}})();` }} />
      </head>
      <body className="min-h-screen bg-gray-50 dark:bg-gray-950">
        <Navbar />
        <div className="ml-[68px]">
          <header className="sticky top-0 z-10 bg-white/80 dark:bg-gray-900/80 backdrop-blur-md border-b border-gray-200/60 dark:border-white/[0.06] px-7 h-12 flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div>
                <span className="text-red-600 font-black text-xl tracking-tight">Court</span><span className="text-gray-900 dark:text-white font-black text-xl tracking-tight">Edge</span>
              </div>
              <TopNav />
            </div>
            <ThemeToggle />
          </header>
          {children}
        </div>
      </body>
    </html>
  );
}
