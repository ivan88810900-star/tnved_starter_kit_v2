import React from 'react';
import {
  ArrowLeft,
  CheckCircle2,
  ChevronRight,
  GitBranch,
  ShieldCheck,
  Sparkles,
  X,
} from 'lucide-react';
import {
  fetchGuidedTnvedNavigation,
  formatCode,
  type GuidedTnvedNode,
  type GuidedTnvedResponse,
} from '../../api/tnvedCatalog';
import {
  formatTnvedCommodityName,
  TNVED_COMMODITY_NAME_CLASS,
} from '../../utils/tnvedDisplayText';

type Props = {
  heading: string;
  onClose: () => void;
  onSelectCode: (code: string) => void;
};

function nodeLabel(node: GuidedTnvedNode): string {
  if (node.role === 'semantic_choice') return 'Смысловая группа';
  if (node.is_leaf) return 'Реальный код';
  return 'Уточнение';
}

function ChoiceIcon({ node }: { node: GuidedTnvedNode }) {
  if (node.role === 'semantic_choice') {
    return <Sparkles className="h-4 w-4" aria-hidden="true" />;
  }
  if (node.is_leaf) {
    return <CheckCircle2 className="h-4 w-4" aria-hidden="true" />;
  }
  return <GitBranch className="h-4 w-4" aria-hidden="true" />;
}

export const GuidedTnvedNavigator: React.FC<Props> = ({
  heading,
  onClose,
  onSelectCode,
}) => {
  const [payload, setPayload] = React.useState<GuidedTnvedResponse | null>(null);
  const [trail, setTrail] = React.useState<GuidedTnvedNode[]>([]);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    setPayload(null);
    setTrail([]);
    void fetchGuidedTnvedNavigation(heading)
      .then((result) => {
        if (!cancelled) setPayload(result);
      })
      .catch(() => {
        if (!cancelled) {
          setError('Не удалось построить умный маршрут. Обычное дерево продолжает работать.');
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [heading]);

  React.useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [onClose]);

  const current = trail[trail.length - 1] ?? null;
  const choices = current?.children ?? payload?.choices ?? [];

  const choose = React.useCallback(
    (node: GuidedTnvedNode) => {
      const code = (node.code ?? '').replace(/\D/g, '');
      if (node.is_leaf && code.length === 10) {
        onSelectCode(code);
        return;
      }
      if (node.children.length > 0) {
        setTrail((previous) => [...previous, node]);
        return;
      }
      if (code.length === 10) onSelectCode(code);
    },
    [onSelectCode],
  );

  const coverage =
    payload?.integrity.canonical_coverage != null
      ? Math.round(payload.integrity.canonical_coverage * 100)
      : null;

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="border-b border-cargo-border px-4 py-4 sm:px-6">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="flex items-center gap-2 text-cargo-trust">
              <Sparkles className="h-5 w-5 shrink-0" aria-hidden="true" />
              <p className="text-[11px] font-semibold uppercase tracking-[0.08em]">
                Умная структура ТН ВЭД
              </p>
            </div>
            <div className="mt-2 flex flex-wrap items-baseline gap-x-3 gap-y-1">
              <span className="font-mono text-2xl font-semibold text-cargo-trust">
                {formatCode(heading)}
              </span>
              {payload?.heading.title ? (
                <span
                  className={`min-w-0 text-sm text-cargo-deep ${TNVED_COMMODITY_NAME_CLASS}`}
                >
                  {formatTnvedCommodityName(payload.heading.title)}
                </span>
              ) : null}
            </div>
          </div>
          <button
            type="button"
            className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-md border border-cargo-border text-cargo-mid hover:bg-cargo-navy-50"
            onClick={onClose}
            aria-label="Закрыть умный маршрут"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-4 py-4 sm:px-6">
        {loading ? (
          <div className="flex min-h-48 items-center justify-center">
            <p className="text-sm text-cargo-mid">Проверяем структуру и строим маршрут…</p>
          </div>
        ) : error ? (
          <div className="rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">
            {error}
          </div>
        ) : payload?.status !== 'OK' ? (
          <div className="space-y-3 rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm text-amber-950">
            <p className="font-semibold">Умный маршрут временно недоступен</p>
            <p>{payload?.message ?? 'Используйте обычное дерево этой товарной позиции.'}</p>
            <button
              type="button"
              onClick={onClose}
              className="rounded-md border border-amber-300 bg-white px-3 py-2 text-xs font-semibold hover:bg-amber-100"
            >
              Вернуться к обычному дереву
            </button>
          </div>
        ) : (
          <>
            <div className="rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-3 text-xs text-emerald-950">
              <div className="flex items-start gap-2">
                <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-emerald-700" aria-hidden="true" />
                <div>
                  <p className="font-semibold">
                    Структура проверена по Canonical
                    {coverage != null ? ` · покрытие ${coverage}%` : ''}
                  </p>
                  <p className="mt-1 leading-relaxed">
                    Смысловые группы помогают выбрать путь, но не являются кодами.
                    Конечный выбор всегда ведёт к реальному коду ТН ВЭД.
                  </p>
                </div>
              </div>
            </div>

            <div className="mt-4">
              {trail.length > 0 ? (
                <button
                  type="button"
                  onClick={() => setTrail((previous) => previous.slice(0, -1))}
                  className="mb-3 inline-flex items-center gap-1.5 rounded-md border border-cargo-border px-3 py-2 text-xs font-medium text-cargo-mid hover:bg-cargo-navy-50"
                >
                  <ArrowLeft className="h-3.5 w-3.5" aria-hidden="true" />
                  Назад
                </button>
              ) : null}

              <p className="text-sm font-semibold text-cargo-deep">
                {current?.title || payload.prompt}
              </p>
              {current ? (
                <p className="mt-1 text-xs text-cargo-light">
                  Выберите следующее уточнение
                </p>
              ) : null}

              <div className="mt-3 grid gap-2">
                {choices.map((node) => (
                  <button
                    key={node.id}
                    type="button"
                    onClick={() => choose(node)}
                    className="group flex w-full items-start gap-3 rounded-lg border border-cargo-border bg-white p-3 text-left transition hover:border-cargo-trust hover:bg-cargo-navy-50"
                  >
                    <span
                      className={`mt-0.5 inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-full ${
                        node.is_leaf
                          ? 'bg-emerald-100 text-emerald-700'
                          : 'bg-indigo-50 text-indigo-700'
                      }`}
                    >
                      <ChoiceIcon node={node} />
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="flex flex-wrap items-center gap-2">
                        {node.code ? (
                          <span className="font-mono text-sm font-semibold text-cargo-trust">
                            {formatCode(node.code)}
                          </span>
                        ) : null}
                        <span className="rounded bg-cargo-cloud px-1.5 py-0.5 text-[10px] font-medium text-cargo-mid">
                          {nodeLabel(node)}
                        </span>
                      </span>
                      <span
                        className={`mt-1 block text-[13px] leading-snug text-cargo-deep ${TNVED_COMMODITY_NAME_CLASS}`}
                      >
                        {formatTnvedCommodityName(node.title)}
                      </span>
                      {!node.is_leaf ? (
                        <span className="mt-1 block text-[11px] text-cargo-light">
                          Конечных кодов: {node.result_count}
                        </span>
                      ) : null}
                    </span>
                    <ChevronRight className="mt-2 h-4 w-4 shrink-0 text-cargo-light transition group-hover:text-cargo-trust" />
                  </button>
                ))}
              </div>

              {choices.length === 0 ? (
                <p className="mt-4 rounded-lg border border-cargo-border bg-cargo-cloud p-3 text-sm text-cargo-mid">
                  Для этого уточнения нет дочерних вариантов. Вернитесь на шаг назад.
                </p>
              ) : null}
            </div>
          </>
        )}
      </div>
    </div>
  );
};

export default GuidedTnvedNavigator;
