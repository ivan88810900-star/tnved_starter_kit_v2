import React from 'react';
import { X } from 'lucide-react';
import { ProductDetails } from '../components/tnved/ProductDetails';
import { TnvedTree } from '../components/tnved/TnvedTree';
import { PageHeader } from '../components/PageHeader';
import { CC_HOME_TNVED_QUERY_KEY, CC_TNVED_SELECT_CODE_KEY } from '../constants/homeNav';

export const Dictionary: React.FC = () => {
  const [selectedCode, setSelectedCode] = React.useState<string | null>(null);
  const [detailsOpen, setDetailsOpen] = React.useState(false);
  const [initialSearch, setInitialSearch] = React.useState<string | undefined>(undefined);

  React.useEffect(() => {
    try {
      const codeRaw = sessionStorage.getItem(CC_TNVED_SELECT_CODE_KEY);
      if (codeRaw?.trim()) {
        const code = codeRaw.replace(/\D/g, '').slice(0, 10);
        sessionStorage.removeItem(CC_TNVED_SELECT_CODE_KEY);
        if (code.length === 10) {
          setSelectedCode(code);
          setDetailsOpen(true);
          return;
        }
      }
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
      <PageHeader
        title="Справочник ТН ВЭД"
        subtitle="Поиск по коду или описанию, дерево классификации и карточка товара"
      />

      <div className="min-h-[min(560px,calc(100dvh-12rem))] overflow-hidden rounded-lg border border-cargo-border bg-cargo-surface sm:min-h-[min(720px,calc(100vh-14rem))]">
        <div className="min-h-0 h-[calc(100dvh-14rem)] overflow-hidden p-3 sm:h-[calc(100vh-16rem)] sm:p-4">
          <TnvedTree
            selectedCode={selectedCode}
            onSelectCode={handleSelectCode}
            initialSearchQuery={initialSearch}
          />
        </div>
      </div>

      {detailsOpen && selectedCode ? (
        <div
          className="fixed inset-0 z-50 flex items-end justify-center bg-cargo-deep/40 p-0 sm:items-center sm:p-4"
          onClick={() => setDetailsOpen(false)}
        >
          <div
            className="flex h-[100dvh] max-h-[100dvh] w-full max-w-5xl flex-col overflow-hidden rounded-none border border-cargo-border bg-cargo-surface shadow-xl sm:h-[90vh] sm:min-h-[480px] sm:rounded-lg"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between border-b border-cargo-border px-4 py-4 sm:px-5">
              <div>
                <p className="text-[11px] font-medium uppercase tracking-[0.06em] text-cargo-light">Карточка товара</p>
                <p className="mt-1 font-mono text-2xl font-medium text-cargo-trust">{selectedCode}</p>
              </div>
              <button
                type="button"
                className="inline-flex h-9 w-9 items-center justify-center rounded-md border border-cargo-border text-cargo-mid hover:bg-cargo-navy-50"
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
