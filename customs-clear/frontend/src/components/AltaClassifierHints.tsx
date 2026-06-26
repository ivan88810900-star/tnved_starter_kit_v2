import React, { useEffect, useState } from 'react';
import { api } from '../api/client';

type AltaStatus = {
  status: string;
  tik: { enabled: boolean; configured: boolean };
  apu: { enabled: boolean; configured: boolean; suggest_public?: boolean };
};

type ApuLine = { term: string; payload: string; weight: string; tngroup: string };
type ApuCodeLine = { tnved: string; weight: number | null; descr: string; descr_sh: string; tncode: string };
type TikItem = { code: string; count: number; notes: { name: string }[] };

export const AltaClassifierHints: React.FC<{ onPickHs: (code: string) => void }> = ({ onPickHs }) => {
  const [st, setSt] = useState<AltaStatus | null>(null);
  const [apuQ, setApuQ] = useState('');
  const [apuLines, setApuLines] = useState<ApuLine[]>([]);
  const [apuCodes, setApuCodes] = useState<ApuCodeLine[]>([]);
  const [tikQ, setTikQ] = useState('');
  const [tikItems, setTikItems] = useState<TikItem[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    api
      .get<AltaStatus>('/integrations/alta/status')
      .then(({ data }) => setSt(data))
      .catch(() => setSt(null));
  }, []);

  if (!st) return null;

  const apuSuggestOk = st.apu?.enabled;
  const apuCodesOk = st.apu?.enabled && st.apu?.configured;
  const tikOk = st.tik?.enabled && st.tik?.configured;

  if (!apuSuggestOk && !tikOk) return null;

  const runApuSuggest = async () => {
    const q = apuQ.trim();
    if (!q) return;
    setBusy('apu-suggest');
    setErr(null);
    setApuCodes([]);
    try {
      const { data } = await api.get<{ status: string; lines?: ApuLine[]; error_descr?: string }>(
        '/integrations/alta/apu/suggest',
        { params: { q, limit: 12 } },
      );
      if (data.status === 'ERROR') {
        setErr(data.error_descr || 'Ошибка АПУ');
        setApuLines([]);
      } else {
        setApuLines(data.lines || []);
      }
    } catch (e: unknown) {
      const ax = e as { response?: { data?: { detail?: string } }; message?: string };
      setErr(ax?.response?.data?.detail || ax?.message || 'Сеть');
      setApuLines([]);
    } finally {
      setBusy(null);
    }
  };

  const runApuCodes = async (payload: string) => {
    setBusy('apu-codes');
    setErr(null);
    try {
      const { data } = await api.get<{ status: string; lines?: ApuCodeLine[]; error_descr?: string }>(
        '/integrations/alta/apu/codes',
        { params: { code: payload, limit: 25 } },
      );
      if (data.status === 'ERROR') {
        setErr(data.error_descr || 'Ошибка кодов АПУ');
        setApuCodes([]);
      } else {
        setApuCodes(data.lines || []);
      }
    } catch (e: unknown) {
      const ax = e as { response?: { data?: { detail?: string } }; message?: string };
      setErr(ax?.response?.data?.detail || ax?.message || 'Сеть');
      setApuCodes([]);
    } finally {
      setBusy(null);
    }
  };

  const runTik = async () => {
    const s = tikQ.trim();
    if (s.length < 3) return;
    setBusy('tik');
    setErr(null);
    try {
      const { data } = await api.get<{ status: string; items?: TikItem[]; error_descr?: string }>(
        '/integrations/alta/tik/search',
        { params: { srchstr: s } },
      );
      if (data.status === 'ERROR') {
        setErr(data.error_descr || 'Ошибка ТиК');
        setTikItems([]);
      } else {
        setTikItems(data.items || []);
      }
    } catch (e: unknown) {
      const ax = e as { response?: { data?: { detail?: string } }; message?: string };
      setErr(ax?.response?.data?.detail || ax?.message || 'Сеть');
      setTikItems([]);
    } finally {
      setBusy(null);
    }
  };

  return (
    <details className="cc-disclosure">
      <summary>Запасной источник: Альта-Софт</summary>
      <div className="cc-disclosure-body space-y-4">
        <p className="text-[11px] leading-relaxed text-slate-500">
          Используйте после договора с Альтой, если локальная база и{' '}
          <a href="https://www.tws.by/tws/tnved/download" target="_blank" rel="noreferrer" className="text-indigo-600 hover:underline">
            выгрузка TWS
          </a>{' '}
          недостаточны. АПУ — подсказки и коды; ТиК — статистика по фразе. Код подставляется в описание.
        </p>
        {err && <div className="rounded-lg border border-red-200 bg-red-50 px-2 py-1.5 text-[11px] text-red-700">{err}</div>}

        {apuSuggestOk && (
          <div className="space-y-2">
            <div className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">Подбор кода (АПУ)</div>
            <div className="flex flex-wrap gap-2">
              <input
                value={apuQ}
                onChange={(e) => setApuQ(e.target.value)}
                placeholder="Слово или фраза"
                className="cc-input min-w-[12rem] flex-1"
              />
              <button type="button" disabled={busy !== null || !apuQ.trim()} className="cc-btn-ghost" onClick={() => void runApuSuggest()}>
                {busy === 'apu-suggest' ? '…' : 'Подсказки'}
              </button>
            </div>
            {apuLines.length > 0 && (
              <ul className="max-h-36 space-y-1 overflow-auto text-[11px] text-slate-600">
                {apuLines.map((l) => (
                  <li key={l.payload} className="flex flex-wrap items-center gap-2 border-b border-slate-200 py-1">
                    <span className="text-slate-700">{l.term}</span>
                    {apuCodesOk ? (
                      <button type="button" className="cc-btn-ghost py-0.5 text-[10px]" onClick={() => void runApuCodes(l.payload)}>
                        Коды ТН ВЭД
                      </button>
                    ) : (
                      <span className="text-[10px] text-slate-600">Сервис недоступен</span>
                    )}
                  </li>
                ))}
              </ul>
            )}
            {apuCodes.length > 0 && (
              <ul className="max-h-40 space-y-1 overflow-auto">
                {apuCodes.map((c) => (
                  <li key={c.tnved} className="flex flex-wrap items-baseline gap-2 text-[11px]">
                    <button type="button" className="cc-mono text-indigo-700 hover:underline" onClick={() => onPickHs(c.tnved)}>
                      {c.tnved}
                    </button>
                    <span className="text-slate-500">{c.descr_sh || c.descr}</span>
                    {c.weight != null && <span className="text-slate-600">· {c.weight}</span>}
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}

        {tikOk && (
          <div className="space-y-2 border-t border-slate-200 pt-3">
            <div className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">Товары и коды (ТиК)</div>
            <div className="flex flex-wrap gap-2">
              <input
                value={tikQ}
                onChange={(e) => setTikQ(e.target.value)}
                placeholder="Не короче 3 символов"
                className="cc-input min-w-[12rem] flex-1"
              />
              <button type="button" disabled={busy !== null || tikQ.trim().length < 3} className="cc-btn-ghost" onClick={() => void runTik()}>
                {busy === 'tik' ? '…' : 'Поиск'}
              </button>
            </div>
            {tikItems.length > 0 && (
              <div className="max-h-48 space-y-2 overflow-auto text-[11px]">
                {tikItems.map((it) => (
                  <div key={it.code} className="rounded-lg border border-slate-200 bg-slate-50 p-2">
                    <button type="button" className="cc-mono font-medium text-indigo-700 hover:underline" onClick={() => onPickHs(it.code)}>
                      {it.code}
                    </button>
                    <span className="ml-2 text-slate-500">×{it.count}</span>
                    {it.notes.slice(0, 2).map((n, i) => (
                      <div key={i} className="mt-1 line-clamp-2 text-slate-500">
                        {n.name}
                      </div>
                    ))}
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </details>
  );
};
