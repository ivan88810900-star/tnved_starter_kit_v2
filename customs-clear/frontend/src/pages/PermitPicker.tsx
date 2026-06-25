import React, { useState } from 'react';
import { api } from '../api/client';
import { getApiErrorMessage } from '../api/error';

type SuggestItem = {
  id: string;
  doc_type: string;
  number: string;
  is_public_registry_example?: boolean;
  product_ru: string;
  applicant_ru?: string;
  manufacturer?: string;
  trademark_note?: string;
  country_of_origin?: string;
  hs_suggest?: string[];
  registry_hint?: string;
};

type SuggestResponse = {
  status: string;
  query: string;
  disclaimer: string;
  exclude_trois: boolean;
  excluded_trois_count?: number;
  data_quality: string;
  items: SuggestItem[];
  meta?: { hint?: string; source?: string };
};

type VerifyRow = {
  type?: string;
  status?: string;
  number?: string;
  holder?: string | null;
  valid_to?: string | null;
  valid_from?: string | null;
  registry_link?: string | null;
  registry_source?: string | null;
  error?: string;
  raw?: { spa_shell?: boolean; note?: string };
};

type AsyncJobRow = { job_id: string; status?: string; summary?: Record<string, number> | null; error?: string | null };

export const PermitPicker: React.FC = () => {
  const [query, setQuery] = useState('');
  const [hsCode, setHsCode] = useState('');
  const [excludeTrois, setExcludeTrois] = useState(true);
  const [onlyDs, setOnlyDs] = useState(false);
  const [onlySs, setOnlySs] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [data, setData] = useState<SuggestResponse | null>(null);
  const [verifyById, setVerifyById] = useState<Record<string, VerifyRow[] | 'loading' | null>>({});
  const [asyncJobs, setAsyncJobs] = useState<AsyncJobRow[]>([]);
  const [jobsLoading, setJobsLoading] = useState(false);
  const [directNumber, setDirectNumber] = useState('');
  const [directLoading, setDirectLoading] = useState(false);
  const [directResult, setDirectResult] = useState<VerifyRow | null>(null);
  const [directError, setDirectError] = useState<string | null>(null);

  const loadAsyncJobs = async () => {
    setJobsLoading(true);
    try {
      const { data } = await api.get<{ items: AsyncJobRow[] }>('/permits/verify/jobs?limit=30');
      setAsyncJobs(data.items || []);
    } catch {
      setAsyncJobs([]);
    } finally {
      setJobsLoading(false);
    }
  };

  const runSuggest = async () => {
    setLoading(true);
    setError(null);
    setData(null);
    setVerifyById({});
    try {
      const doc_types: string[] = [];
      if (onlyDs) doc_types.push('ДС');
      if (onlySs) doc_types.push('СС');
      const { data: res } = await api.post<SuggestResponse>('/permits/suggest', {
        query: query.trim(),
        hs_code: hsCode.trim().replace(/\D/g, ''),
        doc_types,
        exclude_trois: excludeTrois,
        country_hint: 'CN',
        limit: 30
      });
      setData(res);
    } catch (e: unknown) {
      setError(getApiErrorMessage(e, 'Ошибка подбора'));
    } finally {
      setLoading(false);
    }
  };

  const verifyDirectNumber = async () => {
    const num = directNumber.trim();
    if (!num) return;
    setDirectLoading(true);
    setDirectError(null);
    setDirectResult(null);
    try {
      const { data: res } = await api.get<{ items: VerifyRow[] }>(
        `/permits/verify/${encodeURIComponent(num)}`,
        { params: { hs_code: hsCode.trim().replace(/\D/g, '') } },
      );
      setDirectResult(res.items?.[0] ?? null);
    } catch (e: unknown) {
      setDirectError(getApiErrorMessage(e, 'Ошибка проверки сертификата'));
    } finally {
      setDirectLoading(false);
    }
  };

  const verifyOne = async (item: SuggestItem) => {
    setVerifyById((m) => ({ ...m, [item.id]: 'loading' }));
    try {
      const { data: res } = await api.post<{ items: VerifyRow[] }>('/permits/verify', {
        permits: [{ type: item.doc_type, number: item.number }],
        hs_code: hsCode.trim().replace(/\D/g, ''),
        enrich: true
      });
      setVerifyById((m) => ({ ...m, [item.id]: res.items || [] }));
    } catch (e: unknown) {
      setVerifyById((m) => ({
        ...m,
        [item.id]: [{ error: getApiErrorMessage(e, 'Ошибка проверки'), status: 'ERROR' } as VerifyRow]
      }));
    }
  };

  return (
    <div className="space-y-5">
      <p className="text-[12px] text-slate-600">Подбор типовых СС/ДС по описанию товара и коду.</p>
      <p className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-[11px] leading-relaxed text-slate-600">
        Система определяет необходимость документа по ТН ВЭД, но не подтверждает наличие сертификата. Номера проверяйте в
        реестре ФСА.
      </p>

      <details className="cc-disclosure">
        <summary>О подборе</summary>
        <div className="cc-disclosure-body text-[12px] leading-relaxed text-slate-500">
          Используется внутренний справочник примеров. Итоговые номера подтверждайте в реестре кнопкой проверки.
        </div>
      </details>

      <section className="cc-card-soft space-y-3 p-4">
        <h3 className="text-sm font-semibold text-slate-800">Проверить сертификат по номеру</h3>
        <div className="flex flex-col gap-2 sm:flex-row">
          <input
            value={directNumber}
            onChange={(e) => setDirectNumber(e.target.value)}
            placeholder="Введите номер СС/ДС (например: RU С-CN.АД50.В.04618/22)"
            className="cc-input min-w-0 flex-1"
          />
          <button
            type="button"
            disabled={directLoading || !directNumber.trim()}
            onClick={() => void verifyDirectNumber()}
            className="cc-btn-primary shrink-0"
          >
            {directLoading ? 'Проверка…' : 'Проверить'}
          </button>
        </div>
        {directError && (
          <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">{directError}</div>
        )}
        {directResult && (
          <div className="rounded-lg border border-slate-200 bg-white p-3 text-xs text-slate-700">
            <div className="font-mono text-sm text-slate-900">{directResult.number || directNumber}</div>
            <p className="mt-1">
              Статус: <strong>{directResult.status || '—'}</strong>
              {directResult.holder ? ` · Держатель: ${directResult.holder}` : ''}
            </p>
            {directResult.valid_to ? (
              <p className="mt-0.5 text-slate-600">Срок действия: {directResult.valid_to}</p>
            ) : null}
            {directResult.registry_source ? (
              <p className="mt-0.5 text-slate-500">Источник: {directResult.registry_source}</p>
            ) : null}
            {directResult.error && <p className="mt-1 text-red-700">{directResult.error}</p>}
            {directResult.registry_link && (
              <a
                href={directResult.registry_link}
                target="_blank"
                rel="noopener noreferrer"
                className="mt-2 inline-block text-indigo-600 hover:underline"
              >
                Открыть в реестре
              </a>
            )}
          </div>
        )}
      </section>

      <div className="grid gap-3 md:grid-cols-2">
        <label className="space-y-1">
          <span className="cc-label">Описание груза</span>
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Например: электрический чайник из Китая"
            className="cc-input w-full"
          />
        </label>
        <label className="space-y-1">
          <span className="cc-label">ТН ВЭД для ранжирования</span>
          <input value={hsCode} onChange={(e) => setHsCode(e.target.value)} placeholder="8516108008" className="cc-input w-full" />
        </label>
      </div>

      <details className="cc-disclosure">
        <summary>Фильтры</summary>
        <div className="cc-disclosure-body flex flex-col gap-2">
          <label className="flex cursor-pointer items-center gap-2 text-[13px] text-slate-700">
            <input type="checkbox" className="rounded border-slate-600" checked={excludeTrois} onChange={(e) => setExcludeTrois(e.target.checked)} />
            Скрыть варианты с совпадением по ТРОИС
          </label>
          <label className="flex cursor-pointer items-center gap-2 text-[13px] text-slate-700">
            <input type="checkbox" className="rounded border-slate-600" checked={onlyDs} onChange={(e) => setOnlyDs(e.target.checked)} />
            Только декларации (ДС)
          </label>
          <label className="flex cursor-pointer items-center gap-2 text-[13px] text-slate-700">
            <input type="checkbox" className="rounded border-slate-600" checked={onlySs} onChange={(e) => setOnlySs(e.target.checked)} />
            Только сертификаты (СС)
          </label>
        </div>
      </details>

      <button type="button" disabled={loading} onClick={runSuggest} className="cc-btn-primary">
        {loading ? 'Подбор…' : 'Подобрать'}
      </button>

      {error && (
        <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">{error}</div>
      )}

      {data && (
        <div className="space-y-3">
          {data.disclaimer && (
            <details className="cc-disclosure">
              <summary>Оговорка</summary>
              <div className="cc-disclosure-body text-[12px] leading-relaxed text-slate-500">{data.disclaimer}</div>
            </details>
          )}
          <p className="text-[12px] text-slate-500">
            Найдено вариантов: <span className="font-medium text-slate-700">{data.items.length}</span>
            {typeof data.excluded_trois_count === 'number' && data.excluded_trois_count > 0
              ? ` · скрыто (ТРОИС): ${data.excluded_trois_count}`
              : ''}
          </p>
          <div className="space-y-3">
            {data.items.map((item) => {
              const v = verifyById[item.id];
              return (
                <div key={item.id} className="cc-card-soft space-y-2 p-4 text-xs">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="rounded-full bg-indigo-100 px-2.5 py-0.5 font-semibold text-indigo-800">{item.doc_type}</span>
                      {item.is_public_registry_example && (
                        <span className="rounded-full border border-amber-200 bg-amber-100 px-2 py-0.5 text-[10px] text-amber-800">
                          публичный номер из реестра
                        </span>
                      )}
                    </div>
                    <button type="button" onClick={() => verifyOne(item)} className="cc-btn-ghost text-[11px]">
                      {v === 'loading' ? 'Запрос…' : 'Проверить в ФСА'}
                    </button>
                  </div>
                  <div className="font-mono text-slate-900">{item.number}</div>
                  <div className="text-slate-700">{item.product_ru}</div>
                  {item.applicant_ru && <div className="text-slate-600">Заявитель: {item.applicant_ru}</div>}
                  {item.manufacturer && <div className="text-slate-600">Изготовитель: {item.manufacturer}</div>}
                  {item.trademark_note && (
                    <div className="text-amber-700">ТМ / маркировка: {item.trademark_note}</div>
                  )}
                  {item.hs_suggest && item.hs_suggest.length > 0 && (
                    <div className="text-[10px] text-slate-500">ТН ВЭД (подсказка): {item.hs_suggest.join(', ')}</div>
                  )}
                  {item.registry_hint && (
                    <a href={item.registry_hint} target="_blank" rel="noopener noreferrer" className="text-indigo-600 hover:underline">
                      Реестр ФСА
                    </a>
                  )}
                  {v && v !== 'loading' && Array.isArray(v) && v[0] && (
                    <div className="mt-2 rounded-lg border border-slate-200 bg-slate-50 p-2">
                      <div className="text-[10px] uppercase text-slate-500">Результат проверки</div>
                      <div className="text-slate-700">
                        Статус: <strong>{v[0].status}</strong>
                        {v[0].holder ? ` · ${v[0].holder}` : ''}
                      </div>
                      {v[0].error && <div className="text-red-700">{String(v[0].error)}</div>}
                      {v[0].raw?.spa_shell && v[0].raw?.note && (
                        <div className="text-[11px] text-amber-700">{v[0].raw.note}</div>
                      )}
                      {v[0].registry_link && (
                        <a href={v[0].registry_link} className="text-indigo-600 hover:underline" target="_blank" rel="noreferrer">
                          Карточка
                        </a>
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}

      <details
        className="cc-disclosure"
        onToggle={(e) => {
          if (e.currentTarget.open) void loadAsyncJobs();
        }}
      >
        <summary>Фоновые проверки реестра</summary>
        <div className="cc-disclosure-body space-y-2">
          <button type="button" className="cc-btn-ghost text-[11px]" disabled={jobsLoading} onClick={() => void loadAsyncJobs()}>
            {jobsLoading ? '…' : 'Обновить'}
          </button>
          {asyncJobs.length === 0 && !jobsLoading && (
            <p className="text-[11px] text-slate-600">
              Завершённые проверки появятся здесь после запуска фонового режима.
            </p>
          )}
          {asyncJobs.length > 0 && (
            <ul className="max-h-48 space-y-1 overflow-auto text-[11px]">
              {asyncJobs.map((j) => (
                <li key={j.job_id} className="rounded border border-slate-200 bg-slate-50 px-2 py-1">
                  <span className="text-slate-700">Статус проверки: {j.status || 'в обработке'}</span>
                  {j.summary && (
                    <span className="ml-2 text-slate-600">
                      подтверждено {j.summary.valid ?? 0} из {j.summary.total ?? 0}
                    </span>
                  )}
                  {j.error && <div className="text-red-700">{j.error}</div>}
                </li>
              ))}
            </ul>
          )}
        </div>
      </details>
    </div>
  );
};
