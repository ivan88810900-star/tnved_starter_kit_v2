import React from 'react';
import { render, screen, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { api } from '../../api/client';
import { ClassificationRulingsBlock, type ClassificationRulingItem } from './ClassificationRulingsBlock';

vi.mock('../../api/client', () => ({
  api: { get: vi.fn() },
}));

const mockedGet = vi.mocked(api.get);

const ruling = (overrides: Partial<ClassificationRulingItem>): ClassificationRulingItem => ({
  ruling_number: 'TEST-1',
  ruling_date: '2026-01-01',
  agency: 'ФТС',
  goods_description: 'Тестовый товар',
  assigned_hs_code: '8509400000',
  rationale: 'Тестовое обоснование',
  source_url: '',
  is_official: true,
  ...overrides,
});

describe('ClassificationRulingsBlock source-link admission', () => {
  beforeEach(() => {
    mockedGet.mockReset();
  });

  it('renders only strict HTTP(S) ruling URLs as external links', async () => {
    mockedGet.mockResolvedValueOnce({
      data: {
        status: 'OK',
        hs_code: '8509400000',
        official_rulings: [
          ruling({
            ruling_number: 'SAFE-1',
            goods_description: 'Решение с подтверждаемой ссылкой',
            source_url: 'https://customs.gov.example/rulings/SAFE-1',
          }),
          ruling({
            ruling_number: 'UNSAFE-CREDENTIAL',
            goods_description: 'Решение со ссылкой с credentials',
            source_url: 'https://trusted.example@evil.example/source',
          }),
          ruling({
            ruling_number: 'UNSAFE-CONTROL',
            goods_description: 'Решение со ссылкой с кодированным control',
            source_url: 'https://example.test/source%0D%0ainjected',
          }),
          ruling({
            ruling_number: 'UNSAFE-BIDI',
            goods_description: 'Решение со ссылкой с bidi-control',
            source_url: `https://example.test/${String.fromCharCode(0x202e)}evil`,
          }),
          ruling({
            ruling_number: 'UNSAFE-ENCODED-C1',
            goods_description: 'Решение со ссылкой с encoded C1',
            source_url: 'https://example.test/%C2%85',
          }),
          ruling({
            ruling_number: 'UNSAFE-ENCODED-BIDI',
            goods_description: 'Решение со ссылкой с encoded bidi',
            source_url: 'https://example.test/%E2%80%AEevil',
          }),
        ],
        reference_rulings: [],
        official_count: 6,
        reference_count: 0,
        total: 6,
      },
    });

    render(<ClassificationRulingsBlock hsCode="8509400000" />);

    const safeCard = (await screen.findByText('Решение с подтверждаемой ссылкой')).closest('article');
    const credentialCard = screen.getByText('Решение со ссылкой с credentials').closest('article');
    const encodedControlCard = screen.getByText('Решение со ссылкой с кодированным control').closest('article');
    const bidiCard = screen.getByText('Решение со ссылкой с bidi-control').closest('article');
    const encodedC1Card = screen.getByText('Решение со ссылкой с encoded C1').closest('article');
    const encodedBidiCard = screen.getByText('Решение со ссылкой с encoded bidi').closest('article');
    expect(safeCard).not.toBeNull();
    expect(credentialCard).not.toBeNull();
    expect(encodedControlCard).not.toBeNull();
    expect(bidiCard).not.toBeNull();
    expect(encodedC1Card).not.toBeNull();
    expect(encodedBidiCard).not.toBeNull();

    const safeLink = within(safeCard as HTMLElement).getByRole('link', { name: /Источник/ });
    expect(safeLink).toHaveAttribute('href', 'https://customs.gov.example/rulings/SAFE-1');
    expect(safeLink).toHaveAttribute('rel', 'noopener noreferrer');

    for (const card of [credentialCard, encodedControlCard, bidiCard, encodedC1Card, encodedBidiCard]) {
      expect(within(card as HTMLElement).queryByRole('link', { name: /Источник/ })).not.toBeInTheDocument();
      expect(within(card as HTMLElement).getByTestId('unsafe-ruling-source-url-evidence')).toHaveTextContent(
        'Источник (ссылка недоступна):',
      );
    }
    expect(within(credentialCard as HTMLElement).getByTestId('unsafe-ruling-source-url-evidence')).toHaveTextContent(
      'https://trusted.example@evil.example/source',
    );
    expect(within(encodedControlCard as HTMLElement).getByTestId('unsafe-ruling-source-url-evidence')).toHaveTextContent(
      'https://example.test/source%0D%0ainjected',
    );
    expect(within(bidiCard as HTMLElement).getByTestId('unsafe-ruling-source-url-evidence')).toHaveTextContent(
      'https://example.test/\\u202Eevil',
    );
    expect(within(encodedC1Card as HTMLElement).getByTestId('unsafe-ruling-source-url-evidence')).toHaveTextContent(
      'https://example.test/%C2%85',
    );
    expect(within(encodedBidiCard as HTMLElement).getByTestId('unsafe-ruling-source-url-evidence')).toHaveTextContent(
      'https://example.test/%E2%80%AEevil',
    );
  });
});
