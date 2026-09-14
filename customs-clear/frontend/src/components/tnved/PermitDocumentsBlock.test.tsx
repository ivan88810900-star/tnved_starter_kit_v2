import { render, screen } from '@testing-library/react';
import React from 'react';
import { describe, expect, it } from 'vitest';

import type { NormativeRequirementsBlockData } from '../../types/api.types';
import { PermitDocumentsBlock } from './PermitDocumentsBlock';

function block(overrides: Partial<NormativeRequirementsBlockData> = {}): NormativeRequirementsBlockData {
  return {
    status: 'OK',
    required_documents: [],
    missing_documents: [],
    advisory_requirements: [],
    ...overrides,
  };
}

describe('PermitDocumentsBlock normative summary', () => {
  it('does not claim that no permits were identified when advisory NTM needs clarification', () => {
    render(
      <PermitDocumentsBlock
        hsCode="8517620009"
        normativeBlock={block({
          advisory_requirements: [{
            permit_type: 'НФ/ЛЗ',
            applicability: 'needs_clarification',
            source: 'official_ntm_exact_devices_shadow',
            used_for_missing_check: false,
            requires_manual_review: true,
            reason: 'Нужно уточнить криптографические характеристики товара.',
          }],
        })}
      />,
    );

    expect(screen.getByText(/Обязательных документов СС\/ДС\/СГР в брокерском списке нет/)).toBeInTheDocument();
    expect(screen.getByText(/выявлены нетарифные сигналы/)).toBeInTheDocument();
    expect(screen.queryByText(/Специальных разрешительных документов.*не выявлено/)).not.toBeInTheDocument();
  });

  it('uses the same clarification summary for a family-level signal', () => {
    render(
      <PermitDocumentsBlock
        hsCode="9403609009"
        normativeBlock={block({
          measure_families: [{
            family: 'technical_regulations',
            label: 'Техническое регулирование',
            status: 'legacy_signal',
            requirements_count: 0,
            signals_count: 1,
          }],
        })}
      />,
    );

    expect(screen.getByText(/выявлены нетарифные сигналы/)).toBeInTheDocument();
    expect(screen.queryByText(/Специальных разрешительных документов.*не выявлено/)).not.toBeInTheDocument();
  });

  it('keeps the confirmed empty-state wording when there are no NTM signals', () => {
    render(<PermitDocumentsBlock hsCode="0101210000" normativeBlock={block()} />);

    expect(screen.getByText(/Специальных разрешительных документов.*не выявлено/)).toBeInTheDocument();
    expect(screen.queryByText(/выявлены нетарифные сигналы/)).not.toBeInTheDocument();
  });

  it('keeps rendering a mandatory permit instead of a clarification summary', () => {
    render(
      <PermitDocumentsBlock
        hsCode="2201900000"
        normativeBlock={block({
          required_documents: [{
            permit_type: 'СГР',
            tr_ts: '299',
            note: 'Проверьте назначение продукции.',
          }],
          advisory_requirements: [{
            permit_type: 'СГР',
            applicability: 'needs_clarification',
            source: 'official_sgr_registry',
            used_for_missing_check: false,
            requires_manual_review: true,
            reason: 'Есть дополнительный advisory-сигнал.',
          }],
        })}
      />,
    );

    expect(screen.getByText(/Требуется: Свидетельство о государственной регистрации/)).toBeInTheDocument();
    expect(screen.queryByText(/Обязательных документов СС\/ДС\/СГР в брокерском списке нет/)).not.toBeInTheDocument();
  });
});
