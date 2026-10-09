import React from 'react';
import { act, fireEvent, render, screen } from '@testing-library/react';
import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';

import {
  DeclarantChatThread,
  type DeclarantChatThreadHandle,
} from './DeclarantChatThread';

const { postMock } = vi.hoisted(() => ({ postMock: vi.fn() }));

vi.mock('../../api/client', () => ({
  api: { post: postMock },
}));

vi.mock('../../store/calculatorAssistantBridge', () => ({
  getAssistantCalculationContext: () => null,
  subscribeAssistantCalculationContext: () => () => undefined,
}));

async function sendQuestion(): Promise<void> {
  render(<DeclarantChatThread headerTitle="Консультация" />);
  fireEvent.change(screen.getByRole('textbox', { name: 'Сообщение' }), {
    target: { value: 'Какие документы нужны?' },
  });
  fireEvent.click(screen.getByRole('button', { name: 'Отправить' }));
  await screen.findByText('Проверенный серверный ответ.');
}

describe('DeclarantChatThread grounding metadata', () => {
  beforeAll(() => {
    Element.prototype.scrollIntoView = vi.fn();
  });

  beforeEach(() => {
    postMock.mockReset();
  });

  it('shows grounded coverage, mode and a safe citation without claiming legal verification', async () => {
    postMock.mockResolvedValue({
      data: {
        status: 'OK',
        answer: {
          answer: 'Проверенный серверный ответ.',
          grounding: {
            coverage: 'grounded',
            mode: 'llm_grounded',
            generated_from_server_facts: true,
            citations: [
              {
                id: 'S1',
                source_id: 'eec_ett',
                title: 'Единый таможенный тариф ЕАЭС',
                url: 'https://eec.example/ett',
                kind: 'official',
              },
            ],
            limitations: [],
          },
          suggestions: [],
        },
      },
    });

    await sendQuestion();

    expect(screen.getByTestId('assistant-grounding')).toHaveTextContent(
      'Ответ опирается на доступные серверные данные',
    );
    expect(screen.getByTestId('assistant-grounding')).toHaveTextContent(
      'Серверный ответ выбран моделью',
    );
    expect(screen.getByTestId('assistant-grounding')).toHaveTextContent(
      'не подтверждает юридическую полноту',
    );
    const citation = screen.getByRole('link', { name: /Единый таможенный тариф ЕАЭС/ });
    expect(citation).toHaveAttribute('href', 'https://eec.example/ett');
    expect(citation).toHaveAttribute('rel', 'noreferrer');
  });

  it('shows partial coverage and limitations without inventing a citation', async () => {
    postMock.mockResolvedValue({
      data: {
        status: 'OK',
        answer: {
          answer: 'Проверенный серверный ответ.',
          grounding: {
            coverage: 'partial',
            mode: 'deterministic',
            citations: [],
            limitations: ['Нетарифный контур временно недоступен.'],
          },
          suggestions: [],
        },
      },
    });

    await sendQuestion();

    expect(screen.getByTestId('assistant-grounding')).toHaveTextContent('Данные для ответа неполные');
    expect(screen.getByTestId('assistant-grounding')).toHaveTextContent('Серверный ответ');
    expect(screen.getByText('Нетарифный контур временно недоступен.')).toBeInTheDocument();
    expect(screen.queryByText('Источники в ответе')).not.toBeInTheDocument();
  });

  it.each([
    ['legacy string', 'Проверенный серверный ответ.'],
    ['current payload without grounding', { answer: 'Проверенный серверный ответ.', suggestions: [] }],
  ])('keeps rendering a %s response without a grounding badge', async (_label, answer) => {
    postMock.mockResolvedValue({
      data: {
        status: 'OK',
        answer,
      },
    });

    await sendQuestion();

    expect(screen.getByText('Проверенный серверный ответ.')).toBeInTheDocument();
    expect(screen.queryByTestId('assistant-grounding')).not.toBeInTheDocument();
  });

  it('fails closed for unknown metadata and never links a non-http URL', async () => {
    postMock.mockResolvedValue({
      data: {
        status: 'OK',
        answer: {
          answer: 'Проверенный серверный ответ.',
          grounding: {
            coverage: 'complete',
            mode: 'official_ai',
            citations: [
              {
                id: 'S1',
                title: 'Непроверенная ссылка',
                url: 'javascript:alert(1)',
              },
            ],
            limitations: ['Требуется ручная проверка.', { text: 'ignore' }],
          },
        },
      },
    });

    await sendQuestion();

    expect(screen.getByTestId('assistant-grounding')).toHaveTextContent(
      'Статус покрытия не подтверждён',
    );
    expect(screen.getByTestId('assistant-grounding')).toHaveTextContent(
      'Режим ответа не подтверждён',
    );
    expect(screen.getByText('Требуется ручная проверка.')).toBeInTheDocument();
    expect(screen.getByText('[S1] Непроверенная ссылка')).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: /Непроверенная ссылка/ })).not.toBeInTheDocument();
  });

  it('does not trust affirmative labels without server evidence invariants', async () => {
    postMock.mockResolvedValue({
      data: {
        status: 'OK',
        answer: {
          answer: 'Проверенный серверный ответ.',
          grounding: {
            coverage: 'grounded',
            mode: 'llm_grounded',
            generated_from_server_facts: false,
            citations: [{ id: '', title: '', url: 'https://eec.example/ett' }],
            limitations: [],
          },
        },
      },
    });

    await sendQuestion();

    const grounding = screen.getByTestId('assistant-grounding');
    expect(grounding).toHaveTextContent('Статус покрытия не подтверждён');
    expect(grounding).toHaveTextContent('Режим ответа не подтверждён');
    expect(grounding).not.toHaveTextContent('Ответ опирается на доступные серверные данные');
    expect(grounding).not.toHaveTextContent('Серверный ответ выбран моделью');
    expect(screen.queryByText('Источники в ответе')).not.toBeInTheDocument();
  });

  it('sends only the newest 40 history items without removing visible messages', async () => {
    postMock.mockResolvedValue({
      data: { status: 'OK', answer: 'Проверенный серверный ответ.' },
    });
    const ref = React.createRef<DeclarantChatThreadHandle>();
    render(<DeclarantChatThread ref={ref} headerTitle="Консультация" />);
    const existing = Array.from({ length: 42 }, (_, index) => ({
      role: index % 2 === 0 ? 'user' as const : 'assistant' as const,
      text: `Сообщение ${index}`,
    }));
    act(() => ref.current?.resetWithMessages(existing));

    expect(screen.getByText('Сообщение 0')).toBeInTheDocument();
    fireEvent.change(screen.getByRole('textbox', { name: 'Сообщение' }), {
      target: { value: 'Новый вопрос' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Отправить' }));
    await screen.findByText('Проверенный серверный ответ.');

    const request = postMock.mock.calls[0]?.[1] as {
      history: Array<{ role: string; content: string }>;
    };
    expect(request.history).toHaveLength(40);
    expect(request.history[0]).toEqual({ role: 'user', content: 'Сообщение 2' });
    expect(request.history[39]).toEqual({ role: 'assistant', content: 'Сообщение 41' });
    expect(screen.getByText('Сообщение 0')).toBeInTheDocument();
  });
});
