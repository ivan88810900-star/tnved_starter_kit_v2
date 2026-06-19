/**
 * Централизованный словарь типов разрешительных документов (permit_type) для ВЭД.
 *
 * Единый источник человекочитаемых названий и цветового кодирования для всех
 * экранов нетарифного регулирования. Работает для ЛЮБОГО кода ТН ВЭД — частные
 * правила по главам не требуются.
 */

export type PermitSeverity = 'mandatory' | 'conditional' | 'info';

export interface PermitDescriptor {
  /** Исходный код (ДС, СС, ВС, …). */
  code: string;
  /** Человекочитаемое название документа. */
  label: string;
  /** Орган/ведомство, выдающий документ (если известно). */
  organ?: string;
  /** Степень обязательности для цветового кодирования. */
  severity: PermitSeverity;
}

const VOCABULARY: Record<string, Omit<PermitDescriptor, 'code'>> = {
  ДС: { label: 'Декларация о соответствии', organ: 'Росаккредитация', severity: 'mandatory' },
  СС: { label: 'Сертификат соответствия', organ: 'Росаккредитация', severity: 'mandatory' },
  ВС: { label: 'Ветеринарный сертификат', organ: 'Россельхознадзор', severity: 'mandatory' },
  ФСС: { label: 'Фитосанитарный сертификат', organ: 'Россельхознадзор', severity: 'mandatory' },
  РУ: { label: 'Регистрационное удостоверение', organ: 'Росздравнадзор', severity: 'mandatory' },
  ЛЗ: { label: 'Лицензия на импорт', organ: 'Минпромторг России', severity: 'mandatory' },
  НФ: { label: 'Нотификация ФСБ', organ: 'ЦЛСЗ ФСБ России', severity: 'mandatory' },
  СГР: { label: 'Свидетельство о государственной регистрации', organ: 'Роспотребнадзор', severity: 'mandatory' },
  КВ: { label: 'Квота на импорт', organ: 'Минпромторг России', severity: 'conditional' },
};

/** Нормализация кода: верхний регистр, удаление пробелов, латиница-двойники → кириллица. */
function normalizeCode(raw: string | null | undefined): string {
  let c = (raw ?? '').trim().toUpperCase();
  // Частые латинские двойники кириллических букв в кодах из разных источников.
  const map: Record<string, string> = {
    C: 'С', // лат. C → кир. С
    P: 'Р', // лат. P → кир. Р
    H: 'Н', // лат. H → кир. Н
    B: 'В', // лат. B → кир. В
    K: 'К', // лат. K → кир. К
  };
  c = c.replace(/[CPHBK]/g, (ch) => map[ch] ?? ch);
  return c;
}

/** Возвращает дескриптор разрешительного документа по коду (с безопасным fallback). */
export function describePermit(
  code: string | null | undefined,
  severityOverride?: PermitSeverity,
): PermitDescriptor {
  const norm = normalizeCode(code);
  const entry = VOCABULARY[norm];
  if (entry) {
    return { code: norm, ...entry, severity: severityOverride ?? entry.severity };
  }
  return {
    code: norm || (code ?? '').trim(),
    label: norm || 'Разрешительный документ',
    severity: severityOverride ?? 'info',
  };
}

/** Цветовые классы Tailwind для бейджа кода по степени обязательности. */
export function permitBadgeClasses(severity: PermitSeverity): string {
  switch (severity) {
    case 'mandatory':
      return 'border-orange-300 bg-orange-100 text-orange-900';
    case 'conditional':
      return 'border-amber-300 bg-amber-100 text-amber-900';
    default:
      return 'border-slate-200 bg-slate-100 text-slate-600';
  }
}

/** Известен ли код в словаре. */
export function isKnownPermit(code: string | null | undefined): boolean {
  return normalizeCode(code) in VOCABULARY;
}
