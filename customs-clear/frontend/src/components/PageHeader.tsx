import React from 'react';

export type StatCardProps = {
  label: string;
  value: string | number;
};

export const StatCard: React.FC<StatCardProps> = ({ label, value }) => (
  <div className="rounded-lg border border-cargo-border bg-cargo-surface px-4 py-3">
    <p className="text-[11px] font-medium uppercase tracking-[0.06em] text-cargo-light">{label}</p>
    <p className="mt-1 text-xl font-medium tabular-nums text-cargo-deep">{value}</p>
  </div>
);

type PageHeaderProps = {
  title: string;
  subtitle?: string;
  stats?: StatCardProps[];
  children?: React.ReactNode;
};

export const PageHeader: React.FC<PageHeaderProps> = ({ title, subtitle, stats, children }) => (
  <div className="mb-6 flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
    <div className="min-w-0 flex-1">
      <h1 className="text-[22px] font-medium tracking-tight text-cargo-deep">{title}</h1>
      {subtitle ? <p className="mt-1 text-sm text-cargo-mid">{subtitle}</p> : null}
      {children}
    </div>
    {stats && stats.length > 0 ? (
      <div className="grid shrink-0 grid-cols-2 gap-2 sm:grid-cols-3 sm:gap-3">
        {stats.map((s) => (
          <StatCard key={s.label} label={s.label} value={s.value} />
        ))}
      </div>
    ) : null}
  </div>
);
