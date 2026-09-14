import React from 'react';
import {
  AdvisoryRequirementsBlock,
  type AdvisoryRequirement,
} from './AdvisoryRequirementsBlock';
import {
  countNormativeGroups,
  hasNormativeContent,
  type NormativeDocument,
  type NormativeRequirementsBlockData,
} from './normativeBlockHelpers';
import { describePermit, permitBadgeClasses } from '../../utils/permitVocabulary';

const APPLICABILITY_LABELS: Record<string, string> = {
  definite: 'Обязательно',
  possible: 'Возможно',
  needs_clarification: 'Требует уточнения',
};

const FAMILY_STATUS_LABELS: Record<string, string> = {
  definite: 'совпало по введённым данным',
  excluded: 'возможное исключение по введённым данным',
  needs_clarification: 'нужно уточнить',
  legacy_signal: 'сигнал каталога',
  not_detected: 'не выявлено',
};

const CATCH_ALL_ACTION_LABELS: Record<string, string> = {
  stop_transaction_and_escalate_to_export_control_counsel:
    'Приостановите сделку и передайте её на проверку специалисту по экспортному контролю.',
  obtain_identification_and_check_commission_permission:
    'Проведите идентификацию товара и проверьте необходимость разрешения Комиссии по экспортному контролю.',
};

type Props = {
  block: NormativeRequirementsBlockData | null | undefined;
  title?: string;
  className?: string;
};

function DocumentRow({
  doc,
  variant,
}: {
  doc: NormativeDocument;
  variant: 'required' | 'missing';
}) {
  const isMissing = variant === 'missing';
  const permit = describePermit(doc.permit_type, 'mandatory');
  return (
    <li
      className={`rounded-md border px-2.5 py-2 text-[11px] space-y-1 ${
        isMissing ? 'border-red-200 bg-red-50/90 text-red-900' : 'border-slate-200 bg-white text-slate-700'
      }`}
    >
      <div className="flex flex-wrap items-center gap-2">
        <span
          className={`rounded-full border px-2 py-0.5 text-[10px] font-semibold ${
            isMissing ? 'border-red-300 bg-red-100 text-red-900' : permitBadgeClasses(permit.severity)
          }`}
        >
          {permit.code}
        </span>
        <span className={`font-semibold ${isMissing ? 'text-red-900' : 'text-slate-800'}`}>
          {permit.label}
        </span>
        {doc.tr_ts && (
          <span className="rounded-full bg-purple-50 px-2 py-0.5 text-[10px] text-purple-800">
            ТР ТС {doc.tr_ts}
            {doc.tr_ts_full_name ? ` — ${doc.tr_ts_full_name}` : ''}
          </span>
        )}
        {doc.applicability && doc.applicability !== 'definite' && (
          <span className="rounded-full border border-slate-200 bg-slate-50 px-2 py-0.5 text-[10px] text-slate-600">
            {APPLICABILITY_LABELS[doc.applicability] ?? doc.applicability}
          </span>
        )}
        {doc.source_label && (
          <span
            className={`rounded-full px-2 py-0.5 text-[10px] ${
              isMissing ? 'bg-red-100 text-red-800' : 'bg-slate-100 text-slate-600'
            }`}
          >
            {doc.source_label}
          </span>
        )}
      </div>
      {doc.rule_name && <div className="text-[10px] text-slate-600">{doc.rule_name}</div>}
      {doc.reason && (
        <div className={`text-[10px] leading-snug ${isMissing ? 'text-red-800/90' : 'text-slate-600'}`}>
          {doc.reason}
        </div>
      )}
    </li>
  );
}

export const NormativeRequirementsBlock: React.FC<Props> = ({
  block,
  title = 'Нормативные требования',
  className = '',
}) => {
  if (!block) return null;

  const counts = countNormativeGroups(block);
  const hasContent = hasNormativeContent(block);
  const catchAll = block.official_ntm_catch_all;
  const catchAllRisk = catchAll?.status === 'prohibited_transaction_risk'
    || catchAll?.status === 'permission_review_required';
  const catchAllCritical = catchAll?.status === 'prohibited_transaction_risk';
  const catchAllVisible = Boolean(catchAll?.status && catchAll.status !== 'not_applicable_direction');
  const ordinaryAdvisory = (block.advisory_requirements ?? []).filter(
    (item) => !item.transaction_level,
  );

  return (
    <section
      className={`rounded-xl border border-slate-200 bg-white/95 p-3 space-y-3 ${className}`}
      aria-label={title}
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-[12px] font-semibold text-slate-800">{title}</h3>
        {hasContent && (
          <div className="flex flex-wrap gap-1.5 text-[10px] text-slate-500">
            {counts.required > 0 && <span>обязательных: {counts.required}</span>}
            {counts.missing > 0 && <span className="text-red-700">отсутствует: {counts.missing}</span>}
            {counts.advisory > 0 && <span className="text-amber-700">потенциальных: {counts.advisory}</span>}
          </div>
        )}
      </div>

      {!hasContent && (
        <p className="text-[11px] leading-relaxed text-slate-600">
          {block.empty_message ??
            'Для данной позиции не выявлено нормативных требований к разрешительным документам. Уточните код ТН ВЭД и описание товара.'}
        </p>
      )}

      {block.required_documents.length > 0 && (
        <div className="space-y-1.5">
          <div className="text-[11px] font-medium text-slate-700">Обязательные документы</div>
          <ul className="space-y-1.5">
            {block.required_documents.map((doc, idx) => (
              <DocumentRow
                key={`req-${doc.permit_type}-${doc.tr_ts ?? ''}-${idx}`}
                doc={doc}
                variant="required"
              />
            ))}
          </ul>
        </div>
      )}

      {block.missing_documents.length > 0 && (
        <div className="space-y-1.5">
          <div className="text-[11px] font-medium text-red-800">Отсутствующие документы</div>
          <p className="text-[10px] text-red-700/80">
            Влияют на статус проверки — укажите номера разрешений или приложите документы.
          </p>
          <ul className="space-y-1.5">
            {block.missing_documents.map((doc, idx) => (
              <DocumentRow
                key={`miss-${doc.permit_type}-${doc.tr_ts ?? ''}-${idx}`}
                doc={doc}
                variant="missing"
              />
            ))}
          </ul>
        </div>
      )}

      {catchAllVisible && (
        <div
          role="alert"
          className={`rounded-lg border p-2.5 text-[11px] ${
            catchAllCritical
              ? 'border-red-300 bg-red-50 text-red-900'
              : catchAllRisk
                ? 'border-orange-300 bg-orange-50 text-orange-900'
                : 'border-sky-200 bg-sky-50 text-sky-900'
          }`}
        >
          <div className="font-semibold">
            {catchAllCritical
              ? 'Критический риск экспортной сделки'
              : catchAllRisk
                ? 'Требуется проверка экспортной сделки'
                : 'Проверка всеобъемлющего экспортного контроля'}
          </div>
          {catchAll?.reason && <p className="mt-1 leading-snug">{catchAll.reason}</p>}
          {catchAll?.recommended_action && (
            <p className="mt-1 font-medium">
              {CATCH_ALL_ACTION_LABELS[catchAll.recommended_action]
                ?? catchAll.recommended_action}
            </p>
          )}
          {(catchAll?.missing_facts?.length ?? 0) > 0 && (
            <p className="mt-1 font-medium">
              Для окончательного вывода укажите направление перемещения.
            </p>
          )}
          <p className="mt-1 text-[10px] opacity-80">
            Это transaction-level проверка, а не автоматическое требование документа по коду ТН ВЭД;
            она не добавляется в missing-check.
          </p>
          {catchAll?.source_url && (
            <a
              className="mt-1 inline-block text-[10px] underline underline-offset-2"
              href={catchAll.source_url}
              target="_blank"
              rel="noreferrer"
            >
              Официальный источник
            </a>
          )}
        </div>
      )}

      {ordinaryAdvisory.length > 0 && (
        <AdvisoryRequirementsBlock
          items={ordinaryAdvisory as AdvisoryRequirement[]}
          title="Официальные требования и исключения (справочно)"
        />
      )}

      {(block.official_ntm_applicability?.exact_rows_count ?? 0) > 0 && (
        <div className="rounded-lg border border-indigo-100 bg-indigo-50/60 p-2.5 text-[10px] text-indigo-900">
          <div className="font-medium">Точная применимость по характеристикам товара</div>
          <div className="mt-1 leading-snug text-indigo-800/90">
            Точных строк: {block.official_ntm_applicability!.exact_rows_count ?? 0}
            {' · '}совпало по введённым данным: {block.official_ntm_applicability!.definite_advisory_count ?? 0}
            {' · '}исключений: {block.official_ntm_applicability!.excluded_count ?? 0}
            {' · '}требуют уточнения: {block.official_ntm_applicability!.exact_needs_clarification_count ?? 0}
          </div>
          <div className="mt-1 text-indigo-700/80">
            Сервис не проверяет введённые реестровые сведения самостоятельно. Выводы требуют ручной сверки и не
            влияют на статус отсутствующих документов без доверенного source-adapter.
          </div>
        </div>
      )}

      {(block.measure_families?.length ?? 0) > 0 && (
        <div className="space-y-1.5 rounded-lg border border-slate-200 bg-slate-50/70 p-2.5">
          <div className="text-[11px] font-medium text-slate-700">
            Контроль по семействам мер ({block.measure_families!.length})
          </div>
          <div className="grid gap-1 sm:grid-cols-2">
            {block.measure_families!.map((item) => (
              <div key={item.family} className="rounded bg-white px-2 py-1.5 text-[10px]">
                <div className="flex items-center justify-between gap-2">
                  <span className="text-slate-700">{item.label}</span>
                  <span className={item.status === 'definite' ? 'text-indigo-700' : item.status === 'needs_clarification' ? 'text-sky-700' : item.status === 'excluded' ? 'text-emerald-700' : 'text-slate-500'}>
                    {FAMILY_STATUS_LABELS[item.status] ?? item.status}
                  </span>
                </div>
                {((item.permit_types?.length ?? 0) > 0 || (item.regulations?.length ?? 0) > 0 || (item.matched_sections?.length ?? 0) > 0) && (
                  <div className="mt-1 text-[9px] leading-snug text-slate-500">
                    {item.permit_types?.length ? `Документы: ${item.permit_types.join(', ')}` : ''}
                    {item.regulations?.length ? ` · ТР: ${item.regulations.join(', ')}` : ''}
                    {item.matched_sections?.length ? ` · Разделы ЕЭК №30: ${item.matched_sections.join(', ')}` : ''}
                  </div>
                )}
              </div>
            ))}
          </div>
          {block.measure_families_disclaimer && (
            <p className="text-[10px] leading-snug text-slate-500">{block.measure_families_disclaimer}</p>
          )}
        </div>
      )}

      {(block.sources_summary?.length ?? 0) > 0 && (
        <div className="text-[10px] text-slate-500 border-t border-slate-100 pt-2">
          Источники: {block.sources_summary!.join(', ')}
        </div>
      )}
    </section>
  );
};

export type { NormativeRequirementsBlockData };
