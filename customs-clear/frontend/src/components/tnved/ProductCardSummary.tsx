import React from 'react';
import { useNavigate } from 'react-router-dom';
import { ArrowUpRight, FileCheck2, ShieldAlert, ShieldCheck } from 'lucide-react';
import type { TnvedCommodityDetail, TnvedPreview } from '../../api/tnvedCatalog';
import { formatCode } from '../../api/tnvedCatalog';
import { formatDutyDisplay, formatPercentRate } from '../../utils/dutyRate';
import { formatTnvedCommodityName } from '../../utils/tnvedDisplayText';

type Props = {
  detail: TnvedCommodityDetail;
  preview: TnvedPreview | null;
};

export const PERMIT_BADGES = new Set([
  'ДС', 'СС', 'СГР', 'РУ', 'ЛЗ',
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
};

export const MEASURE_TYPE_TO_BADGE: Record<string, string> = {
  sgr: 'СГР',
  phyto_control: 'Фито',
  vet_control: 'Вет',
  certificate: 'Серт',
  license: 'ЛЗ',
  marking: 'Марк',
  fsetc: 'ФСТЭК',
  radiation_control: 'Рад',
};

export const MEASURE_DESCRIPTIONS: Record<string, string> = {
  phyto_control: 'Фитосанитарный сертификат страны экспорта',
  vet_control: 'Ветеринарный сертификат',
  certificate: 'Карантинный сертификат / разрешение на ввоз',
  license: 'Лицензия на ввоз',
  marking: 'Маркировка (ЧЗ / ЕГАИС / Меркурий)',
  fsetc: 'Нотификация ФСТЭК',
  radiation_control: 'Радиационный контроль',
  sgr: 'Свидетельство государственной регистрации',
};

const NON_TARIFF_TAB_TYPES = new Set([
  'phyto_control',
  'vet_control',
  'certificate',
  'license',
  'marking',
  'fsetc',
  'sgr',
  'radiation_control',
]);

export type NonTariffMeasureItem = NonNullable<TnvedCommodityDetail['non_tariff_measures']>[number];

export function badgeForMeasureType(measureType: string): string | null {
  return MEASURE_TYPE_TO_BADGE[measureType.trim().toLowerCase()] ?? null;
}

export function measureTypeLabel(measure: NonTariffMeasureItem): string {
  const t = measure.measure_type.trim().toLowerCase();
  return measure.type_label?.trim() || MEASURE_DESCRIPTIONS[t] || measure.measure_type;
}

function documentsSummary(preview: TnvedPreview | null): { text: string; hasRequirements: boolean } {
  const badges = preview?.non_tariff?.measure_badges ?? [];
  if (preview?.non_tariff?.has_ban) {
    return { text: 'Запрет или ограничение', hasRequirements: true };
  }
  const permits = badges.filter((b) => PERMIT_BADGES.has(b));
  if (permits.length > 0) {
    return { text: permits.join(', '), hasRequirements: true };
  }
  if (badges.length > 0) {
    return { text: badges.slice(0, 4).join(', '), hasRequirements: true };
  }
  return { text: 'Не требуются', hasRequirements: false };
}

type NonTariffMeasureCardsProps = {
  measures: NonTariffMeasureItem[];
};

export function NonTariffMeasureCards({ measures }: NonTariffMeasureCardsProps) {
  const visible = measures.filter((m) => NON_TARIFF_TAB_TYPES.has(m.measure_type.trim().toLowerCase()));

  if (visible.length === 0) {
    return (
      <div className="rounded-xl border border-gray-200 bg-gray-50 px-4 py-3 text-sm text-gray-600">
        Документы не требуются.
      </div>
    );
  }

  return (
    <div className="space-y-2">
      {visible.map((m) => {
        const badge = badgeForMeasureType(m.measure_type);
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

export const ProductCardSummary: React.FC<Props> = ({ detail, preview }) => {
  const navigate = useNavigate();
  const name = formatTnvedCommodityName((detail.name ?? detail.description ?? '').trim());
  const dutyText = formatDutyDisplay(preview?.payments?.duty || detail.import_duty);
  const vatText =
    (preview?.payments?.vat_rates ?? []).length > 0
      ? preview!.payments!.vat_rates!.map((r) => formatPercentRate(r)).join(' / ')
      : '22%';
  const exciseText = (preview?.payments?.excise ?? '').trim();
  const unit = (detail.unit ?? '').trim();
  const docs = documentsSummary(preview);

  const codeDigits = detail.code.replace(/\D/g, '');
  const heading4 = codeDigits.slice(0, 4);
  const crumbs: string[] = [];
  if (detail.section?.roman_number) crumbs.push(`Раздел ${detail.section.roman_number}`);
  if (detail.chapter?.code) crumbs.push(`Гл.${detail.chapter.code}`);
  if (heading4) crumbs.push(heading4);

  const hasBan = Boolean(preview?.non_tariff?.has_ban);
  const measureBadges = preview?.non_tariff?.measure_badges ?? [];
  const showRequirementHint = !hasBan && measureBadges.length > 0;

  return (
    <section className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
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
          <p className="mt-0.5 font-mono text-lg font-bold text-emerald-700">{vatText}</p>
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

      <div className="border-t border-slate-100 px-4 py-3 sm:px-5">
        <button
          type="button"
          onClick={() => navigate(`/calculator?code=${encodeURIComponent(detail.code.replace(/\D/g, '').slice(0, 10))}`)}
          className="inline-flex w-full items-center justify-center gap-2 rounded-lg bg-cargo-trust px-4 py-2.5 text-sm font-semibold text-white transition hover:bg-cargo-trust/90 sm:w-auto"
        >
          Рассчитать платежи по этому коду
          <ArrowUpRight className="h-4 w-4" aria-hidden />
        </button>
      </div>

      {hasBan ? (
        <div className="flex items-center gap-2 border-t border-red-200 bg-red-50 px-4 py-2.5 text-sm font-medium text-red-800 sm:px-5">
          <ShieldAlert className="h-4 w-4 shrink-0" aria-hidden />
          Имеются запреты или ограничения на ввоз — проверьте условия.
        </div>
      ) : showRequirementHint ? (
        <div className="flex items-start gap-2 border-t border-amber-200 bg-amber-50 px-4 py-2.5 text-sm text-amber-800 sm:px-5">
          <FileCheck2 className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
          <span>Требуются разрешительные документы{measureBadges.length > 0 ? `: ${measureBadges.join(', ')}` : ''}.</span>
        </div>
      ) : (
        <div className="flex items-center gap-2 border-t border-emerald-100 bg-emerald-50 px-4 py-2.5 text-sm text-emerald-700 sm:px-5">
          <ShieldCheck className="h-4 w-4 shrink-0" aria-hidden />
          Особых разрешительных документов не выявлено.
        </div>
      )}
    </section>
  );
};
