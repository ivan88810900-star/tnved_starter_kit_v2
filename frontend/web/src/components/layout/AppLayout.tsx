import { type ReactNode, useEffect, useState } from "react";
import { BookOpen } from "lucide-react";
import { Sidebar } from "./Sidebar";
import { TnVedDrawer } from "../TnVedDrawer";

type AppLayoutProps = {
  children: ReactNode;
  activeNav: string;
  onNavigate: (id: string) => void;
};

export function AppLayout({ children, activeNav, onNavigate }: AppLayoutProps) {
  const [drawerOpen, setDrawerOpen] = useState(false);

  // Global Cmd+K / Ctrl+K shortcut
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "k" && (e.metaKey || e.ctrlKey)) {
        e.preventDefault();
        setDrawerOpen((v) => !v);
      }
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, []);

  return (
    <div className="flex h-screen overflow-hidden bg-[#080810]">
      <Sidebar activeId={activeNav} onNavigate={onNavigate} />

      <div className="flex flex-1 flex-col overflow-hidden">
        {/* Global top-right bar with drawer trigger */}
        <div className="flex h-10 shrink-0 items-center justify-end border-b border-white/[0.05] bg-[#080810]/80 px-4 backdrop-blur-sm">
          <button
            onClick={() => setDrawerOpen(true)}
            className="flex items-center gap-2 rounded-lg border border-white/[0.08] bg-white/[0.03] px-3 py-1.5 text-[11px] text-[#8B92A8] transition hover:border-[#00F0FF]/25 hover:text-white"
          >
            <BookOpen size={12} className="text-[#00F0FF]" />
            Справочник ТН ВЭД
            <kbd className="rounded border border-white/[0.1] bg-white/[0.05] px-1 py-0.5 text-[9px] font-mono text-[#4A5166]">
              ⌘K
            </kbd>
          </button>
        </div>

        <main className="flex flex-1 flex-col overflow-hidden">
          {children}
        </main>
      </div>

      <TnVedDrawer open={drawerOpen} onClose={() => setDrawerOpen(false)} />
    </div>
  );
}
