import React, { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../../api/client';
import { getAdminToken } from '../../api/adminToken';
import { getApiErrorMessage } from '../../api/error';
import type { JsonObject } from '../../types/api.types';

type Overview = {
  status?: string;
  generated_at?: string;
  database_reachable?: boolean;
  redis_reachable?: boolean | null;
  narrative_brief_ru?: string[];
  integrated_stats?: Record<string, number>;
  normative_sync_summary?: {
    sources_count?: number;
    latest_sync_iso?: string | null;
    stale_or_fallback_count?: number;
  };
  normative_sources_preview?: Array<{
    source_code?: string;
    source_name?: string;
    synced_at?: string | null;
    fallback?: boolean;
    revision?: string | null;
  }>;
  normative_hints?: Array<{ level?: string; code?: string; text?: string }>;
  calculation_history_summary?: { total?: number; by_kind?: Record<string, number> };
  decisions_journal?: JsonObject;
  ai_configuration?: Record<string, boolean | string>;
  permits_metrics?: Record<string, number>;
  permits_async_jobs_by_status?: Record<string, number>;
  ved_intel_async_jobs_by_status?: Record<string, number>;
  trois?: JsonObject;
  embeddings?: JsonObject;
};

type SyncCenterStatus = {
  scheduler_running?: boolean;
  last_sync_iso?: string | null;
  next_sync_iso?: string | null;
  recent_log?: Array<{ at?: string; level?: string; message?: string }>;
};

function StatCard({
  label,
  value,
  sub,
}: {
  label: string;
  value: string | number;
  sub?: string;
}) {
  return (
    <div className="rounded-xl border border-white/[0.06] bg-black/25 px-3 py-2.5">
      <div className="text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-500">{label}</div>
      <div className="mt-1 font-mono text-lg font-semibold text-slate-100">{value}</div>
      {sub && <div className="mt-0.5 text-[10px] text-slate-500">{sub}</div>}
    </div>
  );
}

function BoolRow({ label, ok }: { label: string; ok: boolean }) {
  return (
    <div className="flex items-center justify-between gap-2 border-b border-white/[0.04] py-1.5 text-[12px] last:border-0">
      <span className="text-slate-400">{label}</span>
      <span className={ok ? 'text-emerald-400' : 'text-amber-400/90'}>{ok ? 'да' : 'нет'}</span>
    </div>
  );
}

function redisLabel(data: Overview): string {
  if (data.redis_reachable === true) return 'подключён';
  if (data.redis_reachable === false) return 'недоступен';
  return 'не задан';
}

/** Админ-сводка: #/admin/system, в меню не показывается. */
export function SystemHealth() {
  const [data, setData] = useState<Overview | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [syncStatus, setSyncStatus] = useState<SyncCenterStatus | null>(null);
  const [syncErr, setSyncErr] = useState<string | null>(null);
  const [syncLoading, setSyncLoading] = useState(false);
  const [syncActionLoading, setSyncActionLoading] = useState(false);

  const loadSync = useCallback(async () => {
    const token = getAdminToken().trim();
    if (!token) {
      setSyncStatus(null);
      setSyncErr('Задайте X-Admin-Token (например, на странице «Платежи») для доступа к Sync Center.');
      return;
    }
    setSyncLoading(true);
    setSyncErr(null);
    try {
      const { data: d } = await api.get<SyncCenterStatus>('/v1/admin/sync/status', {
        headers: { 'X-Admin-Token': token },
      });
      setSyncStatus(d);
    } catch (e) {
      setSyncErr(getApiErrorMessage(e, 'Ошибка загрузки статуса синхронизации'));
      setSyncStatus(null);
    } finally {
      setSyncLoading(false);
    }
  }, []);

  const forceSync = useCallback(async () => {
    const token = getAdminToken().trim();
    if (!token) {
      setSyncErr('Нужен X-Admin-Token для запуска синхронизации.');
      return;
    }
    setSyncActionLoading(true);
    setSyncErr(null);
    try {
      await api.post('/v1/admin/sync/start', null, {
        headers: { 'X-Admin-Token': token },
      });
      await loadSync();
    } catch (e) {
      setSyncErr(getApiErrorMessage(e, 'Не удалось запустить синхронизацию'));
    } finally {
      setSyncActionLoading(false);
    }
  }, [loadSync]);

  const load = useCallback(async () => {
    setLoading(true);
    setErr(null);
    try {
      const token = getAdminToken().trim();
      if (!token) {
        setErr('Задайте X-Admin-Token (например, на странице «Платежи») для просмотра сводки.');
        setData(null);
        return;
      }
      const { data: d } = await api.get<Overview>('/analytics/overview', {
        headers: { 'X-Admin-Token': token },
      });
      setData(d);
    } catch (e) {
      setErr(getApiErrorMessage(e, 'Ошибка загрузки'));
      setData(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    void loadSync();
  }, [loadSync]);

  const s = data?.integrated_stats ?? {};
  const ai = data?.ai_configuration ?? {};
  const hist = data?.calculation_history_summary ?? {};
  const journal = data?.decisions_journal ?? {};
  const pm = data?.permits_metrics ?? {};
  const jobs = data?.permits_async_jobs_by_status ?? {};
  const vedJobs = data?.ved_intel_async_jobs_by_status ?? {};
  const ns = data?.normative_sync_summary;
  const nsPreview = data?.normative_sources_preview ?? [];

  const llmOk = Boolean(ai.gemini_configured || ai.anthropic_configured);
  const llmParts = [ai.gemini_configured && 'Gemini', ai.anthropic_configured && 'Claude'].filter(Boolean);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="max-w-2xl text-[12px] leading-relaxed text-slate-500">
          Кратко: объёмы данных в БД и что включено. Подробные счётчики ФСА, источников и очередей — только ниже, в
          «Расширенной диагностике».
        </p>
        <div className="flex flex-wrap items-center gap-2">
          <Link to="/admin/import" className="cc-btn-ghost text-[11px]">
            Массовая загрузка базы
          </Link>
          <button type="button" className="cc-btn-ghost text-[11px]" disabled={loading} onClick={() => void load()}>
            {loading ? '…' : 'Обновить'}
          </button>
        </div>
      </div>

      {err && (
        <div className="rounded-lg border border-red-500/30 bg-red-950/40 px-3 py-2 text-[12px] text-red-200">
          {err}
        </div>
      )}

      {loading && !data && (
        <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
          {[1, 2, 3, 4].map((i) => (
            <div key={i} className="cc-skeleton h-20 rounded-xl" />
          ))}
        </div>
      )}

      {data && (
        <>
          <div className="rounded-lg border border-white/[0.08] bg-black/20 px-3 py-2.5 text-[12px] text-slate-300">
            <div className="flex flex-wrap gap-x-5 gap-y-1">
              <span>
                База:{' '}
                <span className={data.database_reachable ? 'text-emerald-400' : 'text-red-300'}>
                  {data.database_reachable ? 'ок' : 'нет ответа'}
                </span>
              </span>
              <span>
                Redis: <span className="text-slate-200">{redisLabel(data)}</span>
              </span>
              <span>
                ИИ (LLM):{' '}
                <span className={llmOk ? 'text-emerald-400' : 'text-amber-400/90'}>
                  {llmOk ? llmParts.join(', ') : 'не настроен'}
                </span>
              </span>
            </div>
            {data.generated_at && (
              <div className="mt-1.5 text-[10px] text-slate-500">Обновлено: {data.generated_at}</div>
            )}
          </div>

          {(data.narrative_brief_ru ?? []).length > 0 && (
            <ul className="list-inside list-disc space-y-0.5 text-[11px] leading-relaxed text-slate-400">
              {(data.narrative_brief_ru ?? []).map((line, i) => (
                <li key={i} className="marker:text-slate-600">
                  {line}
                </li>
              ))}
            </ul>
          )}

          <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
            <StatCard label="Ставки ЕТТ (hs_rates)" value={s.hs_rates_count ?? '—'} />
            <StatCard label="ТН ВЭД в БД" value={s.tnved_entries_count ?? '—'} />
            <StatCard label="Нетарифные правила" value={s.non_tariff_rules_count ?? '—'} />
            <StatCard label="Журнал расчётов" value={s.customs_calculation_history_count ?? '—'} />
          </div>

          <div className="rounded-xl border border-sky-500/20 bg-sky-950/25 px-3 py-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div>
                <div className="text-[11px] font-semibold uppercase tracking-[0.12em] text-sky-300/90">
                  Управление синхронизацией
                </div>
                <p className="mt-0.5 max-w-xl text-[11px] text-slate-400">
                  Sync Center: планировщик фоновой нормативной синхронизации (03:00), принудительный запуск и журнал.
                </p>
              </div>
              <button type="button" className="cc-btn-ghost text-[11px]" disabled={syncLoading} onClick={() => void loadSync()}>
                {syncLoading ? '…' : 'Обновить статус'}
              </button>
            </div>
            {syncErr && (
              <div className="mt-2 rounded-lg border border-amber-500/25 bg-amber-950/30 px-2.5 py-1.5 text-[11px] text-amber-100/90">
                {syncErr}
              </div>
            )}
            {syncStatus && (
              <div className="mt-3 space-y-2 text-[12px] text-slate-300">
                <div className="flex flex-wrap gap-x-4 gap-y-1">
                  <span>
                    Планировщик:{' '}
                    <span className={syncStatus.scheduler_running ? 'text-emerald-400' : 'text-amber-300'}>
                      {syncStatus.scheduler_running ? 'Работает' : 'Остановлен'}
                    </span>
                  </span>
                  <span>
                    Последняя синхронизация:{' '}
                    <span className="font-mono text-slate-200">{syncStatus.last_sync_iso ?? '—'}</span>
                  </span>
                  <span>
                    Следующая (по расписанию):{' '}
                    <span className="font-mono text-slate-200">{syncStatus.next_sync_iso ?? '—'}</span>
                  </span>
                </div>
                <div>
                  <button
                    type="button"
                    className="rounded-lg border border-sky-500/35 bg-sky-600/25 px-3 py-1.5 text-[11px] font-medium text-sky-100 hover:bg-sky-600/35 disabled:opacity-50"
                    disabled={syncActionLoading || syncLoading}
                    onClick={() => void forceSync()}
                  >
                    {syncActionLoading ? 'Запуск…' : '🚀 Принудительно запустить синхронизацию сейчас'}
                  </button>
                </div>
                <div>
                  <div className="text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-500">Журнал</div>
                  <ul className="mt-1 max-h-40 space-y-1 overflow-y-auto rounded-md border border-white/[0.06] bg-black/25 px-2 py-1.5 font-mono text-[10px] text-slate-400">
                    {(syncStatus.recent_log ?? []).length ? (
                      (syncStatus.recent_log ?? []).map((line, i) => (
                        <li key={`${line.at ?? i}-${i}`} className="border-b border-white/[0.04] py-0.5 last:border-0">
                          <span className="text-slate-500">{line.at ? `${line.at} · ` : ''}</span>
                          <span
                            className={
                              line.level === 'error' ? 'text-red-300/90' : line.level === 'warning' ? 'text-amber-200/90' : ''
                            }
                          >
                            {line.message}
                          </span>
                        </li>
                      ))
                    ) : (
                      <li className="text-slate-500">Записей пока нет — выполните синхронизацию.</li>
                    )}
                  </ul>
                </div>
              </div>
            )}
          </div>

          <details className="rounded-xl border border-white/[0.06] bg-black/15">
            <summary className="cursor-pointer select-none px-3 py-2.5 text-[11px] font-semibold text-slate-400">
              Расширенная диагностика
            </summary>
            <div className="space-y-4 border-t border-white/[0.05] p-3">
              <div className="grid gap-3 lg:grid-cols-2">
                <div className="rounded-lg border border-white/[0.06] bg-black/20 p-3">
                  <div className="text-[11px] font-semibold text-slate-300">Инфраструктура</div>
                  <div className="mt-2">
                    <BoolRow label="База данных (ping)" ok={Boolean(data.database_reachable)} />
                    <div className="flex items-center justify-between gap-2 border-b border-white/[0.04] py-1.5 text-[12px] last:border-0">
                      <span className="text-slate-400">Redis</span>
                      <span
                        className={
                          data.redis_reachable === true
                            ? 'text-emerald-400'
                            : data.redis_reachable === false
                              ? 'text-red-300'
                              : 'text-slate-500'
                        }
                      >
                        {redisLabel(data)}
                      </span>
                    </div>
                    {data.redis_reachable === null && (
                      <p className="mt-1 text-[10px] text-slate-500">REDIS_URL не задан — кэш в памяти процесса.</p>
                    )}
                  </div>
                </div>

                <div className="rounded-lg border border-white/[0.06] bg-black/20 p-3">
                  <div className="text-[11px] font-semibold text-slate-300">ИИ и вспомогательные сервисы</div>
                  <div className="mt-2">
                    <BoolRow label="Gemini / Google API" ok={Boolean(ai.gemini_configured)} />
                    <BoolRow label="Claude (Anthropic)" ok={Boolean(ai.anthropic_configured)} />
                    <BoolRow label="OpenAI (эмбеддинги)" ok={Boolean(ai.openai_embeddings_configured)} />
                    <BoolRow label="ONNX классификатор ТН ВЭД" ok={Boolean(ai.onnx_hs_classifier_configured)} />
                    <BoolRow label="Внешний классификатор" ok={Boolean(ai.custom_classifier_enabled)} />
                    <BoolRow label="Планировщик синхронизации" ok={Boolean(ai.scheduler_enabled)} />
                    <BoolRow label="RAG (каталог документов)" ok={Boolean(ai.rag_docs_dir_set)} />
                    <BoolRow label="Прокси ФСА" ok={Boolean(ai.fsa_proxy_configured)} />
                  </div>
                </div>
              </div>

              <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
                <StatCard label="ТР ТС (акты)" value={s.tr_ts_acts_count ?? '—'} />
                <StatCard label="Документы (ingested)" value={s.ingested_documents_count ?? '—'} />
                <StatCard label="Векторы ТН ВЭД" value={s.tnved_embeddings_count ?? '—'} />
                <StatCard label="Примечания" value={s.normative_notes_count ?? '—'} />
              </div>

              {(ns || nsPreview.length > 0) && (
                <div className="rounded-lg border border-white/[0.06] bg-black/20 p-3">
                  <div className="text-[11px] font-semibold text-slate-300">Нормативные источники</div>
                  {ns && (
                    <div className="mt-2 text-[11px] text-slate-400">
                      Источников: {ns.sources_count ?? '—'} · Последняя синхронизация: {ns.latest_sync_iso ?? '—'} ·
                      Устар./fallback: {ns.stale_or_fallback_count ?? 0}
                    </div>
                  )}
                  {nsPreview.length > 0 && (
                    <div className="mt-2 max-h-48 overflow-auto text-[10px]">
                      <table className="w-full border-collapse text-left">
                        <thead>
                          <tr className="border-b border-white/[0.06] text-slate-500">
                            <th className="py-1 pr-2 font-medium">Код</th>
                            <th className="py-1 pr-2 font-medium">Синхр.</th>
                            <th className="py-1 font-medium">Версия</th>
                          </tr>
                        </thead>
                        <tbody>
                          {nsPreview.map((r, i) => (
                            <tr key={`${r.source_code ?? i}`} className="border-b border-white/[0.04] text-slate-300">
                              <td className="py-1 pr-2 font-mono">{r.source_code ?? '—'}</td>
                              <td className="py-1 pr-2">{r.synced_at ?? '—'}</td>
                              <td className="py-1">
                                {r.revision ?? '—'}
                                {r.fallback ? <span className="ml-1 text-amber-400/90">fallback</span> : null}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                </div>
              )}

              <div className="grid gap-3 lg:grid-cols-2">
                <div className="rounded-lg border border-white/[0.06] bg-black/20 p-3">
                  <div className="text-[11px] font-semibold text-slate-300">Журнал расчётов</div>
                  <div className="mt-2 font-mono text-sm text-slate-200">Всего: {hist.total ?? 0}</div>
                  <div className="mt-2 flex flex-wrap gap-2 text-[11px]">
                    {Object.entries(hist.by_kind ?? {}).map(([k, v]) =>
                      v ? (
                        <span key={k} className="rounded-md bg-white/[0.06] px-2 py-0.5 text-slate-300">
                          {k}: {v}
                        </span>
                      ) : null,
                    )}
                  </div>
                </div>

                <div className="rounded-lg border border-white/[0.06] bg-black/20 p-3">
                  <div className="text-[11px] font-semibold text-slate-300">Журнал решений классификатора</div>
                  <div className="mt-2 space-y-1 text-[11px] text-slate-400">
                    <div>Записей в хвосте: {String(journal.records_in_index ?? '—')}</div>
                    <div>Уникальных кодов: {String(journal.unique_confirmed_hs_codes ?? '—')}</div>
                    <div>Клиентов (client_id): {String(journal.unique_client_ids ?? '—')}</div>
                  </div>
                </div>
              </div>

              <div className="grid gap-3 lg:grid-cols-2">
                <div className="rounded-lg border border-white/[0.06] bg-black/20 p-3">
                  <div className="text-[11px] font-semibold text-slate-300">ФСА</div>
                  <div className="mt-2 space-y-1 text-[11px] text-slate-400">
                    <div>Запросов verify: {pm.verify_requests_total ?? 0}</div>
                    <div>Документов в пакетах: {pm.verify_documents_total ?? 0}</div>
                    <div>Uptime API, с: {pm.uptime_seconds ?? '—'}</div>
                  </div>
                  {Object.keys(jobs).length > 0 && (
                    <div className="mt-2 text-[11px] text-slate-500">
                      Async ФСА:{' '}
                      {Object.entries(jobs)
                        .map(([k, v]) => `${k}=${v}`)
                        .join(', ')}
                    </div>
                  )}
                  {Object.keys(vedJobs).length > 0 && (
                    <div className="mt-1 text-[11px] text-slate-500">
                      Async ВЭД:{' '}
                      {Object.entries(vedJobs)
                        .map(([k, v]) => `${k}=${v}`)
                        .join(', ')}
                    </div>
                  )}
                </div>

                <div className="rounded-lg border border-white/[0.06] bg-black/20 p-3">
                  <div className="text-[11px] font-semibold text-slate-300">ТРОИС и эмбеддинги</div>
                  <div className="mt-2 space-y-1 text-[11px] text-slate-400">
                    <div>Брендов в кэше: {String(data.trois?.local_brands_count ?? '—')}</div>
                    <div>
                      Эмбеддинги: {String(data.embeddings?.with_vectors ?? '—')} /{' '}
                      {String(data.embeddings?.embedding_rows ?? '—')} строк
                    </div>
                    <div>Модель: {String(data.embeddings?.model ?? '—')}</div>
                  </div>
                </div>
              </div>

              {(data.normative_hints ?? []).length > 0 && (
                <div className="rounded-lg border border-amber-500/15 bg-amber-950/20 p-3">
                  <div className="text-[11px] font-semibold text-amber-200/90">Подсказки по нормативке</div>
                  <ul className="mt-2 space-y-2 text-[12px] text-slate-300">
                    {data.normative_hints!.map((h, i) => (
                      <li
                        key={i}
                        className={
                          h.level === 'warning'
                            ? 'border-l-2 border-amber-400/60 pl-2'
                            : 'border-l-2 border-sky-400/40 pl-2'
                        }
                      >
                        {h.text}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          </details>
        </>
      )}
    </div>
  );
}
