import React, { useState } from 'react';
import { api } from '../api/client';
import { getUserFacingApiError } from '../api/error';
import {
  AdvisoryRequirementsBlock,
  type AdvisoryRequirement,
} from '../components/nonTariff/AdvisoryRequirementsBlock';

/** Не показываем служебные метки версии нормативки конечному пользователю. */
function normativeRevisionLabel(revision: string | undefined | null): string | null {
  const r = (revision || '').trim();
  if (!r) return null;
  const low = r.toLowerCase();
  if (low.includes('seed') || low.includes('fallback') || low.includes('example') || low.includes('import-xlsx')) {
    return null;
  }
  return r;
}

type Permit = { type: string; number: string };

type DataFreshness = {
  source_name: string;
  source_code: string;
  synced_at: string | null;
  is_stale: boolean;
  revision: string;
};

type DataQuality = {
  confidence: 'high' | 'medium' | 'low' | 'none';
  matched_prefix: string;
  match_length: number;
  antidumping_status: string;
};

type ComplianceItem = {
  hs_code: string;
  description: string;
  country: string | null;
  documents?: { required: string[]; provided: string[]; missing: string[] };
  risks?: string[];
  payment: {
    breakdown: {
      duty: number;
      vat: number;
      excise: number;
      antidumping: number;
      total_payable: number;
      vat_rate: number;
      duty_rate: number;
      vat_reason: string;
      excise_reason: string;
      antidumping_reason: string;
      antidumping_status: string;
    };
    auto_detected: {
      duty_rate: number;
      vat_rate: number;
      antidumping_type: string;
      antidumping_value: number;
      antidumping_condition?: string;
      antidumping_countries?: string;
    };
    data_quality: DataQuality;
    sources: { name: string; integrated?: boolean; data_info?: string; revision?: string }[];
  };
  non_tariff: {
    status: string;
    hs_code: string;
    description: string;
    country: string | null;
    tr_ts: string[];
    required_permit_types: string[];
    permits: PermitRegistryRow[];
    missing_permit_types: string[];
    advisory_requirements?: AdvisoryRequirement[];
    notes: string[];
    rule_sources: {
      name: string;
      integrated?: boolean;
      data_info?: string;
      required_permits?: string[];
      revision?: string;
      hs_prefix?: string;
      priority?: number;
      tr_ts_edition?: string;
      exception_note?: string;
    }[];
    data_freshness: DataFreshness;
  };
  permits_verification?: {
    registry: string;
    documents: PermitRegistryRow[];
    summary: { checked: number; valid: number; not_found: number; hs_mismatch: number };
  };
};

type PermitRegistryRow = {
  type: string;
  status: string;
  number: string;
  registry_link?: string;
  registry_source?: string;
  verified_at?: string;
  holder?: string | null;
  valid_to?: string | null;
  hs_code_check?: { hs_match: string; detail?: string };
  error?: string;
};

type ComplianceResponse = {
  status: string;
  items: ComplianceItem[];
  meta?: {
    generated_at: string;
    data_confidence: string[];
    any_stale_source: boolean;
    any_manual_review: boolean;
  };
};

function formatDate(iso: string | null) {
  if (!iso) return 'неизвестно';
  try {
    return new Date(iso).toLocaleString('ru-RU', { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' });
  } catch {
    return iso;
  }
}

const CONFIDENCE_LABELS: Record<string, string> = {
  high: 'Высокая (10–8 зн.)',
  medium: 'Средняя (6 зн.)',
  low: 'Низкая (4 зн.)',
  none: 'Код не найден',
};

export const NonTariff: React.FC = () => {
  const [hsCode, setHsCode] = useState('');
  const [description, setDescription] = useState('');
  const [country, setCountry] = useState('CN');
  const [customsValue, setCustomsValue] = useState('500000');
  const [freight, setFreight] = useState('45000');
  const [permits, setPermits] = useState<Permit[]>([{ type: 'ДС', number: '' }]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<ComplianceResponse | null>(null);
  const [saveComplianceHistory, setSaveComplianceHistory] = useState(false);
  const [complianceDocId, setComplianceDocId] = useState(() => localStorage.getItem('cc_last_ingested_id') || '');
  const [complianceUserRef, setComplianceUserRef] = useState(() => localStorage.getItem('cc_client_id') || '');

  const addPermit = () => setPermits((p) => [...p, { type: 'ДС', number: '' }]);
  const removePermit = (i: number) => setPermits((p) => p.filter((_, j) => j !== i));
  const updatePermit = (i: number, field: 'type' | 'number', v: string) =>
    setPermits((p) => p.map((x, j) => (j === i ? { ...x, [field]: v } : x)));

  const handleCheck = async () => {
    if (!hsCode.trim()) return;
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const ur = complianceUserRef.trim();
      if (ur) localStorage.setItem('cc_client_id', ur);
      const { data } = await api.post<ComplianceResponse>('/compliance/check', {
        items: [{
          hs_code: hsCode.trim(),
          description: description.trim(),
          country: country || null,
          permits: permits.filter((p) => p.number.trim()),
          customs_value: parseFloat(customsValue || '0'),
          freight: parseFloat(freight || '0'),
        }],
        save_history: saveComplianceHistory,
        document_id: complianceDocId.trim() || undefined,
        user_ref: ur || undefined,
      });
      setResult(data);
    } catch (e: unknown) {
      setError(getUserFacingApiError(e, 'Не удалось выполнить проверку. Попробуйте позже.'));
    } finally {
      setLoading(false);
    }
  };

  const meta = result?.meta;

  return (
    <div className="space-y-4">
      <p className="text-[12px] leading-relaxed text-slate-600">
        Совмещённая проверка: платежи, нетарифные меры и реестры разрешений.
      </p>
      <details className="cc-disclosure">
        <summary>Журнал расчётов (комплаенс)</summary>
        <div className="cc-disclosure-body space-y-3 text-[12px]">
          <label className="flex cursor-pointer items-center gap-2 text-slate-700">
            <input
              type="checkbox"
              className="rounded border-slate-600"
              checked={saveComplianceHistory}
              onChange={(e) => setSaveComplianceHistory(e.target.checked)}
            />
            Сохранить результат проверки в историю расчётов (тип «комплаенс»)
          </label>
          <div className="grid gap-3 sm:grid-cols-2">
            <label className="block space-y-1">
              <span className="cc-label">document_id (опционально)</span>
              <input
                value={complianceDocId}
                onChange={(e) => setComplianceDocId(e.target.value)}
                placeholder="UUID после сохранения документа"
                className="cc-input cc-mono text-[11px]"
              />
            </label>
            <label className="block space-y-1">
              <span className="cc-label">user_ref</span>
              <input
                value={complianceUserRef}
                onChange={(e) => setComplianceUserRef(e.target.value)}
                placeholder="как Client ID в документах"
                className="cc-input"
              />
            </label>
          </div>
          <p className="text-[10px] text-slate-600">
            Список записей: раздел «Платежи» → журнал расчётов или{' '}
            <a href="/api/calculator/history?limit=20" className="text-indigo-600 hover:underline" target="_blank" rel="noreferrer">
              API
            </a>
            .
          </p>
        </div>
      </details>

      <details className="cc-disclosure">
        <summary>Нормативные источники</summary>
        <div className="cc-disclosure-body flex flex-wrap gap-2">
          <a href="https://eec.eaeunion.org/comission/department/catr/ett/" target="_blank" rel="noreferrer" className="cc-btn-ghost">
            ЕТТ ЕАЭС
          </a>
          <a href="https://eec.eaeunion.org/comission/department/nts/" target="_blank" rel="noreferrer" className="cc-btn-ghost">
            Нетарифные меры ЕЭК
          </a>
        </div>
      </details>

      <div className="grid gap-3 md:grid-cols-2 text-xs">
        <label className="space-y-1">
          <span className="cc-label">Код ТН ВЭД</span>
          <input
            value={hsCode}
            onChange={(e) => setHsCode(e.target.value)}
            placeholder="8509400000"
            className="cc-input"
          />
        </label>
        <label className="space-y-1">
          <span className="cc-label">Страна происхождения</span>
          <select value={country} onChange={(e) => setCountry(e.target.value)} className="cc-input">
            <option value="CN">Китай</option>
            <option value="EU">ЕС</option>
            <option value="TR">Турция</option>
            <option value="BY">Беларусь</option>
            <option value="KZ">Казахстан</option>
            <option value="RU">Россия</option>
            <option value="">— не указана</option>
          </select>
        </label>
        <label className="space-y-1">
          <span className="cc-label">Таможенная стоимость (₽)</span>
          <input value={customsValue} onChange={(e) => setCustomsValue(e.target.value)} className="cc-input" />
        </label>
        <label className="space-y-1">
          <span className="cc-label">Фрахт (₽)</span>
          <input value={freight} onChange={(e) => setFreight(e.target.value)} className="cc-input" />
        </label>
      </div>

      <label className="block space-y-1 text-xs">
        <span className="cc-label">Описание товара</span>
        <textarea
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          placeholder="Краткое описание"
          className="cc-input min-h-[72px]"
        />
      </label>

      <details className="cc-disclosure">
        <summary>Сверка с реестрами</summary>
        <div className="cc-disclosure-body text-[12px] leading-relaxed text-slate-500">
          При указании номера выполняется запрос к реестрам; при ответе возможна сверка кодов ТН ВЭД с декларацией.
        </div>
      </details>

      <div className="cc-card-soft space-y-2 p-3">
        <div className="flex items-center justify-between">
          <span className="cc-label mb-0">Разрешительные документы</span>
          <button type="button" onClick={addPermit} className="cc-btn-ghost">+ Добавить</button>
        </div>
        {permits.map((p, i) => (
          <div key={i} className="flex gap-2 items-center">
            <select
              value={p.type}
              onChange={(e) => updatePermit(i, 'type', e.target.value)}
              className="cc-input w-24 text-xs"
            >
              <option value="СС">СС</option>
              <option value="ДС">ДС</option>
              <option value="СГР">СГР</option>
              <option value="РУ">РУ</option>
            </select>
            <input
              value={p.number}
              onChange={(e) => updatePermit(i, 'number', e.target.value)}
              placeholder="Номер документа"
              className="cc-input flex-1 text-xs"
            />
            <button type="button" onClick={() => removePermit(i)} className="cc-btn-ghost text-red-600">×</button>
          </div>
        ))}
      </div>

      <button type="button" disabled={!hsCode.trim() || loading} onClick={handleCheck} className="cc-btn-primary">
        {loading ? 'Проверка…' : 'Выполнить проверку'}
      </button>

      {loading && (
        <div className="space-y-2">
          <div className="cc-skeleton h-5 w-44" />
          <div className="cc-skeleton h-16 w-full" />
          <div className="cc-skeleton h-24 w-full" />
        </div>
      )}

      {error && (
        <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
          {error}
        </div>
      )}

      {result && (
        <div className="space-y-3 text-xs">
          {/* Meta / stale warning */}
          {meta?.any_stale_source && (
            <div className="rounded-xl border border-amber-200 bg-amber-50 px-3 py-2.5 text-[12px] text-amber-800">
              Для части позиций используется архивная редакция нормативных данных.
            </div>
          )}
          {meta?.any_manual_review && (
            <div className="rounded-xl border border-orange-200 bg-orange-50 px-3 py-2.5 text-[12px] text-orange-800">
              По позициям возможна ручная проверка антидемпинговых мер (страна не задана или не сопоставлена).
            </div>
          )}

          {/* Overall status */}
          <div
            className={`rounded-lg border px-3 py-2 ${
              result.status === 'ERROR'
                ? 'border-red-200 bg-red-50 text-red-700'
                : result.status === 'WARNING'
                ? 'border-amber-200 bg-amber-50 text-amber-800'
                : 'border-emerald-200 bg-emerald-50 text-emerald-800'
            }`}
          >
            Статус: <strong>{result.status}</strong>
            {meta?.generated_at && (
              <span className="ml-3 text-[10px] opacity-70">
                сформировано {formatDate(meta.generated_at)}
              </span>
            )}
          </div>

          {result.items?.map((item, idx) => {
            const dq = item.payment.data_quality;
            const freshness = item.non_tariff.data_freshness;
            return (
              <div key={idx} className="cc-card-soft p-3 space-y-2">
                {/* Header row */}
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-mono text-indigo-700">{item.hs_code}</span>
                  {item.non_tariff.tr_ts?.length > 0 && (
                    <span className="flex flex-wrap gap-1">
                      {item.non_tariff.tr_ts.map((t) => (
                        <span key={t} className="rounded-full bg-purple-100 px-2 py-0.5 text-[10px] text-purple-800">
                          ТР ТС {t}
                        </span>
                      ))}
                    </span>
                  )}
                  {/* Confidence badge */}
                  {dq && (
                    <span className={`rounded-full border px-2 py-0.5 text-[10px] ${
                      dq.confidence === 'high' ? 'border-emerald-200 bg-emerald-100 text-emerald-800'
                      : dq.confidence === 'medium' ? 'border-amber-200 bg-amber-100 text-amber-800'
                      : dq.confidence === 'low' ? 'border-orange-200 bg-orange-100 text-orange-800'
                      : 'border-red-200 bg-red-100 text-red-700'
                    }`}>
                      Уровень детализации: {CONFIDENCE_LABELS[dq.confidence] ?? dq.confidence}
                    </span>
                  )}
                </div>

                {/* Description */}
                <div className="text-slate-700">{item.description || item.non_tariff.description || '—'}</div>

                {/* Data freshness */}
                <div className={`rounded-lg px-2.5 py-1.5 text-[11px] ${freshness.is_stale ? 'border border-amber-200 bg-amber-50 text-amber-800' : 'border border-slate-200 bg-slate-50 text-slate-600'}`}>
                  {freshness.source_name}
                  {freshness.synced_at ? ` · ${formatDate(freshness.synced_at)}` : ''}
                </div>

                {/* Payment summary */}
                <div className="rounded-lg border border-slate-200 bg-slate-50 p-2 text-[11px] text-slate-700 space-y-1">
                  <div>
                    Пошлина {item.payment.breakdown.duty.toLocaleString('ru-RU')} ₽
                    · НДС {item.payment.breakdown.vat.toLocaleString('ru-RU')} ₽ ({item.payment.breakdown.vat_rate}%)
                    {item.payment.breakdown.antidumping > 0 && ` · антидемпинг ${item.payment.breakdown.antidumping.toLocaleString('ru-RU')} ₽`}
                    {item.payment.breakdown.excise > 0 && ` · акциз ${item.payment.breakdown.excise.toLocaleString('ru-RU')} ₽`}
                    {' · '}<strong>итог {item.payment.breakdown.total_payable.toLocaleString('ru-RU')} ₽</strong>
                  </div>
                  <div className="text-[10px] text-slate-600">{item.payment.breakdown.vat_reason}</div>
                  {(item.payment.breakdown.antidumping > 0 || item.payment.breakdown.antidumping_status === 'manual_review') && (
                    <div className={`text-[10px] ${item.payment.breakdown.antidumping_status === 'manual_review' ? 'text-orange-700' : 'text-red-700'}`}>
                      {item.payment.breakdown.antidumping_reason}
                    </div>
                  )}
                </div>

                {/* Non-tariff: required vs provided */}
                {item.non_tariff.required_permit_types?.length > 0 && (
                  <div className="text-slate-600">
                    Требуются: {item.non_tariff.required_permit_types.join(', ')}
                  </div>
                )}
                {item.non_tariff.missing_permit_types?.length > 0 && (
                  <div className="text-red-700 font-medium">
                    Не хватает: {item.non_tariff.missing_permit_types.join(', ')}
                  </div>
                )}

                <AdvisoryRequirementsBlock items={item.non_tariff.advisory_requirements ?? []} />

                {/* Проверка реестра */}
                {item.permits_verification && item.permits_verification.summary.checked > 0 && (
                  <div className="rounded-lg border border-cyan-200 bg-cyan-50 px-2 py-2 text-[11px] text-cyan-800">
                    <div className="font-medium text-cyan-800 mb-1">Реестр разрешительных документов</div>
                    <div className="text-cyan-700 text-[10px] mb-1">{item.permits_verification.registry}</div>
                    <div className="flex flex-wrap gap-2 text-[10px]">
                      <span>найдено (VALID): {item.permits_verification.summary.valid}</span>
                      <span>не найдено: {item.permits_verification.summary.not_found}</span>
                      {item.permits_verification.summary.hs_mismatch > 0 && (
                        <span className="text-orange-700">расхождение ТН ВЭД: {item.permits_verification.summary.hs_mismatch}</span>
                      )}
                    </div>
                  </div>
                )}

                {/* Permits + детали ФСА */}
                {item.non_tariff.permits?.map((p, i) => (
                  <div key={i} className="rounded border border-slate-200 bg-white px-2 py-1.5 space-y-0.5">
                    <div className="flex flex-wrap items-center gap-2 text-slate-700">
                      <span className="font-medium">{p.type}</span>
                      <span className="font-mono text-xs">{p.number}</span>
                      <span className={`text-[10px] rounded px-1.5 py-0.5 ${
                        p.status === 'VALID' ? 'bg-emerald-100 text-emerald-800'
                          : p.status === 'NOT_FOUND' ? 'bg-red-100 text-red-700'
                          : 'bg-slate-100 text-slate-700'
                      }`}>{p.status}</span>
                      {p.registry_link && (
                        <span className="text-[10px] text-slate-500">{p.registry_source || 'реестр'}</span>
                      )}
                    </div>
                    {p.holder && <div className="text-[10px] text-slate-600">Заявитель: {p.holder}</div>}
                    {p.valid_to && <div className="text-[10px] text-slate-600">Действует до: {p.valid_to}</div>}
                    {p.hs_code_check && p.hs_code_check.hs_match !== 'unknown' && (
                      <div className={`text-[10px] ${
                        p.hs_code_check.hs_match === 'ok' ? 'text-emerald-700'
                          : p.hs_code_check.hs_match === 'mismatch' ? 'text-orange-700'
                          : 'text-amber-700'
                      }`}>
                        ТН ВЭД: {p.hs_code_check.detail}
                      </div>
                    )}
                    {p.registry_link && (
                      <a href={p.registry_link} target="_blank" rel="noreferrer" className="inline-block text-[10px] text-indigo-600 hover:underline">
                        Открыть в реестре
                      </a>
                    )}
                  </div>
                ))}

                {/* Risks */}
                {item.risks && item.risks.length > 0 && (
                  <div className="rounded-lg border border-orange-200 bg-orange-50 px-2 py-1.5 space-y-1">
                    <span className="text-orange-800 font-medium text-[10px]">Риски:</span>
                    {item.risks.map((r, i) => (
                      <div key={i} className="text-orange-700 text-[10px]">{r}</div>
                    ))}
                  </div>
                )}

                {/* Notes */}
                {item.non_tariff.notes?.map((n, i) => (
                  <div key={i} className="text-amber-700">{n}</div>
                ))}

              </div>
            );
          })}
        </div>
      )}
    </div>
  );
};
