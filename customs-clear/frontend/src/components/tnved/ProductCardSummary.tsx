import React from 'react';
import { FileCheck2, ShieldAlert, ShieldCheck } from 'lucide-react';
import type { TnvedCommodityDetail, TnvedPreview } from '../../api/tnvedCatalog';
import { formatCode } from '../../api/tnvedCatalog';
import { formatTnvedCommodityName } from '../../utils/tnvedDisplayText';

type Props = {
  detail: TnvedCommodityDetail;
  preview: TnvedPreview | null;
};

function vatLabel(preview: TnvedPreview | null): { text: string; preferential: boolean } {
  const rates = preview?.payments?.vat_rates ?? [];
  if (rates.length === 0) {
    return { text: '22%', preferential: false };
  }
  return {
    text: rates.map((r) => `${r}%`).join(' / '),
    preferential: rates.includes(10) || rates.includes(0),
  };
}

function documentsLabel(detail: TnvedCommodityDetail, preview: TnvedPreview | null): string {
  const badges = preview?.non_tariff?.measure_badges ?? [];
  if (badges.length > 0) {
    return badges.slice(0, 4).join(', ');
  }
  const measures = (detail.non_tariff_measures ?? []).length;
  if (measures > 0) {
    return `${measures} мер`;
  }
  return 'Не требуются';
}

/**
 * ProductCardSummary — компактная «шапка» карточки товара: код + наименование,
 * хлебные крошки (Раздел › Группа › Позиция) и блок Пошлина / НДС / Документы,
 * с предупреждением при запрете/ограничении или требовании разрешительных документов.
 * Размещается вверху карточки, перед табами.
 */
export const ProductCardSummary: React.FC<Props> = ({ detail, preview }) => {
  const name = formatTnvedCommodityName((detail.name ?? detail.description ?? '').trim());
  const dutyText = (detail.import_duty ?? '').trim() || 'Нет данных';
  const vat = vatLabel(preview);
  const documents = documentsLabel(detail, preview);
  const unit = (detail.unit ?? '').trim();

  const codeDigits = detail.code.replace(/\D/g, '');
  const heading4 = codeDigits.slice(0, 4);
  const crumbs: string[] = [];
  if (detail.section?.roman_number) crumbs.push(`Раздел ${detail.section.roman_number}`);
  if (detail.chapter?.code) crumbs.push(`Гл.${detail.chapter.code}`);
  if (heading4) crumbs.push(heading4);

  const hasBan = Boolean(preview?.non_tariff?.has_ban);
  const measureTypes = preview?.non_tariff?.measure_types ?? [];
  const measureBadges = preview?.non_tariff?.measure_badges ?? [];
  const showRequirementHint = !hasBan && measureTypes.length > 0;

  return (
    <section className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
      {/* Код + наименование + хлебные крошки */}
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
        {crumbs.length > 0 && (
          <p className="mt-1.5 text-xs text-slate-500" aria-label="Расположение в классификаторе">
            {crumbs.join(' › ')}
          </p>
        )}
      </div>

      {/* Пошлина / НДС / Документы */}
      <div className="grid grid-cols-1 divide-y divide-slate-100 sm:grid-cols-3 sm:divide-x sm:divide-y-0">
        <div className="px-4 py-3 text-center sm:px-3">
          <p className="text-[10px] font-semibold uppercase tracking-wide text-slate-500">Пошлина</p>
          <p className="mt-0.5 font-mono text-lg font-bold text-blue-800">{dutyText}</p>
        </div>
        <div className="px-4 py-3 text-center sm:px-3">
          <p className="text-[10px] font-semibold uppercase tracking-wide text-slate-500">НДС</p>
          <p className="mt-0.5 font-mono text-lg font-bold text-emerald-700">{vat.text}</p>
          {vat.preferential && <p className="text-[9px] text-emerald-600">льготная ставка</p>}
        </div>
        <div className="px-4 py-3 text-center sm:px-3">
          <p className="text-[10px] font-semibold uppercase tracking-wide text-slate-500">Документы</p>
          <p className="mt-0.5 text-sm font-semibold text-slate-800">{documents}</p>
          {unit && <p className="text-[9px] text-slate-400">ед. изм.: {unit}</p>}
        </div>
      </div>

      {/* Предупреждение / требования */}
      {hasBan ? (
        <div className="flex items-center gap-2 border-t border-red-200 bg-red-50 px-4 py-2.5 text-sm font-medium text-red-800 sm:px-5">
          <ShieldAlert className="h-4 w-4 shrink-0" aria-hidden />
          Имеются запреты или ограничения на ввоз — проверьте условия.
        </div>
      ) : showRequirementHint ? (
        <div className="flex items-start gap-2 border-t border-amber-200 bg-amber-50 px-4 py-2.5 text-sm text-amber-800 sm:px-5">
          <FileCheck2 className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
          <span>
            Требуются разрешительные документы{measureBadges.length > 0 ? `: ${measureBadges.join(', ')}` : ''}.
          </span>
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
