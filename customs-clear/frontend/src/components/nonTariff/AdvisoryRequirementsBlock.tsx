import React from 'react';
import { describePermit, permitBadgeClasses } from '../../utils/permitVocabulary';

export type AdvisoryRequirement = {
  permit_type: string;
  tr_ts?: string | null;
  applicability: 'possible' | 'needs_clarification' | 'definite' | string;
  source: string;
  source_label?: string | null;
  source_url?: string | null;
  direction?: 'import' | 'export' | 'both' | string;
  section?: string | null;
  used_for_missing_check: false;
  requires_manual_review: boolean;
  hs_prefix?: string | null;
  rule_name?: string | null;
  reason: string;
  note?: string | null;
  outcome?: string | null;
  matched_rule?: string | null;
  matched_hs_scope?: string | null;
  missing_facts?: string[];
  exclusion_reason?: string | null;
  source_revision?: string | null;
  eligible_for_enforcement?: boolean;
  curated_enforcement_key?: string | null;
  transaction_level?: boolean;
  risk_level?: string | null;
  certificate_required?: boolean | null;
  exact_advisory?: boolean;
  evidence_trust?: string | null;
  trusted_source_verified?: boolean;
  identification_url?: string | null;
  source_documents?: Array<{
    number?: number | string | null;
    title?: string | null;
    official_url?: string | null;
  }>;
};

const APPLICABILITY_LABELS: Record<string, string> = {
  possible: 'Возможно',
  needs_clarification: 'Требует уточнения',
  definite: 'Совпадение по указанным данным',
  excluded: 'Возможное точное исключение',
};

const APPLICABILITY_BADGE: Record<string, string> = {
  possible: 'border-amber-200 bg-amber-50 text-amber-800',
  needs_clarification: 'border-sky-200 bg-sky-50 text-sky-800',
  definite: 'border-indigo-200 bg-indigo-50 text-indigo-900',
  excluded: 'border-emerald-200 bg-emerald-50 text-emerald-800',
};

const SOURCE_LABELS: Record<string, string> = {
  official_sgr_registry: 'Решение КТС №299',
  official_ntm_contours: 'Официальные перечни ЕЭК / РФ',
  official_export_control: 'Экспортный контроль РФ (ФСТЭК)',
  official_ntm_exact_devices_shadow: 'Точные правила РЭС/ВЧУ и криптографии',
  official_ntm_exact_health: 'Точные санитарные, ветеринарные и фитосанитарные правила',
  official_ntm_exact_trade: 'Точные торговые и экспортные ограничения',
  legacy_non_tariff_rules: 'Историческое правило (подсказка)',
  legacy_non_tariff_measures: 'Legacy меры (справочно)',
  tr_ts_catalog: 'ТР ТС каталог',
  broker_catalog_layers: 'Каталог нетарифных требований',
  runtime_triggers: 'Триггер по описанию товара',
  sensitive_override: 'Чувствительная группа товара',
  domain_default: 'Доменная форма подтверждения (ЕЭК №620)',
  non_tariff_measures: 'Нетарифные меры (runtime)',
};

const DIRECTION_LABELS: Record<string, string> = {
  import: 'ввоз',
  export: 'вывоз',
  both: 'ввоз/вывоз',
  import_or_transit: 'ввоз/транзит',
};

const FACT_LABELS: Record<string, string> = {
  direction: 'направление перемещения',
  transit_route: 'маршрут транзита',
  product_name_matches_official_row: 'сверка наименования с точной строкой перечня',
  intended_use: 'назначение товара',
  composition: 'состав',
  composition_or_cas_numbers: 'состав или номера CAS',
  cas_numbers: 'номера CAS',
  first_import: 'признак первого ввоза',
  food_contact: 'контакт с пищевой продукцией',
  drinking_water_contact: 'применение в питьевом водоснабжении',
  embedded_radio: 'наличие встроенного радиомодуля',
  frequency_mhz: 'рабочие частоты',
  transmitter_power_mw: 'мощность передатчика',
  cryptography_present: 'наличие криптографических функций',
  notification_registry_verified: 'проверка нотификации в реестре',
  notification_registry_number: 'номер нотификации',
  animal_origin: 'животное происхождение',
  feed_use: 'кормовое назначение',
  processing_method: 'способ переработки',
  packaging: 'вид упаковки',
  phytosanitary_risk_tier: 'категория фитосанитарного риска',
  is_waste: 'признак отхода',
  hazardous_waste: 'класс и опасные свойства отхода',
  export_control_list_item: 'позиция контрольного списка',
  technical_parameters_confirmed: 'подтверждённые технические параметры',
  end_user: 'конечный пользователь',
  destination_country: 'страна назначения',
  origin_country: 'страна происхождения',
  manufacturer_documents_verified: 'проверенные документы изготовителя',
  disinfectant_use: 'дезинфицирующее назначение',
  veterinary_use: 'ветеринарное назначение',
  radio_technology: 'тип радиотехнологии',
  radio_registry_evidence_url: 'ссылка на официальную запись реестра РЭС/ВЧУ',
  crypto_functions: 'криптографические функции',
  mass_market: 'признак массового рынка',
  waste_class: 'класс/код отхода',
  contamination_or_waste_class: 'загрязнение или классификация отхода',
  sealed_container: 'герметичная тара',
  package_volume_ml_or_package_mass_g: 'объём или масса единицы товара',
  notification_or_exact_legal_exemption: 'нотификация или точное нормативное исключение',
  official_active_notification_registry_evidence: 'актуальная запись официального реестра нотификаций',
  verified_current_radio_registry_result: 'актуальный результат проверки реестра РЭС/ВЧУ',
  active_tnved_code: 'актуальная десятизначная подсубпозиция ТН ВЭД',
  section_2_19_hs_scope: 'точная кодовая строка раздела 2.19',
  resolve_conflicting_crypto_facts: 'устранение противоречий в сведениях о криптографии',
  'crypto_exemption.rule_id': 'точная строка нормативного исключения для криптографии',
  'crypto_exemption.verified': 'проверка точного исключения',
  'crypto_exemption.evidence_url': 'официальный источник исключения',
  'crypto_exemption.quantity_at_most_20': 'целое количество тестовых SIM-карт от 1 до 20',
  'crypto_exemption.cellular_operator': 'статус оператора сотовой связи',
  'crypto_exemption.international_exchange_purpose': 'назначение для международного обмена',
  'crypto_exemption.personal_use': 'личное использование',
  'crypto_exemption.natural_person': 'получатель является физическим лицом',
  'crypto_exemption.appendix_5_category': 'категория товара по приложению 5',
  crypto_transit_authorization_or_notification: 'разрешение или нотификация для выбранного маршрута транзита',
};

function factLabel(value: string): string {
  const [base, detail] = value.split(':', 2);
  const label = FACT_LABELS[value] ?? FACT_LABELS[base] ?? (base === 'description' ? 'точное наименование товара' : base);
  return detail ? `${label} (${detail.replace(/_/g, ' ')})` : label;
}

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
          const isOfficial = item.source === 'official_sgr_registry' || item.source === 'official_ntm_contours' || item.source === 'official_export_control';
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
            (isOfficial ? 'Официальный нормативный источник' : item.source);

          return (
            <li
              key={`${item.source}-${item.permit_type}-${item.tr_ts ?? ''}-${app}-${idx}`}
              className={`rounded-md border px-2.5 py-2 text-[11px] text-slate-700 space-y-1 ${liBorder}`}
            >
              <div className="flex flex-wrap items-center gap-2">
                <span
                  className={`rounded-full border px-2 py-0.5 text-[10px] font-semibold ${permitBadgeClasses('conditional')}`}
                >
                  {describePermit(item.permit_type).code}
                </span>
                <span className="font-semibold text-slate-800">
                  {describePermit(item.permit_type).label}
                </span>
                {item.tr_ts && (
                  <span className="rounded-full bg-purple-50 px-2 py-0.5 text-[10px] text-purple-800">
                    ТР ТС {item.tr_ts}
                  </span>
                )}
                <span className={`rounded-full border px-2 py-0.5 text-[10px] font-medium ${badgeCls}`}>
                  {APPLICABILITY_LABELS[app] ?? app}
                </span>
                {item.direction && (
                  <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[10px] text-slate-600">
                    {DIRECTION_LABELS[item.direction] ?? item.direction}
                  </span>
                )}
                {item.source_url ? (
                  <a
                    href={item.source_url}
                    target="_blank"
                    rel="noreferrer"
                    className={`rounded-full px-2 py-0.5 text-[10px] underline ${
                      isOfficial ? 'bg-emerald-100 text-emerald-800' : 'bg-slate-100 text-slate-600'
                    }`}
                  >
                    {sourceText}
                  </a>
                ) : (
                  <span
                    className={`rounded-full px-2 py-0.5 text-[10px] ${
                      isOfficial ? 'bg-emerald-100 text-emerald-800' : 'bg-slate-100 text-slate-600'
                    }`}
                  >
                    {sourceText}
                  </span>
                )}
              </div>
              {item.rule_name && <div className="text-[10px] text-slate-600">{item.rule_name}</div>}
              {item.matched_rule && item.matched_rule !== item.rule_name && (
                <div className="text-[10px] text-slate-600">Точная строка: {item.matched_rule}</div>
              )}
              <div className="text-[10px] leading-snug text-slate-600">{item.reason}</div>
              {item.exact_advisory && item.trusted_source_verified !== true && (
                <div className="rounded border border-amber-200 bg-amber-50 px-2 py-1 text-[10px] text-amber-900">
                  По данным пользователя: сервис не проверял реестр или документы самостоятельно. Требуется ручная сверка.
                </div>
              )}
              {(item.missing_facts?.length ?? 0) > 0 && (
                <div className="rounded border border-sky-100 bg-sky-50 px-2 py-1 text-[10px] text-sky-800">
                  Для точного вывода: {item.missing_facts!.map(factLabel).join(', ')}
                </div>
              )}
              {item.exclusion_reason && (
                <div className="rounded border border-emerald-100 bg-emerald-50 px-2 py-1 text-[10px] text-emerald-800">
                  Исключение: {item.exclusion_reason}
                </div>
              )}
              {(item.matched_hs_scope || item.source_revision) && (
                <div className="text-[9px] text-slate-500">
                  {item.matched_hs_scope ? `Сопоставление: ${item.matched_hs_scope}` : ''}
                  {item.matched_hs_scope && item.source_revision ? ' · ' : ''}
                  {item.source_revision ? `Редакция: ${item.source_revision}` : ''}
                </div>
              )}
              {item.note && <div className="text-[10px] text-slate-500 italic">{item.note}</div>}
              {(item.source_documents?.length ?? 0) > 0 && (
                <div className="flex flex-wrap items-center gap-1 text-[10px] text-slate-600">
                  <span>Совпавшие списки:</span>
                  {item.source_documents!.map((document, documentIndex) => {
                    const label = document.number ? `ПП РФ №${document.number}` : (document.title || 'Документ');
                    return document.official_url ? (
                      <a
                        key={`${document.number ?? document.title ?? 'source'}-${documentIndex}`}
                        href={document.official_url}
                        target="_blank"
                        rel="noreferrer"
                        className="rounded bg-emerald-50 px-1.5 py-0.5 text-emerald-800 underline"
                        title={document.title || undefined}
                      >
                        {label}
                      </a>
                    ) : (
                      <span
                        key={`${document.number ?? document.title ?? 'source'}-${documentIndex}`}
                        className="rounded bg-slate-100 px-1.5 py-0.5"
                        title={document.title || undefined}
                      >
                        {label}
                      </span>
                    );
                  })}
                </div>
              )}
              {item.identification_url && (
                <a
                  href={item.identification_url}
                  target="_blank"
                  rel="noreferrer"
                  className="inline-block text-[10px] text-indigo-700 underline"
                >
                  Идентификация контролируемой продукции (ФСТЭК)
                </a>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
};
