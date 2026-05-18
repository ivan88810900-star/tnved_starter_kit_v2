import React, { useCallback, useState } from 'react';
import { useDropzone } from 'react-dropzone';
import { CloudUpload, FileText, Files } from 'lucide-react';
import { api } from '../api/client';
import { getUserFacingApiError, userFacingMessage } from '../api/error';

const sleep = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms));

function downloadJson(filename: string, data: object) {
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = filename;
  a.click();
  URL.revokeObjectURL(a.href);
}

type Item = {
  line: number;
  description: string;
  quantity: number;
  unit: string;
  weight_gross: number;
  weight_net: number;
  unit_price: number;
  total_price: number;
};

type CheckRow = {
  check: string;
  title?: string;
  status: 'OK' | 'WARNING' | 'ERROR';
  detail: string;
};

type ExtractedPermit = { type: string; number: string };

type HsCodeCheck = {
  hs_match?: string;
  detail?: string;
  matched_registry_code?: string | null;
};

type RegistryPermitRow = {
  type?: string;
  status?: string;
  number?: string;
  holder?: string | null;
  valid_from?: string | null;
  valid_to?: string | null;
  registry_link?: string | null;
  registry_source?: string;
  verified_at?: string;
  hs_code_check?: HsCodeCheck;
  error?: string;
};

type DeclarationLine = {
  line: number;
  commercial_description: string;
  hs_code: string;
  hs_code_source?: string;
  tnved_title_ru?: string;
  graf31_ru: string;
  quantity: number;
  unit: string;
  weight_gross_kg: number;
  weight_net_kg: number;
  places_or_packages: number;
  permit_types: string[];
  tr_ts: string[];
  peculiarities: string[];
  applied_rule_names?: string[];
};

type DeclarationDraft = {
  status: string;
  summary: {
    lines_count: number;
    total_quantity: number;
    total_gross_weight_kg: number;
    total_places_or_packages: number;
    invoice_number?: string | null;
  };
  declaration_lines: DeclarationLine[];
  disclaimer: string;
};

type CopilotBundleRow = {
  effective_hs_code?: string;
  payment?: { breakdown?: { total_payable?: number } };
  non_tariff?: { status?: string };
};

type AiAnalyst = {
  summary?: string;
  classification_advice?: string;
  payment_comment?: string;
  non_tariff_comment?: string;
  documents_comment?: string;
  risks?: string[];
  next_steps?: string[];
  disclaimer?: string;
  note?: string;
  raw?: string;
};

type Result = {
  status: string;
  comparison_mode?: 'invoice_only' | 'invoice_and_packing';
  verdict?: { headline: string; detail: string };
  document_id?: string;
  persisted_to_db?: boolean;
  persist_error?: string;
  declaration_draft?: DeclarationDraft;
  invoice_number?: string | null;
  extracted_at?: string | null;
  items: Item[];
  checks: CheckRow[];
  summary: {
    errors: number;
    warnings: number;
    passed: number;
  };
  extracted_permits?: ExtractedPermit[];
  permits_registry_check?: RegistryPermitRow[];
  permits_registry_note?: string;
  ved_intel_status?: string;
  disclaimer_ved_intel?: string;
  customs_value_allocation_note?: string;
  ai_analyst?: AiAnalyst;
  copilot_batch?: { bundles?: CopilotBundleRow[] };
};

function buildVedExportPayload(result: Result): object {
  const bundles = result.copilot_batch?.bundles;
  const slimBundles = (bundles ?? []).map((b) => ({
    effective_hs_code: b.effective_hs_code,
    non_tariff_status: b.non_tariff?.status,
    total_payable: b.payment?.breakdown?.total_payable,
  }));
  return {
    exported_at: new Date().toISOString(),
    document_id: result.document_id,
    ved_intel_status: result.ved_intel_status,
    customs_value_allocation_note: result.customs_value_allocation_note,
    declaration_draft: result.declaration_draft,
    ai_analyst: result.ai_analyst,
    copilot_positions: slimBundles,
    extracted_permits: result.extracted_permits,
    permits_registry_check: result.permits_registry_check,
    summary: result.summary,
    status: result.status,
  };
}

const DOC_STATUS_LABEL: Record<string, string> = {
  OK: 'Итог: без критичных проблем',
  WARNING: 'Итог: есть предупреждения',
  ERROR: 'Итог: есть расхождения или ошибки данных',
};

const CHECK_STATUS_RU: Record<string, string> = {
  OK: 'Норма',
  WARNING: 'Внимание',
  ERROR: 'Проблема',
};

const REGISTRY_STATUS_RU: Record<string, string> = {
  VALID: 'Документ найден в реестре',
  NOT_FOUND: 'В реестре не найден',
  UNKNOWN: 'Статус не определён',
  SKIPPED: 'Проверка не выполнялась',
};

const HS_MATCH_RU: Record<string, string> = {
  ok: 'ТН ВЭД совпадает',
  partial: 'ТН ВЭД частично совпадает',
  mismatch: 'ТН ВЭД не совпадает с реестром',
  unknown: 'Сверка ТН ВЭД недоступна',
};

export const DocumentCheck: React.FC = () => {
  const [invoiceFile, setInvoiceFile] = useState<File | null>(null);
  const [packingFile, setPackingFile] = useState<File | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [result, setResult] = useState<Result | null>(null);
  const [error, setError] = useState<string | null>(null);
  /** По умолчанию: извлечь СС/ДС из PDF и проверить в ФСА/СГР. */
  const [extractPermits, setExtractPermits] = useState(true);
  const [verifyFsa, setVerifyFsa] = useState(true);
  const [skipRegistry, setSkipRegistry] = useState(false);
  const [hsCode, setHsCode] = useState('');
  const [useAiDeclaration, setUseAiDeclaration] = useState(true);
  /** Сохранять извлечённые данные в БД (ingested_documents + строки). */
  const [persistToDb, setPersistToDb] = useState(true);
  const [clientId, setClientId] = useState(() => localStorage.getItem('cc_client_id') || '');
  /** Полный разбор: нетарифные меры, платежи по строкам, сводка и риски */
  const [fullVedAnalyst, setFullVedAnalyst] = useState(true);
  const [countryOrigin, setCountryOrigin] = useState('CN');
  const [freightTotalRub, setFreightTotalRub] = useState('');
  /** Если в Excel нет total по строкам — распределить эту сумму (пропорционально qty или поровну) */
  const [fallbackCustomsTotalRub, setFallbackCustomsTotalRub] = useState('');
  const [runPaymentEstimates, setRunPaymentEstimates] = useState(true);
  /** Фоновый ВЭД-разбор: POST /ved-intelligent-analyze/async + опрос GET /ved-intel-jobs/{id} */
  const [vedBackgroundJob, setVedBackgroundJob] = useState(false);
  const [vedPdfLoading, setVedPdfLoading] = useState(false);
  type IngestedRow = {
    id: string;
    original_filename: string;
    status: string;
    lines_count?: number;
    created_at?: string | null;
  };
  const [ingestedList, setIngestedList] = useState<IngestedRow[] | null>(null);
  const [ingestedLoading, setIngestedLoading] = useState(false);

  const loadIngested = useCallback(async () => {
    setIngestedLoading(true);
    try {
      const { data } = await api.get<{ items: IngestedRow[] }>('/documents/ingested?limit=40');
      setIngestedList(data.items || []);
    } catch {
      setIngestedList([]);
    } finally {
      setIngestedLoading(false);
    }
  }, []);

  const [calcDocId, setCalcDocId] = useState(() => localStorage.getItem('cc_last_ingested_id') || '');
  const [calcRows, setCalcRows] = useState<
    Array<{ id: string; kind?: string; total_payable?: number | null; created_at?: string | null }>
  >([]);
  const [calcLoading, setCalcLoading] = useState(false);
  const loadCalculationsForDoc = async () => {
    const id = calcDocId.trim();
    if (!id) return;
    setCalcLoading(true);
    try {
      const { data } = await api.get<{ items: typeof calcRows }>(
        `/documents/ingested/${encodeURIComponent(id)}/calculations?limit=80`,
      );
      setCalcRows(data.items || []);
    } catch {
      setCalcRows([]);
    } finally {
      setCalcLoading(false);
    }
  };

  const onDropInvoice = useCallback((files: File[]) => {
    if (files[0]) setInvoiceFile(files[0]);
  }, []);

  const onDropPacking = useCallback((files: File[]) => {
    if (files[0]) setPackingFile(files[0]);
  }, []);

  const invoiceDrop = useDropzone({
    onDrop: onDropInvoice,
    multiple: false
  });
  const packingDrop = useDropzone({
    onDrop: onDropPacking,
    multiple: false
  });

  const canStart = Boolean(invoiceFile) && !isLoading;
  const reset = () => {
    setInvoiceFile(null);
    setPackingFile(null);
    setResult(null);
    setError(null);
    setExtractPermits(true);
    setVerifyFsa(true);
    setSkipRegistry(false);
    setHsCode('');
    setUseAiDeclaration(true);
    setPersistToDb(true);
  };

  const appendCommonFormFields = (formData: FormData) => {
    const doExtract = extractPermits || verifyFsa;
    formData.append('extract_permits', doExtract ? 'true' : 'false');
    formData.append('verify_fsa', verifyFsa ? 'true' : 'false');
    formData.append('skip_registry_verify', skipRegistry ? 'true' : 'false');
    const hs = hsCode.trim().replace(/\D/g, '');
    if (hs) formData.append('hs_code', hs);
    formData.append('use_ai_declaration', useAiDeclaration ? 'true' : 'false');
    formData.append('persist', persistToDb ? 'true' : 'false');
    const cid = clientId.trim();
    if (cid) {
      formData.append('client_id', cid);
      localStorage.setItem('cc_client_id', cid);
    }
  };

  const handleStart = async () => {
    if (!invoiceFile) return;
    setIsLoading(true);
    setError(null);
    setResult(null);
    try {
      const formData = new FormData();
      if (fullVedAnalyst) {
        formData.append('document', invoiceFile);
        if (packingFile) formData.append('companion', packingFile);
        formData.append('country', countryOrigin.trim().slice(0, 4).toUpperCase() || 'CN');
        const fr = parseFloat(freightTotalRub.replace(',', '.')) || 0;
        formData.append('freight_total_rub', String(Math.max(0, fr)));
        const fb = parseFloat(fallbackCustomsTotalRub.replace(',', '.')) || 0;
        formData.append('fallback_customs_total_rub', String(Math.max(0, fb)));
        formData.append('run_payment', runPaymentEstimates ? 'true' : 'false');
        appendCommonFormFields(formData);
        if (vedBackgroundJob) {
          const { data: acc } = await api.post<{ status: string; job_id: string }>(
            '/documents/ved-intelligent-analyze/async',
            formData,
            { headers: { 'Content-Type': 'multipart/form-data' } },
          );
          const jobId = acc.job_id;

          const pollOnce = async (): Promise<
            | { kind: 'done'; result: Result }
            | { kind: 'error'; message: string }
            | { kind: 'pending' }
          > => {
            const { data: st } = await api.get<{
              status: string;
              error?: string;
              result?: Result;
            }>(`/documents/ved-intel-jobs/${encodeURIComponent(jobId)}`);
            if (st.status === 'done' && st.result) return { kind: 'done', result: st.result };
            if (st.status === 'error') return { kind: 'error', message: st.error || 'Ошибка фонового ВЭД-разбора' };
            return { kind: 'pending' };
          };

          const waitViaSse = (): Promise<
            | { kind: 'done'; result: Result }
            | { kind: 'error'; message: string }
            | { kind: 'fallback' }
          > =>
            new Promise((resolve) => {
              if (typeof EventSource === 'undefined') {
                resolve({ kind: 'fallback' });
                return;
              }
              const url = `/api/documents/ved-intel-jobs/${encodeURIComponent(jobId)}/events`;
              const es = new EventSource(url);
              let settled = false;
              es.onmessage = (ev) => {
                try {
                  const st = JSON.parse(ev.data) as {
                    status: string;
                    error?: string;
                    result?: Result;
                  };
                  if (st.status === 'done' && st.result) {
                    settled = true;
                    es.close();
                    resolve({ kind: 'done', result: st.result });
                  }
                  if (st.status === 'error') {
                    settled = true;
                    es.close();
                    resolve({ kind: 'error', message: st.error || 'Ошибка фонового ВЭД-разбора' });
                  }
                } catch {
                  /* ignore */
                }
              };
              es.onerror = () => {
                es.close();
                if (!settled) resolve({ kind: 'fallback' });
              };
            });

          let settled = false;
          const sse = await waitViaSse();
          if (sse.kind === 'done') {
            setResult(sse.result);
            if (sse.result.persisted_to_db && sse.result.document_id) {
              localStorage.setItem('cc_last_ingested_id', sse.result.document_id);
            }
            settled = true;
          } else if (sse.kind === 'error') {
            setError(userFacingMessage(sse.message, 'Не удалось завершить разбор документа.'));
            settled = true;
          } else {
            for (let attempt = 0; attempt < 900; attempt++) {
              await sleep(2000);
              const st = await pollOnce();
              if (st.kind === 'done') {
                setResult(st.result);
                if (st.result.persisted_to_db && st.result.document_id) {
                  localStorage.setItem('cc_last_ingested_id', st.result.document_id);
                }
                settled = true;
                break;
              }
              if (st.kind === 'error') {
                setError(userFacingMessage(st.message, 'Не удалось завершить разбор документа.'));
                settled = true;
                break;
              }
            }
            if (!settled) {
              setError('Обработка заняла слишком много времени. Попробуйте позже или загрузите файл меньшего размера.');
            }
          }
        } else {
          const { data: res } = await api.post<Result>('/documents/ved-intelligent-analyze', formData, {
            headers: { 'Content-Type': 'multipart/form-data' },
          });
          setResult(res);
          if (res.persisted_to_db && res.document_id) {
            localStorage.setItem('cc_last_ingested_id', res.document_id);
          }
        }
      } else {
        formData.append('invoice', invoiceFile);
        if (packingFile) formData.append('packing_list', packingFile);
        formData.append('declaration_draft', 'true');
        appendCommonFormFields(formData);
        const { data: res } = await api.post<Result>('/documents/check', formData, {
          headers: { 'Content-Type': 'multipart/form-data' },
        });
        setResult(res);
        if (res.persisted_to_db && res.document_id) {
          localStorage.setItem('cc_last_ingested_id', res.document_id);
        }
      }
    } catch (e) {
      setError(getUserFacingApiError(e, 'Не удалось обработать документ. Попробуйте позже.'));
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="space-y-6">
      <div className="cc-card flex flex-wrap items-center justify-between gap-3 px-5 py-4">
        <div className="max-w-2xl space-y-1">
          <p className="text-[13px] text-slate-700">
            Загрузите <strong>упаковочный лист или инвойс</strong> (Excel / PDF, в т.ч. на <strong>китайском</strong>) — при
            режиме «ВЭД-аналитик» выполняется полный цикл: <strong>код ТН ВЭД и графа 31</strong>, справка по{' '}
            <strong>разрешительным документам</strong> и <strong>мерам нетарифного регулирования</strong>,{' '}
            <strong>пошлина и НДС</strong> по строкам (если в файле есть суммы), проверка реестра (опционально) и{' '}
            <strong>сводка с рисками и рекомендациями</strong>.
          </p>
          <p className="text-[11px] text-slate-500">
            Поддерживаются <strong className="text-slate-700">китайские</strong> и английские колонки в Excel; для сканов
            PDF при необходимости включается распознавание текста (OCR). Точнее всего — таблица .xlsx.
          </p>
          <p className="text-[11px] text-slate-600">
            Второй файл <strong className="text-slate-700">не обязателен</strong> — для сверки инвойса с упаковочным
            листом. Один файл может быть только packing list — строки товаров извлекаются из него.
          </p>
        </div>
        <button type="button" onClick={reset} className="cc-btn-ghost">
          Сбросить
        </button>
      </div>
      <section className="grid gap-4 md:grid-cols-2">
        <div {...invoiceDrop.getRootProps()} className="cc-dropzone">
          <input {...invoiceDrop.getInputProps()} />
          <span className="mb-3 inline-flex h-14 w-14 items-center justify-center rounded-full bg-indigo-100 text-indigo-700">
            <CloudUpload className="h-7 w-7" />
          </span>
          <p className="text-sm font-semibold text-slate-800">Главный файл — обязательно</p>
          <p className="mt-1 text-[11px] text-slate-600">Перетащите файл сюда или кликните для выбора</p>
          <p className="mt-1 text-[11px] text-slate-500">Инвойс или упаковочный лист: PDF, .xlsx, .xls, .csv</p>
          {invoiceFile && (
            <p className="mt-3 inline-flex items-center gap-1 rounded-full bg-emerald-100 px-2.5 py-1 text-[11px] font-medium text-emerald-800">
              <FileText className="h-3.5 w-3.5" />
              {invoiceFile.name}
            </p>
          )}
        </div>

        <div {...packingDrop.getRootProps()} className="cc-dropzone">
          <input {...packingDrop.getInputProps()} />
          <span className="mb-3 inline-flex h-14 w-14 items-center justify-center rounded-full bg-sky-100 text-sky-700">
            <Files className="h-7 w-7" />
          </span>
          <p className="text-sm font-semibold text-slate-800">Второй документ</p>
          <p className="mt-1 text-[11px] text-slate-600">Необязательно — для сверки (инвойс ↔ packing list)</p>
          {packingFile && (
            <p className="mt-3 inline-flex items-center gap-1 rounded-full bg-blue-100 px-2.5 py-1 text-[11px] font-medium text-blue-800">
              <FileText className="h-3.5 w-3.5" />
              {packingFile.name}
            </p>
          )}
        </div>
      </section>

      <details className="cc-disclosure">
        <summary>Сохранение документа и идентификатор партии</summary>
        <div className="cc-disclosure-body space-y-3">
          <label className="flex cursor-pointer items-center gap-2 text-[13px] text-slate-300">
            <input
              type="checkbox"
              className="rounded border-slate-600"
              checked={persistToDb}
              onChange={(e) => setPersistToDb(e.target.checked)}
            />
            Сохранить документ для журнала и связи с расчётами платежей
          </label>
          <label className="block max-w-md space-y-1">
            <span className="cc-label">Идентификатор клиента / партии (необязательно)</span>
            <input
              type="text"
              value={clientId}
              onChange={(e) => setClientId(e.target.value)}
              placeholder="для фильтра в журнале расчётов"
              className="cc-input"
            />
            <p className="text-[10px] text-slate-600">
              Помогает сопоставить документ с расчётами в разделе «Платежи».
            </p>
          </label>
        </div>
      </details>

      <details
        className="cc-disclosure"
        onToggle={(e) => {
          if (e.currentTarget.open && ingestedList === null) void loadIngested();
        }}
      >
        <summary>Сохранённые документы</summary>
        <div className="cc-disclosure-body space-y-2">
          <p className="text-[11px] text-slate-500">Последние документы, сохранённые в системе.</p>
          <button type="button" className="cc-btn-ghost text-[11px]" disabled={ingestedLoading} onClick={() => void loadIngested()}>
            {ingestedLoading ? 'Загрузка…' : 'Обновить список'}
          </button>
          {ingestedList && ingestedList.length === 0 && !ingestedLoading && (
            <p className="text-[11px] text-slate-600">Пока нет сохранённых документов — включите сохранение выше и выполните проверку.</p>
          )}
          {ingestedList && ingestedList.length > 0 && (
            <ul className="max-h-44 space-y-1 overflow-auto rounded-lg border border-slate-200 bg-slate-50 p-2 text-[11px]">
              {ingestedList.map((row) => (
                <li key={row.id} className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-200 py-1 last:border-0">
                  <span className="cc-mono text-indigo-700">{row.id.slice(0, 8)}…</span>
                  <span className="max-w-[180px] truncate text-slate-600" title={row.original_filename}>
                    {row.original_filename || '—'}
                  </span>
                  <span className="text-slate-500">{row.status}</span>
                  <span className="text-slate-600">стр. {row.lines_count ?? 0}</span>
                  <button
                    type="button"
                    className="text-indigo-600 hover:underline"
                    onClick={() => {
                      localStorage.setItem('cc_last_ingested_id', row.id);
                    }}
                    title="Подставить в «Платежи» как document_id"
                  >
                    в буфер
                  </button>
                  <a
                    href={`/api/documents/ingested/${encodeURIComponent(row.id)}`}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-slate-500 hover:text-indigo-600"
                  >
                    Открыть
                  </a>
                </li>
              ))}
            </ul>
          )}
        </div>
      </details>

      <details className="cc-disclosure">
        <summary>Расчёты в журнале, привязанные к document_id</summary>
        <div className="cc-disclosure-body space-y-2">
          <p className="text-[11px] text-slate-500">
            Записи из журнала расчётов, где указан этот документ (калькулятор, комплаенс, ассистент и т.д.).
          </p>
          <div className="flex flex-wrap items-end gap-2">
            <input
              value={calcDocId}
              onChange={(e) => setCalcDocId(e.target.value)}
              placeholder="Номер документа"
              className="cc-input cc-mono min-w-[240px] flex-1 text-[11px]"
            />
            <button type="button" className="cc-btn-primary" disabled={calcLoading || !calcDocId.trim()} onClick={() => void loadCalculationsForDoc()}>
              {calcLoading ? '…' : 'Загрузить'}
            </button>
          </div>
          {calcRows.length > 0 && (
            <ul className="max-h-40 space-y-1 overflow-auto rounded-lg border border-slate-200 bg-slate-50 p-2 text-[11px]">
              {calcRows.map((r) => (
                <li key={r.id} className="flex flex-wrap gap-2 border-b border-slate-200 py-1 last:border-0">
                  <span className="cc-mono text-indigo-700">{r.id.slice(0, 8)}…</span>
                  <span className="text-slate-500">{r.kind || '—'}</span>
                  <span className="tabular-nums text-slate-400">
                    {r.total_payable != null ? `${r.total_payable.toLocaleString('ru-RU')} ₽` : '—'}
                  </span>
                  <a
                    href={`/api/calculator/history/${encodeURIComponent(r.id)}`}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-indigo-600 hover:underline"
                  >
                    Открыть
                  </a>
                </li>
              ))}
            </ul>
          )}
        </div>
      </details>

      <details className="cc-disclosure" open>
        <summary>Режим ВЭД-аналитика (рекомендуется)</summary>
        <div className="cc-disclosure-body space-y-3">
          <label className="flex cursor-pointer items-center gap-2 text-[13px] text-slate-200">
            <input
              type="checkbox"
              className="rounded border-slate-600"
              checked={fullVedAnalyst}
              onChange={(e) => setFullVedAnalyst(e.target.checked)}
            />
            Полный разбор декларации (нетарифные меры, пошлины и НДС по строкам, риски и рекомендации)
          </label>
          {fullVedAnalyst && (
            <div className="grid gap-3 sm:grid-cols-2">
              <label className="block space-y-1">
                <span className="cc-label">Страна происхождения (ISO-2)</span>
                <input
                  type="text"
                  value={countryOrigin}
                  onChange={(e) => setCountryOrigin(e.target.value)}
                  placeholder="CN"
                  className="cc-input max-w-[120px] uppercase"
                />
              </label>
              <label className="block space-y-1">
                <span className="cc-label">Фрахт всего, ₽ (по строкам пропорционально таможенной стоимости)</span>
                <input
                  type="text"
                  inputMode="decimal"
                  value={freightTotalRub}
                  onChange={(e) => setFreightTotalRub(e.target.value)}
                  placeholder="0"
                  className="cc-input max-w-[160px]"
                />
              </label>
              <label className="block space-y-1 sm:col-span-2">
                <span className="cc-label">Таможенная стоимость всего, ₽ (если в файле нет сумм по строкам)</span>
                <input
                  type="text"
                  inputMode="decimal"
                  value={fallbackCustomsTotalRub}
                  onChange={(e) => setFallbackCustomsTotalRub(e.target.value)}
                  placeholder="0 — не использовать"
                  className="cc-input max-w-[200px]"
                />
                <p className="text-[10px] text-slate-600">
                  Распределение: по количеству из черновика; если количество 0 — поровну между строками.
                </p>
              </label>
              <label className="flex cursor-pointer items-center gap-2 text-[12px] text-slate-400 sm:col-span-2">
                <input
                  type="checkbox"
                  className="rounded border-slate-600"
                  checked={runPaymentEstimates}
                  onChange={(e) => setRunPaymentEstimates(e.target.checked)}
                />
                Считать пошлины/НДС по строкам (нужны total в файле; без сумм блок будет пропущен)
              </label>
              <label className="flex cursor-pointer items-center gap-2 text-[12px] text-slate-300 sm:col-span-2">
                <input
                  type="checkbox"
                  className="rounded border-slate-600"
                  checked={vedBackgroundJob}
                  onChange={(e) => setVedBackgroundJob(e.target.checked)}
                />
                Фоновый режим для больших файлов (результат появится после завершения обработки)
              </label>
            </div>
          )}
          {!fullVedAnalyst && (
            <p className="text-[11px] text-slate-500">Будет базовая проверка и черновик декларации без сводного разбора.</p>
          )}
        </div>
      </details>

      <details className="cc-disclosure">
        <summary>Консультант по строкам декларации</summary>
        <div className="cc-disclosure-body space-y-3">
          <p className="text-[11px] text-slate-500">
            Уточнение кодов ТН ВЭД и текстов граф выполняется на сервере при включённой опции ниже, если для организации
            настроены ключи ИИ.
          </p>
          <label className="flex cursor-pointer items-center gap-2 text-[13px] text-slate-300">
            <input
              type="checkbox"
              className="rounded border-slate-600"
              checked={useAiDeclaration}
              onChange={(e) => setUseAiDeclaration(e.target.checked)}
            />
            Использовать консультанта для строк декларации
          </label>
        </div>
      </details>

      <details className="cc-disclosure">
        <summary>Разрешительные документы и реестр</summary>
        <div className="cc-disclosure-body space-y-3">
          <label className="flex cursor-pointer items-center gap-2 text-[13px] text-slate-300">
            <input type="checkbox" className="rounded border-slate-600" checked={extractPermits} onChange={(e) => setExtractPermits(e.target.checked)} />
            Извлечь номера из текста
          </label>
          <label className="flex cursor-pointer items-center gap-2 text-[13px] text-slate-300">
            <input type="checkbox" className="rounded border-slate-600" checked={verifyFsa} onChange={(e) => setVerifyFsa(e.target.checked)} />
            Проверить в реестре
          </label>
          <label className="flex cursor-pointer items-center gap-2 text-[13px] text-amber-200/85">
            <input type="checkbox" className="rounded border-slate-600" checked={skipRegistry} onChange={(e) => setSkipRegistry(e.target.checked)} />
            Без запросов к реестру (быстрее)
          </label>
          <label className="block space-y-1">
            <span className="cc-label">ТН ВЭД для сверки</span>
            <input
              type="text"
              inputMode="numeric"
              placeholder="8504405500"
              value={hsCode}
              onChange={(e) => setHsCode(e.target.value)}
              className="cc-input max-w-xs"
            />
          </label>
        </div>
      </details>

      <div className="flex flex-wrap items-center gap-4">
        <button type="button" disabled={!canStart} onClick={handleStart} className="cc-btn-primary">
          {isLoading
            ? fullVedAnalyst && vedBackgroundJob
              ? 'Фоновое задание…'
              : 'Обработка…'
            : fullVedAnalyst
              ? 'Запустить ВЭД-аналитика'
              : 'Собрать черновик'}
        </button>
        {result?.declaration_draft && (
          <div className="rounded-full border border-emerald-200 bg-emerald-100 px-3 py-1.5 text-[11px] text-emerald-800">
            Строк в черновике: {result.declaration_draft.summary.lines_count}
          </div>
        )}
        {result?.document_id && (
          <div className="flex flex-wrap items-center gap-2 rounded-lg border border-slate-200 bg-slate-50 px-3 py-1.5 text-[11px] text-slate-600">
            <span>
              Номер документа: <span className="cc-mono text-indigo-700">{result.document_id}</span>
            </span>
            {result.persisted_to_db === true && (
              <span className="rounded-full bg-emerald-100 px-2 py-0.5 text-[10px] font-semibold text-emerald-800">в БД</span>
            )}
            {result.persisted_to_db === false && result.persist_error && (
              <span className="text-amber-700" title={result.persist_error}>
                не сохранено в БД
              </span>
            )}
            <a
              className="text-indigo-600 hover:underline"
              href={`/api/documents/ingested/${encodeURIComponent(result.document_id)}`}
              target="_blank"
              rel="noopener noreferrer"
            >
              Открыть карточку
            </a>
          </div>
        )}
      </div>

      {error && (
        <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
          {error}
        </div>
      )}
      {isLoading && (
        <section className="space-y-3">
          <div className="cc-skeleton h-4 w-40" />
          <div className="cc-skeleton h-44 w-full" />
          <div className="cc-skeleton h-10 w-full" />
        </section>
      )}

      {result?.declaration_draft && result.declaration_draft.declaration_lines.length > 0 && (
        <section className="space-y-4">
          <div className="flex flex-wrap items-center gap-3 text-[11px] text-slate-400">
            <span className="rounded-md bg-slate-800/80 px-2 py-1">
              Позиций: <strong className="text-slate-200">{result.declaration_draft.summary.lines_count}</strong>
            </span>
            <span className="rounded-md bg-slate-800/80 px-2 py-1">
              Σ кол-ва:{' '}
              <strong className="text-slate-200">
                {result.declaration_draft.summary.total_quantity.toLocaleString('ru-RU')}
              </strong>
            </span>
            <span className="rounded-md bg-slate-800/80 px-2 py-1">
              Σ брутто, кг:{' '}
              <strong className="text-slate-200">
                {result.declaration_draft.summary.total_gross_weight_kg.toLocaleString('ru-RU')}
              </strong>
            </span>
            <span className="rounded-md bg-slate-800/80 px-2 py-1">
              Мест / упак.:{' '}
              <strong className="text-slate-200">
                {result.declaration_draft.summary.total_places_or_packages.toLocaleString('ru-RU')}
              </strong>
            </span>
          </div>
          <p className="text-[11px] leading-relaxed text-slate-500">{result.declaration_draft.disclaimer}</p>
          <div className="overflow-x-auto rounded-xl border border-white/[0.08] bg-black/25">
            <table className="min-w-[920px] border-collapse text-left text-[11px]">
              <thead className="sticky top-0 border-b border-white/[0.08] bg-[#020617]/95">
                <tr>
                  <th className="px-2 py-2 font-medium text-slate-400">№</th>
                  <th className="px-2 py-2 font-medium text-slate-400">Как в файле</th>
                  <th className="px-2 py-2 font-medium text-slate-400">ТН ВЭД</th>
                  <th className="px-2 py-2 font-medium text-slate-400">Графа 31 (черновик)</th>
                  <th className="px-2 py-2 text-right font-medium text-slate-400">Кол-во</th>
                  <th className="px-2 py-2 font-medium text-slate-400">Ед.</th>
                  <th className="px-2 py-2 text-right font-medium text-slate-400">Брутто кг</th>
                  <th className="px-2 py-2 text-right font-medium text-slate-400">Места</th>
                  <th className="px-2 py-2 font-medium text-slate-400">Документы</th>
                  <th className="px-2 py-2 font-medium text-slate-400">ТР ТС / особенности</th>
                </tr>
              </thead>
              <tbody>
                {result.declaration_draft.declaration_lines.map((row) => (
                  <tr key={row.line} className="border-t border-white/[0.05] align-top">
                    <td className="px-2 py-2 text-slate-500">{row.line}</td>
                    <td className="max-w-[200px] px-2 py-2 text-slate-200">{row.commercial_description}</td>
                    <td className="px-2 py-2">
                      <div className="cc-mono text-sky-200/90">{row.hs_code || '—'}</div>
                      {row.hs_code_source && (
                        <div className="mt-0.5 text-[10px] text-slate-600">источник: {row.hs_code_source}</div>
                      )}
                    </td>
                    <td className="max-w-[260px] px-2 py-2 text-slate-200">{row.graf31_ru}</td>
                    <td className="px-2 py-2 text-right tabular-nums">{row.quantity.toLocaleString('ru-RU')}</td>
                    <td className="px-2 py-2 text-slate-400">{row.unit || '—'}</td>
                    <td className="px-2 py-2 text-right tabular-nums">{row.weight_gross_kg.toLocaleString('ru-RU')}</td>
                    <td className="px-2 py-2 text-right tabular-nums">
                      {row.places_or_packages > 0 ? row.places_or_packages.toLocaleString('ru-RU') : '—'}
                    </td>
                    <td className="px-2 py-2 text-slate-300">
                      {row.permit_types?.length ? row.permit_types.join(', ') : '—'}
                    </td>
                    <td className="max-w-[220px] px-2 py-2 text-slate-400">
                      {row.tr_ts?.length ? <div className="mb-1">{row.tr_ts.join(', ')}</div> : null}
                      {row.peculiarities?.map((p, i) => (
                        <div key={i} className="text-[10px] leading-snug text-slate-500">
                          {p}
                        </div>
                      ))}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {result?.ved_intel_status && (
        <section className="space-y-3 rounded-xl border border-violet-500/20 bg-violet-950/20 p-4">
          <div className="flex flex-wrap items-center gap-2 text-[12px]">
            <span className="rounded-md bg-violet-500/20 px-2 py-1 font-semibold text-violet-200">
              ВЭД-аналитик: {result.ved_intel_status}
            </span>
            {result.disclaimer_ved_intel && (
              <span className="text-[11px] text-slate-500">{result.disclaimer_ved_intel}</span>
            )}
          </div>
          {result.customs_value_allocation_note && (
            <p className="rounded-lg border border-sky-500/20 bg-sky-950/25 px-3 py-2 text-[11px] text-sky-100/90">
              {result.customs_value_allocation_note}
            </p>
          )}
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              className="cc-btn-ghost text-[11px]"
              onClick={() => {
                const payload = buildVedExportPayload(result);
                downloadJson(`ved_report_${result.document_id?.slice(0, 8) || 'export'}.json`, payload);
              }}
            >
              Скачать отчёт (данные)
            </button>
            <button
              type="button"
              disabled={vedPdfLoading}
              className="cc-btn-ghost text-[11px] disabled:opacity-50"
              onClick={async () => {
                setVedPdfLoading(true);
                try {
                  const payload = buildVedExportPayload(result);
                  const res = await api.post('/documents/ved-report-pdf', payload, {
                    responseType: 'blob',
                  });
                  const blob = new Blob([res.data as BlobPart], { type: 'application/pdf' });
                  const url = URL.createObjectURL(blob);
                  const a = document.createElement('a');
                  a.href = url;
                  a.download = `ved_report_${result.document_id?.slice(0, 8) || 'export'}.pdf`;
                  a.click();
                  URL.revokeObjectURL(url);
                } catch (e) {
                  setError(getUserFacingApiError(e, 'Не удалось сформировать PDF.'));
                } finally {
                  setVedPdfLoading(false);
                }
              }}
            >
              {vedPdfLoading ? 'PDF…' : 'Скачать отчёт PDF'}
            </button>
          </div>
          {result.copilot_batch?.bundles && result.copilot_batch.bundles.length > 0 && (
            <div className="overflow-x-auto rounded-lg border border-white/[0.06] bg-black/20">
              <table className="min-w-[520px] border-collapse text-left text-[11px]">
                <thead>
                  <tr className="border-b border-white/[0.08] text-slate-500">
                    <th className="px-2 py-2">Строка</th>
                    <th className="px-2 py-2">ТН ВЭД</th>
                    <th className="px-2 py-2">Нетарифка</th>
                    <th className="px-2 py-2 text-right">Платежи Σ, ₽</th>
                  </tr>
                </thead>
                <tbody>
                  {result.copilot_batch.bundles.map((b, i) => (
                    <tr key={i} className="border-t border-white/[0.05]">
                      <td className="px-2 py-1.5 text-slate-500">{i + 1}</td>
                      <td className="cc-mono px-2 py-1.5 text-sky-200/90">{b.effective_hs_code || '—'}</td>
                      <td className="px-2 py-1.5 text-slate-400">{b.non_tariff?.status ?? '—'}</td>
                      <td className="px-2 py-1.5 text-right tabular-nums text-slate-300">
                        {b.payment?.breakdown?.total_payable != null
                          ? Number(b.payment.breakdown.total_payable).toLocaleString('ru-RU', {
                              maximumFractionDigits: 0,
                            })
                          : '—'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {result.ai_analyst && (
            <div className="space-y-3 rounded-lg border border-white/[0.06] bg-black/30 p-3 text-[12px] leading-relaxed text-slate-200">
              {result.ai_analyst.note && <p className="text-amber-200/90">{result.ai_analyst.note}</p>}
              {result.ai_analyst.summary && (
                <div>
                  <div className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">Сводка</div>
                  <p className="mt-1">{result.ai_analyst.summary}</p>
                </div>
              )}
              {result.ai_analyst.classification_advice && (
                <div>
                  <div className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">Классификация</div>
                  <p className="mt-1 text-slate-300">{result.ai_analyst.classification_advice}</p>
                </div>
              )}
              {result.ai_analyst.payment_comment && (
                <div>
                  <div className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">Платежи</div>
                  <p className="mt-1 text-slate-300">{result.ai_analyst.payment_comment}</p>
                </div>
              )}
              {result.ai_analyst.non_tariff_comment && (
                <div>
                  <div className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">Нетарифка</div>
                  <p className="mt-1 text-slate-300">{result.ai_analyst.non_tariff_comment}</p>
                </div>
              )}
              {result.ai_analyst.documents_comment && (
                <div>
                  <div className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">Документы</div>
                  <p className="mt-1 text-slate-300">{result.ai_analyst.documents_comment}</p>
                </div>
              )}
              {result.ai_analyst.risks && result.ai_analyst.risks.length > 0 && (
                <div>
                  <div className="text-[10px] font-semibold uppercase tracking-wider text-red-300/80">Риски</div>
                  <ul className="mt-1 list-inside list-disc space-y-1 text-slate-300">
                    {result.ai_analyst.risks.map((r, j) => (
                      <li key={j}>{r}</li>
                    ))}
                  </ul>
                </div>
              )}
              {result.ai_analyst.next_steps && result.ai_analyst.next_steps.length > 0 && (
                <div>
                  <div className="text-[10px] font-semibold uppercase tracking-wider text-emerald-300/80">Дальнейшие шаги</div>
                  <ul className="mt-1 list-inside list-decimal space-y-1 text-slate-300">
                    {result.ai_analyst.next_steps.map((r, j) => (
                      <li key={j}>{r}</li>
                    ))}
                  </ul>
                </div>
              )}
              {result.ai_analyst.disclaimer && (
                <p className="border-t border-white/[0.06] pt-2 text-[10px] text-slate-500">{result.ai_analyst.disclaimer}</p>
              )}
              {result.ai_analyst.raw && !result.ai_analyst.summary && (
                <pre className="max-h-48 overflow-auto whitespace-pre-wrap text-[11px] text-slate-400">{result.ai_analyst.raw}</pre>
              )}
            </div>
          )}
        </section>
      )}

      {result?.declaration_draft && result.declaration_draft.declaration_lines.length === 0 && (
        <section className="rounded-lg border border-amber-800/40 bg-amber-950/25 px-3 py-2 text-xs text-amber-100">
          Черновик не содержит строк: из файла не удалось выделить таблицу товаров. Загрузите{' '}
          <strong>Excel (.xlsx)</strong> с колонками описания и количества или улучшите качество PDF / включите OCR.
        </section>
      )}

      <details className="cc-disclosure">
        <summary className="text-slate-400">Дополнительно: сырой инвойс, сверка двух файлов, реестр</summary>
        <div className="cc-disclosure-body space-y-5 pt-2">
          {result && (
            <div className="rounded-lg border border-white/[0.06] bg-black/20 px-3 py-1.5 text-[11px] text-slate-500">
              <span className="font-medium text-slate-300">{DOC_STATUS_LABEL[result.status] ?? result.status}</span>
              <span className="mx-2 text-slate-600">·</span>
              критичных: {result.summary.errors}, замечаний: {result.summary.warnings}
              {result.comparison_mode === 'invoice_only' && (
                <span className="ml-2 text-sky-400/90">· только инвойс</span>
              )}
            </div>
          )}

      {result?.verdict && (
        <section className="rounded-xl border border-cyan-900/50 bg-cyan-950/40 px-4 py-3 text-sm">
          <h3 className="font-semibold text-cyan-100">{result.verdict.headline}</h3>
          <p className="mt-2 text-[13px] leading-relaxed text-slate-300">{result.verdict.detail}</p>
        </section>
      )}

      {result && result.items.length > 0 && (
        <section className="space-y-3">
          <span className="text-[11px] font-semibold uppercase tracking-[0.14em] text-slate-500">Товарные позиции</span>
          <div className="overflow-x-auto rounded-xl border border-white/[0.06] bg-black/20">
            <table className="min-w-full border-collapse text-xs">
              <thead className="border-b border-white/[0.06] bg-[#020617]/90">
                <tr>
                  <th className="px-3 py-2 text-left font-medium text-slate-400">№</th>
                  <th className="px-3 py-2 text-left font-medium text-slate-400">Описание</th>
                  <th className="px-3 py-2 text-right font-medium text-slate-400">Кол-во</th>
                  <th className="px-3 py-2 text-left font-medium text-slate-400">Ед.</th>
                  <th className="px-3 py-2 text-right font-medium text-slate-400">Брутто</th>
                  <th className="px-3 py-2 text-right font-medium text-slate-400">Нетто</th>
                  <th className="px-3 py-2 text-right font-medium text-slate-400">Цена</th>
                  <th className="px-3 py-2 text-right font-medium text-slate-400">Сумма</th>
                </tr>
              </thead>
              <tbody>
                {result.items.map((item) => (
                  <tr key={item.line} className="border-t border-white/[0.04]">
                    <td className="px-3 py-1.5 text-slate-400">{item.line}</td>
                    <td className="px-3 py-1.5">{item.description}</td>
                    <td className="px-3 py-1.5 text-right">
                      {item.quantity.toLocaleString('ru-RU')}
                    </td>
                    <td className="px-3 py-1.5">{item.unit}</td>
                    <td className="px-3 py-1.5 text-right">
                      {item.weight_gross.toLocaleString('ru-RU')}
                    </td>
                    <td className="px-3 py-1.5 text-right">
                      {item.weight_net.toLocaleString('ru-RU')}
                    </td>
                    <td className="px-3 py-1.5 text-right">
                      {item.unit_price.toLocaleString('ru-RU')}
                    </td>
                    <td className="px-3 py-1.5 text-right">
                      {item.total_price.toLocaleString('ru-RU')}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {result && result.items.length === 0 && (
        <section className="rounded-lg border border-white/[0.08] bg-amber-950/20 px-3 py-2 text-xs text-amber-100/90">
          <strong className="text-amber-200">Таблица позиций пуста.</strong> Часто так бывает для PDF: программа видит
          текст страницы, но не выделяет строки счёта. Загрузите таблицу в Excel или добавьте упаковочный лист вторым
          файлом для сверки.
        </section>
      )}

      {result && result.extracted_permits && result.extracted_permits.length > 0 && (
        <section className="space-y-3">
          <span className="text-[11px] font-semibold uppercase tracking-[0.14em] text-slate-500">
            Номера из текста (СС / ДС / СГР)
          </span>
          <ul className="space-y-1 rounded-xl border border-white/[0.06] bg-black/20 p-3 text-xs">
            {result.extracted_permits.map((p, i) => (
              <li key={i} className="cc-mono text-sky-200/90">
                {p.type} · {p.number}
              </li>
            ))}
          </ul>
        </section>
      )}

      {result &&
        extractPermits &&
        Array.isArray(result.extracted_permits) &&
        result.extracted_permits.length === 0 && (
          <p className="text-xs text-slate-500">
            В тексте загруженных файлов номера сертификатов/деклараций (СС, ДС, СГР) не найдены.
          </p>
        )}

      {result?.permits_registry_note && (
        <div className="rounded-lg border border-amber-700/50 bg-amber-900/20 px-3 py-2 text-xs text-amber-100">
          {result.permits_registry_note}
        </div>
      )}

      {result && result.permits_registry_check && result.permits_registry_check.length > 0 && (
        <section className="space-y-3">
          <span className="text-[11px] font-semibold uppercase tracking-[0.14em] text-slate-500">
            Проверка в реестре Росаккредитации / СГР
          </span>
          <div className="space-y-2">
            {result.permits_registry_check.map((row, idx) => {
              const hs = row.hs_code_check;
              let hsBadge = 'text-slate-400';
              if (hs?.hs_match === 'ok') hsBadge = 'text-emerald-300';
              if (hs?.hs_match === 'partial') hsBadge = 'text-amber-300';
              if (hs?.hs_match === 'mismatch') hsBadge = 'text-red-300';
              return (
                <div key={idx} className="cc-card-soft space-y-1 p-3 text-xs">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="cc-mono font-semibold text-slate-100">
                      {row.type} {row.number}
                    </span>
                    <span className="rounded bg-slate-800 px-2 py-0.5 text-[10px]">
                      {REGISTRY_STATUS_RU[row.status ?? ''] ?? row.status}
                    </span>
                  </div>
                  {row.holder && <div className="text-slate-400">Заявитель: {row.holder}</div>}
                  {(row.valid_from || row.valid_to) && (
                    <div className="text-slate-500">
                      Срок: {row.valid_from ?? '—'} — {row.valid_to ?? '—'}
                    </div>
                  )}
                  {hs && hs.hs_match && hs.hs_match !== 'unknown' && (
                    <div className={hsBadge}>
                      {HS_MATCH_RU[hs.hs_match] ?? hs.hs_match}: {hs.detail ?? ''}
                    </div>
                  )}
                  {row.registry_source && (
                    <div className="text-[10px] text-slate-600">{row.registry_source}</div>
                  )}
                  {row.registry_link && (
                    <a
                      href={row.registry_link}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="inline-block text-sky-400 hover:underline"
                    >
                      Открыть в реестре
                    </a>
                  )}
                  {row.error && <div className="text-red-300">{row.error}</div>}
                </div>
              );
            })}
          </div>
        </section>
      )}

      {result && result.checks.length > 0 && (
        <section className="space-y-3">
          <span className="text-[11px] font-semibold uppercase tracking-[0.14em] text-slate-500">
            Детали проверки (что означает каждый пункт)
          </span>
          <div className="space-y-1.5">
            {result.checks.map((c, idx) => {
              let color = 'text-emerald-300 border-emerald-700/60 bg-emerald-900/20';
              if (c.status === 'WARNING') {
                color = 'text-amber-300 border-amber-700/60 bg-amber-900/20';
              }
              if (c.status === 'ERROR') {
                color = 'text-red-300 border-red-700/60 bg-red-900/20';
              }
              return (
                <div
                  key={idx}
                  className={`flex items-start gap-2 rounded-lg border px-3 py-2 text-xs ${color}`}
                >
                  <span className="mt-0.5 inline-block rounded-full bg-black/20 px-2 py-0.5 text-[10px] font-semibold tracking-wide">
                    {CHECK_STATUS_RU[c.status] ?? c.status}
                  </span>
                  <div>
                    <div className="text-[12px] font-medium text-slate-200">{c.title ?? c.check}</div>
                    <div className="mt-0.5 text-[11px] leading-relaxed text-slate-300/95">{c.detail}</div>
                  </div>
                </div>
              );
            })}
          </div>
        </section>
      )}
        </div>
      </details>
    </div>
  );
};

