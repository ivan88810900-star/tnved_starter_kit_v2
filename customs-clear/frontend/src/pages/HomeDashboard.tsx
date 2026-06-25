import React, { useState } from 'react';
import { Calculator, FileSpreadsheet, Search } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { CC_HOME_TNVED_QUERY_KEY } from '../constants/homeNav';

export const HomeDashboard: React.FC = () => {
  const navigate = useNavigate();
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

  const quickActions = [
    {
      icon: Search,
      title: 'Найти код',
      onClick: () => navigate('/tnved'),
    },
    {
      icon: Calculator,
      title: 'Рассчитать платежи',
      onClick: () => navigate('/calculator'),
    },
    {
      icon: FileSpreadsheet,
      title: 'Пакинг-лист',
      onClick: () => navigate('/invoice'),
    },
  ];

  return (
    <div className="mx-auto max-w-3xl space-y-8 py-4">
      <h1 className="text-2xl font-medium leading-snug tracking-tight text-cargo-deep sm:text-[26px]">
        Таможенная классификация и расчёт
        <br />
        платежей для импортёров
      </h1>

      <form onSubmit={submitSearch} className="relative">
        <label htmlFor="home-tnved-search" className="sr-only">
          Поиск по ТН ВЭД
        </label>
        <Search
          className="pointer-events-none absolute left-4 top-1/2 h-5 w-5 -translate-y-1/2 text-cargo-light"
          aria-hidden
        />
        <input
          id="home-tnved-search"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Найти товар по коду или описанию..."
          className="w-full rounded-lg border-2 border-cargo-border bg-cargo-surface py-3 pl-12 pr-4 text-base text-cargo-deep placeholder:text-cargo-light focus:border-cargo-trust focus:outline-none focus:ring-2 focus:ring-cargo-trust-light"
          style={{ minHeight: 48 }}
        />
      </form>

      <div className="grid gap-3 sm:grid-cols-3">
        {quickActions.map((action) => (
          <button
            key={action.title}
            type="button"
            onClick={action.onClick}
            className="group flex flex-col items-start rounded-lg border border-cargo-border bg-cargo-surface p-4 text-left transition-colors hover:border-cargo-trust"
          >
            <span className="flex h-10 w-10 items-center justify-center rounded-lg bg-cargo-trust-light text-cargo-trust">
              <action.icon className="h-5 w-5" aria-hidden />
            </span>
            <span className="mt-3 text-sm font-medium text-cargo-deep">{action.title}</span>
          </button>
        ))}
      </div>
    </div>
  );
};
