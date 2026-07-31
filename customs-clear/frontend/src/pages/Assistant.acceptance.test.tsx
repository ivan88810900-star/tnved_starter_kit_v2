import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { setAssistantCalculationContext } from '../store/calculatorAssistantBridge';
import { Assistant } from './Assistant';

const apiMocks = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
}));

const capabilityMocks = vi.hoisted(() => ({
  assistantLlmConfigured: false,
}));

vi.mock('../api/client', () => ({
  api: apiMocks,
}));

vi.mock('../context/ClientCapabilitiesContext', () => ({
  useClientCapabilities: () => ({
    health: 'ok',
    assistantLlmConfigured: capabilityMocks.assistantLlmConfigured,
    refetchHealth: vi.fn(),
  }),
}));

const productQuestion =
  'Проверьте товар по коду ТН ВЭД 8517130000 (Смартфоны). Объясните платежи, обязательные документы и риски.';

const deterministicAnswer = {
  status: 'OK',
  answer:
    '### Проверка товара\nДля кода **8517130000** собраны платежи, документы и риск-сигналы из серверных модулей.',
  grounding: {
    mode: 'deterministic',
    coverage: 'grounded',
    llm_configured: false,
    generated_from_server_facts: true,
    resolved_hs_code: '8517130000',
    hs_source: 'message',
    facts_used: ['tnved', 'payments', 'requirements', 'risk'],
    citations: [
      {
        id: 'S1',
        source_id: 'canonical_tnved',
        title: 'Canonical ТН ВЭД',
        kind: 'canonical',
        status: 'verified',
        excerpt: 'Код и наименование получены из текущего Canonical snapshot.',
      },
    ],
    limitations: ['Проверьте характеристики конкретной модели перед подачей декларации.'],
  },
  suggestions: ['Покажите обязательные документы'],
};

describe('Assistant grounded product consultation', () => {
  beforeEach(() => {
    sessionStorage.clear();
    localStorage.clear();
    setAssistantCalculationContext(null);
    capabilityMocks.assistantLlmConfigured = false;
    Object.defineProperty(Element.prototype, 'scrollIntoView', {
      configurable: true,
      value: vi.fn(),
    });
    apiMocks.post.mockImplementation((url: string) => {
      if (url === '/v1/assistant/chat') {
        return Promise.resolve({ data: deterministicAnswer });
      }
      return Promise.reject(new Error(`Unexpected POST ${url}`));
    });
    apiMocks.get.mockRejectedValue(new Error('Unexpected GET'));
  });

  it('focuses the prefilled question and renders a cited deterministic answer', async () => {
    const user = userEvent.setup();
    const onConsumed = vi.fn();

    render(
      <Assistant
        assistantOpenJob={{ id: 101, chatPrefillText: productQuestion }}
        onAssistantOpenJobConsumed={onConsumed}
      />,
    );

    expect(screen.getByText('Фактический режим.')).toBeInTheDocument();
    const messageBox = screen.getByRole('textbox', { name: 'Сообщение' });
    await waitFor(() => expect(messageBox).toHaveValue(productQuestion));
    expect(messageBox).toHaveFocus();
    expect(onConsumed).toHaveBeenCalledTimes(1);

    await user.click(screen.getByRole('button', { name: 'Отправить' }));

    await screen.findByRole('heading', { name: 'Проверка товара' });
    expect(apiMocks.post).toHaveBeenCalledWith('/v1/assistant/chat', {
      message: productQuestion,
      history: [],
      context: undefined,
    });
    expect(screen.getByText(productQuestion)).toBeInTheDocument();
    expect(screen.getByText('Проверяемый контекст')).toBeInTheDocument();
    expect(screen.getByText('серверные факты')).toBeInTheDocument();
    expect(
      screen.getByText('Проверено: ТН ВЭД, платежи, документы, риски'),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/Проверьте характеристики конкретной модели перед подачей декларации/),
    ).toBeInTheDocument();

    const sources = screen.getByText('Источники и происхождение данных (1)');
    await user.click(sources);
    const sourcePanel = sources.closest('details');
    expect(sourcePanel).not.toBeNull();
    expect(within(sourcePanel as HTMLElement).getByText('Canonical ТН ВЭД')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Покажите обязательные документы' })).toBeInTheDocument();
  });

  it('labels a validated optional-LLM response as grounded AI without calling a provider', async () => {
    const user = userEvent.setup();
    capabilityMocks.assistantLlmConfigured = true;
    apiMocks.post.mockResolvedValueOnce({
      data: {
        ...deterministicAnswer,
        answer: 'Проверка выполнена по серверным фактам. [S1]',
        grounding: {
          ...deterministicAnswer.grounding,
          mode: 'llm_grounded',
          llm_configured: true,
          provider: 'anthropic',
        },
      },
    });

    render(
      <Assistant
        assistantOpenJob={{ id: 102, chatPrefillText: productQuestion }}
        onAssistantOpenJobConsumed={vi.fn()}
      />,
    );

    const messageBox = screen.getByRole('textbox', { name: 'Сообщение' });
    await waitFor(() => expect(messageBox).toHaveValue(productQuestion));
    expect(screen.queryByText('Фактический режим.')).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Отправить' }));

    await screen.findByText(/Проверка выполнена по серверным фактам/);
    expect(screen.getByText('ИИ + серверные факты')).toBeInTheDocument();
    expect(screen.getByText('Проверяемый контекст')).toBeInTheDocument();
    expect(apiMocks.post).toHaveBeenCalledTimes(1);
  });
});
