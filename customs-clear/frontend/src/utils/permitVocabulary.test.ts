import { describe, expect, it } from 'vitest';
import { describePermit, isKnownPermit } from './permitVocabulary';

describe('permitVocabulary advisory permit types', () => {
  it.each([
    [
      'РЭВЧУ',
      'Разрешительный документ на ввоз РЭС и ВЧУ',
      'Роскомнадзор / Минпромторг России',
    ],
    ['НФ/ЛЗ', 'Нотификация ФСБ или лицензия на ввоз', 'ЦЛСЗ ФСБ России / Минпромторг России'],
    ['ВЕТКОНТРОЛЬ', 'Ветеринарный контроль (вид документа уточняется)', 'Россельхознадзор'],
    [
      'ФИТОКОНТРОЛЬ (без ФСС)',
      'Фитосанитарный контроль без фитосанитарного сертификата',
      'Россельхознадзор',
    ],
    [
      'ЛЗ/разрешение ФСТЭК',
      'Лицензия или разрешение в сфере экспортного контроля',
      'ФСТЭК России',
    ],
    ['ДС/СС', 'Форма оценки соответствия уточняется', 'Росаккредитация'],
    ['CITES', 'Разрешение или сертификат CITES', 'Административный орган CITES'],
  ])('describes %s without falling back to the raw code', (code, label, organ) => {
    const descriptor = describePermit(code);

    expect(isKnownPermit(code)).toBe(true);
    expect(descriptor.label).toBe(label);
    expect(descriptor.organ).toBe(organ);
    expect(descriptor.severity).toBe('conditional');
  });

  it.each([
    ['ДС/СС/СГР', 'Форма подтверждения или регистрации уточняется'],
    ['ЗАПРЕТ', 'Запрет или ограничение перемещения (применимость уточняется)'],
  ])('describes %s even when no single issuing authority applies', (code, label) => {
    const descriptor = describePermit(code);

    expect(isKnownPermit(code)).toBe(true);
    expect(descriptor.label).toBe(label);
    expect(descriptor.severity).toBe('conditional');
  });

  it('attributes a cryptography notification to the FSB, not FSTEC', () => {
    const descriptor = describePermit('НФ');

    expect(descriptor.label).toBe('Нотификация ФСБ');
    expect(descriptor.organ).toBe('ЦЛСЗ ФСБ России');
    expect(descriptor.label).not.toContain('ФСТЭК');
  });
});
