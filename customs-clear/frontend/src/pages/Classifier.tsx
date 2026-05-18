import React, { useState } from 'react';
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
  query: string;
  results: {
    code: string;
    name: string;
    duty_rate: string;
    permits: string[];
    confidence: number;
    recommended: boolean;
    reasoning: string;
  }[];
  note?: string;
};

export const Classifier: React.FC = () => {
  const [text, setText] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<ClassifyResult | null>(null);
  const [useJournalHints, setUseJournalHints] = useState(true);
  const [clientId, setClientId] = useState(() => localStorage.getItem('cc_audit_client_id') || '');

  const handleSubmit = async () => {
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

  const fillDemo = (value: string) => setText(value);

  const copyJson = async () => {
    if (!result) return;
    await navigator.clipboard.writeText(JSON.stringify(result, null, 2));
  };

  return (
    <div className="space-y-4">
      <p className="text-[12px] text-slate-600">Описание товара → варианты кодов с обоснованием.</p>
      <details className="cc-disclosure">
        <summary>Расширенные источники подбора</summary>
        <div className="cc-disclosure-body text-[11px] leading-relaxed text-slate-500">
          Дополнительные модули подбора кода ТН ВЭД подключаются на стороне организации. При отсутствии расширений
          используются стандартные средства приложения.
        </div>
      </details>
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
        <button type="button" className="cc-btn-ghost" onClick={() => fillDemo('Электрический чайник 1.7 л, 220В, бытовой, пластик/нержавеющая сталь')}>
          Чайник
        </button>
        <button type="button" className="cc-btn-ghost" onClick={() => fillDemo('Смартфон, 6.7", 256GB, LTE/5G, аккумулятор Li-ion')}>
          Смартфон
        </button>
        <button type="button" className="cc-btn-ghost" onClick={() => setText('')}>
          Очистить
        </button>
      </div>
      <textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder="Опишите товар на русском, английском или китайском языке…"
        className="cc-input min-h-[140px]"
      />
      <div className="flex flex-wrap gap-2">
        <button type="button" disabled={!text.trim() || loading} onClick={handleSubmit} className="cc-btn-primary">
          {loading ? 'Анализ…' : 'Определить код'}
        </button>
      </div>
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
      {loading && (
        <div className="space-y-2">
          <div className="cc-skeleton h-5 w-40" />
          <div className="cc-skeleton h-24 w-full" />
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
          {userVisibleClassifierNote(result.note) && (
            <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-amber-800">
              {userVisibleClassifierNote(result.note)}
            </div>
          )}
          {result.results?.map((r) => (
            <div
              key={r.code}
              className="cc-card-soft p-3 space-y-1.5"
            >
              <div className="flex items-center justify-between gap-2">
                <div className="font-mono text-sm text-indigo-700">{r.code}</div>
                {r.recommended && (
                  <span className="cc-badge-ok">
                    Рекомендуется
                  </span>
                )}
              </div>
              <div className="text-slate-800">{r.name}</div>
              <div className="flex flex-wrap gap-2 text-[11px] text-slate-700">
                <span className="rounded-full bg-blue-100 px-2 py-0.5 text-blue-800">
                  Пошлина: {r.duty_rate || '—'}
                </span>
                <span className="rounded-full bg-indigo-100 px-2 py-0.5 text-indigo-800">
                  Уверенность: {(r.confidence * 100).toFixed(1)}%
                </span>
              </div>
              {r.permits?.length > 0 && (
                <div className="text-[11px] text-slate-700">
                  Документы: {r.permits.join(', ')}
                </div>
              )}
              <div className="text-[11px] text-slate-600">Обоснование: {r.reasoning}</div>
            </div>
          ))}
          <details className="cc-disclosure">
            <summary>Экспорт результата</summary>
            <div className="cc-disclosure-body">
              <button type="button" onClick={copyJson} className="cc-btn-ghost">
                Копировать JSON
              </button>
            </div>
          </details>
        </div>
      )}
    </div>
  );
};

