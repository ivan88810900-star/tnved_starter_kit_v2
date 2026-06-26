/** Нормализация ставки пошлины из API/БД (без дублирования «Пошлина:»). */
export function normalizeDutyRate(raw?: string | null): string {
  let t = (raw ?? '').trim();
  if (!t) return '';

  const low = t.toLowerCase();
  if (low.includes('пошлина:') && low.includes('ндс:')) {
    if (!/\d/.test(t)) return '';
    t = t.split('|')[0]?.replace(/^.*?пошлина:\s*/i, '').trim() ?? '';
  } else if (/^пошлина:\s*/i.test(t)) {
    t = t.replace(/^пошлина:\s*/i, '').split('|')[0].trim();
  }

  if (!t || !/\d/.test(t)) {
    if (/^пошлина/i.test(low) || /^ндс/i.test(low)) return '';
    return t;
  }
  return t.replace(/\s+/g, ' ').replace(' %', '%');
}

export type DutyBadgeInfo = {
  label: string;
  tone: 'zero' | 'percent' | 'specific';
} | null;

export function parseDutyBadge(raw?: string | null): DutyBadgeInfo {
  const t = normalizeDutyRate(raw);
  if (!t) return null;

  if (/eur|€/i.test(t)) {
    return { label: t.toLowerCase().includes('eur') ? 'EUR/кг' : t, tone: 'specific' };
  }

  const numeric = parseFloat(t.replace('%', '').replace(',', '.').replace(/[^\d.,]/g, ''));
  if (!Number.isFinite(numeric)) return null;
  if (numeric === 0) return { label: '0%', tone: 'zero' };
  return { label: t.includes('%') ? t : `${t}%`, tone: 'percent' };
}

/** Человекочитаемая ставка для карточки товара. */
export function formatDutyDisplay(raw?: string | null): string {
  const badge = parseDutyBadge(raw);
  return badge?.label ?? '—';
}

export function formatPercentRate(value?: number | null): string {
  if (value == null || !Number.isFinite(value)) return '—';
  return `${Number.isInteger(value) ? value : parseFloat(value.toFixed(1))}%`;
}
