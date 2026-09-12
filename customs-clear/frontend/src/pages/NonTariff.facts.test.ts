import { describe, expect, it } from 'vitest';

import {
  isIsoCountryCode,
  normalizeIsoCountryCode,
  parseFrequencyFacts,
  parsePositiveInteger,
  validateCountryFacts,
} from './NonTariff';

describe('NonTariff structured frequency facts', () => {
  it('keeps explicit ranges distinct from separate point frequencies', () => {
    expect(parseFrequencyFacts('2400–2483,5; 5150–5350')).toEqual([
      { min: 2400, max: 2483.5 },
      { min: 5150, max: 5350 },
    ]);
    expect(parseFrequencyFacts('2400; 5150')).toEqual([2400, 5150]);
  });

  it('drops reversed or malformed ranges instead of guessing', () => {
    expect(parseFrequencyFacts('2483,5-2400; unknown')).toEqual([]);
  });
});

describe('NonTariff country facts', () => {
  it('normalizes arbitrary syntactically valid ISO alpha codes', () => {
    expect(normalizeIsoCountryCode(' de ')).toBe('DE');
    expect(normalizeIsoCountryCode('deu')).toBe('DEU');
    expect(isIsoCountryCode('JP')).toBe(true);
    expect(isIsoCountryCode('JPN')).toBe(true);
    expect(isIsoCountryCode('1P')).toBe(false);
    expect(isIsoCountryCode('TOO-LONG')).toBe(false);
  });

  it('requires a valid destination for export without inventing country defaults', () => {
    expect(validateCountryFacts('import', '', '')).toBeNull();
    expect(validateCountryFacts('export', '', '')).toMatch(/обязательно укажите страну назначения/);
    expect(validateCountryFacts('export', 'ru', 'de')).toBeNull();
    expect(validateCountryFacts('export', 'RU', 'D1')).toMatch(/Страна назначения/);
  });
});

describe('NonTariff exact test-SIM quantity', () => {
  it('accepts only positive safe integers', () => {
    expect(parsePositiveInteger('1')).toBe(1);
    expect(parsePositiveInteger('0001')).toBe(1);
    expect(parsePositiveInteger('20')).toBe(20);
    expect(parsePositiveInteger('0')).toBeNull();
    expect(parsePositiveInteger('-1')).toBeNull();
    expect(parsePositiveInteger('0.5')).toBeNull();
    expect(parsePositiveInteger('1e2')).toBeNull();
  });
});
