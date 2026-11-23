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
  return t;
}

export type DutyBadgeInfo = {
  label: string;
  tone: 'zero' | 'percent' | 'specific';
} | null;

export function parseDutyBadge(raw?: string | null): DutyBadgeInfo {
  const t = normalizeDutyRate(raw);
  if (!t) return null;

  const percent = /^(\d+(?:[.,]\d+)?)\s*%?$/.exec(t);
  if (percent) {
    const value = percent[1];
    return { label: value + ' %', tone: Number(value.replace(',', '.')) === 0 ? 'zero' : 'percent' };
  }

  // A bare first operand in a combined ETT rate has the percentage column's unit.
  const combined = /^(\d+(?:[.,]\d+)?)(,?\s+(?:плюс|но не менее)\s+\d.*)$/u.exec(t);
  return { label: combined ? combined[1] + ' %' + combined[2] : t, tone: 'specific' };
}

/** Человекочитаемая ставка для карточки товара. */
export function formatDutyDisplay(raw?: string | null): string {
  const badge = parseDutyBadge(raw);
  return badge?.label ?? '—';
}

export function formatPercentRate(value?: number | null): string {
  if (value == null || !Number.isFinite(value)) return '—';
  return String(value).replace('.', ',') + ' %';
}

export function parseManualDutyPercent(input: string): number | undefined {
  const value = input.trim();
  if (!value) return undefined;
  const percent = Number(value.replace(',', '.'));
  if (!/^\+?(?:\d+(?:[.,]\d*)?|[.,]\d+)(?:[eE][+-]?\d+)?$/.test(value) || !Number.isFinite(percent)) {
    throw new Error('Введите неотрицательную ставку пошлины в процентах, например 7,5.');
  }
  return percent;
}
