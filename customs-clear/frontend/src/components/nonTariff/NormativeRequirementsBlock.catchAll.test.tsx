import React from 'react';
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { NormativeRequirementsBlock } from './NormativeRequirementsBlock';
import type { NormativeRequirementsBlockData } from './normativeBlockHelpers';

function block(status: string, recommendedAction: string): NormativeRequirementsBlockData {
  return {
    status: 'WARNING',
    required_documents: [],
    missing_documents: [],
    advisory_requirements: [],
    official_ntm_catch_all: {
      status,
      reason: 'Выявлены сведения о контролируемом конечном использовании.',
      recommended_action: recommendedAction,
      source_url: 'https://fstec.ru/export-control/example',
      automatic_document_requirement: false,
    },
  };
}

describe('NormativeRequirementsBlock catch-all risk', () => {
  it('renders a stop-and-escalate alert for a prohibited-transaction risk', () => {
    render(
      <NormativeRequirementsBlock
        block={block(
          'prohibited_transaction_risk',
          'stop_transaction_and_escalate_to_export_control_counsel',
        )}
      />,
    );

    expect(screen.getByRole('alert')).toHaveTextContent('Критический риск экспортной сделки');
    expect(screen.getByRole('alert')).toHaveTextContent('Приостановите сделку');
    expect(screen.getByRole('alert')).toHaveTextContent('не добавляется в missing-check');
    expect(screen.queryByText(/не выявлено нормативных требований/)).not.toBeInTheDocument();
  });

  it('renders a distinct identification action for permission review', () => {
    render(
      <NormativeRequirementsBlock
        block={block(
          'permission_review_required',
          'obtain_identification_and_check_commission_permission',
        )}
      />,
    );

    expect(screen.getByRole('alert')).toHaveTextContent('Требуется проверка экспортной сделки');
    expect(screen.getByRole('alert')).toHaveTextContent('Проведите идентификацию товара');
  });

  it('does not present caller-supplied exact family results as verified facts', () => {
    render(
      <NormativeRequirementsBlock
        block={{
          status: 'OK',
          required_documents: [],
          missing_documents: [],
          advisory_requirements: [],
          measure_families: [
            {
              family: 'cryptography',
              label: 'Шифровальные средства',
              status: 'definite',
              requirements_count: 1,
            },
            {
              family: 'phytosanitary_control',
              label: 'Фитосанитарный контроль',
              status: 'excluded',
              requirements_count: 1,
            },
          ],
        }}
      />,
    );

    expect(screen.getByText('совпало по введённым данным')).toBeInTheDocument();
    expect(screen.getByText('возможное исключение по введённым данным')).toBeInTheDocument();
    expect(screen.queryByText('исключение подтверждено')).not.toBeInTheDocument();
  });
});
