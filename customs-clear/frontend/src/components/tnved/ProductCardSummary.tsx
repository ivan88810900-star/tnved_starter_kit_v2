import React from 'react';
import { useNavigate } from 'react-router-dom';
import { ArrowUpRight, Bot, FileCheck2, ShieldAlert, ShieldCheck } from 'lucide-react';
import type { TnvedCommodityDetail, TnvedPreview } from '../../api/tnvedCatalog';
import { formatCode } from '../../api/tnvedCatalog';
import { useAssistantSurfaceVisible } from '../../context/ClientCapabilitiesContext';
import { requestAssistantWithPrefill } from '../../store/calculatorAssistantBridge';
import type { NormativeRequirementsBlockData } from '../../types/api.types';
import { formatDutyDisplay, formatPercentRate } from '../../utils/dutyRate';
import { formatTnvedCommodityName } from '../../utils/tnvedDisplayText';

export type ProductPreviewStatus = 'idle' | 'loading' | 'loaded' | 'error';

type Props = {
  detail: TnvedCommodityDetail;
  preview: TnvedPreview | null;
  previewStatus?: ProductPreviewStatus;
  normativeBlock: NormativeRequirementsBlockData | null;
  normativeLoading: boolean;
  normativeLoaded: boolean;
  normativeError?: string | null;
};

export const PERMIT_BADGES = new Set([
  'ДС', 'СС', 'СГР', 'РУ', 'ЛЗ',
  'ВС', 'ФСС', 'НФ',
  'Фито', 'Вет', 'Серт', 'Марк', 'ФСТЭК', 'Рад',
]);

export const BADGE_COLORS: Record<string, { bg: string; text: string }> = {
  ДС: { bg: 'bg-blue-50', text: 'text-blue-700' },
  СС: { bg: 'bg-blue-50', text: 'text-blue-700' },
  СГР: { bg: 'bg-purple-50', text: 'text-purple-700' },
  РУ: { bg: 'bg-purple-50', text: 'text-purple-700' },
  ЛЗ: { bg: 'bg-orange-50', text: 'text-orange-700' },
  Фито: { bg: 'bg-green-50', text: 'text-green-700' },
  Вет: { bg: 'bg-teal-50', text: 'text-teal-700' },
  Серт: { bg: 'bg-yellow-50', text: 'text-yellow-700' },
  Марк: { bg: 'bg-gray-50', text: 'text-gray-700' },
  ФСТЭК: { bg: 'bg-red-50', text: 'text-red-700' },
  Рад: { bg: 'bg-red-50', text: 'text-red-700' },
  ВС: { bg: 'bg-teal-50', text: 'text-teal-700' },
  ФСС: { bg: 'bg-green-50', text: 'text-green-700' },
  НФ: { bg: 'bg-red-50', text: 'text-red-700' },
};

export const MEASURE_TYPE_TO_BADGE: Record<string, string> = {
  sgr: 'СГР',
  phyto_control: 'Фито',
  vet_control: 'Вет',
  certificate: 'Серт',
  license: 'ЛЗ',
  marking: 'Марк',
  fsetc: 'ФСТЭК',
  fsb: 'НФ',
  radiation_control: 'Рад',
};

export const MEASURE_DESCRIPTIONS: Record<string, string> = {
  phyto_control: 'Фитосанитарный сертификат страны экспорта',
  vet_control: 'Ветеринарный сертификат',
  certificate: 'Карантинный сертификат / разрешение на ввоз',
  license: 'Лицензия на ввоз',
  marking: 'Маркировка (ЧЗ / ЕГАИС / Меркурий)',
  fsetc: 'Требования ФСТЭК в сфере экспортного контроля',
  fsb: 'Нотификация ФСБ',
  radiation_control: 'Радиационный контроль',
  sgr: 'Свидетельство государственной регистрации',
};

const NON_TARIFF_TAB_TYPES = new Set([
  'tr_ts',
  'phyto_control',
  'vet_control',
  'certificate',
  'license',
  'marking',
  'fsetc',
  'fsb',
  'sgr',
  'radiation_control',
  'other',
]);

export type NonTariffMeasureItem = NonNullable<TnvedCommodityDetail['non_tariff_measures']>[number];

export function badgeForMeasureType(measure: NonTariffMeasureItem): string | null {
  const permit = (measure as { permit_type?: string }).permit_type?.trim();
  if (permit && PERMIT_BADGES.has(permit)) {
    return permit;
  }
  return MEASURE_TYPE_TO_BADGE[measure.measure_type.trim().toLowerCase()] ?? null;
}

export function measureTypeLabel(measure: NonTariffMeasureItem): string {
  const t = measure.measure_type.trim().toLowerCase();
  return measure.type_label?.trim() || MEASURE_DESCRIPTIONS[t] || measure.measure_type;
}

function documentsSummary(
  preview: TnvedPreview | null,
  previewStatus: ProductPreviewStatus,
  normativeBlock: NormativeRequirementsBlockData | null,
  normativeLoading: boolean,
  normativeLoaded: boolean,
  normativeError?: string | null,
): { text: string; state: 'unknown' | 'required' | 'clear' } {
  const previewVerified = previewStatus === 'loaded' && preview?.non_tariff != null;
  const normativeVerified =
    normativeLoaded && !normativeLoading && !normativeError && normativeBlock != null;

  if (previewVerified && preview.non_tariff?.has_ban) {
    return { text: 'Запрет или ограничение', state: 'required' };
  }

  const requirementLabels = Array.from(
    new Set([
      ...(normativeVerified
        ? (normativeBlock.required_documents ?? [])
            .map((document) => String(document.permit_type ?? '').trim().toUpperCase())
            .filter(Boolean)
        : []),
      ...(previewVerified ? (preview.non_tariff?.measure_badges ?? []) : []),
    ]),
  );
  if (requirementLabels.length > 0) {
    return { text: requirementLabels.slice(0, 4).join(', '), state: 'required' };
  }

  if (!previewVerified || !normativeVerified) {
    const unavailable =
      previewStatus === 'error'
      || Boolean(normativeError)
      || (normativeLoaded && !normativeBlock);
    return {
      text: unavailable ? 'Нет данных' : 'Проверяем…',
      state: 'unknown',
    };
  }

  return { text: 'Не выявлены', state: 'clear' };
}

type NonTariffMeasureCardsProps = {
  measures: NonTariffMeasureItem[];
};

export function NonTariffMeasureCards({ measures }: NonTariffMeasureCardsProps) {
  const visible = measures.filter((m) => NON_TARIFF_TAB_TYPES.has(m.measure_type.trim().toLowerCase()));

  if (visible.length === 0) {
    return (
      <div className="rounded-xl border border-gray-200 bg-gray-50 px-4 py-3 text-sm text-gray-600">
        В карточке товара нет отдельных мер нетарифного регулирования. Требования
        к документам проверяются по нормативному блоку.
      </div>
    );
  }

  return (
    <div className="space-y-2">
      {visible.map((m) => {
        const badge = badgeForMeasureType(m);
        const colors = badge ? BADGE_COLORS[badge] : { bg: 'bg-gray-50', text: 'text-gray-700' };
        return (
          <div key={`${m.id}-${m.measure_type}-${m.commodity_code}`} className="mb-2 rounded-lg border border-cargo-border p-3">
            <div className="mb-1 flex items-center gap-2">
              {badge ? (
                <span className={`rounded px-2 py-0.5 text-xs font-bold ${colors.bg} ${colors.text}`}>
                  {badge}
                </span>
              ) : null}
              <span className="text-sm font-medium text-cargo-deep">{measureTypeLabel(m)}</span>
            </div>
            {m.document_required ? (
              <p className="text-xs text-cargo-mid">{m.document_required}</p>
            ) : null}
            {m.regulatory_act ? (
              <p className="text-xs text-cargo-light">{m.regulatory_act}</p>
            ) : null}
            {!m.document_required && !m.regulatory_act && m.description ? (
              <p className="text-xs text-cargo-mid">{m.description}</p>
            ) : null}
          </div>
        );
      })}
    </div>
  );
}

export const ProductCardSummary: React.FC<Props> = ({
  detail,
  preview,
  previewStatus = preview ? 'loaded' : 'idle',
  normativeBlock,
  normativeLoading,
  normativeLoaded,
  normativeError,
}) => {
  const navigate = useNavigate();
  const assistantVisible = useAssistantSurfaceVisible();
  const name = formatTnvedCommodityName((detail.name ?? detail.description ?? '').trim());
  const dutyText = formatDutyDisplay(preview?.payments?.duty || detail.import_duty);
  const vatRates = preview?.payments?.vat_rates ?? [];
  const vatText =
    previewStatus === 'loaded'
      ? vatRates.length > 0
        ? vatRates.map((rate) => formatPercentRate(rate)).join(' / ')
        : 'Нет данных'
      : previewStatus === 'error'
        ? 'Нет данных'
        : 'Проверяем…';
  const vatTextClass =
    previewStatus === 'loaded' && vatRates.length > 0
      ? 'text-emerald-700'
      : 'text-slate-500';
  const exciseText = (preview?.payments?.excise ?? '').trim();
  const unit = (detail.unit ?? '').trim();
  const docs = documentsSummary(
    preview,
    previewStatus,
    normativeBlock,
    normativeLoading,
    normativeLoaded,
    normativeError,
  );

  const codeDigits = detail.code.replace(/\D/g, '');
  const heading4 = codeDigits.slice(0, 4);
  const crumbs: string[] = [];
  if (detail.section?.roman_number) crumbs.push(`Раздел ${detail.section.roman_number}`);
  if (detail.chapter?.code) crumbs.push(`Гл.${detail.chapter.code}`);
  if (heading4) crumbs.push(heading4);

  const previewVerified = previewStatus === 'loaded' && preview != null;
  const hasBan = previewVerified && Boolean(preview?.non_tariff?.has_ban);

  const askAssistant = () => {
    const description = name ? ` (${name})` : '';
    requestAssistantWithPrefill(
      `Проверьте товар по коду ТН ВЭД ${codeDigits}${description}. Объясните платежи, обязательные документы и риски.`,
    );
  };

  return (
    <section
      className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm"
      aria-label="Сводка по товару"
    >
      <div className="border-b border-slate-100 px-4 py-3 sm:px-5">
        <div className="flex flex-col gap-1 sm:flex-row sm:flex-wrap sm:items-baseline sm:gap-3">
          <span className="font-mono text-xl font-bold tracking-tight text-blue-700 sm:text-2xl">
            {formatCode(detail.code)}
          </span>
          {name ? (
            <span className="text-sm font-medium leading-snug text-slate-800 sm:text-base">{name}</span>
          ) : (
            <span className="text-sm italic text-slate-400">Описание отсутствует</span>
          )}
        </div>
        <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-slate-500">
          {crumbs.length > 0 ? <span>{crumbs.join(' › ')}</span> : null}
          {unit ? <span className="text-slate-400">ед. изм.: {unit}</span> : null}
        </div>
      </div>

      <div
        className={`grid grid-cols-1 divide-y divide-slate-100 sm:divide-x sm:divide-y-0 ${
          exciseText ? 'sm:grid-cols-4' : 'sm:grid-cols-3'
        }`}
      >
        <div className="px-4 py-3 text-center sm:px-3">
          <p className="text-[10px] font-semibold uppercase tracking-wide text-slate-500">Пошлина</p>
          <p className="mt-0.5 font-mono text-lg font-bold text-blue-800">{dutyText}</p>
        </div>
        <div className="px-4 py-3 text-center sm:px-3">
          <p className="text-[10px] font-semibold uppercase tracking-wide text-slate-500">НДС</p>
          <p className={`mt-0.5 font-mono text-lg font-bold ${vatTextClass}`}>{vatText}</p>
        </div>
        {exciseText ? (
          <div className="px-4 py-3 text-center sm:px-3">
            <p className="text-[10px] font-semibold uppercase tracking-wide text-slate-500">Акциз</p>
            <p className="mt-0.5 font-mono text-lg font-bold text-amber-700">{exciseText}</p>
          </div>
        ) : null}
        <div className="px-4 py-3 text-center sm:px-3">
          <p className="text-[10px] font-semibold uppercase tracking-wide text-slate-500">Документы</p>
          <p className="mt-0.5 text-sm font-semibold text-slate-800">{docs.text}</p>
        </div>
      </div>

      <div className="flex flex-wrap gap-2 border-t border-slate-100 px-4 py-3 sm:px-5">
        <button
          type="button"
          onClick={() => navigate(`/calculator?code=${encodeURIComponent(detail.code.replace(/\D/g, '').slice(0, 10))}`)}
          className="inline-flex w-full items-center justify-center gap-2 rounded-lg bg-cargo-trust px-4 py-2.5 text-sm font-semibold text-white transition hover:bg-cargo-trust/90 sm:w-auto"
        >
          Рассчитать платежи по этому коду
          <ArrowUpRight className="h-4 w-4" aria-hidden />
        </button>
        {assistantVisible ? (
          <button
            type="button"
            onClick={askAssistant}
            className="inline-flex w-full items-center justify-center gap-2 rounded-lg border border-indigo-200 bg-indigo-50 px-4 py-2.5 text-sm font-semibold text-indigo-800 transition hover:border-indigo-300 hover:bg-indigo-100 sm:w-auto"
          >
            <Bot className="h-4 w-4" aria-hidden />
            Спросить помощника
          </button>
        ) : null}
      </div>

      {hasBan ? (
        <div className="flex items-center gap-2 border-t border-red-200 bg-red-50 px-4 py-2.5 text-sm font-medium text-red-800 sm:px-5">
          <ShieldAlert className="h-4 w-4 shrink-0" aria-hidden />
          Имеются запреты или ограничения на ввоз — проверьте условия.
        </div>
      ) : docs.state === 'required' ? (
        <div className="flex items-start gap-2 border-t border-amber-200 bg-amber-50 px-4 py-2.5 text-sm text-amber-800 sm:px-5">
          <FileCheck2 className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
          <span>Требуются разрешительные документы: {docs.text}.</span>
        </div>
      ) : docs.state === 'clear' ? (
        <div className="flex items-center gap-2 border-t border-emerald-100 bg-emerald-50 px-4 py-2.5 text-sm text-emerald-700 sm:px-5">
          <ShieldCheck className="h-4 w-4 shrink-0" aria-hidden />
          Особых разрешительных документов не выявлено.
        </div>
      ) : (
        <div className="flex items-start gap-2 border-t border-slate-200 bg-slate-50 px-4 py-2.5 text-sm text-slate-700 sm:px-5">
          <FileCheck2 className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
          <span>
            {previewStatus === 'error'
              ? 'Не удалось подтвердить наличие или отсутствие разрешительных документов.'
              : 'Проверяем разрешительные документы и ограничения.'}
          </span>
        </div>
      )}
    </section>
  );
};
