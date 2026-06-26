import React from 'react';

export type StatusType = 'success' | 'warning' | 'danger' | 'info' | 'neutral';

const STATUS_STYLES: Record<StatusType, string> = {
  success: 'bg-cargo-clear-light text-cargo-clear',
  warning: 'bg-cargo-warning-light text-cargo-warning',
  danger: 'bg-cargo-alert-light text-cargo-alert',
  info: 'bg-cargo-trust-light text-cargo-trust',
  neutral: 'bg-slate-100 text-slate-600',
};

type Props = {
  type?: StatusType;
  children: React.ReactNode;
  className?: string;
};

export const StatusPill: React.FC<Props> = ({ type = 'neutral', children, className = '' }) => (
  <span
    className={`inline-flex items-center rounded-md px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.06em] ${STATUS_STYLES[type]} ${className}`}
  >
    {children}
  </span>
);

export function confidenceStatus(pct: number): StatusType {
  if (pct >= 85) return 'success';
  if (pct >= 60) return 'warning';
  return 'danger';
}
