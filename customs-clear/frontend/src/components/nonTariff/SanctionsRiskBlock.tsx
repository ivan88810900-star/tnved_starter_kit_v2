import React from 'react';
import type { SanctionsRiskBlockData, SanctionsRiskSignal } from '../../types/api.types';
import { sanitizeNonTariffLine } from '../../utils/nonTariffUiFilter';

const SEVERITY_LABELS: Record<string, string> = {
  clear: 'Без сигналов',
  low: 'Низкий',
  medium: 'Средний',
  high: 'Высокий',
  unknown: 'Не определён',
  manual_review_required: 'Ручная проверка',
};

const SEVERITY_STYLES: Record<string, string> = {
  clear: 'border-emerald-200 bg-emerald-50 text-emerald-900',
  low: 'border-slate-200 bg-slate-50 text-slate-700',
  medium: 'border-amber-200 bg-amber-50 text-amber-900',
  high: 'border-red-200 bg-red-50 text-red-900',
  unknown: 'border-slate-300 bg-slate-100 text-slate-700',
  manual_review_required: 'border-orange-200 bg-orange-50 text-orange-900',
};

const CATEGORY_LABELS: Record<string, string> = {
  hs_sanctions: 'Санкции по коду ТН ВЭД',
  country_restrictions: 'Страновые ограничения',
  embargo: 'Эмбарго / запрет ввоза',
  counterparty_ofac: 'Контрагент (OFAC)',
  counterparty_eu: 'Контрагент (ЕС)',
  other: 'Прочие риски',
};

type Props = {
  block: SanctionsRiskBlockData | null | undefined;
  title?: string;
  className?: string;
};

function SignalRow({ signal }: { signal: SanctionsRiskSignal }) {
  const sev = signal.severity ?? 'unknown';
  const explanation = sanitizeNonTariffLine(signal.explanation) || 'Выявлен санкционный сигнал.';
  return (
    <li
      className={`rounded-md border px-2.5 py-2 text-[11px] space-y-1 ${SEVERITY_STYLES[sev] ?? SEVERITY_STYLES.unknown}`}
    >
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-semibold">{CATEGORY_LABELS[signal.category] ?? signal.category}</span>
        <span className="rounded-full border border-current/20 px-2 py-0.5 text-[10px] opacity-90">
          {SEVERITY_LABELS[sev] ?? sev}
        </span>
        {signal.source_label ? (
          <span className="rounded-full bg-white/60 px-2 py-0.5 text-[10px]">{signal.source_label}</span>
        ) : null}
      </div>
      <p className="text-[10px] leading-snug opacity-95">{explanation}</p>
      {(signal.matched_entity || signal.matched_hs_prefix || signal.legal_ref) && (
        <div className="text-[10px] opacity-80 space-y-0.5">
          {signal.matched_entity ? <div>Совпадение: {signal.matched_entity}</div> : null}
          {signal.matched_hs_prefix ? <div>Префикс ТН ВЭД: {signal.matched_hs_prefix}</div> : null}
          {signal.legal_ref ? <div>Основание: {signal.legal_ref}</div> : null}
        </div>
      )}
    </li>
  );
}

export const SanctionsRiskBlock: React.FC<Props> = ({
  block,
  title = 'Санкции и риски',
  className = '',
}) => {
  if (!block) return null;

  const sev = block.overall_severity ?? 'unknown';
  const hasSignals = (block.signals?.length ?? 0) > 0;
  const isIncomplete = sev === 'manual_review_required' || sev === 'unknown' || block.coverage_complete === false;

  return (
    <section
      className={`rounded-xl border border-slate-200 bg-white/95 p-3 space-y-3 ${className}`}
      aria-label={title}
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-[12px] font-semibold text-slate-800">{title}</h3>
        <span
          className={`rounded-full border px-2.5 py-0.5 text-[10px] font-medium ${
            SEVERITY_STYLES[sev] ?? SEVERITY_STYLES.unknown
          }`}
        >
          {SEVERITY_LABELS[sev] ?? sev}
        </span>
      </div>

      {block.disclaimer ? (
        <p className="text-[10px] leading-relaxed text-slate-500 border-b border-slate-100 pb-2">
          {block.disclaimer}
        </p>
      ) : null}

      {!hasSignals && block.empty_message ? (
        <p
          className={`text-[11px] leading-relaxed ${
            isIncomplete ? 'text-orange-800' : 'text-slate-600'
          }`}
        >
          {block.empty_message}
        </p>
      ) : null}

      {hasSignals ? (
        <ul className="space-y-1.5">
          {block.signals!.map((signal, idx) => (
            <SignalRow key={`${signal.category}-${signal.source}-${idx}`} signal={signal} />
          ))}
        </ul>
      ) : null}

      {(block.warnings?.length ?? 0) > 0 ? (
        <div className="rounded-md border border-amber-200 bg-amber-50/80 px-2.5 py-2 text-[10px] text-amber-900 space-y-1">
          <div className="font-medium">Предупреждения о покрытии</div>
          <ul className="list-disc pl-4 space-y-0.5">
            {block.warnings!.map((w, i) => (
              <li key={i}>{w}</li>
            ))}
          </ul>
        </div>
      ) : null}

      {(block.source_coverage?.length ?? 0) > 0 ? (
        <details className="text-[10px] text-slate-500">
          <summary className="cursor-pointer select-none">Статус источников ({block.source_coverage!.length})</summary>
          <ul className="mt-1 space-y-0.5 pl-2">
            {block.source_coverage!.map((src) => (
              <li key={src.source_id}>
                {src.title}: {src.coverage_status}
                {src.record_count != null ? ` (${src.record_count})` : ''}
              </li>
            ))}
          </ul>
        </details>
      ) : null}
    </section>
  );
};

export type { SanctionsRiskBlockData };
