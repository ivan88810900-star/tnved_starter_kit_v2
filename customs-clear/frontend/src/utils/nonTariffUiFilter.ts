/** Служебные/шумовые фрагменты в текстах мер (fallback-парсер и т.п.) */
export const NT_FALLBACK_NOISE_SUBSTRING = 'Извлечено в fallback-режиме без LLM';

export function isNonTariffUiNoise(text: string | null | undefined): boolean {
  const t = (text ?? '').trim();
  if (!t) return true;
  if (t.includes(NT_FALLBACK_NOISE_SUBSTRING)) return true;
  if (/^\d+$/.test(t)) return true;
  return false;
}

/** Убирает служебный хвост fallback; если после очистки строка — только шум, возвращает пусто. */
export function sanitizeNonTariffLine(line: string | null | undefined): string {
  const raw = (line ?? '').trim();
  if (!raw) return '';
  const escaped = NT_FALLBACK_NOISE_SUBSTRING.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  let t = raw.replace(new RegExp(escaped, 'gi'), '').replace(/\s+/g, ' ').trim();
  t = t.replace(/^[.,;\s]+|[.,;\s]+$/g, '').trim();
  if (isNonTariffUiNoise(t)) return '';
  return t;
}

export type NonTariffMeasureLike = {
  document_required?: string;
  regulatory_act?: string;
  description?: string;
};

/** Поля для отображения карточки; пустые строки = скрыть строку. */
export function pickNonTariffVisibleFields(m: NonTariffMeasureLike): {
  document_required: string;
  regulatory_act: string;
  description: string;
} {
  const doc = (m.document_required ?? '').trim();
  const act = (m.regulatory_act ?? '').trim();
  const desc = (m.description ?? '').trim();
  return {
    document_required: isNonTariffUiNoise(doc) ? '' : doc,
    regulatory_act: isNonTariffUiNoise(act) ? '' : act,
    description: isNonTariffUiNoise(desc) ? '' : desc,
  };
}

export function hasVisibleNonTariffContent(m: NonTariffMeasureLike): boolean {
  const v = pickNonTariffVisibleFields(m);
  return Boolean(v.document_required || v.regulatory_act || v.description);
}
