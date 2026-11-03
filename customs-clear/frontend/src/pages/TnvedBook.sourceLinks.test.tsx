import React from 'react';
import { fireEvent, render, screen, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { api } from '../api/client';
import { TnvedBook } from './TnvedBook';

vi.mock('../api/client', () => ({
  api: { get: vi.fn() },
}));

const mockedGet = vi.mocked(api.get);

describe('TnvedBook source-link admission', () => {
  beforeEach(() => {
    mockedGet.mockReset();
  });

  it('keeps unsafe imported URLs visible but non-clickable and preserves valid HTTPS links', async () => {
    mockedGet.mockImplementation(async (url: string) => {
      if (url.startsWith('/tnved/search?')) {
        return {
          data: {
            results: [{ hs_code: '8509400000', title: 'Измельчители пищевых продуктов', level: 10, chapter: '85' }],
          },
        };
      }
      if (url.startsWith('/tnved/lookup/')) {
        return {
          data: {
            hs_code: '8509400000',
            title: 'Измельчители пищевых продуктов',
            description: '',
            breadcrumb: [],
            official_ett_url: 'https://./source',
            notes: [
              {
                id: 1,
                category: 'legal',
                title: 'Безопасный источник',
                body: 'Опубликованная запись.',
                source_url: 'https://eec.eaeunion.org/documents/source?id=1',
              },
              {
                id: 2,
                category: 'legal',
                title: 'Небезопасный источник',
                body: 'Импортированное значение должно остаться видимым.',
                source_url: 'data:text/html,<img src=x onerror=alert(1)>',
              },
            ],
          },
        };
      }
      throw new Error(`unexpected URL: ${url}`);
    });

    render(<TnvedBook />);

    fireEvent.change(screen.getByPlaceholderText('8509400000 или чайник'), {
      target: { value: '8509400000' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Поиск' }));
    fireEvent.click(await screen.findByRole('button', { name: /8509400000/ }));

    const safeNote = (await screen.findByText('Безопасный источник')).closest('li');
    const unsafeNote = screen.getByText('Небезопасный источник').closest('li');
    expect(safeNote).not.toBeNull();
    expect(unsafeNote).not.toBeNull();

    const safeLink = within(safeNote as HTMLElement).getByRole('link', { name: 'Источник' });
    expect(safeLink).toHaveAttribute('href', 'https://eec.eaeunion.org/documents/source?id=1');

    expect(within(unsafeNote as HTMLElement).queryByRole('link', { name: /Источник/ })).not.toBeInTheDocument();
    const unsafeEvidence = within(unsafeNote as HTMLElement).getByTestId('unsafe-source-url-evidence');
    expect(unsafeEvidence).toHaveTextContent('Источник (ссылка недоступна):');
    expect(unsafeEvidence).toHaveTextContent('data:text/html,<img src=x onerror=alert(1)>');
    expect(within(unsafeNote as HTMLElement).queryByRole('img')).not.toBeInTheDocument();

    const officialLabel = screen.getByTestId('unsafe-official-ett-url-evidence');
    expect(officialLabel).toHaveTextContent('ТН ВЭД и ЕТТ на сайте ЕЭК (ссылка недоступна):');
    expect(officialLabel).toHaveTextContent('https://./source');
    expect(officialLabel.closest('a')).toBeNull();
  });
});
