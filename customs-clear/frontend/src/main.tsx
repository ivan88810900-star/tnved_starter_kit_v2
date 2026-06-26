import React from 'react';
import ReactDOM from 'react-dom/client';
import { BrowserRouter, Navigate, Route, Routes, useNavigate } from 'react-router-dom';
import './styles.css';
import { Layout } from './components/Layout';
import { SystemHealth } from './pages/admin/SystemHealth';
import { BulkNormativeImport } from './pages/admin/BulkNormativeImport';
import { InvoicePage } from './pages/Invoice';
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
import { ClientCapabilitiesProvider } from './context/ClientCapabilitiesContext';

const root = ReactDOM.createRoot(document.getElementById('root') as HTMLElement);

function readAdminHash(): boolean {
  if (typeof window === 'undefined') return false;
  const h = (window.location.hash || '').replace(/^#\/?/, '').toLowerCase();
  return h === 'admin/system' || h === 'admin';
}

function clearUrlHash(): void {
  if (typeof window === 'undefined' || !window.location.hash) return;
  window.history.replaceState(null, '', window.location.pathname + window.location.search);
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
      <Route path="/" element={<Layout />}>
        <Route index element={<HomeDashboard />} />
        <Route path="docs" element={<DocumentCheck />} />
        <Route path="classifier" element={<Classifier />} />
        <Route path="tnved" element={<Dictionary />} />
        <Route path="trois" element={<Trois />} />
        <Route path="permits" element={<PermitPicker />} />
        <Route path="calculator" element={<Calculator />} />
        <Route path="invoice" element={<InvoicePage />} />
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
