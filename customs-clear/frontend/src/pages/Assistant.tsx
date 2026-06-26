import React, { useEffect, useRef, useState } from 'react';
import { api } from '../api/client';
import { getUserFacingApiError } from '../api/error';
import { useClientCapabilities } from '../context/ClientCapabilitiesContext';
import { Sparkles } from 'lucide-react';
import type {
  AssistantAnalyzeResponse,
  AssistantCopilotAi,
  AssistantCopilotBatchResponse,
  AssistantCopilotBundle,
  AssistantCopilotResponse,
  AssistantDecisionHintItem,
  AssistantDecisionHintsResponse,
  AssistantDecisionRecord,
  AssistantDecisionsRecentResponse,
  AssistantHsSuggestionItem,
  AssistantJournalStatsResponse,
  AssistantPipelineStep,
  JsonObject,
  JsonValue,
  PermitInput,
} from '../types/api.types';
import { formatCode } from '../api/tnvedCatalog';
import { formatTnvedCommodityName, TNVED_COMMODITY_NAME_CLASS } from '../utils/tnvedDisplayText';
import type { AssistantNavigationJob } from '../store/calculatorAssistantBridge';
import {
  getAssistantCalculationContext,
  setAssistantCalculationContext,
  subscribeAssistantCalculationContext,
} from '../store/calculatorAssistantBridge';
import {
  DeclarantChatThread,
  type DeclarantChatThreadHandle,
} from '../components/assistant/DeclarantChatThread';

function downloadJson<T>(filename: string, data: T) {
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = filename;
  a.click();
  URL.revokeObjectURL(a.href);
}

type BatchLine = {
  id: string;
  description: string;
  hs_code: string;
  country: string;
  customs_value: string;
  freight: string;
  permits: PermitInput[];
};

type LegacyLine = {
  id: string;
  hs_code: string;
  description: string;
  country: string;
  permits: PermitInput[];
};

function newRowId(): string {
  return globalThis.crypto?.randomUUID?.() ?? `row-${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
}

function emptyBatchLine(): BatchLine {
  return {
    id: newRowId(),
    description: '',
    hs_code: '',
    country: 'CN',
    customs_value: '',
    freight: '0',
    permits: [{ type: 'ДС', number: '' }],
  };
}

function emptyLegacyLine(): LegacyLine {
  return {
    id: newRowId(),
    hs_code: '',
    description: '',
    country: 'CN',
    permits: [{ type: 'ДС', number: '' }],
  };
}

const CountrySelect: React.FC<{ value: string; onChange: (v: string) => void; className?: string }> = ({
  value,
  onChange,
  className = 'cc-input',
}) => (
  <select value={value} onChange={(e) => onChange(e.target.value)} className={className}>
    <option value="CN">Китай</option>
    <option value="EU">ЕС</option>
    <option value="BY">Беларусь</option>
    <option value="KZ">Казахстан</option>
  </select>
);

const PIPELINE_STEP_LABELS: Record<string, string> = {
  classification: 'Классификация',
  non_tariff: 'Нетарифные меры',
  payment: 'Платежи в бюджет',
  registry: 'Реестр ФСА',
};

function pipelineStepCaption(step: AssistantPipelineStep): { label: string; line: string; skipped: boolean } {
  const key = String(step.step || 'этап');
  const label = PIPELINE_STEP_LABELS[key] || key;
  if (step.skipped) {
    return { label, line: String(step.detail || 'Не выполнялось'), skipped: true };
  }
  if (key === 'payment' && step.ok && typeof step.total === 'number') {
    return {
      label,
      line: `Итого к уплате: ${step.total.toLocaleString('ru-RU')} ₽`,
      skipped: false,
    };
  }
  if (key === 'non_tariff' && step.status) {
    return { label, line: `Статус: ${String(step.status)}`, skipped: false };
  }
  if (key === 'registry' && typeof step.count === 'number') {
    return { label, line: `Проверено документов: ${step.count}`, skipped: false };
  }
  if (key === 'classification' && step.detail) {
    return { label, line: String(step.detail), skipped: false };
  }
  if (step.ok) {
    return { label, line: 'Выполнено', skipped: false };
  }
  return { label, line: 'Завершено', skipped: false };
}

function formatDecisionTs(ts?: string | null): string {
  if (!ts) return '—';
  try {
    return new Date(ts).toLocaleString('ru-RU', {
      day: '2-digit',
      month: '2-digit',
      year: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
    });
  } catch {
    return ts.slice(0, 16);
  }
}

const JournalStatsPanel: React.FC<{ data: AssistantJournalStatsResponse }> = ({ data }) => {
  if (data.status === 'ERROR' || data.message) {
    return (
      <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-[12px] text-red-700">
        {String(data.message || 'Нет данных')}
      </div>
    );
  }
  const records = data.records_in_index ?? 0;
  const uniqHs = data.unique_confirmed_hs_codes ?? 0;
  const uniqClients = data.unique_client_ids ?? 0;
  const top = data.top_confirmed_hs ?? [];
  const bySrc = data.by_source ?? [];

  return (
    <div className="space-y-4">
      <div className="cc-stat-grid">
        <div className="cc-stat">
          <span className="cc-stat-label">Записей</span>
          <span className="cc-stat-value">{records}</span>
        </div>
        <div className="cc-stat">
          <span className="cc-stat-label">Кодов ТН ВЭД</span>
          <span className="cc-stat-value">{uniqHs}</span>
        </div>
        <div className="cc-stat">
          <span className="cc-stat-label">Клиентов</span>
          <span className="cc-stat-value">{uniqClients}</span>
        </div>
      </div>
      {top.length > 0 && (
        <div>
          <div className="cc-label mb-2 !normal-case !tracking-normal text-slate-500">Частые коды</div>
          <div className="flex flex-wrap gap-1.5">
            {top.slice(0, 8).map((row) => (
              <span
                key={row.hs_code}
                className="cc-mono rounded-md border border-slate-200 bg-slate-50 px-2 py-1 text-[11px] text-indigo-700"
              >
                {row.hs_code}
                <span className="ml-1 text-slate-500">×{row.count}</span>
              </span>
            ))}
          </div>
        </div>
      )}
      {bySrc.length > 0 && (
        <div>
          <div className="cc-label mb-2 !normal-case !tracking-normal text-slate-500">Источники</div>
          <ul className="space-y-1 text-[11px] text-slate-500">
            {bySrc.slice(0, 6).map((row) => (
              <li key={row.source} className="flex justify-between gap-2 border-b border-slate-200 py-1 last:border-0">
                <span className="truncate">{row.source}</span>
                <span className="cc-mono shrink-0 text-slate-400">{row.count}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
};

const RecentDecisionsTable: React.FC<{ items: AssistantDecisionRecord[] }> = ({ items }) => (
  <div className="max-h-48 overflow-auto rounded-lg border border-slate-200 bg-slate-50">
    <table className="w-full text-left text-[11px]">
      <thead className="sticky top-0 border-b border-slate-200 bg-white text-[10px] font-semibold uppercase tracking-wider text-slate-500">
        <tr>
          <th className="p-2">ТН ВЭД</th>
          <th className="p-2">Описание</th>
          <th className="p-2">Время</th>
        </tr>
      </thead>
      <tbody className="text-slate-600">
        {items.map((row, i) => (
          <tr key={i} className="border-b border-slate-200">
            <td className="cc-mono whitespace-nowrap p-2 text-indigo-700">{String(row.confirmed_hs || '—')}</td>
            <td className="max-w-[min(220px,45vw)] truncate p-2" title={String(row.description || '')}>
              {String(row.description || '—').slice(0, 96)}
            </td>
            <td className="cc-mono whitespace-nowrap p-2 text-slate-500">{formatDecisionTs(row.ts)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  </div>
);

const CopilotBundleView: React.FC<{ bundle: AssistantCopilotBundle; title: string }> = ({ bundle, title }) => {
  const classificationNote = bundle.classification?.note;
  return (
  <div className="cc-card-soft space-y-4 p-4">
    <div className="flex flex-wrap items-baseline justify-between gap-2">
      <span className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-500">{title}</span>
      {bundle.effective_hs_code && (
        <span className="cc-mono text-[13px] font-medium text-indigo-700">{bundle.effective_hs_code}</span>
      )}
    </div>
    <ul className="space-y-2">
      {bundle.pipeline?.map((step, i) => {
        const { label, line, skipped } = pipelineStepCaption(step);
        return (
          <li key={i} className={`cc-timeline-item ${skipped ? 'is-skip' : ''}`}>
            <span className="font-medium text-slate-800">{label}</span>
            <span className="mt-0.5 block text-slate-500">{line}</span>
          </li>
        );
      })}
    </ul>
    {Boolean(classificationNote) && (
      <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-[12px] text-amber-800">
        {String(classificationNote)}
      </div>
    )}
    {bundle.tnved_context && (bundle.tnved_context.title || (bundle.tnved_context.notes?.length ?? 0) > 0) && (
      <div className="space-y-2 border-t border-emerald-500/15 pt-3">
        <span className="cc-label">Справочник ТН ВЭД (БД)</span>
        {bundle.tnved_context.title && (
          <p className={`text-[12px] text-slate-700 ${TNVED_COMMODITY_NAME_CLASS}`}>
            {formatTnvedCommodityName(bundle.tnved_context.title)}
          </p>
        )}
        {bundle.tnved_context.description && (
          <p className={`text-[11px] leading-relaxed text-slate-500 ${TNVED_COMMODITY_NAME_CLASS}`}>
            {formatTnvedCommodityName(String(bundle.tnved_context.description)).slice(0, 400)}
          </p>
        )}
        {bundle.tnved_context.notes && bundle.tnved_context.notes.length > 0 && (
          <ul className="space-y-1 text-[11px] text-slate-400">
            {bundle.tnved_context.notes.slice(0, 4).map((n, i) => (
              <li key={i}>
                <span className="font-medium text-slate-700">{n.title}</span>
                {n.body ? <span className="ml-1">— {String(n.body).slice(0, 120)}</span> : null}
              </li>
            ))}
          </ul>
        )}
        {bundle.tnved_context.official_ett_url && (
          <a
            href={bundle.tnved_context.official_ett_url}
            target="_blank"
            rel="noreferrer"
            className="text-[11px] text-indigo-600 hover:underline"
          >
            ТН ВЭД и ЕТТ на сайте ЕЭК
          </a>
        )}
      </div>
    )}
    {bundle.payment?.breakdown && (
      <div className="space-y-2 border-t border-slate-200 pt-3">
        <span className="cc-label">Детализация платежей</span>
        <div className="grid grid-cols-2 gap-x-3 gap-y-1 text-[12px]">
          {Object.entries(bundle.payment.breakdown).map(([k, v]) => (
            <React.Fragment key={k}>
              <span className="text-slate-500">{k}</span>
              <span className="cc-mono text-right text-slate-700">
                {typeof v === 'number' ? v.toLocaleString('ru-RU') : String(v)}
              </span>
            </React.Fragment>
          ))}
        </div>
      </div>
    )}
    {bundle.non_tariff && (
      <div className="space-y-2 border-t border-slate-200 pt-3">
        <span className="cc-label">Нетарифный контроль</span>
        <div className="text-[12px] text-slate-400">
          Статус:{' '}
          <span className="font-medium text-slate-700">{bundle.non_tariff.status}</span>
        </div>
        {Array.isArray(bundle.non_tariff.tr_ts) &&
          bundle.non_tariff.tr_ts.length > 0 && (
            <div className="text-[12px] text-slate-400">
              ТР ТС:{' '}
              <span className="text-slate-700">{bundle.non_tariff.tr_ts.join(', ')}</span>
            </div>
          )}
      </div>
    )}
  </div>
  );
};

const CopilotAiView: React.FC<{ ai: AssistantCopilotAi }> = ({ ai }) => (
  <div className="space-y-3 text-[13px] leading-relaxed">
    {ai.summary && (
      <div className="rounded-xl border border-indigo-200 bg-indigo-50 p-4 text-slate-800">
        <div className="mb-1.5 text-[10px] font-semibold uppercase tracking-[0.2em] text-indigo-700">Экспертная сводка</div>
        <p className="text-[13px] text-slate-700">{ai.summary}</p>
      </div>
    )}
    {ai.note && (
      <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-[12px] text-amber-800">{ai.note}</div>
    )}
    {(ai.classification_advice || ai.payment_comment || ai.non_tariff_comment || ai.documents_comment) && (
      <div className="grid gap-2 sm:grid-cols-2">
        {ai.classification_advice && (
          <div className="cc-card-soft p-3">
            <div className="cc-label mb-1">Классификация</div>
            <p className="text-[12px] text-slate-400">{ai.classification_advice}</p>
          </div>
        )}
        {ai.payment_comment && (
          <div className="cc-card-soft p-3">
            <div className="cc-label mb-1">Платежи</div>
            <p className="text-[12px] text-slate-400">{ai.payment_comment}</p>
          </div>
        )}
        {ai.non_tariff_comment && (
          <div className="cc-card-soft p-3">
            <div className="cc-label mb-1">Нетарифка</div>
            <p className="text-[12px] text-slate-400">{ai.non_tariff_comment}</p>
          </div>
        )}
        {ai.documents_comment && (
          <div className="cc-card-soft p-3">
            <div className="cc-label mb-1">Документы</div>
            <p className="text-[12px] text-slate-400">{ai.documents_comment}</p>
          </div>
        )}
      </div>
    )}
    {ai.risks && ai.risks.length > 0 && (
      <div className="rounded-xl border border-amber-200 bg-gradient-to-br from-amber-50 to-white p-4">
        <div className="mb-2 text-[10px] font-semibold uppercase tracking-[0.18em] text-amber-800">Факторы внимания</div>
        <ul className="space-y-1.5 text-[12px] text-amber-800">
          {ai.risks.map((r, i) => (
            <li key={i} className="flex gap-2">
              <span className="text-amber-500/80">·</span>
              <span>{r}</span>
            </li>
          ))}
        </ul>
      </div>
    )}
    {ai.next_steps && ai.next_steps.length > 0 && (
      <div className="cc-card-soft p-4">
        <div className="cc-label mb-2">Рекомендуемые действия</div>
        <ol className="list-decimal space-y-1.5 pl-4 text-[12px] text-slate-400">
          {ai.next_steps.map((s, i) => (
            <li key={i}>{s}</li>
          ))}
        </ol>
      </div>
    )}
    {ai.disclaimer && (
      <details className="cc-disclosure">
        <summary>Юридическая оговорка</summary>
        <div className="cc-disclosure-body text-[11px] leading-relaxed text-slate-500">{ai.disclaimer}</div>
      </details>
    )}
  </div>
);

type AssistantPageProps = {
  assistantOpenJob?: AssistantNavigationJob | null;
  onAssistantOpenJobConsumed?: () => void;
};

export const Assistant: React.FC<AssistantPageProps> = ({
  assistantOpenJob,
  onAssistantOpenJobConsumed,
}) => {
  const [auditClientId, setAuditClientId] = useState(() => sessionStorage.getItem('cc_audit_client_id') || '');
  const [auditSubject, setAuditSubject] = useState(() => sessionStorage.getItem('cc_audit_subject') || '');
  const [mode, setMode] = useState<'copilot' | 'batch' | 'legacy'>('copilot');

  const [hsCode, setHsCode] = useState('');
  const [description, setDescription] = useState('');
  const [country, setCountry] = useState('CN');
  const [permits, setPermits] = useState<PermitInput[]>([{ type: 'ДС', number: '' }]);

  const [batchLines, setBatchLines] = useState<BatchLine[]>(() => [emptyBatchLine()]);
  const [legacyLines, setLegacyLines] = useState<LegacyLine[]>(() => [emptyLegacyLine()]);

  const [customsValue, setCustomsValue] = useState('');
  const [freight, setFreight] = useState('');
  const [runAiClass, setRunAiClass] = useState(false);
  const [runPayment, setRunPayment] = useState(true);
  const [runRegistry, setRunRegistry] = useState(false);
  const [saveCopilotHistory, setSaveCopilotHistory] = useState(false);
  const [copilotDocumentId, setCopilotDocumentId] = useState(() => localStorage.getItem('cc_last_ingested_id') || '');

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [copilotResult, setCopilotResult] = useState<{
    bundle: AssistantCopilotBundle;
    ai: AssistantCopilotAi;
  } | null>(null);

  const [batchResult, setBatchResult] = useState<{
    bundles: AssistantCopilotBundle[];
    ai: AssistantCopilotAi;
  } | null>(null);

  const [legacyResult, setLegacyResult] = useState<AssistantAnalyzeResponse | null>(null);

  const [logSuggestedHs, setLogSuggestedHs] = useState('');
  const [logConfirmedHs, setLogConfirmedHs] = useState('');
  const [logDescForLog, setLogDescForLog] = useState('');
  const [logNotes, setLogNotes] = useState('');
  const [logStatus, setLogStatus] = useState<string | null>(null);
  const [recentDecisions, setRecentDecisions] = useState<AssistantDecisionRecord[]>([]);
  const [showRecent, setShowRecent] = useState(false);
  const [similarHints, setSimilarHints] = useState<AssistantDecisionHintItem[]>([]);
  const [hsSuggestions, setHsSuggestions] = useState<AssistantHsSuggestionItem[]>([]);
  const [journalStats, setJournalStats] = useState<AssistantJournalStatsResponse | null>(null);
  const [journalStatsLoading, setJournalStatsLoading] = useState(false);
  const journalPanelPrimed = useRef(false);
  const lastHandledOpenJobId = useRef<number | null>(null);

  const declarantChatRef = useRef<DeclarantChatThreadHandle>(null);
  const [hasCalcContext, setHasCalcContext] = useState(() => !!getAssistantCalculationContext());

  const similarQuery = React.useMemo(() => {
    if (mode === 'copilot') return description.trim();
    if (mode === 'batch')
      return batchLines
        .map((r) => r.description.trim())
        .filter(Boolean)
        .join(' | ')
        .slice(0, 500);
    return legacyLines
      .map((r) => r.description.trim())
      .filter(Boolean)
      .join(' | ')
      .slice(0, 500);
  }, [mode, description, batchLines, legacyLines]);

  useEffect(() => {
    return subscribeAssistantCalculationContext(() => {
      setHasCalcContext(!!getAssistantCalculationContext());
    });
  }, []);

  useEffect(() => {
    const job = assistantOpenJob;
    if (!job) return;
    if (lastHandledOpenJobId.current === job.id) return;
    lastHandledOpenJobId.current = job.id;
    if (job.calculatorConsult) {
      const ctx = job.calculatorConsult.context;
      setAssistantCalculationContext(ctx);
      const raw = (ctx.hs_code || '').replace(/\D/g, '');
      const hsShown = raw.length === 10 ? formatCode(raw) : (ctx.hs_code || '').trim() || '—';
      declarantChatRef.current?.resetWithMessages([
        { role: 'assistant', text: `Вижу ваш расчет по коду ${hsShown}. Чем я могу помочь?` },
      ]);
      onAssistantOpenJobConsumed?.();
      return;
    }
    const t = (job.chatPrefillText || '').trim();
    if (t) declarantChatRef.current?.setInput(t);
    onAssistantOpenJobConsumed?.();
  }, [assistantOpenJob, onAssistantOpenJobConsumed]);

  useEffect(() => {
    if (similarQuery.length < 3) {
      setSimilarHints([]);
      setHsSuggestions([]);
      return;
    }
    const t = window.setTimeout(() => {
      api
        .get<AssistantDecisionHintsResponse>('/assistant/decisions/hints', {
          params: { q: similarQuery, similar_limit: 6, hs_limit: 8 },
        })
        .then(({ data }) => {
          setSimilarHints(Array.isArray(data.similar) ? data.similar : []);
          setHsSuggestions(Array.isArray(data.hs_suggestions) ? data.hs_suggestions : []);
        })
        .catch(() => {
          setSimilarHints([]);
          setHsSuggestions([]);
        });
    }, 450);
    return () => window.clearTimeout(t);
  }, [similarQuery]);

  useEffect(() => {
    if (copilotResult?.bundle) {
      const hs = String(copilotResult.bundle.effective_hs_code || '');
      setLogSuggestedHs(hs);
      setLogConfirmedHs(hs);
      setLogDescForLog(description);
    }
  }, [copilotResult, description]);

  useEffect(() => {
    if (batchResult?.bundles?.length) {
      const hsList = batchResult.bundles.map((b) => b.effective_hs_code).filter(Boolean);
      setLogSuggestedHs(hsList.join(', '));
      setLogConfirmedHs(String(batchResult.bundles[0].effective_hs_code || ''));
      setLogDescForLog(
        batchResult.bundles
          .map((b) => b.description)
          .filter(Boolean)
          .join(' | ')
          .slice(0, 800),
      );
    }
  }, [batchResult]);

  const applyHintHs = (hs: string) => {
    const c = (hs || '').replace(/\D/g, '').slice(0, 10);
    if (!c) return;
    if (mode === 'copilot') setHsCode(c);
    else if (mode === 'batch')
      setBatchLines((rows) =>
        rows.length ? rows.map((r, i) => (i === 0 ? { ...r, hs_code: c } : r)) : rows,
      );
    else
      setLegacyLines((rows) =>
        rows.length ? rows.map((r, i) => (i === 0 ? { ...r, hs_code: c } : r)) : rows,
      );
  };

  const persistKeys = () => {
    if (auditClientId.trim()) sessionStorage.setItem('cc_audit_client_id', auditClientId.trim());
    else sessionStorage.removeItem('cc_audit_client_id');
    if (auditSubject.trim()) sessionStorage.setItem('cc_audit_subject', auditSubject.trim());
    else sessionStorage.removeItem('cc_audit_subject');
  };

  const addPermit = () => setPermits((p) => [...p, { type: 'ДС', number: '' }]);
  const removePermit = (i: number) => setPermits((p) => p.filter((_, j) => j !== i));
  const updatePermit = (i: number, field: 'type' | 'number', v: string) =>
    setPermits((p) => p.map((x, j) => (j === i ? { ...x, [field]: v } : x)));

  const updateBatchLine = (id: string, patch: Partial<BatchLine>) =>
    setBatchLines((rows) => rows.map((r) => (r.id === id ? { ...r, ...patch } : r)));

  const addBatchPermit = (lineId: string) =>
    setBatchLines((rows) =>
      rows.map((r) => (r.id === lineId ? { ...r, permits: [...r.permits, { type: 'ДС', number: '' }] } : r)),
    );

  const removeBatchPermit = (lineId: string, pi: number) =>
    setBatchLines((rows) =>
      rows.map((r) =>
        r.id === lineId ? { ...r, permits: r.permits.filter((_, j) => j !== pi) } : r,
      ),
    );

  const updateBatchPermit = (lineId: string, pi: number, field: 'type' | 'number', v: string) =>
    setBatchLines((rows) =>
      rows.map((r) =>
        r.id === lineId
          ? {
              ...r,
              permits: r.permits.map((x, j) => (j === pi ? { ...x, [field]: v } : x)),
            }
          : r,
      ),
    );

  const updateLegacyLine = (id: string, patch: Partial<LegacyLine>) =>
    setLegacyLines((rows) => rows.map((r) => (r.id === id ? { ...r, ...patch } : r)));

  const addLegacyPermit = (lineId: string) =>
    setLegacyLines((rows) =>
      rows.map((r) => (r.id === lineId ? { ...r, permits: [...r.permits, { type: 'ДС', number: '' }] } : r)),
    );

  const removeLegacyPermit = (lineId: string, pi: number) =>
    setLegacyLines((rows) =>
      rows.map((r) =>
        r.id === lineId ? { ...r, permits: r.permits.filter((_, j) => j !== pi) } : r,
      ),
    );

  const updateLegacyPermit = (lineId: string, pi: number, field: 'type' | 'number', v: string) =>
    setLegacyLines((rows) =>
      rows.map((r) =>
        r.id === lineId
          ? {
              ...r,
              permits: r.permits.map((x, j) => (j === pi ? { ...x, [field]: v } : x)),
            }
          : r,
      ),
    );

  const handleCopilot = async () => {
    if (!description.trim() && !hsCode.trim()) {
      setError('Укажите описание или код ТН ВЭД');
      return;
    }
    setLoading(true);
    setError(null);
    setCopilotResult(null);
    persistKeys();
    const cv = parseFloat(customsValue.replace(',', '.'));
    const fr = parseFloat(freight.replace(',', '.')) || 0;
    try {
      const { data } = await api.post<AssistantCopilotResponse>('/assistant/copilot', {
        description: description.trim(),
        hs_code: hsCode.trim(),
        country: country || null,
        customs_value: Number.isFinite(cv) && cv > 0 ? cv : null,
        freight: fr,
        permits: permits.filter((p) => p.number.trim()),
        run_ai_classification: runAiClass,
        run_payment: runPayment,
        run_registry_verify: runRegistry,
        save_calculation_history: saveCopilotHistory,
        document_id: copilotDocumentId.trim() || undefined,
        user_ref: auditClientId.trim() || undefined,
      });
      setCopilotResult({ bundle: data.bundle, ai: data.ai || {} });
    } catch (e) {
      setError(getUserFacingApiError(e, 'Не удалось выполнить разбор. Попробуйте позже.'));
    } finally {
      setLoading(false);
    }
  };

  const handleBatchCopilot = async () => {
    const valid = batchLines.filter((r) => r.description.trim() || r.hs_code.trim());
    if (valid.length === 0) {
      setError('Добавьте хотя бы одну позицию с описанием или кодом ТН ВЭД');
      return;
    }
    setLoading(true);
    setError(null);
    setBatchResult(null);
    persistKeys();
    try {
      const items = valid.map((r) => {
        const cv = parseFloat(r.customs_value.replace(',', '.'));
        const fr = parseFloat(r.freight.replace(',', '.')) || 0;
        return {
          description: r.description.trim(),
          hs_code: r.hs_code.trim(),
          country: r.country || null,
          customs_value: Number.isFinite(cv) && cv > 0 ? cv : null,
          freight: fr,
          permits: r.permits.filter((p) => p.number.trim()),
        };
      });
      const { data } = await api.post<AssistantCopilotBatchResponse>('/assistant/copilot/batch', {
        items,
        run_ai_classification: runAiClass,
        run_payment: runPayment,
        run_registry_verify: runRegistry,
        save_calculation_history: saveCopilotHistory,
        document_id: copilotDocumentId.trim() || undefined,
        user_ref: auditClientId.trim() || undefined,
      });
      setBatchResult({ bundles: data.bundles || [], ai: data.ai || {} });
    } catch (e) {
      setError(getUserFacingApiError(e, 'Не удалось выполнить пакетный разбор. Попробуйте позже.'));
    } finally {
      setLoading(false);
    }
  };

  const handleLegacyAnalyze = async () => {
    const items = legacyLines
      .filter((r) => r.hs_code.trim())
      .map((r) => ({
        hs_code: r.hs_code.trim(),
        description: r.description.trim(),
        country: r.country || null,
        permits: r.permits.filter((p) => p.number.trim()),
      }));
    if (items.length === 0) {
      setError('Укажите код ТН ВЭД хотя бы в одной строке');
      return;
    }
    setLoading(true);
    setError(null);
    setLegacyResult(null);
    persistKeys();
    try {
      const { data } = await api.post<AssistantAnalyzeResponse>('/assistant/analyze', {
        items,
      });
      setLegacyResult(data);
    } catch (e) {
      setError(getUserFacingApiError(e, 'Не удалось выполнить анализ. Попробуйте позже.'));
    } finally {
      setLoading(false);
    }
  };

  const handleLogDecision = async () => {
    if (!logConfirmedHs.trim()) {
      setLogStatus('Укажите подтверждённый ТН ВЭД');
      return;
    }
    setLogStatus(null);
    persistKeys();
    try {
      await api.post('/assistant/decisions/log', {
        description: logDescForLog.trim(),
        suggested_hs: logSuggestedHs.trim(),
        confirmed_hs: logConfirmedHs.trim(),
        source: mode === 'batch' ? 'ui_batch' : 'ui_copilot',
        notes: logNotes.trim(),
      });
      setLogStatus('Запись сохранена');
    } catch (e) {
      setLogStatus(getUserFacingApiError(e, 'Не удалось сохранить запись.'));
    }
  };

  const loadRecentDecisions = async () => {
    try {
      const { data } = await api.get<AssistantDecisionsRecentResponse>('/assistant/decisions/recent', { params: { limit: 15 } });
      setRecentDecisions(data.items || []);
      setShowRecent(true);
    } catch {
      setRecentDecisions([]);
    }
  };

  const loadJournalStats = async () => {
    setJournalStatsLoading(true);
    try {
      const { data } = await api.get<AssistantJournalStatsResponse>('/assistant/decisions/stats');
      setJournalStats(data);
    } catch {
      setJournalStats({ status: 'ERROR', message: 'Не удалось загрузить статистику' });
    } finally {
      setJournalStatsLoading(false);
    }
  };

  const onJournalPanelToggle = (e: React.SyntheticEvent<HTMLDetailsElement>) => {
    if (e.currentTarget.open && !journalPanelPrimed.current) {
      journalPanelPrimed.current = true;
      void loadJournalStats();
    }
  };

  const aiRiskLevel = React.useMemo(() => {
    let risks = 0;
    if (mode === 'copilot') risks = copilotResult?.ai?.risks?.length || 0;
    else if (mode === 'batch') risks = batchResult?.ai?.risks?.length || 0;
    else risks = legacyResult?.ai?.risks?.length || 0;

    if (mode === 'copilot' && !copilotResult) return null;
    if (mode === 'batch' && !batchResult) return null;
    if (mode === 'legacy' && !legacyResult) return null;

    if (risks >= 4) return { level: 'Высокий', cls: 'cc-badge-err', score: 90 };
    if (risks >= 2) return { level: 'Средний', cls: 'cc-badge-warn', score: 60 };
    return { level: 'Низкий', cls: 'cc-badge-ok', score: 25 };
  }, [copilotResult, batchResult, legacyResult, mode]);

  const { health, assistantLlmConfigured } = useClientCapabilities();
  const assistantAllowed = health !== 'loading' && assistantLlmConfigured;

  if (health === 'loading') {
    return (
      <div className="space-y-3 py-10">
        <div className="cc-skeleton mx-auto h-6 w-full max-w-lg rounded-lg" />
        <div className="cc-skeleton h-48 w-full rounded-xl" />
      </div>
    );
  }

  if (!assistantAllowed) {
    return (
      <div className="rounded-xl border border-slate-200 bg-slate-50 px-6 py-12 text-center text-[13px] text-slate-600">
        Консультант по декларации сейчас недоступен.
      </div>
    );
  }

  return (
    <div className="space-y-5">
      <p className="text-[12px] leading-relaxed text-slate-500">
        Подбор кода, платежи, меры и проверки в одном диалоге.
      </p>

      <div className="cc-card-soft p-4">
        <DeclarantChatThread
          ref={declarantChatRef}
          variant="full"
          headerTitle="Чат с декларантом"
          headerExtra={
            hasCalcContext ? (
              <span className="rounded-full border border-emerald-200 bg-emerald-100 px-2 py-0.5 text-[10px] text-emerald-800">
                контекст расчёта из калькулятора
              </span>
            ) : (
              <span className="text-[10px] text-slate-600">
                после расчёта на вкладке «Платежи» контекст подставится автоматически
              </span>
            )
          }
          onBeforeSend={persistKeys}
        />
      </div>

      <div className="cc-segmented flex w-full sm:w-auto">
        <button type="button" data-active={mode === 'copilot'} onClick={() => setMode('copilot')}>
          Конвейер
        </button>
        <button type="button" data-active={mode === 'batch'} onClick={() => setMode('batch')}>
          Пакет
        </button>
        <button type="button" data-active={mode === 'legacy'} onClick={() => setMode('legacy')}>
          Нетарифка
        </button>
      </div>

      <details className="cc-disclosure" onToggle={onJournalPanelToggle}>
        <summary>Журнал подтверждений</summary>
        <div className="cc-disclosure-body space-y-3">
          {journalStatsLoading && (
            <div className="space-y-2">
              <div className="cc-skeleton h-4 w-40" />
              <div className="cc-skeleton h-16 w-full" />
            </div>
          )}
          {!journalStatsLoading && journalStats && <JournalStatsPanel data={journalStats} />}
          <div className="flex flex-wrap gap-2">
            <button type="button" className="cc-btn-ghost" onClick={() => void loadJournalStats()}>
              Обновить сводку
            </button>
            <button type="button" className="cc-btn-ghost" onClick={() => void loadRecentDecisions()}>
              Недавние записи
            </button>
          </div>
          {showRecent && recentDecisions.length > 0 && (
            <RecentDecisionsTable items={recentDecisions} />
          )}
        </div>
      </details>

      <details className="cc-disclosure">
        <summary>Дополнительные настройки</summary>
        <div className="cc-disclosure-body space-y-3">
          <div className="grid gap-3 md:grid-cols-2">
            <label className="block space-y-1">
              <span className="cc-label">Идентификатор клиента</span>
              <input
                value={auditClientId}
                onChange={(e) => setAuditClientId(e.target.value)}
                placeholder="Для приоритета записей журнала"
                className="cc-input"
              />
            </label>
            <label className="block space-y-1">
              <span className="cc-label">Тема аудита</span>
              <input
                value={auditSubject}
                onChange={(e) => setAuditSubject(e.target.value)}
                placeholder="Номер ДТ, партия…"
                className="cc-input"
              />
            </label>
          </div>
          <label className="flex cursor-pointer items-center gap-2 text-[12px] text-slate-700">
            <input
              type="checkbox"
              className="rounded border-slate-600"
              checked={saveCopilotHistory}
              onChange={(e) => setSaveCopilotHistory(e.target.checked)}
            />
            Сохранять блок платежей конвейера в журнал расчётов (раздел «Платежи»; для batch — сводка по позициям)
          </label>
          <label className="block max-w-xl space-y-1">
            <span className="cc-label">document_id для истории расчётов</span>
            <input
              value={copilotDocumentId}
              onChange={(e) => setCopilotDocumentId(e.target.value)}
              placeholder="UUID из вкладки «Документы» после сохранения в БД"
              className="cc-input cc-mono text-[11px]"
            />
            <button
              type="button"
              className="mt-1 text-[10px] text-indigo-600 hover:underline"
              onClick={() => setCopilotDocumentId(localStorage.getItem('cc_last_ingested_id') || '')}
            >
              Подставить последний сохранённый документ
            </button>
          </label>
        </div>
      </details>

      {(similarHints.length > 0 || hsSuggestions.length > 0) && (
        <div className="cc-card-soft space-y-3 p-3 text-[11px]">
          {hsSuggestions.length > 0 && (
            <div className="space-y-2">
              <span className="cc-label">Подсказки по журналу</span>
              <div className="flex flex-wrap gap-2">
                {hsSuggestions.map((h) => (
                  <button
                    key={h.hs_code}
                    type="button"
                    className="rounded border border-slate-200 bg-slate-50 px-2 py-1 font-mono text-xs text-indigo-700 hover:bg-indigo-50"
                    title={h.sample_description || ''}
                    onClick={() => applyHintHs(h.hs_code)}
                  >
                    {h.hs_code}
                    <span className="ml-1 text-slate-500">
                      ×{h.count} ~{h.best_similarity}
                    </span>
                    {(h.client_boosted_rows || 0) > 0 && (
                      <span className="ml-1 text-emerald-400/90" title="Записи вашего client_id">
                        ●
                      </span>
                    )}
                  </button>
                ))}
              </div>
            </div>
          )}
          {similarHints.length > 0 && (
            <div className="space-y-2">
              <span className="cc-label">Похожие описания</span>
              <ul className="space-y-1.5 text-slate-400">
                {similarHints.map((h, i) => (
                  <li key={i} className="flex flex-wrap items-baseline gap-2">
                    <button
                      type="button"
                      className="font-mono text-indigo-700 hover:underline"
                      onClick={() => applyHintHs(h.confirmed_hs || '')}
                      title="Подставить код в форму"
                    >
                      {h.confirmed_hs || '—'}
                    </button>
                    <span>
                      {(h.description || '').slice(0, 120)}
                      {(h.description || '').length > 120 ? '…' : ''}
                    </span>
                    {typeof h.similarity === 'number' && (
                      <span className="text-slate-600">
                        ~{h.similarity}
                        {h.client_match && (
                          <span className="ml-1 text-emerald-400" title="Ваш client_id">
                            ●
                          </span>
                        )}
                      </span>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}

      {mode !== 'batch' && mode !== 'legacy' && (
        <>
          <div className="grid gap-3 md:grid-cols-2 text-xs">
            <label className="space-y-1">
              <span className="cc-label">Код ТН ВЭД (можно пусто — подбор по описанию)</span>
              <input
                value={hsCode}
                onChange={(e) => setHsCode(e.target.value)}
                placeholder="8509400000"
                className="cc-input"
              />
            </label>
            <label className="space-y-1">
              <span className="cc-label">Страна</span>
              <CountrySelect value={country} onChange={setCountry} />
            </label>
          </div>

          <label className="block space-y-1 text-xs">
            <span className="cc-label">Описание товара</span>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="Опишите товар (обязательно, если код ТН ВЭД не указан)"
              className="cc-input min-h-[92px]"
            />
          </label>

          <div className="cc-card-soft space-y-3 p-3 text-xs">
            <div className="grid gap-2 md:grid-cols-2">
              <label className="space-y-1">
                <span className="cc-label">Таможенная стоимость (₽)</span>
                <input
                  value={customsValue}
                  onChange={(e) => setCustomsValue(e.target.value)}
                  placeholder="500000"
                  className="cc-input"
                />
              </label>
              <label className="space-y-1">
                <span className="cc-label">Фрахт / доходимость (₽)</span>
                <input
                  value={freight}
                  onChange={(e) => setFreight(e.target.value)}
                  placeholder="0"
                  className="cc-input"
                />
              </label>
            </div>
            <label className="flex cursor-pointer items-center gap-2">
              <input type="checkbox" checked={runAiClass} onChange={(e) => setRunAiClass(e.target.checked)} />
              Подобрать код ТН ВЭД по описанию (если код не указан)
            </label>
            <label className="flex cursor-pointer items-center gap-2">
              <input type="checkbox" checked={runPayment} onChange={(e) => setRunPayment(e.target.checked)} />
              Считать платежи (пошлина, НДС, акциз…)
            </label>
            <label className="flex cursor-pointer items-center gap-2 text-amber-700">
              <input type="checkbox" checked={runRegistry} onChange={(e) => setRunRegistry(e.target.checked)} />
              Проверять СС/ДС в реестре ФСА (медленно, нужна сеть)
            </label>
          </div>

          <div className="cc-card-soft space-y-2 p-3">
            <span className="cc-label text-xs">Разрешительные документы</span>
            {permits.map((p, i) => (
              <div key={i} className="flex items-center gap-2">
                <select
                  value={p.type}
                  onChange={(e) => updatePermit(i, 'type', e.target.value)}
                  className="cc-input w-24 text-xs"
                >
                  <option value="СС">СС</option>
                  <option value="ДС">ДС</option>
                  <option value="СГР">СГР</option>
                </select>
                <input
                  value={p.number}
                  onChange={(e) => updatePermit(i, 'number', e.target.value)}
                  placeholder="Номер"
                  className="cc-input flex-1 text-xs"
                />
                <button type="button" onClick={() => removePermit(i)} className="cc-btn-ghost text-red-600">
                  ×
                </button>
              </div>
            ))}
            <button type="button" onClick={addPermit} className="cc-btn-ghost text-xs">
              + Добавить документ
            </button>
          </div>

          <button
            disabled={loading || (!description.trim() && !hsCode.trim())}
            onClick={handleCopilot}
            className="cc-btn-primary"
          >
            {loading ? 'Конвейер…' : 'Запустить умный конвейер'}
          </button>
        </>
      )}

      {mode === 'batch' && (
        <div className="space-y-3 text-xs">
          <div className="cc-card-soft space-y-3 p-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span className="cc-label">Товарные позиции (до 50)</span>
              <button
                type="button"
                className="cc-btn-ghost"
                onClick={() => setBatchLines((r) => [...r, emptyBatchLine()])}
              >
                + Строка
              </button>
            </div>
            {batchLines.map((row, idx) => (
              <div key={row.id} className="space-y-2 rounded-lg border border-slate-700/50 p-2">
                <div className="flex items-center justify-between">
                  <span className="text-slate-400">Позиция {idx + 1}</span>
                  {batchLines.length > 1 && (
                    <button
                      type="button"
                      className="cc-btn-ghost text-red-600"
                      onClick={() => setBatchLines((r) => r.filter((x) => x.id !== row.id))}
                    >
                      Удалить
                    </button>
                  )}
                </div>
                <div className="grid gap-2 md:grid-cols-2">
                  <input
                    className="cc-input"
                    placeholder="Код ТН ВЭД"
                    value={row.hs_code}
                    onChange={(e) => updateBatchLine(row.id, { hs_code: e.target.value })}
                  />
                  <CountrySelect
                    value={row.country}
                    onChange={(v) => updateBatchLine(row.id, { country: v })}
                  />
                </div>
                <textarea
                  className="cc-input min-h-[64px]"
                  placeholder="Описание товара"
                  value={row.description}
                  onChange={(e) => updateBatchLine(row.id, { description: e.target.value })}
                />
                <div className="grid gap-2 md:grid-cols-2">
                  <input
                    className="cc-input"
                    placeholder="Таможенная стоимость (₽)"
                    value={row.customs_value}
                    onChange={(e) => updateBatchLine(row.id, { customs_value: e.target.value })}
                  />
                  <input
                    className="cc-input"
                    placeholder="Фрахт (₽)"
                    value={row.freight}
                    onChange={(e) => updateBatchLine(row.id, { freight: e.target.value })}
                  />
                </div>
                <div className="space-y-1">
                  <span className="text-slate-500">Документы</span>
                  {row.permits.map((p, pi) => (
                    <div key={pi} className="flex items-center gap-2">
                      <select
                        value={p.type}
                        onChange={(e) => updateBatchPermit(row.id, pi, 'type', e.target.value)}
                        className="cc-input w-24 text-xs"
                      >
                        <option value="СС">СС</option>
                        <option value="ДС">ДС</option>
                        <option value="СГР">СГР</option>
                      </select>
                      <input
                        value={p.number}
                        onChange={(e) => updateBatchPermit(row.id, pi, 'number', e.target.value)}
                        placeholder="Номер"
                        className="cc-input flex-1 text-xs"
                      />
                      <button
                        type="button"
                        onClick={() => removeBatchPermit(row.id, pi)}
                        className="cc-btn-ghost text-red-600"
                      >
                        ×
                      </button>
                    </div>
                  ))}
                  <button type="button" className="cc-btn-ghost text-[11px]" onClick={() => addBatchPermit(row.id)}>
                    + Документ
                  </button>
                </div>
              </div>
            ))}
          </div>

          <div className="cc-card-soft space-y-2 p-3">
            <label className="flex cursor-pointer items-center gap-2">
              <input type="checkbox" checked={runAiClass} onChange={(e) => setRunAiClass(e.target.checked)} />
              Подбор кода ТН ВЭД для строк без кода
            </label>
            <label className="flex cursor-pointer items-center gap-2">
              <input type="checkbox" checked={runPayment} onChange={(e) => setRunPayment(e.target.checked)} />
              Считать платежи по строкам
            </label>
            <label className="flex cursor-pointer items-center gap-2 text-amber-700">
              <input type="checkbox" checked={runRegistry} onChange={(e) => setRunRegistry(e.target.checked)} />
              Проверка ФСА по строкам
            </label>
          </div>

          <button type="button" onClick={handleBatchCopilot} disabled={loading} className="cc-btn-primary">
            {loading ? 'Пакетный конвейер…' : 'Запустить пакетный конвейер'}
          </button>
        </div>
      )}

      {mode === 'legacy' && (
        <div className="space-y-3 text-xs">
          <div className="cc-card-soft space-y-3 p-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span className="cc-label">Позиции (код ТН ВЭД обязателен в каждой заполняемой строке)</span>
              <button
                type="button"
                className="cc-btn-ghost"
                onClick={() => setLegacyLines((r) => [...r, emptyLegacyLine()])}
              >
                + Строка
              </button>
            </div>
            {legacyLines.map((row, idx) => (
              <div key={row.id} className="space-y-2 rounded-lg border border-slate-700/50 p-2">
                <div className="flex items-center justify-between">
                  <span className="text-slate-400">Строка {idx + 1}</span>
                  {legacyLines.length > 1 && (
                    <button
                      type="button"
                      className="cc-btn-ghost text-red-600"
                      onClick={() => setLegacyLines((r) => r.filter((x) => x.id !== row.id))}
                    >
                      Удалить
                    </button>
                  )}
                </div>
                <div className="grid gap-2 md:grid-cols-2">
                  <input
                    className="cc-input font-mono"
                    placeholder="ТН ВЭД *"
                    value={row.hs_code}
                    onChange={(e) => updateLegacyLine(row.id, { hs_code: e.target.value })}
                  />
                  <CountrySelect
                    value={row.country}
                    onChange={(v) => updateLegacyLine(row.id, { country: v })}
                  />
                </div>
                <textarea
                  className="cc-input min-h-[56px]"
                  placeholder="Описание"
                  value={row.description}
                  onChange={(e) => updateLegacyLine(row.id, { description: e.target.value })}
                />
                <div className="space-y-1">
                  {row.permits.map((p, pi) => (
                    <div key={pi} className="flex items-center gap-2">
                      <select
                        value={p.type}
                        onChange={(e) => updateLegacyPermit(row.id, pi, 'type', e.target.value)}
                        className="cc-input w-24 text-xs"
                      >
                        <option value="СС">СС</option>
                        <option value="ДС">ДС</option>
                        <option value="СГР">СГР</option>
                      </select>
                      <input
                        value={p.number}
                        onChange={(e) => updateLegacyPermit(row.id, pi, 'number', e.target.value)}
                        placeholder="Номер"
                        className="cc-input flex-1 text-xs"
                      />
                      <button
                        type="button"
                        onClick={() => removeLegacyPermit(row.id, pi)}
                        className="cc-btn-ghost text-red-600"
                      >
                        ×
                      </button>
                    </div>
                  ))}
                  <button type="button" className="cc-btn-ghost text-[11px]" onClick={() => addLegacyPermit(row.id)}>
                    + Документ
                  </button>
                </div>
              </div>
            ))}
          </div>
          <button type="button" onClick={handleLegacyAnalyze} disabled={loading} className="cc-btn-primary">
            {loading ? 'Анализируем…' : 'Анализ мер нетарифного регулирования (все строки)'}
          </button>
        </div>
      )}

      {loading && (
        <div className="space-y-2">
          <div className="cc-skeleton h-5 w-52" />
          <div className="cc-skeleton h-20 w-full" />
          <div className="cc-skeleton h-20 w-full" />
        </div>
      )}
      {error && (
        <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
          {error}
        </div>
      )}

      {mode === 'copilot' && copilotResult && (
        <div className="space-y-4 text-xs">
          <details className="cc-disclosure">
            <summary>Экспорт данных</summary>
            <div className="cc-disclosure-body flex flex-wrap gap-2">
              <button
                type="button"
                className="cc-btn-ghost"
                onClick={() =>
                  downloadJson(`tariff-copilot-${Date.now()}.json`, {
                    exported_at: new Date().toISOString(),
                    bundle: copilotResult.bundle,
                    ai: copilotResult.ai,
                  })
                }
              >
                Скачать JSON
              </button>
            </div>
          </details>
          <div className="cc-card-soft space-y-3 p-4">
            <span className="cc-label">Сохранить в журнал</span>
            <input
              className="cc-input font-mono"
              placeholder="Предложенный код"
              value={logSuggestedHs}
              onChange={(e) => setLogSuggestedHs(e.target.value)}
            />
            <input
              className="cc-input font-mono"
              placeholder="Подтверждённый код *"
              value={logConfirmedHs}
              onChange={(e) => setLogConfirmedHs(e.target.value)}
            />
            <textarea
              className="cc-input min-h-[56px]"
              placeholder="Описание (для истории)"
              value={logDescForLog}
              onChange={(e) => setLogDescForLog(e.target.value)}
            />
            <textarea
              className="cc-input min-h-[44px]"
              placeholder="Заметки (опционально)"
              value={logNotes}
              onChange={(e) => setLogNotes(e.target.value)}
            />
            <button type="button" className="cc-btn-primary" onClick={handleLogDecision}>
              Зафиксировать
            </button>
            {logStatus && <div className="text-[12px] text-amber-700">{logStatus}</div>}
          </div>
          {aiRiskLevel && (
            <div className="cc-card-soft p-4">
              <div className="mb-3 flex items-center justify-between gap-2">
                <span className="text-[11px] font-semibold uppercase tracking-[0.14em] text-slate-500">Оценка внимания</span>
                <span className={aiRiskLevel.cls}>{aiRiskLevel.level}</span>
              </div>
              <div className="cc-risk-bar">
                <span
                  className={
                    aiRiskLevel.score >= 80 ? 'bg-red-500' : aiRiskLevel.score >= 50 ? 'bg-amber-400' : 'bg-emerald-500'
                  }
                  style={{ width: `${aiRiskLevel.score}%` }}
                />
              </div>
            </div>
          )}
          <CopilotAiView ai={copilotResult.ai} />
          <CopilotBundleView bundle={copilotResult.bundle} title="Ход обработки" />
        </div>
      )}

      {mode === 'batch' && batchResult && (
        <div className="space-y-4 text-xs">
          <details className="cc-disclosure">
            <summary>Экспорт данных</summary>
            <div className="cc-disclosure-body flex flex-wrap gap-2">
              <button
                type="button"
                className="cc-btn-ghost"
                onClick={() =>
                  downloadJson(`tariff-batch-${Date.now()}.json`, {
                    exported_at: new Date().toISOString(),
                    bundles: batchResult.bundles,
                    ai: batchResult.ai,
                  })
                }
              >
                Скачать JSON
              </button>
            </div>
          </details>
          <div className="cc-card-soft space-y-3 p-4">
            <span className="cc-label">Сохранить в журнал</span>
            <input
              className="cc-input font-mono"
              placeholder="Предложенные коды"
              value={logSuggestedHs}
              onChange={(e) => setLogSuggestedHs(e.target.value)}
            />
            <input
              className="cc-input font-mono"
              placeholder="Подтверждённый код *"
              value={logConfirmedHs}
              onChange={(e) => setLogConfirmedHs(e.target.value)}
            />
            <textarea
              className="cc-input min-h-[56px]"
              placeholder="Описания позиций"
              value={logDescForLog}
              onChange={(e) => setLogDescForLog(e.target.value)}
            />
            <textarea
              className="cc-input min-h-[44px]"
              placeholder="Заметки"
              value={logNotes}
              onChange={(e) => setLogNotes(e.target.value)}
            />
            <button type="button" className="cc-btn-primary" onClick={handleLogDecision}>
              Зафиксировать
            </button>
            {logStatus && <div className="text-[12px] text-amber-700">{logStatus}</div>}
          </div>
          {aiRiskLevel && (
            <div className="cc-card-soft p-4">
              <div className="mb-3 flex items-center justify-between gap-2">
                <span className="text-[11px] font-semibold uppercase tracking-[0.14em] text-slate-500">Оценка внимания</span>
                <span className={aiRiskLevel.cls}>{aiRiskLevel.level}</span>
              </div>
              <div className="cc-risk-bar">
                <span
                  className={
                    aiRiskLevel.score >= 80 ? 'bg-red-500' : aiRiskLevel.score >= 50 ? 'bg-amber-400' : 'bg-emerald-500'
                  }
                  style={{ width: `${aiRiskLevel.score}%` }}
                />
              </div>
            </div>
          )}
          <CopilotAiView ai={batchResult.ai} />
          <div className="space-y-3">
            <span className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-500">Позиции</span>
            {batchResult.bundles.map((b, i) => (
              <CopilotBundleView key={i} bundle={b} title={`Строка ${i + 1}`} />
            ))}
          </div>
        </div>
      )}

      {mode === 'legacy' && legacyResult && (
        <div className="space-y-4 text-xs">
          <details className="cc-disclosure">
            <summary>Экспорт данных</summary>
            <div className="cc-disclosure-body">
              <button
                type="button"
                className="cc-btn-ghost"
                onClick={() =>
                  downloadJson(`tariff-legacy-${Date.now()}.json`, {
                    exported_at: new Date().toISOString(),
                    status: legacyResult.status,
                    items: legacyResult.items,
                    ai: legacyResult.ai,
                  })
                }
              >
                Скачать JSON
              </button>
            </div>
          </details>
          {aiRiskLevel && (
            <div className="cc-card-soft p-4">
              <div className="mb-3 flex items-center justify-between gap-2">
                <span className="text-[11px] font-semibold uppercase tracking-[0.14em] text-slate-500">Оценка внимания</span>
                <span className={aiRiskLevel.cls}>{aiRiskLevel.level}</span>
              </div>
              <div className="cc-risk-bar">
                <span
                  className={
                    aiRiskLevel.score >= 80 ? 'bg-red-500' : aiRiskLevel.score >= 50 ? 'bg-amber-400' : 'bg-emerald-500'
                  }
                  style={{ width: `${aiRiskLevel.score}%` }}
                />
              </div>
            </div>
          )}
          {Array.isArray(legacyResult.items) && legacyResult.items.length > 0 && (
            <div className="space-y-2">
              <strong className="text-slate-700">Результат проверки по правилам:</strong>
              {legacyResult.items.map((item, idx: number) => (
                <div key={idx} className="cc-card-soft space-y-1 p-3">
                  <span className="font-mono text-indigo-700">{item.hs_code}</span>
                  {(item.tr_ts ?? []).length > 0 && <div className="text-slate-400">ТР ТС: {(item.tr_ts ?? []).join(', ')}</div>}
                  {(item.required_permit_types ?? []).length > 0 && (
                    <div>Требуются: {(item.required_permit_types ?? []).join(', ')}</div>
                  )}
                  {(item.missing_permit_types ?? []).length > 0 && (
                    <div className="text-red-700">Не хватает: {(item.missing_permit_types ?? []).join(', ')}</div>
                  )}
                  {(item.advisory_requirements ?? []).length > 0 && (
                    <div className="rounded border border-amber-200 bg-amber-50 px-2 py-1.5 text-[11px] text-amber-900 space-y-1">
                      <div className="font-medium">Потенциальные требования</div>
                      {(item.advisory_requirements ?? []).map((a, ai) => (
                        <div key={ai} className="text-amber-800">
                          {a.permit_type}
                          {a.tr_ts ? ` · ТР ТС ${a.tr_ts}` : ''}
                          {' · '}
                          {a.applicability === 'needs_clarification' ? 'Требует уточнения' : 'Возможно'}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
          {legacyResult.ai?.conclusion && (
            <div className="cc-card-soft p-3 text-slate-700">
              <strong>Заключение консультанта:</strong> {legacyResult.ai.conclusion}
            </div>
          )}
          {legacyResult.ai?.risks && legacyResult.ai.risks.length > 0 && (
            <div className="rounded-xl border border-amber-200 bg-amber-50 p-3">
              <strong className="text-amber-800">Риски:</strong>
              <ul className="mt-1 list-inside list-disc text-amber-800">
                {legacyResult.ai.risks.map((r, i) => (
                  <li key={i}>{r}</li>
                ))}
              </ul>
            </div>
          )}
          {legacyResult.ai?.note && <div className="text-amber-700">{legacyResult.ai.note}</div>}
        </div>
      )}
    </div>
  );
};
