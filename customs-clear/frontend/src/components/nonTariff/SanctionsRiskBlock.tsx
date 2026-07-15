import React from 'react';
import { AlertTriangle, CheckCircle2, CircleHelp, ExternalLink, ShieldAlert } from 'lucide-react';
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

const COVERAGE_LABELS: Record<string, string> = {
  present: 'Подключён',
  partial: 'Частичное покрытие',
  missing: 'Нет данных',
  not_configured: 'Не настроен',
  not_applicable: 'Не применяется',
};

const MATCH_METHOD_LABELS: Record<string, string> = {
  hs_prefix: 'Совпадение по префиксу ТН ВЭД',
  country: 'Совпадение по стране',
  country_hs_prefix: 'Совпадение по стране и префиксу ТН ВЭД',
  name_substring: 'Предварительное текстовое совпадение наименования',
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
      {(signal.matched_entity || signal.matched_hs_prefix || signal.matched_country || signal.match_method || signal.legal_ref) && (
        <div className="text-[10px] opacity-80 space-y-0.5">
          {signal.matched_entity ? <div>Совпадение: {signal.matched_entity}</div> : null}
          {signal.matched_hs_prefix ? <div>Префикс ТН ВЭД: {signal.matched_hs_prefix}</div> : null}
          {signal.matched_country ? <div>Страна: {signal.matched_country}</div> : null}
          {signal.match_method ? <div>Метод: {MATCH_METHOD_LABELS[signal.match_method] ?? signal.match_method}</div> : null}
          {signal.legal_ref ? <div>Основание: {signal.legal_ref}</div> : null}
        </div>
      )}
      {signal.source_url ? (
        <a
          href={signal.source_url}
          target="_blank"
          rel="noreferrer"
          className="inline-flex items-center gap-1 text-[10px] font-semibold underline"
        >
          Открыть источник
          <ExternalLink className="h-3 w-3" aria-hidden />
        </a>
      ) : null}
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
        <h3 className="flex items-center gap-2 text-[12px] font-semibold text-slate-800">
          {sev === 'high' ? (
            <ShieldAlert className="h-4 w-4 text-red-600" aria-hidden />
          ) : isIncomplete ? (
            <AlertTriangle className="h-4 w-4 text-orange-600" aria-hidden />
          ) : (
            <CheckCircle2 className="h-4 w-4 text-emerald-600" aria-hidden />
          )}
          {title}
        </h3>
        <span
          className={`rounded-full border px-2.5 py-0.5 text-[10px] font-medium ${
            SEVERITY_STYLES[sev] ?? SEVERITY_STYLES.unknown
          }`}
        >
          {SEVERITY_LABELS[sev] ?? sev}
        </span>
      </div>

      {(block.screening_scope?.length ?? 0) > 0 ? (
        <div className="grid gap-2 sm:grid-cols-3" aria-label="Охват проверки">
          {block.screening_scope!.map((scope) => {
            const checked = scope.status === 'checked';
            return (
              <div
                key={scope.code}
                className={`rounded-lg border px-3 py-2 ${
                  checked ? 'border-emerald-200 bg-emerald-50/70' : 'border-orange-200 bg-orange-50/70'
                }`}
              >
                <p className="flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wide text-slate-700">
                  {checked ? (
                    <CheckCircle2 className="h-3.5 w-3.5 text-emerald-600" aria-hidden />
                  ) : (
                    <CircleHelp className="h-3.5 w-3.5 text-orange-600" aria-hidden />
                  )}
                  {scope.label}
                </p>
                <p className="mt-1 truncate font-mono text-[11px] font-medium text-slate-900">
                  {scope.value || 'Не указано'}
                </p>
                {scope.explanation ? <p className="mt-1 text-[9px] leading-snug text-slate-600">{scope.explanation}</p> : null}
              </div>
            );
          })}
        </div>
      ) : null}

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
        <details className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-[10px] text-slate-600">
          <summary className="cursor-pointer select-none font-semibold text-slate-700">
            Источники и полнота данных ({block.source_coverage!.length})
          </summary>
          <ul className="mt-2 space-y-2">
            {block.source_coverage!.map((src) => (
              <li key={src.source_id} className="rounded-md border border-slate-200 bg-white px-2.5 py-2">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="font-medium text-slate-800">{src.title}</span>
                  <span className="rounded-full bg-slate-100 px-2 py-0.5">
                    {COVERAGE_LABELS[src.coverage_status] ?? src.coverage_status}
                    {src.record_count != null ? ` · ${src.record_count}` : ''}
                  </span>
                </div>
                {src.authority_level ? <p className="mt-1">Статус: {src.authority_level}</p> : null}
                {src.manual_review_required ? <p className="mt-1 text-amber-700">Требует ручной верификации</p> : null}
                {(src.known_gaps?.length ?? 0) > 0 ? (
                  <ul className="mt-1 list-disc space-y-0.5 pl-4 text-slate-500">
                    {src.known_gaps!.map((gap) => <li key={gap}>{gap}</li>)}
                  </ul>
                ) : null}
                {src.source_url ? (
                  <a
                    href={src.source_url}
                    target="_blank"
                    rel="noreferrer"
                    className="mt-1 inline-flex items-center gap-1 font-semibold text-indigo-700 underline"
                  >
                    Официальная страница
                    <ExternalLink className="h-3 w-3" aria-hidden />
                  </a>
                ) : null}
              </li>
            ))}
          </ul>
        </details>
      ) : null}
    </section>
  );
};

export type { SanctionsRiskBlockData };
