import React from 'react';

type DutyBadgeInfo = {
  label: string;
  tone: 'zero' | 'percent' | 'specific';
} | null;

function parseDutyBadge(raw?: string): DutyBadgeInfo {
  const t = (raw || '').trim();
  if (!t) return null;
  const low = t.toLowerCase();
  if (low.includes('пошлина:') && !/\d/.test(t)) return null;
  if (/eur|€/i.test(t)) {
    const compact = t.replace(/\s+/g, ' ');
    return { label: compact.toLowerCase().includes('eur') ? 'EUR/кг' : compact, tone: 'specific' };
  }
  const numeric = parseFloat(t.replace('%', '').replace(',', '.').replace(/[^\d.,]/g, ''));
  if (!Number.isFinite(numeric)) return null;
  if (numeric === 0) return { label: '0%', tone: 'zero' };
  return { label: t.includes('%') ? t : `${t}%`, tone: 'percent' };
}

export function RateBadges({ dutyRate, vatRate }: { dutyRate?: string; vatRate?: number | null }) {
  const duty = parseDutyBadge(dutyRate);
  if (!duty && vatRate == null) return null;

  return (
    <span className="inline-flex flex-wrap items-center gap-1.5">
      {duty ? (
        <span
          className={`rounded-full px-2 py-0.5 text-[11px] font-medium ${
            duty.tone === 'zero'
              ? 'bg-cargo-cloud text-cargo-mid'
              : duty.tone === 'specific'
                ? 'bg-cargo-warning-light text-cargo-warning'
                : 'bg-cargo-trust-light text-cargo-trust'
          }`}
        >
          {duty.label}
        </span>
      ) : null}
      {vatRate != null ? (
        <span className="rounded-full bg-cargo-cloud px-2 py-0.5 text-[11px] font-medium text-cargo-mid">
          НДС {Number.isInteger(vatRate) ? vatRate : vatRate.toFixed(1)}%
        </span>
      ) : null}
    </span>
  );
}
