import React from 'react';
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { NormativeRequirementsBlock } from './NormativeRequirementsBlock';
import {
  normativeBlockFromNonTariff,
  type NormativeRequirementsBlockData,
} from './normativeBlockHelpers';

function block(dataFreshness?: NormativeRequirementsBlockData['data_freshness']): NormativeRequirementsBlockData {
  return {
    status: 'ERROR',
    required_documents: [{ permit_type: 'ДС', used_for_missing_check: true }],
    missing_documents: [{ permit_type: 'ДС', used_for_missing_check: true }],
    advisory_requirements: [],
    data_freshness: dataFreshness,
  };
}

describe('NormativeRequirementsBlock data freshness visibility', () => {
  it.each([
    ['missing', undefined],
    ['unreadable', 'unreadable'],
    ['explicit unknown', { is_stale: null, source_code: 'UNKNOWN' }],
    ['incomplete false', { is_stale: false, source_code: 'EEC_ETT' }],
  ])('renders missing or unreadable %s status as amber unknown', (_label, dataFreshness) => {
    const normalized = normativeBlockFromNonTariff({
      status: 'ERROR',
      required_permit_types: ['ДС'],
      missing_permit_types: ['ДС'],
      data_freshness: dataFreshness,
    });

    render(<NormativeRequirementsBlock block={normalized} />);

    const signal = screen.getByTestId('normative-data-freshness');
    expect(signal).toHaveAttribute('data-state', 'unknown');
    expect(signal).toHaveTextContent('Свежесть данных источника не подтверждена');
    expect(signal).toHaveClass('border-amber-200');
    expect(screen.getByText('Отсутствующие документы')).toBeInTheDocument();
  });

  it('renders stale status in amber without changing document groups', () => {
    render(
      <NormativeRequirementsBlock
        block={block({
          state: 'stale',
          tone: 'amber',
          source_name: 'Локальная база правил',
          source_code: 'LOCAL',
          synced_at: null,
          revision: 'seed',
          is_stale: true,
          scope: 'technical_source_status_only',
          affects_applicability: false,
          affects_required_documents: false,
          affects_missing_documents: false,
          ntm_coverage_verified: false,
        })}
      />,
    );

    const signal = screen.getByTestId('normative-data-freshness');
    expect(signal).toHaveAttribute('data-state', 'stale');
    expect(signal).toHaveTextContent('Данные источника устарели или требуют обновления');
    expect(signal).toHaveTextContent('Локальная база правил');
    expect(screen.getByText('Обязательные документы')).toBeInTheDocument();
    expect(screen.getByText('Отсутствующие документы')).toBeInTheDocument();
  });

  it('renders complete fresh EEC_ETT status neutrally with an explicit NTM coverage boundary', () => {
    render(
      <NormativeRequirementsBlock
        block={block({
          state: 'fresh',
          tone: 'neutral',
          source_name: 'Единый таможенный тариф ЕАЭС',
          source_code: 'EEC_ETT',
          synced_at: '2026-09-16T09:00:00+00:00',
          revision: 'ett:2026-09-16',
          is_stale: false,
          scope: 'technical_source_status_only',
          affects_applicability: false,
          affects_required_documents: false,
          affects_missing_documents: false,
          ntm_coverage_verified: false,
        })}
      />,
    );

    const signal = screen.getByTestId('normative-data-freshness');
    expect(signal).toHaveAttribute('data-state', 'fresh');
    expect(signal).toHaveClass('border-slate-200');
    expect(signal).toHaveTextContent('Источник данных отмечен как свежий');
    expect(signal).toHaveTextContent(
      'Свежий ЕТТ не подтверждает полноту или актуальность покрытия нетарифных мер',
    );
    expect(screen.getByText('Обязательные документы')).toBeInTheDocument();
    expect(screen.getByText('Отсутствующие документы')).toBeInTheDocument();
  });
});
