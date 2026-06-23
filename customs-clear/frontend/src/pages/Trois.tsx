import React, { useEffect, useState } from 'react';
import { api } from '../api/client';
import { getAdminToken, setAdminToken as setAdminTokenMemory } from '../api/adminToken';
import { getUserFacingApiError } from '../api/error';
import type {
  TroisCheckResponse,
  TroisSuggestResponse,
  TroisSuggestion,
  TroisSyncResponse,
} from '../types/api.types';

export const Trois: React.FC = () => {
  const [query, setQuery] = useState('');
  const [loading, setLoading] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<TroisCheckResponse | null>(null);
  const [suggestions, setSuggestions] = useState<TroisSuggestion[]>([]);
  const [syncInfo, setSyncInfo] = useState<string>('');
  const [adminToken, setAdminToken] = useState(() => getAdminToken());

  useEffect(() => {
    const q = query.trim();
    if (q.length < 2) {
      setSuggestions([]);
      return;
    }
    const t = setTimeout(async () => {
      try {
        const { data } = await api.get<TroisSuggestResponse>('/trois/suggest', { params: { q, limit: 8 } });
        setSuggestions(data.suggestions || []);
      } catch {
        setSuggestions([]);
      }
    }, 300);
    return () => clearTimeout(t);
  }, [query]);

  const handleCheck = async () => {
    if (!query.trim()) return;
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const { data } = await api.post<TroisCheckResponse>('/trois/check', { query });
      setResult(data);
    } catch (e) {
      setError(getUserFacingApiError(e, 'Не удалось выполнить проверку ТРОИС.'));
    } finally {
      setLoading(false);
    }
  };

  const handleSync = async () => {
    setSyncing(true);
    setError(null);
    setSyncInfo('');
    try {
      const headers: Record<string, string> = {};
      const adminTokenValue = adminToken.trim();
      if (adminTokenValue) headers['X-Admin-Token'] = adminTokenValue;
      const { data } = await api.post<TroisSyncResponse>('/trois/sync', {}, { headers });
      setSyncInfo(
        `Синхронизация завершена: parsed=${data?.parsed_records ?? 0}, dedup=${data?.dedup_records ?? 0}, created=${data?.created ?? 0}, updated=${data?.updated ?? 0}`,
      );
    } catch (e) {
      setError(getUserFacingApiError(e, 'Не удалось обновить справочник ТРОИС.'));
    } finally {
      setSyncing(false);
    }
  };

  return (
    <div className="space-y-4">
      <p className="text-[12px] text-slate-600">Поиск по локальному справочнику товарных знаков.</p>
      <p className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-[11px] leading-relaxed text-slate-600">
        Проверка по локальной копии реестра ТРОИС (открытые данные ФТС). Для юридически значимой проверки используйте{' '}
        <a
          href="https://customs.gov.ru/registers/objects-intellectual-property"
          target="_blank"
          rel="noopener noreferrer"
          className="text-indigo-600 hover:underline"
        >
          официальный реестр ФТС
        </a>
        .
      </p>
      <details className="cc-disclosure">
        <summary>Быстрый выбор бренда</summary>
        <div className="cc-disclosure-body flex flex-wrap gap-1.5">
          {['Apple', 'Samsung', 'Philips', 'Bosch', 'Nike', 'IKEA', 'BMW', 'Coca-Cola'].map((b) => (
            <button key={b} type="button" className="cc-btn-ghost text-[11px]" onClick={() => setQuery(b)}>
              {b}
            </button>
          ))}
        </div>
      </details>
      <input
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        placeholder="Торговая марка"
        className="cc-input"
      />
      {suggestions.length > 0 && (
        <div className="flex flex-wrap gap-1 text-[11px]">
          {suggestions.map((s) => (
            <button key={s.key} type="button" className="cc-btn-ghost py-0.5 px-2" onClick={() => setQuery(s.label)}>
              {s.label}
            </button>
          ))}
        </div>
      )}
      <div className="flex flex-wrap gap-2">
        <input
          type="password"
          value={adminToken}
          onChange={(e) => {
            const value = e.target.value;
            setAdminToken(value);
            setAdminTokenMemory(value);
          }}
          placeholder="Токен администратора (для обновления справочника)"
          className="cc-input min-w-[260px] flex-1"
        />
        <button type="button" disabled={!query.trim() || loading} onClick={handleCheck} className="cc-btn-primary">
          {loading ? 'Поиск…' : 'Проверить'}
        </button>
        <button type="button" disabled={syncing} onClick={handleSync} className="cc-btn-ghost">
          {syncing ? 'Синхронизация…' : 'Обновить реестр ТРОИС'}
        </button>
      </div>
      {syncInfo && (
        <div className="rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-xs text-emerald-700">
          {syncInfo}
        </div>
      )}
      {error && (
        <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
          {error}
        </div>
      )}
      {result && (
        <div className="space-y-2 text-xs">
          {result.status === 'ERROR' && result.error && (
            <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-amber-800">
              {result.error}
              {result.note && <p className="mt-1 text-amber-700">{result.note}</p>}
            </div>
          )}
          {result.status !== 'ERROR' && (
            <div
              className={`rounded-lg px-3 py-2 ${
                result.found
                  ? 'border-amber-200 bg-amber-50 text-amber-800'
                  : result.risk_level === 'low'
                    ? 'border-emerald-200 bg-emerald-50 text-emerald-800'
                    : 'border-slate-200 bg-slate-50 text-slate-700'
              }`}
            >
              {result.found
                ? '⚠️ Знак найден в реестре: требуется разрешение правообладателя.'
                : result.risk_level === 'low'
                  ? '✅ Бренд не найден в локальной БД — риск по ТРОИС низкий (проверьте официальный реестр).'
                  : '❓ Бренд не проверен автоматически — проверьте вручную в реестре ФТС.'}
            </div>
          )}
          {result.freshness_label && (
            <p className="text-[11px] text-slate-500">
              {result.freshness_label}
              {result.registry_source ? ` · Источник: ${result.registry_source}` : ''}
            </p>
          )}
          {result.note && result.status !== 'ERROR' && (
            <div className="cc-card-soft px-3 py-2 text-slate-700">
              {result.note}
            </div>
          )}
          {Array.isArray(result.details) && result.details.length > 0 && (
            <details className="cc-disclosure" open>
              <summary>Записи справочника</summary>
              <div className="cc-disclosure-body space-y-2">
                {result.details.map((d, i) => (
                  <div key={i} className="flex flex-wrap gap-x-4 gap-y-1 border-b border-slate-200 pb-2 text-[12px] text-slate-700 last:border-0">
                    {Array.isArray(d.cols) && d.cols.map((c, j) => (
                      <span key={j}>{String(c)}</span>
                    ))}
                  </div>
                ))}
              </div>
            </details>
          )}
        </div>
      )}
    </div>
  );
};

