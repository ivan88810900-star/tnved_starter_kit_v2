import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { ClassifyResults } from './Classifier';

describe('ClassifyResults manual review boundary', () => {
  it('shows the limitation and suppresses recommendation for unconfirmed web data', () => {
    render(
      <ClassifyResults
        result={{
          status: 'MANUAL_REVIEW',
          manual_review_required: true,
          web_search_attempted: true,
          web_search_status: 'unavailable',
          note: 'Поиск технических характеристик не дал подтверждённых данных.',
          results: [
            {
              hs_code: '8501529000',
              name: 'Электродвигатель',
              confidence: 0.9,
              recommended: true,
            },
          ],
        }}
      />,
    );

    expect(screen.getByTestId('classifier-manual-review')).toHaveTextContent('Требуется ручная проверка');
    expect(screen.getByText(/варианты кода предварительные/i)).toBeInTheDocument();
    expect(screen.queryByText('Рекомендуется')).not.toBeInTheDocument();
    expect(screen.getByText('8501529000')).toBeInTheDocument();
  });
});
