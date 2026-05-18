/**
 * Приводит наименования позиций ТН ВЭД к единому виду: типичный ВЕРХНИЙ РЕГИСТР
 * из официальных выгрузок → читаемый регистр; смешанный текст не трогаем.
 */
export function formatTnvedCommodityName(raw: string): string {
  const text = raw.trim().replace(/\s+/g, ' ');
  if (!text) return text;

  const letters = [...text].filter((ch) => /[A-Za-zА-Яа-яЁё]/.test(ch));
  if (letters.length === 0) return text;

  const upperCount = letters.filter((ch) => ch === ch.toUpperCase() && ch !== ch.toLowerCase()).length;
  if (upperCount / letters.length < 0.65) return text;

  const conj = new Set([
    'и',
    'или',
    'либо',
    'в',
    'во',
    'к',
    'ко',
    'на',
    'по',
    'из',
    'для',
    'без',
    'до',
    'от',
    'за',
    'при',
    'под',
    'над',
    'об',
    'о',
    'с',
    'со',
    'у',
    'а',
    'но',
    'как',
    'же',
    'ли',
    'бы',
    'то',
  ]);

  const parts = text
    .toLowerCase()
    .split(/(\s+|[–—-])/)
    .filter((p) => p.length > 0);

  let wordIndex = 0;
  return parts
    .map((part) => {
      if (/^\s+$/.test(part)) return part;
      if (/^[–—-]$/.test(part)) return part;

      const isFirst = wordIndex === 0;
      wordIndex += 1;
      if (!isFirst && conj.has(part)) return part;

      if (part.includes('-')) {
        return part
          .split('-')
          .map((seg, i) => {
            if (!seg) return seg;
            if (i > 0 && conj.has(seg)) return seg;
            return seg.charAt(0).toLocaleUpperCase('ru-RU') + seg.slice(1);
          })
          .join('-');
      }

      return part.charAt(0).toLocaleUpperCase('ru-RU') + part.slice(1);
    })
    .join('');
}

/** Единая гарнитура и межбуквенное расстояние для наименований в справочнике. */
export const TNVED_COMMODITY_NAME_CLASS = 'font-sans font-normal leading-snug tracking-normal antialiased';
