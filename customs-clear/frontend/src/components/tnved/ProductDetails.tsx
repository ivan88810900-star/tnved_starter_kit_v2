import React from 'react';
import axios from 'axios';
import { useNavigate } from 'react-router-dom';
import { api } from '../../api/client';
import type { TnvedCommodityDetail, TnvedImportReference, TnvedPreview } from '../../api/tnvedCatalog';
import { fetchCommodityByCode, fetchTnvedImportReference, fetchTnvedPreview, isFullTnvedCode } from '../../api/tnvedCatalog';
import { formatLinks, splitReadableParagraphs } from '../../utils/formatLinks';
import { getUserFacingApiError } from '../../api/error';
import { CC_NORMATIVE_PREFILL_KEY } from '../../constants/homeNav';
import { NormativeRequirementsBlock } from '../nonTariff/NormativeRequirementsBlock';
import { SmartRiskCheckBlock } from '../nonTariff/SmartRiskCheckBlock';
import { normativeBlockFromNonTariff } from '../nonTariff/normativeBlockHelpers';
import { PreliminaryDecisionsBlock } from './PreliminaryDecisionsBlock';
import { ClassificationRulingsBlock } from './ClassificationRulingsBlock';
import { ProductCardSummary, NonTariffMeasureCards } from './ProductCardSummary';
import type { ProductPreviewStatus } from './ProductCardSummary';
import { PermitDocumentsBlock } from './PermitDocumentsBlock';
import { SmartPaymentsBlock } from '../payments/SmartPaymentsBlock';
import type { NormativeRequirementsBlockData } from '../../types/api.types';
import { ArrowUpRight, ShieldCheck } from 'lucide-react';

type Props = {
  selectedCode: string | null;
};

type DetailTab = 'payments' | 'nonTariff' | 'risks' | 'decisions' | 'normative';

const DETAIL_TABS: ReadonlyArray<readonly [DetailTab, string]> = [
  ['payments', 'Платежи'],
  ['nonTariff', 'Нетарифка'],
  ['risks', 'Риски'],
  ['decisions', 'Решения'],
  ['normative', 'Документы'],
];

export const ProductDetails: React.FC<Props> = ({ selectedCode }) => {
  const navigate = useNavigate();
  const [detail, setDetail] = React.useState<TnvedCommodityDetail | null>(null);
  const [loading, setLoading] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [reference, setReference] = React.useState<TnvedImportReference | null>(null);
  const [referenceLoading, setReferenceLoading] = React.useState(false);
  const [preview, setPreview] = React.useState<TnvedPreview | null>(null);
  const [previewStatus, setPreviewStatus] = React.useState<ProductPreviewStatus>('idle');
  const [activeTab, setActiveTab] = React.useState<DetailTab>('payments');
  const [normativeBlock, setNormativeBlock] = React.useState<NormativeRequirementsBlockData | null>(null);
  const [normativeLoading, setNormativeLoading] = React.useState(false);
  const [normativeLoaded, setNormativeLoaded] = React.useState(false);
  const [normativeError, setNormativeError] = React.useState<string | null>(null);
  const tabsId = React.useId().replace(/:/g, '');

  React.useEffect(() => {
    if (!selectedCode || !isFullTnvedCode(selectedCode)) {
      setDetail(null); setError(null); setLoading(false); return;
    }
    let cancelled = false;
    setLoading(true); setError(null);
    fetchCommodityByCode(selectedCode)
      .then((d) => { if (!cancelled) setDetail(d); })
      .catch((e: unknown) => {
        if (!cancelled) {
          const msg =
            axios.isAxiosError(e) && e.response?.data && typeof e.response.data === 'object' && 'detail' in e.response.data
              ? String((e.response.data as { detail?: unknown }).detail)
              : 'Не удалось загрузить позицию';
          setError(msg); setDetail(null);
        }
      })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [selectedCode]);

  React.useEffect(() => {
    if (!detail?.code) {
      setReference(null);
      setReferenceLoading(false);
      return;
    }
    let cancelled = false;
    setReferenceLoading(true);
    fetchTnvedImportReference(detail.code)
      .then((ref) => {
        if (!cancelled) setReference(ref);
      })
      .catch(() => {
        if (!cancelled) setReference(null);
      })
      .finally(() => {
        if (!cancelled) setReferenceLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [detail?.code]);

  React.useEffect(() => {
    if (!detail?.code) {
      setPreview(null);
      setPreviewStatus('idle');
      return;
    }
    let cancelled = false;
    setPreview(null);
    setPreviewStatus('loading');
    fetchTnvedPreview(detail.code)
      .then((p) => {
        if (!cancelled) {
          setPreview(p);
          setPreviewStatus('loaded');
        }
      })
      .catch(() => {
        if (!cancelled) {
          setPreview(null);
          setPreviewStatus('error');
        }
      });
    return () => { cancelled = true; };
  }, [detail?.code]);

  React.useEffect(() => {
    setActiveTab('payments');
    setNormativeBlock(null);
    setNormativeLoaded(false);
    setNormativeError(null);
    setNormativeLoading(false);
  }, [selectedCode]);

  React.useEffect(() => {
    if (!detail?.code) return;
    let cancelled = false;
    setNormativeLoading(true);
    setNormativeLoaded(false);
    setNormativeError(null);
    api
      .post<{ status: string; items: Array<{ normative_block?: NormativeRequirementsBlockData }> }>(
        '/non_tariff/normative-block',
        {
          items: [
            {
              hs_code: detail.code,
              description: (detail.name ?? detail.description ?? '').trim(),
            },
          ],
        },
      )
      .then(({ data }) => {
        if (cancelled) return;
        const item = data.items?.[0];
        setNormativeBlock(normativeBlockFromNonTariff(item) ?? item?.normative_block ?? null);
      })
      .catch((e: unknown) => {
        if (cancelled) return;
        setNormativeBlock(null);
        const status = axios.isAxiosError(e) ? e.response?.status : undefined;
        if (status === 401) {
          setNormativeError('Войдите в систему, чтобы загрузить нормативный блок, или откройте полную проверку на странице «Нетарифка».');
        } else {
          setNormativeError(getUserFacingApiError(e, 'Не удалось загрузить нормативные требования.'));
        }
      })
      .finally(() => {
        if (!cancelled) {
          setNormativeLoading(false);
          setNormativeLoaded(true);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [detail?.code, detail?.description, detail?.name]);

  // Пусто — приглашение
  if (!selectedCode) {
    return (
      <div className="flex min-h-[300px] flex-col items-center justify-center rounded-xl border border-dashed border-gray-300 bg-white px-8 py-16 text-center">
        <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.2" className="mx-auto mb-4 text-gray-300" aria-hidden>
          <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" /><polyline points="14 2 14 8 20 8" />
          <line x1="16" y1="13" x2="8" y2="13" /><line x1="16" y1="17" x2="8" y2="17" /><polyline points="10 9 9 9 8 9" />
        </svg>
        <p className="text-base font-medium text-gray-500">Выберите код товара в дереве слева</p>
        <p className="mt-1 text-sm text-gray-400">Кликните на любой 10-значный код</p>
      </div>
    );
  }

  if (loading) {
    return (
      <div className="flex min-h-[200px] items-center justify-center bg-white text-sm text-gray-500">
        Загрузка позиции…
      </div>
    );
  }

  if (error) {
    return (
      <div className="rounded-lg border border-red-200 bg-red-50 px-5 py-4 text-sm text-red-800">
        {error}
      </div>
    );
  }

  if (!detail) return null;

  const nonTariffMeasures = detail.non_tariff_measures ?? [];
  const intellectualProperties = detail.intellectual_properties ?? [];

  const renderLinkedParagraphs = (
    text: string,
    keyPrefix: string,
    emptyLabel = 'Описание отсутствует',
  ): React.ReactNode => {
    const paragraphs = splitReadableParagraphs(text);
    if (paragraphs.length === 0) {
      return <p className="text-sm italic text-gray-400">{emptyLabel}</p>;
    }
    return (
      <div className="space-y-1.5">
        {paragraphs.map((line, idx) => (
          <p key={`${keyPrefix}-${idx}`} className="whitespace-pre-wrap break-words text-sm leading-relaxed text-gray-800">
            {formatLinks(line, `${keyPrefix}-${idx}`)}
          </p>
        ))}
      </div>
    );
  };

  const paymentSections = (reference?.sections ?? []).filter((s) => /пошлин|ндс|акциз/i.test(s.title));
  const preliminaryBlock = detail.preliminary_decisions ?? null;

  const openNormativeCheck = () => {
    try {
      sessionStorage.setItem(
        CC_NORMATIVE_PREFILL_KEY,
        JSON.stringify({
          hs_code: detail.code,
          description: (detail.name ?? detail.description ?? '').trim(),
        }),
      );
    } catch {
      /* ignore */
    }
    navigate('/non-tariff');
  };

  const selectAndFocusTab = (tab: DetailTab) => {
    setActiveTab(tab);
    const target = document.getElementById(`${tabsId}-tab-${tab}`);
    if (target instanceof HTMLButtonElement) target.focus();
  };

  const handleTabKeyDown = (
    event: React.KeyboardEvent<HTMLButtonElement>,
    currentTab: DetailTab,
  ) => {
    const currentIndex = DETAIL_TABS.findIndex(([tab]) => tab === currentTab);
    let targetIndex: number | null = null;
    if (event.key === 'ArrowRight') targetIndex = (currentIndex + 1) % DETAIL_TABS.length;
    if (event.key === 'ArrowLeft') targetIndex = (currentIndex - 1 + DETAIL_TABS.length) % DETAIL_TABS.length;
    if (event.key === 'Home') targetIndex = 0;
    if (event.key === 'End') targetIndex = DETAIL_TABS.length - 1;
    if (targetIndex == null) return;
    event.preventDefault();
    selectAndFocusTab(DETAIL_TABS[targetIndex][0]);
  };

  return (
    <div className="space-y-6 bg-white text-gray-900">
      {/* Шапка-резюме карточки товара */}
      <ProductCardSummary
        detail={detail}
        preview={preview}
        previewStatus={previewStatus}
        normativeBlock={normativeBlock}
        normativeLoading={normativeLoading}
        normativeLoaded={normativeLoaded}
        normativeError={normativeError}
      />

      <PermitDocumentsBlock
        hsCode={detail.code}
        productName={(detail.name ?? detail.description ?? '').trim()}
        normativeBlock={normativeBlock}
        normativeLoading={normativeLoading}
        normativeLoaded={normativeLoaded}
        normativeError={normativeError}
      />

      {intellectualProperties.length > 0 ? (
        <div className="flex items-center gap-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm font-medium text-amber-800">
          <ShieldCheck className="h-4 w-4 shrink-0" aria-hidden />
          ТРОИС: есть совпадения по защищённым брендам — см. вкладку «Нетарифное регулирование».
        </div>
      ) : null}
      <div
        className="-mx-1 flex gap-1 overflow-x-auto border-b border-cargo-border px-1 pb-0 sm:mx-0 sm:px-0"
        role="tablist"
        aria-label="Разделы карточки товара"
      >
        {DETAIL_TABS.map(([tab, label]) => (
          <button
            key={tab}
            type="button"
            className={`shrink-0 border-b-2 px-3 py-2.5 text-sm font-medium transition sm:shrink ${
              activeTab === tab
                ? 'border-cargo-trust text-cargo-trust'
                : 'border-transparent text-cargo-mid hover:text-cargo-deep'
            }`}
            onClick={() => setActiveTab(tab)}
            onKeyDown={(event) => handleTabKeyDown(event, tab)}
            role="tab"
            id={`${tabsId}-tab-${tab}`}
            aria-selected={activeTab === tab}
            aria-controls={`${tabsId}-panel-${tab}`}
            tabIndex={activeTab === tab ? 0 : -1}
          >
            {label}
            {tab === 'decisions' && (preliminaryBlock?.total_count ?? 0) > 0 ? (
              <span className="ml-1.5 rounded-full bg-cargo-trust-light px-1.5 py-0.5 text-[10px] font-semibold text-cargo-trust">
                {preliminaryBlock?.total_count}
              </span>
            ) : null}
          </button>
        ))}
      </div>

      {activeTab === 'payments' ? (
        <div
          className="space-y-4"
          role="tabpanel"
          id={`${tabsId}-panel-payments`}
          aria-labelledby={`${tabsId}-tab-payments`}
        >
          <SmartPaymentsBlock
            hsCode={detail.code}
            description={(detail.name ?? detail.description ?? '').trim()}
          />

          <details className="rounded-xl border border-gray-200 bg-gray-50 px-4 py-3">
            <summary className="cursor-pointer text-xs font-bold uppercase tracking-wide text-gray-600">
              Дополнительные нормативные справки
            </summary>
            <div className="mt-3 space-y-3">
              {referenceLoading ? (
                <p className="text-sm text-gray-500">Загрузка…</p>
              ) : paymentSections.length > 0 ? (
                paymentSections.map((s, idx) => (
                  <article key={`${s.title}-${idx}`} className="rounded-lg border border-gray-200 bg-white px-3 py-2">
                    <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-gray-600">{s.title}</p>
                    <div className="space-y-1.5">
                      {(s.items ?? []).map((line, lineIdx) => (
                        <p key={`${s.title}-${lineIdx}`} className="whitespace-pre-wrap break-words text-sm leading-snug text-gray-700">
                          {formatLinks(line, `pay-${s.title}-${lineIdx}`)}
                        </p>
                      ))}
                    </div>
                  </article>
                ))
              ) : (
                <p className="text-sm italic text-gray-400">Нет дополнительных правовых текстов для этого кода.</p>
              )}
            </div>
          </details>
        </div>
      ) : null}

      {activeTab === 'nonTariff' ? (
        <div
          className="space-y-4"
          role="tabpanel"
          id={`${tabsId}-panel-nonTariff`}
          aria-labelledby={`${tabsId}-tab-nonTariff`}
        >
          <section>
            <h3 className="mb-3 text-xs font-bold uppercase tracking-wide text-gray-600 border-b border-gray-200 pb-2">
              Меры нетарифного регулирования
            </h3>
            <NonTariffMeasureCards measures={nonTariffMeasures} />
          </section>

          <section>
            <h3 className="mb-3 border-b border-gray-200 pb-2 text-xs font-bold uppercase tracking-wide text-gray-600">
              Торговые меры
            </h3>
            {previewStatus !== 'loaded' ? (
              <div className="rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-700">
                {previewStatus === 'error'
                  ? 'Не удалось подтвердить наличие или отсутствие специальных торговых мер.'
                  : 'Проверяем специальные торговые меры…'}
              </div>
            ) : !preview?.special_duties ? (
              <div className="rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-700">
                Нет подтверждённых данных о специальных торговых мерах.
              </div>
            ) : preview.special_duties.has_measures ? (
              <div className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
                <p>
                  ⚠️{' '}
                  {preview.special_duties.warning ||
                    `Для данного кода действуют специальные торговые меры (страны: ${preview.special_duties.countries.join(', ')}).`}
                </p>
              </div>
            ) : (
              <div className="rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800">
                Специальные торговые меры (антидемпинг, компенсационные пошлины) для этого кода не выявлены в справочнике.
              </div>
            )}
          </section>

          <section>
            <h3 className="mb-3 text-xs font-bold uppercase tracking-wide text-gray-600 border-b border-gray-200 pb-2">
              Защита бренда (ТРОИС)
            </h3>
            {intellectualProperties.length === 0 ? (
              <div className="rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800">
                Совпадений с ТРОИС по этому коду не найдено.
              </div>
            ) : (
              <div className="space-y-3">
                <div className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
                  ⚠️ Внимание! Данный код содержит бренды под защитой ТРОИС. Проверьте наличие вашего бренда в списке:{' '}
                  {Array.from(new Set(intellectualProperties.map((x) => x.brand_name).filter(Boolean))).join(', ')}.
                </div>
                <div className="space-y-2">
                  {intellectualProperties.map((ip) => (
                    <article
                      key={`${ip.id}-${ip.brand_name}-${ip.hs_code_prefix}`}
                      className="rounded-xl border border-amber-200 bg-amber-50/50 px-4 py-3"
                    >
                      <p className="text-base font-semibold text-gray-900">{ip.brand_name}</p>
                      <p className="mt-1 text-sm text-gray-700">
                        Префикс ТН ВЭД: <span className="font-mono">{ip.hs_code_prefix}</span>
                      </p>
                      {ip.reg_number && <p className="mt-1 text-sm text-gray-700">Рег. номер: {ip.reg_number}</p>}
                      {ip.right_holder && <p className="mt-1 text-xs text-gray-500">Правообладатель: {ip.right_holder}</p>}
                    </article>
                  ))}
                </div>
              </div>
            )}
          </section>
        </div>
      ) : null}

      {activeTab === 'decisions' ? (
        <section
          className="space-y-6"
          role="tabpanel"
          id={`${tabsId}-panel-decisions`}
          aria-labelledby={`${tabsId}-tab-decisions`}
        >
          <div>
            <h3 className="mb-3 text-xs font-bold uppercase tracking-wide text-gray-600 border-b border-gray-200 pb-2">
              Предварительные решения
            </h3>
            <PreliminaryDecisionsBlock block={preliminaryBlock} loading={loading} />
          </div>
          {detail?.code ? (
            <div>
              <h3 className="mb-3 text-xs font-bold uppercase tracking-wide text-gray-600 border-b border-gray-200 pb-2">
                Решения по классификации
              </h3>
              <ClassificationRulingsBlock hsCode={detail.code} />
            </div>
          ) : null}
        </section>
      ) : null}

      {activeTab === 'risks' ? (
        <div
          role="tabpanel"
          id={`${tabsId}-panel-risks`}
          aria-labelledby={`${tabsId}-tab-risks`}
        >
          <SmartRiskCheckBlock
            hsCode={detail.code}
            description={(detail.name ?? detail.description ?? '').trim()}
          />
        </div>
      ) : null}

      {activeTab === 'normative' ? (
        <section
          className="space-y-4"
          role="tabpanel"
          id={`${tabsId}-panel-normative`}
          aria-labelledby={`${tabsId}-tab-normative`}
        >
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-gray-200 pb-3">
            <h3 className="text-xs font-bold uppercase tracking-wide text-gray-600">
              Нормативные требования по коду
            </h3>
            <button
              type="button"
              onClick={openNormativeCheck}
              className="inline-flex items-center gap-1.5 rounded-lg border border-indigo-200 bg-indigo-50 px-3 py-2 text-sm font-medium text-indigo-800 hover:bg-indigo-100"
            >
              Полная проверка на «Нетарифке»
              <ArrowUpRight className="h-4 w-4" aria-hidden />
            </button>
          </div>
          {normativeLoading || !normativeLoaded ? (
            <p className="text-sm text-gray-500">Загрузка нормативного блока…</p>
          ) : normativeError ? (
            <div className="space-y-3 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
              <p>{normativeError}</p>
              <button
                type="button"
                onClick={openNormativeCheck}
                className="inline-flex items-center gap-1.5 rounded-lg border border-amber-300 bg-white px-3 py-2 text-sm font-medium text-amber-900 hover:bg-amber-100"
              >
                Открыть проверку с этим кодом
                <ArrowUpRight className="h-4 w-4" aria-hidden />
              </button>
            </div>
          ) : (
            <NormativeRequirementsBlock block={normativeBlock} title="Нормативные требования" />
          )}
          {!normativeLoading && !normativeError && !normativeBlock ? (
            <p className="text-sm italic text-gray-500">
              Нормативный блок пуст для этого кода. Запустите полную проверку на странице «Нетарифка».
            </p>
          ) : null}
        </section>
      ) : null}
    </div>
  );
};
