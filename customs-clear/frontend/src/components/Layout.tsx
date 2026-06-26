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
import { TariffLogo } from './TariffLogo';
import { useAssistantSurfaceVisible, useClientCapabilities } from '../context/ClientCapabilitiesContext';

export const APP_NAME = 'Tariff';

export const PAGE_HEADERS: Record<string, { title: string; desc: string; breadcrumb?: string }> = {
  '/': { title: 'Главная', desc: 'Поиск по ТН ВЭД и быстрые действия', breadcrumb: 'Главная' },
  '/docs': { title: 'Документы', desc: 'Инвойс и упаковочные листы', breadcrumb: 'Документы' },
  '/classifier': { title: 'Классификатор', desc: 'Подбор кода по описанию, фото или характеристикам', breadcrumb: 'Классификатор' },
  '/tnved': { title: 'Справочник ТН ВЭД', desc: 'Наименования, примечания, ссылки ЕЭК', breadcrumb: 'Справочник' },
  '/trois': { title: 'ТРОИС', desc: 'Товарные знаки', breadcrumb: 'ТРОИС' },
  '/permits': { title: 'СС и ДС', desc: 'Разрешительные документы', breadcrumb: 'СС и ДС' },
  '/invoice': { title: 'Инвойс', desc: 'Загрузка и классификация пакинг-листа', breadcrumb: 'Инвойс' },
  '/calculator': { title: 'Платежи', desc: 'Расчёт пошлины, НДС и сборов', breadcrumb: 'Калькулятор' },
  '/non-tariff': { title: 'Нетарифка', desc: 'Проверка нетарифных мер и разрешений', breadcrumb: 'Нетарифка' },
  '/assistant': { title: 'Ассистент', desc: 'Подбор кода, платежи, меры и проверки в одном диалоге', breadcrumb: 'Ассистент' },
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
        `group mx-2 flex items-center gap-2.5 rounded-md py-2 text-[13px] transition-all duration-150 ${
          isActive
            ? 'border-l-2 border-[var(--sidebar-accent)] bg-[var(--sidebar-active)] pl-[10px] pr-3 font-medium text-[var(--sidebar-text-active)]'
            : 'px-3 font-normal text-[var(--sidebar-text)] hover:bg-[var(--sidebar-hover)] hover:text-[#CBD8EA]'
        }`
      }
    >
      {({ isActive }) => (
        <>
          <item.icon
            className={`h-4 w-4 shrink-0 transition-colors ${
              isActive
                ? 'text-[var(--sidebar-accent)]'
                : 'text-[var(--sidebar-text)] group-hover:text-[#CBD8EA]'
            }`}
            aria-hidden
          />
          <span>{item.label}</span>
        </>
      )}
    </NavLink>
  );
}

export function Layout() {
  const { pathname } = useLocation();
  const header = PAGE_HEADERS[pathname] ?? { title: APP_NAME, desc: '', breadcrumb: APP_NAME };

  React.useEffect(() => {
    const page = header.breadcrumb || header.title;
    document.title =
      page && page !== APP_NAME ? `${APP_NAME} — ${page}` : `${APP_NAME} — Customs Intelligence`;
  }, [header.breadcrumb, header.title]);
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
      <TariffLogo variant="dark" onNavigate={onNavigate} />
      <div className="mx-4 mb-2 h-px bg-[var(--sidebar-border)]" aria-hidden />
      <nav className="flex-1 space-y-1 overflow-y-auto pb-3">
        {filterGroups.map((group) => (
          <div key={group.label}>
            <p className="px-4 pb-1.5 pt-4 text-[10px] font-bold uppercase tracking-widest text-[var(--sidebar-label)]">
              {group.label}
            </p>
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
      <aside className="fixed inset-y-0 left-0 z-30 hidden w-[240px] flex-col border-r border-[var(--sidebar-border)] bg-[var(--sidebar-bg)] lg:flex">
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
          <aside className="fixed inset-y-0 left-0 z-50 flex w-[min(280px,88vw)] flex-col border-r border-[var(--sidebar-border)] bg-[var(--sidebar-bg)] shadow-xl lg:hidden">
            <div className="flex items-center justify-end border-b border-[var(--sidebar-border)] px-2 py-2">
              <button
                type="button"
                className="inline-flex h-9 w-9 items-center justify-center rounded-md text-[var(--sidebar-text)] hover:bg-[var(--sidebar-hover)]"
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

      <div className="flex min-h-0 min-w-0 flex-1 flex-col lg:pl-[240px]">
        {/* Topbar */}
        <header className="sticky top-0 z-20 flex h-14 shrink-0 items-center justify-between gap-3 border-b border-[var(--cargo-border)] bg-white px-6 shadow-[0_1px_0_var(--cargo-border)]">
          <div className="flex min-w-0 items-center gap-2">
            <button
              type="button"
              className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-md border border-[var(--cargo-border)] text-[var(--cargo-mid)] hover:bg-[var(--cargo-navy-50)] lg:hidden"
              onClick={() => setDrawerOpen(true)}
              aria-label="Открыть меню"
            >
              <Menu className="h-5 w-5" />
            </button>
            <div className="min-w-0 lg:hidden">
              <TariffLogo iconOnly />
            </div>
            <nav className="hidden text-[13px] lg:block">
              <span className="text-[var(--cargo-light)]">{APP_NAME}</span>
              <span className="mx-1.5 text-[var(--cargo-light)]">/</span>
              <span className="font-medium text-[var(--cargo-deep)]">{header.breadcrumb || header.title}</span>
            </nav>
          </div>
          <AuthBar variant="cargo" />
        </header>

        {apiReady === 'down' ? (
          <div className="border-b border-cargo-warning/30 bg-cargo-warning-light px-4 py-2 text-center text-xs text-cargo-warning">
            Сервис временно недоступен. Обновите страницу или повторите попытку позже.
          </div>
        ) : null}

        <main className="flex min-h-0 flex-1 flex-col bg-[var(--cargo-cloud)] p-6 pb-20 lg:pb-6">
          <div className="mx-auto flex min-h-0 w-full max-w-[1200px] flex-1 flex-col">
            <div key={pathname} className="cc-tab-enter flex min-h-0 flex-1 flex-col">
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
