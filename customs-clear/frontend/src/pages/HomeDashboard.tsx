import React, { useEffect, useState } from 'react';
import { Calculator, FileSpreadsheet, Search } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { api } from '../api/client';
import { CC_HOME_TNVED_QUERY_KEY } from '../constants/homeNav';
import { DeclarantChatPanel } from '../components/assistant/DeclarantChatPanel';
import { PageHeader } from '../components/PageHeader';
import { useAssistantSurfaceVisible } from '../context/ClientCapabilitiesContext';

function formatStat(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  return n.toLocaleString('ru-RU');
}

export const HomeDashboard: React.FC = () => {
  const navigate = useNavigate();
  const assistantVisible = useAssistantSurfaceVisible();
  const [q, setQ] = useState('');
  const [stats, setStats] = useState<{ tnved: string; nt: string; rates: string }>({
    tnved: '—',
    nt: '—',
    rates: '—',
  });

  useEffect(() => {
    void api
      .get<{ tnved_entries_count?: number; non_tariff_rules_count?: number; hs_rates_count?: number }>(
        '/tnved/stats',
      )
      .then(({ data }) => {
        setStats({
          tnved: formatStat(data.tnved_entries_count ?? 0),
          nt: formatStat(data.non_tariff_rules_count ?? 0),
          rates: formatStat(data.hs_rates_count ?? 0),
        });
      })
      .catch(() => {
        /* keep placeholders */
      });
  }, []);

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
      desc: 'Справочник ТН ВЭД с деревом и поиском',
      onClick: () => navigate('/tnved'),
    },
    {
      icon: Calculator,
      title: 'Рассчитать платежи',
      desc: 'Пошлина, НДС и таможенные сборы',
      onClick: () => navigate('/calculator'),
    },
    {
      icon: FileSpreadsheet,
      title: 'Загрузить пакинг-лист',
      desc: 'AI-классификация по названиям и фото',
      onClick: () => navigate('/invoice'),
    },
  ];

  return (
    <div className="space-y-6">
      <PageHeader
        title="Главная"
        subtitle="Найдите код ТН ВЭД, рассчитайте платежи или загрузите пакинг-лист для классификации"
        stats={[
          { label: 'Кодов ТН ВЭД', value: stats.tnved },
          { label: 'Нетарифных мер', value: stats.nt },
          { label: 'Ставок hs_rates', value: stats.rates },
        ]}
      />

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
            <span className="mt-1 text-xs text-cargo-mid">{action.desc}</span>
          </button>
        ))}
      </div>

      {assistantVisible ? <DeclarantChatPanel variant="home" /> : null}
    </div>
  );
};
