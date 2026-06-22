import React from 'react';
import ReactDOM from 'react-dom/client';
import {
  BrowserRouter,
  Navigate,
  NavLink,
  Outlet,
  Route,
  Routes,
  useLocation,
  useNavigate,
} from 'react-router-dom';
import {
  BadgeCheck,
  BookOpenText,
  Bot,
  Calculator as CalculatorIcon,
  FileSearch,
  Files,
  FileText,
  Menu,
  ShieldCheck,
  Stamp,
  X,
} from 'lucide-react';
import './styles.css';
import { SystemHealth } from './pages/admin/SystemHealth';
import { BulkNormativeImport } from './pages/admin/BulkNormativeImport';
import { HomeDashboard } from './pages/HomeDashboard';
import { DocumentCheck } from './pages/DocumentCheck';
import { Classifier } from './pages/Classifier';
import { Trois } from './pages/Trois';
import { Calculator } from './pages/Calculator';
import { NonTariff } from './pages/NonTariff';
import { Assistant } from './pages/Assistant';
import {
  drainAssistantNavigationJob,
  subscribeAssistantNavigation,
  type AssistantNavigationJob,
} from './store/calculatorAssistantBridge';
import { PermitPicker } from './pages/PermitPicker';
import { Dictionary } from './pages/Dictionary';
import { AuthBar } from './components/AuthBar';
import { ClientCapabilitiesProvider, useAssistantSurfaceVisible, useClientCapabilities } from './context/ClientCapabilitiesContext';

const root = ReactDOM.createRoot(document.getElementById('root') as HTMLElement);

const PAGE_HEADERS: Record<string, { title: string; desc: string }> = {
  '/': { title: 'Главная', desc: 'Поиск по ТН ВЭД и быстрые действия' },
  '/docs': { title: 'Документы', desc: 'Инвойс и упаковочные листы' },
  '/classifier': { title: 'Классификатор', desc: 'Подбор кода ТН ВЭД' },
  '/tnved': { title: 'Справочник ТН ВЭД', desc: 'Наименования, примечания, ссылки ЕЭК' },
  '/trois': { title: 'ТРОИС', desc: 'Товарные знаки' },
  '/permits': { title: 'СС и ДС', desc: 'Разрешительные документы' },
  '/calculator': { title: 'Платежи', desc: 'Пошлина, НДС, база' },
  '/non-tariff': { title: 'Нетарифка', desc: 'ТР ТС, меры' },
  '/assistant': { title: 'Ассистент', desc: 'Сводный разбор: ТН ВЭД, платежи, нетарифные меры' },
  '/admin/system': { title: 'Состояние системы', desc: 'Краткая сводка БД и ИИ; детали — в блоке «Расширенная диагностика»' },
  '/admin/import': { title: 'Массовая загрузка базы', desc: 'ИИ-импорт PDF/DOCX/HTML в нормативные таблицы' },
};

const NAV_ITEMS: Array<{ to: string; label: string; icon: React.ComponentType<{ className?: string }>; end?: boolean }> = [
  { to: '/', label: 'Главная', icon: FileSearch, end: true },
  { to: '/docs', label: 'Документы', icon: FileText },
  { to: '/classifier', label: 'Классификатор', icon: Stamp },
  { to: '/tnved', label: 'Справочник ТН ВЭД', icon: BookOpenText },
  { to: '/trois', label: 'ТРОИС', icon: BadgeCheck },
  { to: '/permits', label: 'СС и ДС', icon: Files },
  { to: '/calculator', label: 'Платежи', icon: CalculatorIcon },
  { to: '/non-tariff', label: 'Нетарифка', icon: ShieldCheck },
  { to: '/assistant', label: 'Ассистент', icon: Bot },
];

function readAdminHash(): boolean {
  if (typeof window === 'undefined') return false;
  const h = (window.location.hash || '').replace(/^#\/?/, '').toLowerCase();
  return h === 'admin/system' || h === 'admin';
}

function clearUrlHash(): void {
  if (typeof window === 'undefined' || !window.location.hash) return;
  window.history.replaceState(null, '', window.location.pathname + window.location.search);
}

function AppShell() {
  const { pathname } = useLocation();
  const header = PAGE_HEADERS[pathname] ?? { title: 'CustomsClear', desc: '' };
  const { health } = useClientCapabilities();
  const showAssistantNav = useAssistantSurfaceVisible();
  const apiReady = health === 'loading' ? 'unknown' : health === 'down' ? 'down' : health === 'ok' ? 'ok' : 'degraded';
  const [navOpen, setNavOpen] = React.useState(false);

  React.useEffect(() => {
    setNavOpen(false);
  }, [pathname]);

  React.useEffect(() => {
    if (!navOpen) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => {
      document.body.style.overflow = prev;
    };
  }, [navOpen]);

  const navLinkClass = ({ isActive }: { isActive: boolean }) =>
    `flex w-full items-center gap-2.5 rounded-lg px-3 py-2.5 text-left transition-all duration-200 ${
      isActive
        ? 'border border-indigo-500 bg-indigo-600 text-white shadow-md shadow-indigo-700/35'
        : 'border border-slate-700 bg-slate-800/90 text-slate-100 hover:-translate-y-0.5 hover:bg-slate-700 hover:shadow-md'
    }`;

  const navItems = NAV_ITEMS.filter((item) => item.to !== '/assistant' || showAssistantNav);

  return (
    <div className="cc-bg min-h-screen text-slate-900">
      <header className="sticky top-0 z-20 border-b border-slate-200/90 bg-white/95 backdrop-blur">
        <div className="mx-auto flex max-w-7xl items-center justify-between gap-3 px-3 py-3 sm:px-4 sm:py-3.5">
          <div className="flex min-w-0 items-center gap-2 sm:gap-3">
            <button
              type="button"
              className="inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-lg border border-slate-200 bg-white text-slate-700 shadow-sm hover:bg-slate-50 lg:hidden"
              onClick={() => setNavOpen((v) => !v)}
              aria-expanded={navOpen}
              aria-controls="cc-main-nav"
              aria-label={navOpen ? 'Закрыть меню' : 'Открыть меню'}
            >
              {navOpen ? <X className="h-5 w-5" aria-hidden /> : <Menu className="h-5 w-5" aria-hidden />}
            </button>
            <div className="cc-logo-ring">
              <div className="cc-logo-inner">CC</div>
            </div>
            <div className="min-w-0">
              <h1 className="truncate text-base font-semibold tracking-tight text-slate-900">CustomsClear</h1>
              <p className="hidden text-[11px] font-medium tracking-wide text-slate-500 sm:block">Профессиональная ВЭД-аналитика</p>
            </div>
          </div>
          <div className="flex shrink-0 items-center gap-2 sm:gap-3">
            <AuthBar />
          </div>
        </div>
      </header>

      {apiReady === 'down' ? (
        <div className="border-b border-amber-200 bg-amber-50 px-3 py-2.5 text-center text-[12px] text-amber-800 sm:px-4">
          Сервис временно недоступен. Обновите страницу или повторите попытку позже.
        </div>
      ) : null}

      {navOpen ? (
        <button
          type="button"
          className="fixed inset-0 z-30 bg-slate-900/45 backdrop-blur-[1px] lg:hidden"
          aria-label="Закрыть меню"
          onClick={() => setNavOpen(false)}
        />
      ) : null}

      <main className="mx-auto grid max-w-[1500px] grid-cols-1 gap-4 px-3 py-4 sm:px-5 sm:py-6 lg:grid-cols-[280px_minmax(0,1fr)] lg:gap-6">
        <aside
          id="cc-main-nav"
          className={`fixed inset-y-0 left-0 z-40 h-full w-[min(300px,88vw)] overflow-y-auto rounded-none border-r border-slate-800 bg-gradient-to-b from-slate-950 to-slate-900 p-3 shadow-2xl shadow-slate-900/40 transition-transform duration-200 ease-out lg:static lg:z-auto lg:h-fit lg:w-auto lg:overflow-visible lg:rounded-2xl lg:border lg:shadow-xl lg:shadow-slate-900/30 ${
            navOpen ? 'translate-x-0' : '-translate-x-full lg:translate-x-0'
          }`}
        >
          <div className="mb-2 flex items-center justify-between px-2 pt-1 lg:block">
            <div className="text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-500">Меню</div>
            <button
              type="button"
              className="inline-flex h-8 w-8 items-center justify-center rounded-lg text-slate-400 hover:bg-slate-800 hover:text-white lg:hidden"
              onClick={() => setNavOpen(false)}
              aria-label="Закрыть меню"
            >
              <X className="h-4 w-4" aria-hidden />
            </button>
          </div>
          <nav className="space-y-1">
            {navItems.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.end}
                title={PAGE_HEADERS[item.to]?.desc}
                onClick={() => {
                  clearUrlHash();
                  setNavOpen(false);
                }}
                className={navLinkClass}
              >
                <span className="inline-flex h-8 w-8 items-center justify-center rounded-md bg-white/15">
                  <item.icon className="h-4 w-4" />
                </span>
                <span className="text-[13px] font-semibold tracking-tight">{item.label}</span>
              </NavLink>
            ))}
          </nav>
        </aside>

        <section className="min-w-0 space-y-3 rounded-2xl border border-slate-200/80 bg-slate-50/70 p-2 shadow-[inset_0_1px_0_rgba(255,255,255,0.8)] sm:p-3">
          <div className="cc-card px-4 py-3 sm:px-5 sm:py-4">
            <h2 className="text-[15px] font-semibold tracking-tight text-slate-900">{header.title}</h2>
            <p className="mt-0.5 text-[12px] leading-relaxed text-slate-500">{header.desc}</p>
          </div>

          <div className="rounded-2xl border border-slate-200 bg-slate-50 p-3 shadow-lg shadow-slate-200/60 sm:p-4 md:p-5">
            <div key={pathname} className="cc-tab-enter">
              <Outlet />
            </div>
          </div>
        </section>
      </main>
    </div>
  );
}

function AppRoutes() {
  const navigate = useNavigate();
  const [assistantOpenJob, setAssistantOpenJob] = React.useState<AssistantNavigationJob | null>(null);
  const clearAssistantOpenJob = React.useCallback(() => setAssistantOpenJob(null), []);

  React.useLayoutEffect(() => {
    if (typeof window === 'undefined') return;
    const h = (window.location.hash || '').replace(/^#\/?/, '').toLowerCase();
    if (h === 'admin/import') {
      clearUrlHash();
      navigate('/admin/import', { replace: true });
      return;
    }
    if (readAdminHash()) {
      clearUrlHash();
      navigate('/admin/system', { replace: true });
    }
  }, [navigate]);

  React.useEffect(() => {
    return subscribeAssistantNavigation(() => {
      const job = drainAssistantNavigationJob();
      if (!job) return;
      setAssistantOpenJob(job);
      navigate('/assistant');
    });
  }, [navigate]);

  return (
    <Routes>
      <Route path="/" element={<AppShell />}>
        <Route index element={<HomeDashboard />} />
        <Route path="docs" element={<DocumentCheck />} />
        <Route path="classifier" element={<Classifier />} />
        <Route path="tnved" element={<Dictionary />} />
        <Route path="trois" element={<Trois />} />
        <Route path="permits" element={<PermitPicker />} />
        <Route path="calculator" element={<Calculator />} />
        <Route path="non-tariff" element={<NonTariff />} />
        <Route
          path="assistant"
          element={
            <Assistant
              assistantOpenJob={assistantOpenJob}
              onAssistantOpenJobConsumed={clearAssistantOpenJob}
            />
          }
        />
        <Route path="admin/system" element={<SystemHealth />} />
        <Route path="admin/import" element={<BulkNormativeImport />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

const App: React.FC = () => (
  <BrowserRouter>
    <ClientCapabilitiesProvider>
      <AppRoutes />
    </ClientCapabilitiesProvider>
  </BrowserRouter>
);

root.render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
