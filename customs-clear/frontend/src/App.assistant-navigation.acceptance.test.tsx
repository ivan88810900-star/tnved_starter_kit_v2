import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { AppRoutes } from './App';
import { drainAssistantNavigationJob } from './store/calculatorAssistantBridge';

const productQuestion =
  'Проверьте товар по коду ТН ВЭД 8517130000 (Смартфоны). Объясните платежи, обязательные документы и риски.';

vi.mock('./components/Layout', async () => {
  const { Outlet } = await vi.importActual<typeof import('react-router-dom')>(
    'react-router-dom',
  );
  return { Layout: () => <Outlet /> };
});

vi.mock('./pages/Dictionary', async () => {
  const { requestAssistantWithPrefill } = await vi.importActual<
    typeof import('./store/calculatorAssistantBridge')
  >('./store/calculatorAssistantBridge');
  return {
    Dictionary: () => (
      <button type="button" onClick={() => requestAssistantWithPrefill(productQuestion)}>
        Спросить помощника из карточки
      </button>
    ),
  };
});

vi.mock('./pages/Assistant', async () => {
  const { useLocation } = await vi.importActual<typeof import('react-router-dom')>(
    'react-router-dom',
  );
  return {
    Assistant: ({
      assistantOpenJob,
    }: {
      assistantOpenJob?: { chatPrefillText?: string } | null;
    }) => {
      const location = useLocation();
      return (
        <section>
          <h1>Assistant route</h1>
          <p>{location.pathname}</p>
          <p>{assistantOpenJob?.chatPrefillText}</p>
        </section>
      );
    },
  };
});

describe('application assistant navigation bridge', () => {
  beforeEach(() => {
    while (drainAssistantNavigationJob()) {
      // Empty jobs left by an interrupted test before mounting the route listener.
    }
  });

  it('opens the assistant route with the product-card question intact', async () => {
    const user = userEvent.setup();
    render(
      <MemoryRouter
        initialEntries={['/tnved']}
        future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
      >
        <AppRoutes />
      </MemoryRouter>,
    );

    await user.click(screen.getByRole('button', { name: 'Спросить помощника из карточки' }));

    await screen.findByRole('heading', { name: 'Assistant route' });
    expect(screen.getByText('/assistant')).toBeInTheDocument();
    expect(screen.getByText(productQuestion)).toBeInTheDocument();
  });
});
