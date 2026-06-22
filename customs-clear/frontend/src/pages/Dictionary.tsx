import React from 'react';
import { X } from 'lucide-react';
import { ProductDetails } from '../components/tnved/ProductDetails';
import { TnvedTree } from '../components/tnved/TnvedTree';
import { CC_HOME_TNVED_QUERY_KEY } from '../constants/homeNav';

export const Dictionary: React.FC = () => {
  const [selectedCode, setSelectedCode] = React.useState<string | null>(null);
  const [detailsOpen, setDetailsOpen] = React.useState(false);
  const [initialSearch, setInitialSearch] = React.useState<string | undefined>(undefined);

  React.useEffect(() => {
    try {
      const raw = sessionStorage.getItem(CC_HOME_TNVED_QUERY_KEY);
      if (raw?.trim()) {
        setInitialSearch(raw.trim());
        sessionStorage.removeItem(CC_HOME_TNVED_QUERY_KEY);
      }
    } catch {
      /* ignore */
    }
  }, []);

  const handleSelectCode = React.useCallback((code: string) => {
    setSelectedCode(code);
    setDetailsOpen(true);
  }, []);

  React.useEffect(() => {
    if (!detailsOpen) return;
    const onEsc = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setDetailsOpen(false);
    };
    window.addEventListener('keydown', onEsc);
    return () => window.removeEventListener('keydown', onEsc);
  }, [detailsOpen]);

  return (
    <>
      <div className="min-h-[min(640px,calc(100dvh-8rem))] overflow-hidden rounded-2xl border border-slate-100 bg-white text-gray-900 shadow-lg shadow-slate-200/70 sm:min-h-[min(860px,calc(100vh-10rem))]">
        <div className="shrink-0 border-b border-slate-100 bg-slate-50 px-4 py-3 sm:px-6 sm:py-4">
          <p className="text-[11px] font-semibold uppercase tracking-widest text-gray-500">Справочник ТН ВЭД</p>
          <p className="mt-0.5 text-xs text-gray-500">
            Выберите 10-значный код для карточки товара: платежи, нетарифные меры, предварительные решения и ссылка на нормативный блок.
          </p>
        </div>
        <div className="min-h-0 h-[calc(100dvh-11rem)] overflow-hidden px-3 py-3 sm:h-[calc(100vh-13.5rem)] sm:px-5 sm:py-4">
          <TnvedTree
            selectedCode={selectedCode}
            onSelectCode={handleSelectCode}
            initialSearchQuery={initialSearch}
          />
        </div>
      </div>

      {detailsOpen && selectedCode ? (
        <div
          className="fixed inset-0 z-50 flex items-end justify-center bg-slate-900/45 p-0 backdrop-blur-[2px] sm:items-center sm:p-4"
          onClick={() => setDetailsOpen(false)}
        >
          <div
            className="flex h-[100dvh] max-h-[100dvh] w-full max-w-5xl flex-col overflow-hidden rounded-none border border-slate-200 bg-white shadow-2xl shadow-slate-900/20 sm:h-[90vh] sm:min-h-[480px] sm:rounded-2xl"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between border-b border-slate-200 bg-slate-50 px-4 py-3 sm:px-5">
              <div>
                <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-slate-500">Справка по товару</p>
                <p className="mt-0.5 font-mono text-sm text-slate-700">{selectedCode}</p>
              </div>
              <button
                type="button"
                className="inline-flex h-8 w-8 items-center justify-center rounded-lg border border-slate-200 bg-white text-slate-500 hover:bg-slate-100"
                onClick={() => setDetailsOpen(false)}
                aria-label="Закрыть"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
            <div className="min-h-0 flex-1 overflow-y-auto p-3 sm:p-5">
              <ProductDetails selectedCode={selectedCode} />
            </div>
          </div>
        </div>
      ) : null}
    </>
  );
};
