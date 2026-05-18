import React, { useState } from 'react';
import { api } from '../api/client';

type TnvedHit = { hs_code: string; title: string; level: number; chapter: string };
type Note = {
  id: number;
  category: string;
  title: string;
  body: string;
  source_url?: string;
  scope_type?: string;
  scope_value?: string;
};

export const TnvedBook: React.FC = () => {
  const [q, setQ] = useState('');
  const [hits, setHits] = useState<TnvedHit[]>([]);
  const [loading, setLoading] = useState(false);
  const [stats, setStats] = useState<{
    tnved: number;
    notes: number;
    rates: number;
    nt: number;
    ingested?: number;
    embeddings?: number;
    calcHist?: number;
  } | null>(null);
  const [semQ, setSemQ] = useState('');
  const [semLoading, setSemLoading] = useState(false);
  const [semErr, setSemErr] = useState<string | null>(null);
  const [semHits, setSemHits] = useState<Array<{ score: number; hs_code: string; title: string; embedding_model?: string }>>(
    [],
  );
  const [embStatus, setEmbStatus] = useState<{
    with_vectors?: number;
    tnved_entries?: number;
    openai_configured?: boolean;
    model?: string;
  } | null>(null);
  const [detail, setDetail] = useState<{
    hs_code: string;
    title: string;
    description: string;
    breadcrumb: { hs_code: string; title: string }[];
    notes: Note[];
    official_ett_url: string;
  } | null>(null);

  React.useEffect(() => {
    api
      .get<{
        tnved_entries_count: number;
        normative_notes_count: number;
        hs_rates_count: number;
        non_tariff_rules_count: number;
        ingested_documents_count?: number;
        tnved_embeddings_count?: number;
        customs_calculation_history_count?: number;
      }>('/tnved/stats')
      .then(({ data }) => {
        setStats({
          tnved: data.tnved_entries_count,
          notes: data.normative_notes_count,
          rates: data.hs_rates_count,
          nt: data.non_tariff_rules_count,
          ingested: data.ingested_documents_count,
          embeddings: data.tnved_embeddings_count,
          calcHist: data.customs_calculation_history_count,
        });
      })
      .catch(() => setStats(null));
  }, []);

  const loadEmbStatus = async () => {
    try {
      const { data } = await api.get<{
        with_vectors?: number;
        tnved_entries?: number;
        openai_configured?: boolean;
        model?: string;
      }>('/tnved/embeddings/status');
      setEmbStatus(data);
    } catch {
      setEmbStatus(null);
    }
  };

  const semanticSearch = async () => {
    const t = semQ.trim();
    if (t.length < 2) return;
    setSemLoading(true);
    setSemErr(null);
    setSemHits([]);
    try {
      const { data } = await api.get<{ results: typeof semHits }>(
        `/tnved/search/semantic?q=${encodeURIComponent(t)}&limit=12`,
      );
      setSemHits(data.results || []);
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } }; message?: string };
      setSemErr(err?.response?.data?.detail || err.message || 'Ошибка поиска');
    } finally {
      setSemLoading(false);
    }
  };

  const search = async () => {
    if (q.trim().length < 2) return;
    setLoading(true);
    setDetail(null);
    try {
      const { data } = await api.get<{ results: TnvedHit[] }>(`/tnved/search?q=${encodeURIComponent(q.trim())}&limit=50`);
      setHits(data.results || []);
    } catch {
      setHits([]);
    } finally {
      setLoading(false);
    }
  };

  const loadLookup = async (code: string) => {
    setLoading(true);
    try {
      const { data } = await api.get(`/tnved/lookup/${encodeURIComponent(code)}`);
      setDetail(data as typeof detail);
    } catch {
      setDetail(null);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="space-y-4">
      <p className="text-[12px] leading-relaxed text-slate-500">
        Локальный справочник наименований и примечаний после{' '}
        <a href="/api/sources/template/bundle" className="text-sky-400/90 hover:underline" download>
          импорта JSON-пакета
        </a>{' '}
        или смешанного импорта (.json с секциями <span className="cc-mono text-slate-400">tnved</span>,{' '}
        <span className="cc-mono text-slate-400">rates</span>, <span className="cc-mono text-slate-400">notes</span>). Ставки ЕТТ —
        через Excel (
        <a href="https://www.tws.by/tws/tnved/download" target="_blank" rel="noreferrer" className="text-sky-400/90 hover:underline">
          TWS.BY
        </a>
        ) или тот же пакет. Официальные PDF ТН ВЭД:{' '}
        <a
          href="https://eec.eaeunion.org/comission/department/catr/ett/"
          target="_blank"
          rel="noreferrer"
          className="text-sky-400/90 hover:underline"
        >
          ЕЭК
        </a>
        .
      </p>

      {stats && (
        <div className="flex flex-wrap gap-2 text-[11px] text-slate-400">
          <span className="rounded-md border border-white/[0.06] px-2 py-1">ТН ВЭД в БД: {stats.tnved}</span>
          <span className="rounded-md border border-white/[0.06] px-2 py-1">Примечания: {stats.notes}</span>
          <span className="rounded-md border border-white/[0.06] px-2 py-1">Ставки (hs_rates): {stats.rates}</span>
          <span className="rounded-md border border-white/[0.06] px-2 py-1">Нетарифные правила: {stats.nt}</span>
          {stats.ingested != null && (
            <span className="rounded-md border border-emerald-900/40 px-2 py-1 text-emerald-200/80">
              Загрузки документов: {stats.ingested}
            </span>
          )}
          {stats.embeddings != null && (
            <span className="rounded-md border border-violet-900/40 px-2 py-1 text-violet-200/80">
              Векторов ТН ВЭД: {stats.embeddings}
            </span>
          )}
          {stats.calcHist != null && (
            <span className="rounded-md border border-sky-900/40 px-2 py-1 text-sky-200/80">
              История расчётов: {stats.calcHist}
            </span>
          )}
        </div>
      )}

      <details
        className="cc-disclosure"
        onToggle={(e) => {
          const el = e.currentTarget;
          if (el.open && !embStatus) void loadEmbStatus();
        }}
      >
        <summary>Семантический поиск по наименованиям (OpenAI)</summary>
        <div className="cc-disclosure-body space-y-3">
          <p className="text-[11px] leading-relaxed text-slate-500">
            Сначала на сервере выполняется пакетная индексация: <span className="cc-mono text-slate-400">POST /api/tnved/embeddings/ingest</span>{' '}
            (нужны <span className="cc-mono">OPENAI_API_KEY</span> и при необходимости <span className="cc-mono">X-Admin-Token</span>). Затем здесь
            можно искать формулировкой товара на естественном языке.
          </p>
          {embStatus && (
            <p className="text-[11px] text-slate-400">
              В БД векторов: <strong className="text-slate-200">{embStatus.with_vectors ?? 0}</strong> из{' '}
              <strong className="text-slate-200">{embStatus.tnved_entries ?? '—'}</strong> позиций · OpenAI:{' '}
              <strong className={embStatus.openai_configured ? 'text-emerald-300' : 'text-amber-300'}>
                {embStatus.openai_configured ? 'да' : 'нет'}
              </strong>
              {embStatus.model && <span className="text-slate-600"> · {embStatus.model}</span>}
            </p>
          )}
          <div className="flex flex-wrap items-end gap-2">
            <input
              value={semQ}
              onChange={(e) => setSemQ(e.target.value)}
              placeholder="например: электрический чайник пластик"
              className="cc-input min-w-[200px] flex-1"
              onKeyDown={(e) => e.key === 'Enter' && void semanticSearch()}
            />
            <button type="button" className="cc-btn-primary" disabled={semLoading || semQ.trim().length < 2} onClick={() => void semanticSearch()}>
              {semLoading ? '…' : 'Семантика'}
            </button>
          </div>
          {semErr && <p className="text-[11px] text-amber-200/90">{semErr}</p>}
          {semHits.length > 0 && (
            <ul className="max-h-52 space-y-1 overflow-auto rounded-lg border border-white/[0.06] bg-black/20 p-2 text-[11px]">
              {semHits.map((h) => (
                <li key={`${h.hs_code}-${h.score}`}>
                  <button
                    type="button"
                    className="flex w-full flex-col items-start rounded-md px-2 py-1.5 text-left hover:bg-white/[0.04]"
                    onClick={() => void loadLookup(h.hs_code)}
                  >
                    <span className="cc-mono text-sky-200/90">{h.hs_code}</span>
                    <span className="text-slate-400">{h.title || '—'}</span>
                    <span className="text-[10px] text-slate-600">score {h.score}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </details>

      <div className="cc-card-soft flex flex-wrap items-end gap-2 p-4">
        <div className="min-w-[200px] flex-1">
          <span className="cc-label">Код или наименование</span>
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="8509400000 или чайник"
            className="cc-input"
            onKeyDown={(e) => e.key === 'Enter' && search()}
          />
        </div>
        <button type="button" disabled={loading || q.trim().length < 2} onClick={search} className="cc-btn-primary">
          {loading ? '…' : 'Поиск'}
        </button>
      </div>

      {hits.length > 0 && (
        <div className="max-h-48 overflow-auto rounded-xl border border-white/[0.06] bg-black/20 p-2">
          {hits.map((h) => (
            <button
              key={h.hs_code}
              type="button"
              className="mb-1 flex w-full flex-col items-start rounded-lg px-2 py-1.5 text-left hover:bg-white/[0.04]"
              onClick={() => {
                void loadLookup(h.hs_code);
                setHits([]);
              }}
            >
              <span className="cc-mono text-[12px] text-sky-200/90">{h.hs_code}</span>
              <span className="text-[11px] text-slate-400">{h.title || '—'}</span>
            </button>
          ))}
        </div>
      )}

      {detail && (
        <div className="space-y-3 rounded-xl border border-sky-500/20 bg-sky-950/20 p-4">
          <div>
            <div className="cc-mono text-lg font-semibold text-sky-100">{detail.hs_code}</div>
            <p className="mt-1 text-[13px] text-slate-200">{detail.title || 'Наименование не загружено — импортируйте пакет.'}</p>
            {detail.description && <p className="mt-2 text-[12px] leading-relaxed text-slate-400">{detail.description}</p>}
          </div>
          {detail.breadcrumb?.length > 0 && (
            <div>
              <span className="cc-label">Иерархия</span>
              <ol className="mt-1 list-decimal pl-4 text-[11px] text-slate-400">
                {detail.breadcrumb.map((b) => (
                  <li key={b.hs_code}>
                    <span className="cc-mono text-sky-200/80">{b.hs_code}</span> — {b.title || '—'}
                  </li>
                ))}
              </ol>
            </div>
          )}
          {detail.notes?.length > 0 && (
            <div>
              <span className="cc-label">Примечания</span>
              <ul className="mt-2 space-y-2">
                {detail.notes.map((n) => (
                  <li key={n.id} className="rounded-lg border border-white/[0.06] bg-black/20 px-3 py-2 text-[11px] text-slate-300">
                    <span className="font-medium text-slate-200">{n.title}</span>
                    <span className="ml-2 rounded bg-white/[0.06] px-1.5 py-0.5 text-[9px] uppercase text-slate-500">{n.category}</span>
                    <p className="mt-1 whitespace-pre-wrap text-slate-400">{n.body}</p>
                    {n.source_url && (
                      <a href={n.source_url} target="_blank" rel="noreferrer" className="mt-1 inline-block text-sky-400/80 hover:underline">
                        Источник
                      </a>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          )}
          <a href={detail.official_ett_url} target="_blank" rel="noreferrer" className="cc-btn-ghost inline-flex">
            ТН ВЭД и ЕТТ на сайте ЕЭК
          </a>
        </div>
      )}
    </div>
  );
};
