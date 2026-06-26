import React from 'react';
import { parseDutyBadge } from '../../utils/dutyRate';

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
