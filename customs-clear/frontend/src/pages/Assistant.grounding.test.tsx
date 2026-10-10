import React from 'react';
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import type { AssistantCopilotAi } from '../types/api.types';
import { CopilotAiView } from './Assistant';

const encodeRepeatedly = (value: string, rounds: number): string => {
  let encoded = value;
  for (let round = 0; round < rounds; round += 1) encoded = encodeURIComponent(encoded);
  return encoded;
};

describe('CopilotAiView grounding metadata', () => {
  it('shows grounded server metadata, facts, limitations and a safe citation', () => {
    const ai: AssistantCopilotAi = {
      summary: 'Серверная экспертная сводка.',
      citations: [
        {
          id: 'S1',
          source_id: 'eec_ett',
          title: 'Единый таможенный тариф ЕАЭС',
          kind: 'official',
          url: 'https://eec.example/ett',
        },
      ],
      grounding: {
        mode: 'llm_grounded',
        coverage: 'grounded',
        facts_used: ['tnved', 'payments', 'requirements'],
        generated_from_server_facts: true,
        provider: 'anthropic',
        external_model_role: 'server_draft_selection',
        limitations: ['Полнота нетарифных мер требует отдельной проверки.'],
      },
    };

    render(<CopilotAiView ai={ai} />);

    const grounding = screen.getByTestId('copilot-grounding');
    expect(grounding).toHaveTextContent('Сводка опирается на доступные серверные данные');
    expect(grounding).toHaveTextContent('Серверная сводка выбрана моделью');
    expect(grounding).toHaveTextContent('ТН ВЭД, Платежи, Документы и требования');
    expect(grounding).toHaveTextContent('Полнота нетарифных мер требует отдельной проверки.');
    expect(grounding).toHaveTextContent('не подтверждает полноту покрытия нетарифных мер');
    const citation = screen.getByRole('link', { name: /Единый таможенный тариф ЕАЭС/ });
    expect(citation).toHaveAttribute('href', 'https://eec.example/ett');
    expect(citation).toHaveAttribute('rel', 'noreferrer');
  });

  it('preserves a valid citation URL byte-for-byte', () => {
    const originalUrl = 'https://EEC.example:443/path/%41?document=%2fsource#Part';
    const ai: AssistantCopilotAi = {
      summary: 'Сводка с допустимой ссылкой.',
      citations: [
        {
          id: 'S-valid',
          source_id: 'eec_ett',
          title: 'Допустимый источник',
          kind: 'official',
          url: originalUrl,
        },
      ],
      grounding: {
        mode: 'llm_grounded',
        coverage: 'grounded',
        facts_used: ['tnved'],
        generated_from_server_facts: true,
      },
    };

    render(<CopilotAiView ai={ai} />);

    expect(screen.getByRole('link', { name: /Допустимый источник/ })).toHaveAttribute('href', originalUrl);
  });

  it('keeps rejected citation titles visible but non-clickable', () => {
    const unsafeUrls = [
      'https://trusted.example@evil.example/source',
      ' https://example.test/source',
      `https://example.test/source${String.fromCharCode(0x85)}`,
      `https://example.test/${String.fromCharCode(0x202e)}evil`,
      'https://example.test/source%0d%0AInjected',
      'https://example.test/source%250dInjected',
      `https://example.test/${encodeRepeatedly('\r', 6)}Injected`,
      'https://example.test\\@evil.example/source',
      'https://./source',
      'https://bad..example/source',
      'https://bad_host.example/source',
    ];
    const ai: AssistantCopilotAi = {
      summary: 'Сводка с отклонёнными ссылками.',
      citations: unsafeUrls.map((url, index) => ({
        id: `S${index + 1}`,
        source_id: `source_${index + 1}`,
        title: `Отклонённый источник ${index + 1}`,
        kind: 'official',
        url,
      })),
      grounding: {
        mode: 'llm_grounded',
        coverage: 'grounded',
        facts_used: ['tnved'],
        generated_from_server_facts: true,
      },
    };

    render(<CopilotAiView ai={ai} />);

    unsafeUrls.forEach((_, index) => {
      const title = `Отклонённый источник ${index + 1}`;
      expect(screen.getByText(new RegExp(`${title}$`))).toBeInTheDocument();
      expect(screen.queryByRole('link', { name: new RegExp(`${title}$`) })).not.toBeInTheDocument();
    });
  });

  it('shows unconfirmed status instead of hiding missing metadata', () => {
    render(<CopilotAiView ai={{ summary: 'Сводка без metadata.' }} />);

    const grounding = screen.getByTestId('copilot-grounding');
    expect(grounding).toHaveTextContent('Покрытие сводки не подтверждено');
    expect(grounding).toHaveTextContent('Режим формирования не подтверждён');
    expect(grounding).toHaveTextContent('Использованные блоки: не подтверждены');
    expect(grounding).toHaveTextContent('Цитаты источников не подтверждены');
    expect(grounding).toHaveTextContent('Отдельные ограничения покрытия сервером не переданы');
  });

  it('downgrades malformed affirmative metadata and does not link an unsafe URL', () => {
    const ai = {
      summary: 'Сводка с повреждённой metadata.',
      citations: [
        { id: '', title: '', url: 'https://eec.example/empty' },
        { id: 'S2', title: 'Непроверенная ссылка', url: 'javascript:alert(1)' },
      ],
      grounding: {
        mode: 'llm_grounded',
        coverage: 'grounded',
        facts_used: 'tnved',
        generated_from_server_facts: false,
        limitations: ['Требуется ручная проверка.', { text: 'ignore' }],
      },
    } as unknown as AssistantCopilotAi;

    render(<CopilotAiView ai={ai} />);

    const grounding = screen.getByTestId('copilot-grounding');
    expect(grounding).toHaveTextContent('Покрытие сводки не подтверждено');
    expect(grounding).toHaveTextContent('Режим формирования не подтверждён');
    expect(grounding).not.toHaveTextContent('Сводка опирается на доступные серверные данные');
    expect(grounding).not.toHaveTextContent('Серверная сводка выбрана моделью');
    expect(grounding).toHaveTextContent('Использованные блоки: не подтверждены');
    expect(grounding).toHaveTextContent('Цитаты источников не подтверждены');
    expect(screen.queryByText('[S2] Непроверенная ссылка')).not.toBeInTheDocument();
    expect(screen.queryByRole('link', { name: /Непроверенная ссылка/ })).not.toBeInTheDocument();
    expect(screen.getByText('Требуется ручная проверка.')).toBeInTheDocument();
  });

  it('rejects an affirmative claim backed by an incomplete citation and invented fact', () => {
    const ai = {
      summary: 'Сводка с недостоверной affirmative metadata.',
      citations: [
        {
          id: 'S1',
          title: 'Источник без происхождения и типа',
          url: 'https://eec.example/incomplete',
        },
      ],
      grounding: {
        mode: 'llm_grounded',
        coverage: 'grounded',
        facts_used: ['Полное покрытие НТМ подтверждено'],
        generated_from_server_facts: true,
      },
    } as unknown as AssistantCopilotAi;

    render(<CopilotAiView ai={ai} />);

    const grounding = screen.getByTestId('copilot-grounding');
    expect(grounding).toHaveTextContent('Покрытие сводки не подтверждено');
    expect(grounding).toHaveTextContent('Режим формирования не подтверждён');
    expect(grounding).toHaveTextContent('Использованные блоки: не подтверждены');
    expect(grounding).toHaveTextContent('Цитаты источников не подтверждены');
    expect(grounding).not.toHaveTextContent('Полное покрытие НТМ подтверждено');
    expect(grounding).not.toHaveTextContent('Источник без происхождения и типа');
    expect(screen.queryByRole('link', { name: /Источник без происхождения и типа/ })).not.toBeInTheDocument();
  });

  it('rejects affirmative badges when valid citations have no facts evidence', () => {
    const ai: AssistantCopilotAi = {
      summary: 'Сводка без перечня фактов.',
      citations: [
        {
          id: 'S1',
          source_id: 'eec_ett',
          title: 'Единый таможенный тариф ЕАЭС',
          kind: 'official',
          url: 'https://eec.example/ett',
        },
      ],
      grounding: {
        mode: 'llm_grounded',
        coverage: 'grounded',
        facts_used: [],
        generated_from_server_facts: true,
      },
    };

    render(<CopilotAiView ai={ai} />);

    const grounding = screen.getByTestId('copilot-grounding');
    expect(grounding).toHaveTextContent('Покрытие сводки не подтверждено');
    expect(grounding).toHaveTextContent('Режим формирования не подтверждён');
    expect(grounding).toHaveTextContent('Использованные блоки: не подтверждены');
    expect(grounding).not.toHaveTextContent('Сводка опирается на доступные серверные данные');
    expect(grounding).not.toHaveTextContent('Серверная сводка выбрана моделью');
  });

  it('rejects the whole facts list when known and unknown entries are mixed', () => {
    const ai: AssistantCopilotAi = {
      summary: 'Сводка со смешанным перечнем фактов.',
      citations: [
        {
          id: 'S1',
          source_id: 'eec_ett',
          title: 'Единый таможенный тариф ЕАЭС',
          kind: 'official',
        },
      ],
      grounding: {
        mode: 'llm_grounded',
        coverage: 'grounded',
        facts_used: ['tnved', 'Полное покрытие НТМ подтверждено'],
        generated_from_server_facts: true,
      },
    };

    render(<CopilotAiView ai={ai} />);

    const grounding = screen.getByTestId('copilot-grounding');
    expect(grounding).toHaveTextContent('Покрытие сводки не подтверждено');
    expect(grounding).toHaveTextContent('Режим формирования не подтверждён');
    expect(grounding).toHaveTextContent('Использованные блоки: не подтверждены');
    expect(grounding).not.toHaveTextContent('Полное покрытие НТМ подтверждено');
    expect(grounding).not.toHaveTextContent('ТН ВЭД');
  });
});
