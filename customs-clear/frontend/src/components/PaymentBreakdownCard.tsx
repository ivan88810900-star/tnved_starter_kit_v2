import React from 'react';
import { AnimatedNumber } from './AnimatedNumber';

type Row = {
  label: string;
  amount: number;
  meta?: string;
  tone?: 'default' | 'trust' | 'total';
};

type Props = {
  rows: Row[];
  totalLabel?: string;
  totalAmount: number;
};

export const PaymentBreakdownCard: React.FC<Props> = ({
  rows,
  totalLabel = 'Итого к уплате',
  totalAmount,
}) => (
  <div className="overflow-hidden rounded-xl" style={{ boxShadow: 'var(--shadow-card)' }}>
    <div className="rounded-t-xl border border-b-0 border-[var(--cargo-border)] bg-white">
      {rows.map((row, idx) => (
        <div
          key={`${row.label}-${idx}`}
          className="flex items-center justify-between border-b border-[var(--cargo-border)] px-6 py-3.5 last:border-0"
        >
          <span className="text-[11px] font-semibold uppercase tracking-wider text-[var(--cargo-light)]">
            {row.label}
          </span>
          <div className="text-right">
            <span
              className={`text-base font-semibold tabular-nums ${
                row.tone === 'trust' ? 'text-[var(--cargo-trust)]' : 'text-[var(--cargo-deep)]'
              }`}
            >
              {row.amount.toLocaleString('ru-RU')} ₽
            </span>
            {row.meta ? (
              <span className="ml-1.5 text-xs text-[var(--cargo-light)]">{row.meta}</span>
            ) : null}
          </div>
        </div>
      ))}
    </div>
    <div
      className="flex items-center justify-between rounded-b-xl px-6 py-5"
      style={{ background: 'var(--hero-from)' }}
    >
      <span className="text-[11px] font-bold uppercase tracking-widest text-white/50">{totalLabel}</span>
      <span className="text-[32px] font-light tabular-nums tracking-tight text-white">
        <AnimatedNumber value={totalAmount} format="currency" />
      </span>
    </div>
  </div>
);
