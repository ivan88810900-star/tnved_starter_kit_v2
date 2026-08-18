import { describe, expect, it } from 'vitest';
import {
  badgeForMeasureType,
  measureTypeLabel,
  type NonTariffMeasureItem,
} from './ProductCardSummary';

function measure(measureType: string): NonTariffMeasureItem {
  return {
    id: 1,
    commodity_code: '8517130000',
    measure_type: measureType,
    description: '',
    document_required: '',
    regulatory_act: '',
  };
}

describe('ProductCardSummary permit labels', () => {
  it('keeps FSB notifications separate from FSTEC export control', () => {
    const fsb = measure('fsb');
    const fstec = measure('fsetc');

    expect(badgeForMeasureType(fsb)).toBe('НФ');
    expect(measureTypeLabel(fsb)).toBe('Нотификация ФСБ');
    expect(badgeForMeasureType(fstec)).toBe('ФСТЭК');
    expect(measureTypeLabel(fstec)).toBe('Требования ФСТЭК в сфере экспортного контроля');
    expect(measureTypeLabel(fstec)).not.toContain('Нотификация');
  });
});
