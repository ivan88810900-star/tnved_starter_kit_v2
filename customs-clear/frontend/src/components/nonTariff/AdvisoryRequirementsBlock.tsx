import React from 'react';

export type AdvisoryRequirement = {
  permit_type: string;
  tr_ts?: string | null;
  applicability: 'possible' | 'needs_clarification' | 'definite' | string;
  source: string;
  source_label?: string | null;
  used_for_missing_check: false;
  requires_manual_review: boolean;
  hs_prefix?: string | null;
  rule_name?: string | null;
  reason: string;
  note?: string | null;
};

const APPLICABILITY_LABELS: Record<string, string> = {
  possible: 'Возможно',
  needs_clarification: 'Требует уточнения',
  definite: 'Нормативное требование выявлено',
};

const APPLICABILITY_BADGE: Record<string, string> = {
  possible: 'border-amber-200 bg-amber-50 text-amber-800',
  needs_clarification: 'border-sky-200 bg-sky-50 text-sky-800',
  definite: 'border-indigo-200 bg-indigo-50 text-indigo-900',
};

const SOURCE_LABELS: Record<string, string> = {
  official_sgr_registry: 'Официальный нормативный контур',
  legacy_non_tariff_rules: 'Историческое правило (подсказка)',
  legacy_non_tariff_measures: 'Legacy меры (справочно)',
  tr_ts_catalog: 'ТР ТС каталог',
  broker_catalog_layers: 'Каталог нетарифных требований',
  runtime_triggers: 'Триггер по описанию товара',
  sensitive_override: 'Чувствительная группа товара',
  domain_default: 'Доменная форма подтверждения (ЕЭК №620)',
  non_tariff_measures: 'Нетарифные меры (runtime)',
};

type Props = {
  items: AdvisoryRequirement[];
  title?: string;
};

export const AdvisoryRequirementsBlock: React.FC<Props> = ({
  items,
  title = 'Потенциальные требования',
}) => {
  if (!items?.length) return null;

  return (
    <div className="rounded-lg border border-amber-200 bg-amber-50/80 px-3 py-2.5 space-y-2">
      <div className="text-[11px] font-medium text-amber-900">{title}</div>
      <div className="text-[10px] text-amber-800/90">
        Не являются обязательными для статуса проверки. Уточните характеристики товара или проконсультируйтесь с
        экспертом.
      </div>
      <ul className="space-y-2">
        {items.map((item, idx) => {
          const app = item.applicability || 'possible';
          const isOfficial = item.source === 'official_sgr_registry';
          const isDefinite = app === 'definite';
          const badgeCls =
            APPLICABILITY_BADGE[app] ??
            (isDefinite ? APPLICABILITY_BADGE.definite : 'border-slate-200 bg-slate-50 text-slate-700');
          const liBorder = isOfficial
            ? isDefinite
              ? 'border-indigo-200 bg-indigo-50/40'
              : 'border-emerald-200/80 bg-white/95'
            : 'border-amber-100 bg-white/90';
          const sourceText =
            item.source_label ||
            SOURCE_LABELS[item.source] ||
            (isOfficial ? 'ЕЭК №299' : item.source);

          return (
            <li
              key={`${item.source}-${item.permit_type}-${item.tr_ts ?? ''}-${app}-${idx}`}
              className={`rounded-md border px-2.5 py-2 text-[11px] text-slate-700 space-y-1 ${liBorder}`}
            >
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-semibold text-slate-800">{item.permit_type}</span>
                {item.tr_ts && (
                  <span className="rounded-full bg-purple-50 px-2 py-0.5 text-[10px] text-purple-800">
                    ТР ТС {item.tr_ts}
                  </span>
                )}
                <span className={`rounded-full border px-2 py-0.5 text-[10px] font-medium ${badgeCls}`}>
                  {APPLICABILITY_LABELS[app] ?? app}
                </span>
                <span
                  className={`rounded-full px-2 py-0.5 text-[10px] ${
                    isOfficial ? 'bg-emerald-100 text-emerald-800' : 'bg-slate-100 text-slate-600'
                  }`}
                >
                  {sourceText}
                </span>
              </div>
              {item.rule_name && <div className="text-[10px] text-slate-600">{item.rule_name}</div>}
              <div className="text-[10px] leading-snug text-slate-600">{item.reason}</div>
              {item.note && <div className="text-[10px] text-slate-500 italic">{item.note}</div>}
            </li>
          );
        })}
      </ul>
    </div>
  );
};