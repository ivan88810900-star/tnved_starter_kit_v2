import React from 'react';
import { NavLink, Outlet, useLocation } from 'react-router-dom';
import {
  BadgeCheck,
  BookOpenText,
  Bot,
  Calculator as CalculatorIcon,
  FileSpreadsheet,
  FileSearch,
  FileText,
  Files,
  Menu,
  ShieldCheck,
  Stamp,
  X,
} from 'lucide-react';
import { AuthBar } from './AuthBar';
import { useAssistantSurfaceVisible, useClientCapabilities } from '../context/ClientCapabilitiesContext';

export const PAGE_HEADERS: Record<string, { title: string; desc: string; breadcrumb?: string }> = {
  '/': { title: 'Главная', desc: 'Поиск по ТН ВЭД и быстрые действия', breadcrumb: 'Главная' },
  '/docs': { title: 'Документы', desc: 'Инвойс и упаковочные листы', breadcrumb: 'Документы' },
  '/classifier': { title: 'Классификатор', desc: 'Подбор кода ТН ВЭД', breadcrumb: 'Классификатор' },
  '/tnved': { title: 'Справочник ТН ВЭД', desc: 'Наименования, примечания, ссылки ЕЭК', breadcrumb: 'Справочник' },
  '/trois': { title: 'ТРОИС', desc: 'Товарные знаки', breadcrumb: 'ТРОИС' },
  '/permits': { title: 'СС и ДС', desc: 'Разрешительные документы', breadcrumb: 'СС и ДС' },
  '/invoice': { title: 'Инвойс', desc: 'Загрузка и классификация пакинг-листа', breadcrumb: 'Инвойс' },
  '/calculator': { title: 'Платежи', desc: 'Пошлина, НДС, база', breadcrumb: 'Калькулятор' },
  '/non-tariff': { title: 'Нетарифка', desc: 'ТР ТС, меры', breadcrumb: 'Нетарифка' },
  '/assistant': { title: 'Ассистент', desc: 'Сводный разбор: ТН ВЭД, платежи, нетарифные меры', breadcrumb: 'Ассистент' },
  '/admin/system': { title: 'Состояние системы', desc: 'Сводка БД и ИИ', breadcrumb: 'Админ' },
  '/admin/import': { title: 'Массовая загрузка базы', desc: 'Импорт PDF/DOCX/HTML', breadcrumb: 'Админ' },
};

type NavItem = {
  to: string;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
  end?: boolean;
};

const NAV_GROUPS: Array<{ label: string; items: NavItem[] }> = [
  {
    label: 'СПРАВОЧНИКИ',
    items: [
      { to: '/tnved', label: 'Справочник ТН ВЭД', icon: BookOpenText },
      { to: '/trois', label: 'ТРОИС', icon: BadgeCheck },
      { to: '/permits', label: 'СС и ДС', icon: Files },
    ],
  },
  {
    label: 'ИНСТРУМЕНТЫ',
    items: [
      { to: '/', label: 'Главная', icon: FileSearch, end: true },
      { to: '/classifier', label: 'Классификатор', icon: Stamp },
      { to: '/calculator', label: 'Платежи', icon: CalculatorIcon },
      { to: '/invoice', label: 'Инвойс', icon: FileSpreadsheet },
      { to: '/non-tariff', label: 'Нетарифка', icon: ShieldCheck },
      { to: '/docs', label: 'Документы', icon: FileText },
      { to: '/assistant', label: 'Ассистент', icon: Bot },
    ],
  },
];

const MOBILE_NAV: NavItem[] = [
  { to: '/tnved', label: 'Поиск', icon: BookOpenText },
  { to: '/calculator', label: 'Кальк.', icon: CalculatorIcon },
  { to: '/invoice', label: 'Пакинг', icon: FileSpreadsheet },
  { to: '/assistant', label: 'Ассист.', icon: Bot },
];

function clearUrlHash(): void {
  if (typeof window === 'undefined' || !window.location.hash) return;
  window.history.replaceState(null, '', window.location.pathname + window.location.search);
}

function SidebarLink({ item, onNavigate }: { item: NavItem; onNavigate?: () => void }) {
  return (
    <NavLink
      to={item.to}
      end={item.end}
      title={PAGE_HEADERS[item.to]?.desc}
      onClick={() => {
        clearUrlHash();
        onNavigate?.();
      }}
      className={({ isActive }) =>
        `relative flex h-10 items-center gap-2 rounded-md px-2 text-[13px] font-medium transition-colors ${
          isActive
            ? 'bg-cargo-trust-light pl-[5px] text-cargo-trust before:absolute before:left-0 before:top-1 before:bottom-1 before:w-[3px] before:rounded-full before:bg-cargo-trust before:content-[""]'
            : 'text-cargo-mid hover:bg-cargo-navy-50 hover:text-cargo-deep'
        }`
      }
    >
      {({ isActive }) => (
        <>
          <item.icon className={`h-4 w-4 shrink-0 ${isActive ? 'text-cargo-trust' : 'text-cargo-light'}`} aria-hidden />
          <span>{item.label}</span>
        </>
      )}
    </NavLink>
  );
}

export function Layout() {
  const { pathname } = useLocation();
  const header = PAGE_HEADERS[pathname] ?? { title: 'CustomsClear', desc: '', breadcrumb: 'CustomsClear' };
  const { health } = useClientCapabilities();
  const showAssistantNav = useAssistantSurfaceVisible();
  const apiReady = health === 'loading' ? 'unknown' : health === 'down' ? 'down' : health === 'ok' ? 'ok' : 'degraded';
  const [drawerOpen, setDrawerOpen] = React.useState(false);

  React.useEffect(() => {
    setDrawerOpen(false);
  }, [pathname]);

  React.useEffect(() => {
    if (!drawerOpen) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => {
      document.body.style.overflow = prev;
    };
  }, [drawerOpen]);

  const filterGroups = NAV_GROUPS.map((g) => ({
    ...g,
    items: g.items.filter((item) => item.to !== '/assistant' || showAssistantNav),
  }));

  const mobileNav = MOBILE_NAV.filter((item) => item.to !== '/assistant' || showAssistantNav);

  const sidebarContent = (onNavigate?: () => void) => (
    <>
      <div className="border-b border-cargo-border px-4 py-4">
        <p className="text-base font-medium text-cargo-deep">CustomsClear</p>
        <p className="text-[11px] text-cargo-light">Профессиональная ВЭД-аналитика</p>
      </div>
      <nav className="flex-1 space-y-4 overflow-y-auto px-2 py-3">
        {filterGroups.map((group) => (
          <div key={group.label}>
            <p className="mb-1 px-2 text-[11px] font-medium uppercase tracking-[0.06em] text-cargo-light">{group.label}</p>
            <div className="space-y-0.5">
              {group.items.map((item) => (
                <SidebarLink key={item.to} item={item} onNavigate={onNavigate} />
              ))}
            </div>
          </div>
        ))}
      </nav>
    </>
  );

  return (
    <div className="flex min-h-screen bg-cargo-cloud text-cargo-deep">
      {/* Desktop sidebar */}
      <aside className="fixed inset-y-0 left-0 z-30 hidden w-[240px] flex-col border-r border-cargo-border bg-cargo-surface lg:flex">
        {sidebarContent()}
      </aside>

      {/* Mobile drawer */}
      {drawerOpen ? (
        <>
          <button
            type="button"
            className="fixed inset-0 z-40 bg-cargo-deep/40 lg:hidden"
            aria-label="Закрыть меню"
            onClick={() => setDrawerOpen(false)}
          />
          <aside className="fixed inset-y-0 left-0 z-50 flex w-[min(280px,88vw)] flex-col bg-cargo-surface shadow-xl lg:hidden">
            <div className="flex items-center justify-end border-b border-cargo-border px-2 py-2">
              <button
                type="button"
                className="inline-flex h-9 w-9 items-center justify-center rounded-md text-cargo-mid hover:bg-cargo-navy-50"
                onClick={() => setDrawerOpen(false)}
                aria-label="Закрыть"
              >
                <X className="h-5 w-5" />
              </button>
            </div>
            {sidebarContent(() => setDrawerOpen(false))}
          </aside>
        </>
      ) : null}

      <div className="flex min-w-0 flex-1 flex-col lg:pl-[240px]">
        {/* Topbar */}
        <header className="sticky top-0 z-20 flex h-14 shrink-0 items-center justify-between gap-3 border-b border-cargo-border bg-cargo-surface px-4 lg:px-6">
          <div className="flex min-w-0 items-center gap-2">
            <button
              type="button"
              className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-md border border-cargo-border text-cargo-mid hover:bg-cargo-navy-50 lg:hidden"
              onClick={() => setDrawerOpen(true)}
              aria-label="Открыть меню"
            >
              <Menu className="h-5 w-5" />
            </button>
            <div className="min-w-0 lg:hidden">
              <p className="truncate text-sm font-medium text-cargo-deep">CustomsClear</p>
            </div>
            <p className="hidden truncate text-[13px] text-cargo-mid lg:block">
              CustomsClear / <span className="text-cargo-deep">{header.breadcrumb || header.title}</span>
            </p>
          </div>
          <AuthBar variant="cargo" />
        </header>

        {apiReady === 'down' ? (
          <div className="border-b border-cargo-warning/30 bg-cargo-warning-light px-4 py-2 text-center text-xs text-cargo-warning">
            Сервис временно недоступен. Обновите страницу или повторите попытку позже.
          </div>
        ) : null}

        <main className="flex-1 px-4 py-6 pb-20 lg:px-6 lg:pb-6">
          <div className="mx-auto max-w-[1200px]">
            <div key={pathname} className="cc-tab-enter">
              <Outlet />
            </div>
          </div>
        </main>
      </div>

      {/* Mobile bottom nav */}
      <nav className="fixed inset-x-0 bottom-0 z-30 flex h-14 items-stretch border-t border-cargo-border bg-cargo-surface lg:hidden">
        {mobileNav.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.end}
            className={({ isActive }) =>
              `flex flex-1 flex-col items-center justify-center gap-0.5 text-[10px] font-medium ${
                isActive ? 'text-cargo-trust' : 'text-cargo-light'
              }`
            }
          >
            {({ isActive }) => (
              <>
                <item.icon className={`h-5 w-5 ${isActive ? 'text-cargo-trust' : 'text-cargo-light'}`} aria-hidden />
                <span>{item.label}</span>
              </>
            )}
          </NavLink>
        ))}
        <button
          type="button"
          className="flex flex-1 flex-col items-center justify-center gap-0.5 text-[10px] font-medium text-cargo-light"
          onClick={() => setDrawerOpen(true)}
        >
          <Menu className="h-5 w-5" aria-hidden />
          <span>Меню</span>
        </button>
      </nav>
    </div>
  );
}
