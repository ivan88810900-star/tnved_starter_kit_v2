import React, { useState } from 'react';
import { Calculator, FileSpreadsheet, Search } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { CC_HOME_TNVED_QUERY_KEY } from '../constants/homeNav';

const HERO_GRID_STYLE: React.CSSProperties = {
  backgroundImage: `repeating-linear-gradient(
      0deg, transparent, transparent 40px,
      rgba(255,255,255,0.02) 40px, rgba(255,255,255,0.02) 41px
    ), repeating-linear-gradient(
      90deg, transparent, transparent 40px,
      rgba(255,255,255,0.02) 40px, rgba(255,255,255,0.02) 41px
    )`,
};

export const HomeDashboard: React.FC = () => {
  const navigate = useNavigate();
  const [q, setQ] = useState('');
  const [searchFocused, setSearchFocused] = useState(false);

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
    { icon: Search, title: 'Найти код', href: '/tnved' },
    { icon: Calculator, title: 'Рассчитать платежи', href: '/calculator' },
    { icon: FileSpreadsheet, title: 'Пакинг-лист', href: '/invoice' },
  ];

  return (
    <div className="mx-auto max-w-3xl">
      {/* Hero — выходит за padding main (p-6) */}
      <div
        className="relative -mx-6 -mt-6 mb-6 overflow-hidden px-8 pb-10 pt-12"
        style={{
          background: 'linear-gradient(135deg, var(--hero-from) 0%, var(--hero-to) 100%)',
        }}
      >
        <div className="pointer-events-none absolute inset-0" style={HERO_GRID_STYLE} aria-hidden />

        <h1 className="relative text-[28px] font-semibold leading-snug tracking-tight text-white">
          Таможенная классификация
          <br />
          и расчёт платежей
        </h1>
        <p className="relative mb-6 mt-2 text-sm text-white/55">
          Справочник ТН ВЭД · Расчёт платежей · Нетарифные меры
        </p>

        <form onSubmit={submitSearch} className="relative max-w-xl">
          <label htmlFor="home-tnved-search" className="sr-only">
            Поиск по ТН ВЭД
          </label>
          <Search
            className={`pointer-events-none absolute left-3.5 top-1/2 -translate-y-1/2 transition-colors ${
              searchFocused ? 'text-white/60' : 'text-white/40'
            }`}
            size={18}
            aria-hidden
          />
          <input
            id="home-tnved-search"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            onFocus={() => setSearchFocused(true)}
            onBlur={() => setSearchFocused(false)}
            placeholder="Найти товар по коду или описанию..."
            className="h-12 w-full rounded-[10px] border pl-11 pr-4 text-[15px] text-white outline-none backdrop-blur-md transition-all placeholder:text-white/40"
            style={{
              background: searchFocused ? 'rgba(255,255,255,0.15)' : 'rgba(255,255,255,0.1)',
              borderColor: searchFocused ? 'rgba(74,158,255,0.6)' : 'rgba(255,255,255,0.15)',
              boxShadow: searchFocused ? '0 0 0 3px rgba(74,158,255,0.15)' : 'none',
            }}
          />
        </form>
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        {quickActions.map((action) => (
          <button
            key={action.title}
            type="button"
            onClick={() => navigate(action.href)}
            className="group flex flex-col items-center gap-3 rounded-xl border border-[var(--cargo-border)] bg-white p-6 transition-all duration-200 hover:-translate-y-0.5 hover:border-[var(--cargo-trust)]"
            style={{ boxShadow: 'var(--shadow-card)' }}
            onMouseEnter={(e) => {
              e.currentTarget.style.boxShadow = 'var(--shadow-card-hover)';
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.boxShadow = 'var(--shadow-card)';
            }}
          >
            <div className="flex h-11 w-11 items-center justify-center rounded-[10px] bg-[var(--cargo-trust-light)]">
              <action.icon size={20} className="text-[var(--cargo-trust)]" aria-hidden />
            </div>
            <span className="text-[13px] font-medium text-[var(--cargo-deep)]">{action.title}</span>
          </button>
        ))}
      </div>
    </div>
  );
};
