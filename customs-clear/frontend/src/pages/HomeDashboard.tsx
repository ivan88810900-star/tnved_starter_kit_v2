import React, { useState } from 'react';
import { Calculator, Copyright, Search } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { CC_HOME_TNVED_QUERY_KEY } from '../constants/homeNav';
import { DeclarantChatPanel } from '../components/assistant/DeclarantChatPanel';
import { useAssistantSurfaceVisible } from '../context/ClientCapabilitiesContext';

export const HomeDashboard: React.FC = () => {
  const navigate = useNavigate();
  const assistantVisible = useAssistantSurfaceVisible();
  const [q, setQ] = useState('');

  const submitSearch = (e: React.FormEvent) => {
    e.preventDefault();
    const t = q.trim();
    try {
      if (t) sessionStorage.setItem(CC_HOME_TNVED_QUERY_KEY, t);
      else sessionStorage.removeItem(CC_HOME_TNVED_QUERY_KEY);
    } catch {
      /* ignore */
    }
    navigate('/tnved');
  };

  return (
    <div className="mx-auto max-w-4xl space-y-8 py-2">
      <div className="cc-card px-8 py-8 text-center">
        <h2 className="text-2xl font-semibold tracking-tight text-slate-900">Добро пожаловать</h2>
        <p className="mx-auto mt-2 max-w-2xl text-[13px] leading-relaxed text-slate-500">
          Найдите код ТН ВЭД в справочнике или перейдите к расчёту платежей и проверке товарных знаков.
        </p>
      </div>

      <form onSubmit={submitSearch} className="cc-card grid gap-3 p-4 sm:grid-cols-[1fr_auto] sm:items-stretch">
        <label htmlFor="home-tnved-search" className="sr-only">
          Поиск по ТН ВЭД
        </label>
        <div className="relative min-w-0">
          <Search
            className="pointer-events-none absolute left-4 top-1/2 h-5 w-5 -translate-y-1/2 text-slate-500"
            aria-hidden
          />
          <input
            id="home-tnved-search"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Введите код ТН ВЭД или наименование товара…"
            className="w-full rounded-2xl border border-slate-200 bg-white py-4 pl-12 pr-4 text-[15px] text-slate-900 shadow-sm placeholder:text-slate-400 focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-200"
          />
        </div>
        <button
          type="submit"
          className="rounded-2xl bg-indigo-600 px-5 py-3 text-[13px] font-semibold text-white transition-all hover:-translate-y-0.5 hover:bg-indigo-500 hover:shadow-md sm:min-h-[56px] sm:rounded-xl sm:py-0"
        >
          Справочник ТН ВЭД
        </button>
      </form>

      {assistantVisible ? <DeclarantChatPanel variant="home" /> : null}

      <div className="grid gap-3 sm:grid-cols-2">
        <button
          type="button"
          onClick={() => navigate('/calculator')}
          className="group cc-card flex flex-col items-center px-6 py-8 text-center transition-all hover:-translate-y-0.5 hover:border-indigo-200 hover:shadow-md"
        >
          <span className="flex h-12 w-12 items-center justify-center rounded-full bg-indigo-100 text-indigo-700">
            <Calculator className="h-6 w-6" aria-hidden />
          </span>
          <span className="mt-4 text-[15px] font-semibold text-slate-900">Калькулятор платежей</span>
          <span className="mt-1 text-[12px] leading-snug text-slate-500">Пошлина, НДС и сборы</span>
        </button>

        <button
          type="button"
          onClick={() => navigate('/trois')}
          className="group cc-card flex flex-col items-center px-6 py-8 text-center transition-all hover:-translate-y-0.5 hover:border-amber-200 hover:shadow-md"
        >
          <span className="flex h-12 w-12 items-center justify-center rounded-full bg-amber-100 text-amber-700">
            <Copyright className="h-6 w-6" aria-hidden />
          </span>
          <span className="mt-4 text-[15px] font-semibold text-slate-900">ТРОИС</span>
          <span className="mt-1 text-[12px] leading-snug text-slate-500">Проверка по реестру товарных знаков</span>
        </button>
      </div>
    </div>
  );
};
