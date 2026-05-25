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

const APPLICABILITY_LABELS: Record<string, string> = {
  definite: 'Обязательно',
  possible: 'Возможно',
  needs_clarification: 'Требует уточнения',
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
  return (
    <li
      className={`rounded-md border px-2.5 py-2 text-[11px] space-y-1 ${
        isMissing ? 'border-red-200 bg-red-50/90 text-red-900' : 'border-slate-200 bg-white text-slate-700'
      }`}
    >
      <div className="flex flex-wrap items-center gap-2">
        <span className={`font-semibold ${isMissing ? 'text-red-900' : 'text-slate-800'}`}>
          {doc.permit_type}
        </span>
        {doc.tr_ts && (
          <span className="rounded-full bg-purple-50 px-2 py-0.5 text-[10px] text-purple-800">
            ТР ТС {doc.tr_ts}
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

      {(block.advisory_requirements?.length ?? 0) > 0 && (
        <AdvisoryRequirementsBlock
          items={block.advisory_requirements as AdvisoryRequirement[]}
          title="Потенциальные требования"
        />
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
