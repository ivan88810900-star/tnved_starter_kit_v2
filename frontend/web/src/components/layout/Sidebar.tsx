import { useState } from "react";
import {
  LayoutDashboard,
  ScanSearch,
  BookOpen,
  ShieldCheck,
  Settings,
  ChevronLeft,
  Zap,
} from "lucide-react";
import { cn } from "../../lib/utils";

type NavItem = {
  icon: React.ElementType;
  label: string;
  id: string;
  badge?: string;
};

const NAV_ITEMS: NavItem[] = [
  { icon: LayoutDashboard, label: "Обзор", id: "overview" },
  { icon: BookOpen,        label: "Реестр ТН ВЭД", id: "registries" },
  { icon: ScanSearch,      label: "Классификация", id: "classify" },
  { icon: ShieldCheck,     label: "Комплаенс", id: "compliance", badge: "Soon" },
  { icon: Settings,        label: "Настройки", id: "settings", badge: "Soon" },
];

type SidebarProps = {
  activeId?: string;
  onNavigate?: (id: string) => void;
};

export function Sidebar({ activeId = "overview", onNavigate }: SidebarProps) {
  const [collapsed, setCollapsed] = useState(false);

  return (
    <aside
      className={cn(
        "relative flex h-full flex-col border-r border-white/[0.06] bg-[#0a0a14] transition-all duration-300",
        collapsed ? "w-[60px]" : "w-[220px]",
      )}
    >
      {/* Logo */}
      <div
        className={cn(
          "flex h-16 shrink-0 items-center border-b border-white/[0.06]",
          collapsed ? "justify-center px-2" : "gap-3 px-4",
        )}
      >
        <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-[#00F0FF]/15">
          <Zap size={16} className="text-[#00F0FF]" style={{ filter: "drop-shadow(0 0 6px #00F0FF)" }} />
        </div>
        {!collapsed && (
          <span className="text-sm font-bold tracking-tight text-white">
            VED<span className="text-[#00F0FF]">·</span>AI
          </span>
        )}
      </div>

      {/* Nav */}
      <nav className="flex flex-1 flex-col gap-0.5 px-2 py-3">
        {NAV_ITEMS.map(({ icon: Icon, label, id, badge }) => {
          const isActive = activeId === id;
          return (
            <button
              key={id}
              type="button"
              onClick={() => onNavigate?.(id)}
              title={collapsed ? label : undefined}
              className={cn(
                "group flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-left text-sm transition-all duration-150",
                isActive
                  ? "bg-[#00F0FF]/10 text-[#00F0FF]"
                  : "text-[#8B92A8] hover:bg-white/[0.05] hover:text-white",
              )}
            >
              <Icon
                size={16}
                className="shrink-0"
                style={isActive ? { filter: "drop-shadow(0 0 5px #00F0FF)" } : undefined}
              />
              {!collapsed && (
                <>
                  <span className="flex-1 font-medium">{label}</span>
                  {badge && (
                    <span className="rounded-full bg-white/[0.07] px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wider text-[#4A5166]">
                      {badge}
                    </span>
                  )}
                </>
              )}
            </button>
          );
        })}
      </nav>

      {/* Collapse toggle */}
      <button
        type="button"
        onClick={() => setCollapsed((v) => !v)}
        className="absolute -right-3 top-[72px] flex h-6 w-6 items-center justify-center rounded-full border border-white/[0.1] bg-[#0f0f1e] text-[#4A5166] transition hover:text-white"
        aria-label="Свернуть/развернуть"
      >
        <ChevronLeft
          size={12}
          className={cn("transition-transform duration-300", collapsed && "rotate-180")}
        />
      </button>

      {/* Footer */}
      {!collapsed && (
        <div className="border-t border-white/[0.06] px-4 py-3">
          <p className="text-[10px] leading-relaxed text-[#2A2E3E]">
            ТН ВЭД ЕАЭС · ИИ-агент<br />v2.0 · MVP
          </p>
        </div>
      )}
    </aside>
  );
}
