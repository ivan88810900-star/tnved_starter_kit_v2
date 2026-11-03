import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { api } from '../api/client';
import { TnvedBook } from './TnvedBook';

vi.mock('../api/client', () => ({
  api: { get: vi.fn() },
}));

const mockedGet = vi.mocked(api.get);

describe('TnvedBook semantic search candidate boundary', () => {
  beforeEach(() => {
    mockedGet.mockReset();
  });

  it('labels vector matches as candidates requiring manual classification verification', async () => {
    mockedGet.mockResolvedValueOnce({
      data: {
        results: [
          {
            score: 0.812345,
            hs_code: '8516797000',
            title: 'Приборы электронагревательные прочие',
            embedding_model: 'model-a',
          },
        ],
      },
    });

    render(<TnvedBook />);

    fireEvent.change(screen.getByPlaceholderText('например: электрический чайник пластик'), {
      target: { value: 'электрический чайник' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Семантика' }));

    const warning = await screen.findByTestId('semantic-search-candidate-warning');
    expect(warning).toHaveTextContent('только кандидаты семантического поиска по векторному сходству');
    expect(warning).toHaveTextContent('не подтверждённая классификация ТН ВЭД');
    expect(warning).toHaveTextContent('вручную сверить с описанием, примечаниями и классификационными решениями');
    expect(screen.getByText('Векторное сходство: 0.812345')).toBeInTheDocument();
    expect(screen.queryByText(/score/i)).not.toBeInTheDocument();
  });
});
