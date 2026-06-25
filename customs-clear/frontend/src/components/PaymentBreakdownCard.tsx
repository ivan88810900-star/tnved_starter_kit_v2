import React from 'react';

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
  totalLabel = 'ИТОГО К УПЛАТЕ',
  totalAmount,
}) => (
  <div className="overflow-hidden rounded-lg border border-cargo-border bg-cargo-surface">
    {rows.map((row, idx) => (
      <div
        key={`${row.label}-${idx}`}
        className={`flex items-start justify-between gap-3 border-b border-cargo-border px-4 py-3 ${
          row.tone === 'trust' ? 'text-cargo-trust' : 'text-cargo-mid'
        }`}
      >
        <div className="min-w-0">
          <p className="text-[11px] font-medium uppercase tracking-[0.06em] text-cargo-light">{row.label}</p>
          <p className={`mt-1 text-lg font-medium tabular-nums ${row.tone === 'trust' ? 'text-cargo-trust' : 'text-cargo-deep'}`}>
            {row.amount.toLocaleString('ru-RU')} ₽
          </p>
        </div>
        {row.meta ? <span className="shrink-0 pt-5 text-xs text-cargo-light">{row.meta}</span> : null}
      </div>
    ))}
    <div className="flex items-center justify-between bg-cargo-deep px-4 py-4 text-white">
      <p className="text-[11px] font-medium uppercase tracking-[0.06em] text-white/70">{totalLabel}</p>
      <p className="text-xl font-medium tabular-nums">{totalAmount.toLocaleString('ru-RU')} ₽</p>
    </div>
  </div>
);
