import React, { useCallback, useEffect, useState } from 'react';
import { api } from '../api/client';
import { getUserFacingApiError, isTechnicalErrorMessage } from '../api/error';
import { AltaClassifierHints } from '../components/AltaClassifierHints';

function userVisibleClassifierNote(note?: string): string | null {
  const t = (note || '').trim();
  if (!t) return null;
  const low = t.toLowerCase();
  if (
    low.includes('onnx') ||
    low.includes('llm') ||
    low.includes('fallback') ||
    low.includes('custom_class') ||
    low.includes('http')
  ) {
    return null;
  }
  if (isTechnicalErrorMessage(t)) return null;
  return t;
}

type ClassifyResult = {
  status: string;
  query?: string;
  results: {
    code?: string;
    hs_code?: string;
    name?: string;
    duty_rate?: string;
    permits?: string[];
    confidence?: number;
    recommended?: boolean;
    reasoning?: string;
  }[];
  note?: string;
};

type HistoryItem = {
  id: string;
  timestamp: string;
  query: string;
  source: string;
  top_codes: string[];
};

type ClassifyMode = 'text' | 'image' | 'characteristics' | 'history';

function resultCode(r: ClassifyResult['results'][0]): string {
  return (r.code || r.hs_code || '').trim();
}

function ClassifyResults({ result }: { result: ClassifyResult }) {
  return (
    <div className="space-y-3 text-xs">
      {userVisibleClassifierNote(result.note) && (
        <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-amber-800">
          {userVisibleClassifierNote(result.note)}
        </div>
      )}
      {result.results?.map((r, i) => (
        <div key={resultCode(r) || i} className="cc-card-soft space-y-1.5 p-3">
          <div className="flex items-center justify-between gap-2">
            <div className="font-mono text-sm text-indigo-700">{resultCode(r) || '—'}</div>
            {r.recommended ? <span className="cc-badge-ok">Рекомендуется</span> : null}
          </div>
          {r.name ? <div className="text-slate-800">{r.name}</div> : null}
          <div className="flex flex-wrap gap-2 text-[11px] text-slate-700">
            {r.duty_rate ? (
              <span className="rounded-full bg-blue-100 px-2 py-0.5 text-blue-800">Пошлина: {r.duty_rate}</span>
            ) : null}
            {typeof r.confidence === 'number' ? (
              <span className="rounded-full bg-indigo-100 px-2 py-0.5 text-indigo-800">
                Уверенность: {(r.confidence * 100).toFixed(1)}%
              </span>
            ) : null}
          </div>
          {r.permits && r.permits.length > 0 ? (
            <div className="text-[11px] text-slate-700">Документы: {r.permits.join(', ')}</div>
          ) : null}
          {r.reasoning ? <div className="text-[11px] text-slate-600">Обоснование: {r.reasoning}</div> : null}
        </div>
      ))}
    </div>
  );
}

export const Classifier: React.FC = () => {
  const [mode, setMode] = useState<ClassifyMode>('text');
  const [text, setText] = useState('');
  const [imageHint, setImageHint] = useState('');
  const [imagePreview, setImagePreview] = useState<string | null>(null);
  const [imageBase64, setImageBase64] = useState('');
  const [chars, setChars] = useState({ material: '', purpose: '', principle: '', function: '', description: '' });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<ClassifyResult | null>(null);
  const [history, setHistory] = useState<HistoryItem[]>([]);
  const [useJournalHints, setUseJournalHints] = useState(true);
  const [clientId, setClientId] = useState(() => localStorage.getItem('cc_audit_client_id') || '');

  const loadHistory = useCallback(async () => {
    try {
      const { data } = await api.get<{ items: HistoryItem[] }>('/classify/history?limit=20');
      setHistory(data.items || []);
    } catch {
      setHistory([]);
    }
  }, []);

  useEffect(() => {
    if (mode === 'history') void loadHistory();
  }, [mode, loadHistory]);

  const handleTextSubmit = async () => {
    if (!text.trim()) return;
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      if (clientId.trim()) sessionStorage.setItem('cc_audit_client_id', clientId.trim());
      else sessionStorage.removeItem('cc_audit_client_id');
      const { data } = await api.post<ClassifyResult>('/classify', {
        description: text,
        use_journal_hints: useJournalHints,
        client_id: clientId.trim() || undefined,
      });
      setResult(data);
    } catch (e: unknown) {
      setError(getUserFacingApiError(e, 'Не удалось подобрать код ТН ВЭД. Попробуйте позже.'));
    } finally {
      setLoading(false);
    }
  };

  const onImageFile = (file: File) => {
    const reader = new FileReader();
    reader.onload = () => {
      const dataUrl = String(reader.result || '');
      setImagePreview(dataUrl);
      setImageBase64(dataUrl);
    };
    reader.readAsDataURL(file);
  };

  const handleImageSubmit = async () => {
    if (!imageBase64) return;
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const { data } = await api.post<ClassifyResult>('/classify/image', {
        image_base64: imageBase64,
        hint: imageHint.trim(),
      });
      setResult(data);
      void loadHistory();
    } catch (e: unknown) {
      setError(getUserFacingApiError(e, 'Не удалось классифицировать по фото.'));
    } finally {
      setLoading(false);
    }
  };

  const handleCharacteristicsSubmit = async () => {
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const { data } = await api.post<ClassifyResult>('/classify/characteristics', chars);
      setResult(data);
      void loadHistory();
    } catch (e: unknown) {
      setError(getUserFacingApiError(e, 'Не удалось классифицировать по характеристикам.'));
    } finally {
      setLoading(false);
    }
  };

  const fillDemo = (value: string) => setText(value);

  const copyJson = async () => {
    if (!result) return;
    await navigator.clipboard.writeText(JSON.stringify(result, null, 2));
  };

  const tabs: { id: ClassifyMode; label: string }[] = [
    { id: 'text', label: 'Описание' },
    { id: 'image', label: 'Фото' },
    { id: 'characteristics', label: 'Характеристики' },
    { id: 'history', label: 'История' },
  ];

  return (
    <div className="space-y-4">
      <p className="text-[12px] text-slate-600">Подбор кода ТН ВЭД по описанию, фото или структурированным характеристикам.</p>

      <div className="flex flex-wrap gap-1 rounded-lg border border-slate-200 bg-slate-50 p-1">
        {tabs.map((t) => (
          <button
            key={t.id}
            type="button"
            className={`rounded-md px-3 py-1.5 text-[12px] ${mode === t.id ? 'bg-white font-medium text-indigo-700 shadow-sm' : 'text-slate-600'}`}
            onClick={() => {
              setMode(t.id);
              setError(null);
              setResult(null);
            }}
          >
            {t.label}
          </button>
        ))}
      </div>

      {mode === 'text' ? (
        <>
          <details className="cc-disclosure">
            <summary>Дополнительные параметры</summary>
            <div className="cc-disclosure-body space-y-3">
              <input
                value={clientId}
                onChange={(e) => setClientId(e.target.value)}
                placeholder="Идентификатор клиента (приоритет в журнале)"
                className="cc-input"
              />
              <label className="flex cursor-pointer items-center gap-2 text-[12px] text-slate-700">
                <input type="checkbox" checked={useJournalHints} onChange={(e) => setUseJournalHints(e.target.checked)} />
                Учитывать журнал подтверждений
              </label>
            </div>
          </details>
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              className="cc-btn-ghost"
              onClick={() => fillDemo('Электрический чайник 1.7 л, 220В, бытовой, пластик/нержавеющая сталь')}
            >
              Чайник
            </button>
            <button
              type="button"
              className="cc-btn-ghost"
              onClick={() => fillDemo('Смартфон, 6.7", 256GB, LTE/5G, аккумулятор Li-ion')}
            >
              Смартфон
            </button>
            <button type="button" className="cc-btn-ghost" onClick={() => setText('')}>
              Очистить
            </button>
          </div>
          <textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="Опишите товар на любом языке…"
            className="cc-input min-h-[140px]"
          />
          <button type="button" disabled={!text.trim() || loading} onClick={() => void handleTextSubmit()} className="cc-btn-primary">
            {loading ? 'Анализ…' : 'Определить код'}
          </button>
          <AltaClassifierHints
            onPickHs={(code) => {
              const c = code.replace(/\D/g, '').slice(0, 10);
              if (!c) return;
              const line = `ТН ВЭД ${c}`;
              setText((t) => {
                if (!t.trim()) return line;
                if (t.replace(/\D/g, '').includes(c)) return t;
                return `${t.trim()}\n${line}`;
              });
            }}
          />
        </>
      ) : null}

      {mode === 'image' ? (
        <div className="space-y-3">
          <input
            type="file"
            accept="image/*"
            className="text-sm"
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) onImageFile(f);
            }}
          />
          {imagePreview ? (
            <img src={imagePreview} alt="Превью" className="max-h-48 rounded-lg border border-slate-200 object-contain" />
          ) : null}
          <input
            value={imageHint}
            onChange={(e) => setImageHint(e.target.value)}
            placeholder="Подсказка (опционально)"
            className="cc-input"
          />
          <button type="button" disabled={!imageBase64 || loading} onClick={() => void handleImageSubmit()} className="cc-btn-primary">
            {loading ? 'Анализ фото…' : 'Классифицировать по фото'}
          </button>
        </div>
      ) : null}

      {mode === 'characteristics' ? (
        <div className="grid gap-2 sm:grid-cols-2">
          {(
            [
              ['material', 'Материал'],
              ['purpose', 'Назначение'],
              ['principle', 'Принцип работы'],
              ['function', 'Функция'],
              ['description', 'Доп. описание'],
            ] as const
          ).map(([key, label]) => (
            <label key={key} className="space-y-1 sm:col-span-2">
              <span className="cc-label">{label}</span>
              <input
                value={chars[key]}
                onChange={(e) => setChars((c) => ({ ...c, [key]: e.target.value }))}
                className="cc-input"
              />
            </label>
          ))}
          <div className="sm:col-span-2">
            <button type="button" disabled={loading} onClick={() => void handleCharacteristicsSubmit()} className="cc-btn-primary">
              {loading ? 'Анализ…' : 'Классифицировать по характеристикам'}
            </button>
          </div>
        </div>
      ) : null}

      {mode === 'history' ? (
        <div className="space-y-2">
          <button type="button" className="cc-btn-ghost text-sm" onClick={() => void loadHistory()}>
            Обновить
          </button>
          {history.length === 0 ? (
            <p className="text-[12px] text-slate-500">История пуста — выполните классификацию по фото или характеристикам.</p>
          ) : (
            <ul className="divide-y divide-slate-100 rounded-xl border border-slate-200 bg-white text-[12px]">
              {history.map((h) => (
                <li key={h.id} className="px-3 py-2">
                  <div className="flex flex-wrap justify-between gap-1 text-slate-500">
                    <span>{new Date(h.timestamp).toLocaleString('ru-RU')}</span>
                    <span>{h.source}</span>
                  </div>
                  <p className="mt-1 text-slate-800">{h.query}</p>
                  {h.top_codes?.length ? (
                    <p className="mt-0.5 font-mono text-indigo-700">{h.top_codes.filter(Boolean).join(', ')}</p>
                  ) : null}
                </li>
              ))}
            </ul>
          )}
        </div>
      ) : null}

      {loading && mode !== 'history' ? (
        <div className="space-y-2">
          <div className="cc-skeleton h-5 w-40" />
          <div className="cc-skeleton h-24 w-full" />
        </div>
      ) : null}
      {error ? (
        <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">{error}</div>
      ) : null}
      {result && mode !== 'history' ? (
        <>
          <ClassifyResults result={result} />
          <details className="cc-disclosure">
            <summary>Экспорт результата</summary>
            <div className="cc-disclosure-body">
              <button type="button" onClick={copyJson} className="cc-btn-ghost">
                Копировать JSON
              </button>
            </div>
          </details>
        </>
      ) : null}
    </div>
  );
};
