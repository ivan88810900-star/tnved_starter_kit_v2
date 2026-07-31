import React from 'react';
import {
  BrowserRouter,
  Navigate,
  Route,
  Routes,
  useLocation,
  useNavigate,
} from 'react-router-dom';
import { Layout } from './components/Layout';
import { RouteLoadBoundary } from './components/routing/RouteLoadBoundary';
import {
  drainAssistantNavigationJob,
  subscribeAssistantNavigation,
  type AssistantNavigationJob,
} from './store/calculatorAssistantBridge';
import { ClientCapabilitiesProvider } from './context/ClientCapabilitiesContext';

const HomeDashboard = React.lazy(() =>
  import('./pages/HomeDashboard').then((module) => ({ default: module.HomeDashboard })),
);
const DocumentCheck = React.lazy(() =>
  import('./pages/DocumentCheck').then((module) => ({ default: module.DocumentCheck })),
);
const Classifier = React.lazy(() =>
  import('./pages/Classifier').then((module) => ({ default: module.Classifier })),
);
const Dictionary = React.lazy(() =>
  import('./pages/Dictionary').then((module) => ({ default: module.Dictionary })),
);
const Trois = React.lazy(() =>
  import('./pages/Trois').then((module) => ({ default: module.Trois })),
);
const PermitPicker = React.lazy(() =>
  import('./pages/PermitPicker').then((module) => ({ default: module.PermitPicker })),
);
const Calculator = React.lazy(() =>
  import('./pages/Calculator').then((module) => ({ default: module.Calculator })),
);
const InvoicePage = React.lazy(() =>
  import('./pages/Invoice').then((module) => ({ default: module.InvoicePage })),
);
const NonTariff = React.lazy(() =>
  import('./pages/NonTariff').then((module) => ({ default: module.NonTariff })),
);
const Assistant = React.lazy(() =>
  import('./pages/Assistant').then((module) => ({ default: module.Assistant })),
);
const SystemHealth = React.lazy(() =>
  import('./pages/admin/SystemHealth').then((module) => ({ default: module.SystemHealth })),
);
const BulkNormativeImport = React.lazy(() =>
  import('./pages/admin/BulkNormativeImport').then((module) => ({
    default: module.BulkNormativeImport,
  })),
);

function readAdminHash(): boolean {
  if (typeof window === 'undefined') return false;
  const h = (window.location.hash || '').replace(/^#\/?/, '').toLowerCase();
  return h === 'admin/system' || h === 'admin';
}

function clearUrlHash(): void {
  if (typeof window === 'undefined' || !window.location.hash) return;
  window.history.replaceState(null, '', window.location.pathname + window.location.search);
}

export function AppRoutes() {
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const [assistantOpenJob, setAssistantOpenJob] = React.useState<AssistantNavigationJob | null>(null);
  const clearAssistantOpenJob = React.useCallback(() => setAssistantOpenJob(null), []);
  const routeElement = (children: React.ReactNode) => (
    <RouteLoadBoundary key={pathname}>{children}</RouteLoadBoundary>
  );

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
      <Route path="/" element={<Layout />}>
        <Route index element={routeElement(<HomeDashboard />)} />
        <Route path="docs" element={routeElement(<DocumentCheck />)} />
        <Route path="classifier" element={routeElement(<Classifier />)} />
        <Route path="tnved" element={routeElement(<Dictionary />)} />
        <Route path="trois" element={routeElement(<Trois />)} />
        <Route path="permits" element={routeElement(<PermitPicker />)} />
        <Route path="calculator" element={routeElement(<Calculator />)} />
        <Route path="invoice" element={routeElement(<InvoicePage />)} />
        <Route path="non-tariff" element={routeElement(<NonTariff />)} />
        <Route
          path="assistant"
          element={routeElement(
            <Assistant
              assistantOpenJob={assistantOpenJob}
              onAssistantOpenJobConsumed={clearAssistantOpenJob}
            />,
          )}
        />
        <Route path="admin/system" element={routeElement(<SystemHealth />)} />
        <Route path="admin/import" element={routeElement(<BulkNormativeImport />)} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

export const App: React.FC = () => (
  <BrowserRouter>
    <ClientCapabilitiesProvider>
      <AppRoutes />
    </ClientCapabilitiesProvider>
  </BrowserRouter>
);
