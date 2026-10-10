import React from 'react';
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import type { AssistantCopilotAi, AssistantCopilotBundle } from '../types/api.types';
import { CopilotAiView, CopilotBundleView } from './Assistant';

const encodeRepeatedly = (value: string, rounds: number): string => {
  let encoded = value;
  for (let round = 0; round < rounds; round += 1) encoded = encodeURIComponent(encoded);
  return encoded;
};

const bundleWithOfficialUrl = (officialUrl: string): AssistantCopilotBundle => ({
  effective_hs_code: '0101210000',
  description: 'Тестовый товар',
  pipeline: [],
  tnved_context: {
    hs_code: '0101210000',
    title: 'Лошади чистопородные племенные',
    description: '',
    breadcrumb: [],
    notes: [],
    official_ett_url: officialUrl,
    source_revision: 'test',
  },
});

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

describe('CopilotBundleView official ETT source URL', () => {
  it('preserves an admitted HTTP(S) source URL byte-for-byte', () => {
    const originalUrl = 'https://EEC.example:443/path/%41?document=%2fsource#Part';

    render(<CopilotBundleView bundle={bundleWithOfficialUrl(originalUrl)} title="Ход обработки" />);

    expect(screen.getByRole('link', { name: 'ТН ВЭД и ЕТТ на сайте ЕЭК' })).toHaveAttribute(
      'href',
      originalUrl,
    );
  });

  it.each([
    ['credentials', 'https://trusted.example@evil.example/source'],
    ['leading whitespace', ' https://example.test/source'],
    ['literal C1 control', `https://example.test/source${String.fromCharCode(0x85)}`],
    ['literal bidi control', `https://example.test/${String.fromCharCode(0x202e)}evil`],
    ['encoded control', 'https://example.test/source%0d%0AInjected'],
    ['double-encoded control', 'https://example.test/source%250dInjected'],
    ['deeply encoded control', `https://example.test/${encodeRepeatedly('\r', 6)}Injected`],
    ['backslash authority confusion', 'https://example.test\\@evil.example/source'],
    ['empty hostname label', 'https://./source'],
    ['repeated hostname dot', 'https://bad..example/source'],
    ['invalid hostname character', 'https://bad_host.example/source'],
  ])('renders rejected %s evidence as bounded plain text, not an anchor', (_case, unsafeUrl) => {
    render(<CopilotBundleView bundle={bundleWithOfficialUrl(unsafeUrl)} title="Ход обработки" />);

    expect(screen.queryByRole('link', { name: 'ТН ВЭД и ЕТТ на сайте ЕЭК' })).not.toBeInTheDocument();
    const evidence = screen.getByTestId('copilot-bundle-unsafe-official-url');
    expect(evidence).toBeInTheDocument();
    expect(evidence.textContent?.length).toBeLessThanOrEqual(170);
    expect(evidence.textContent).not.toMatch(/[\u0000-\u001f\u007f-\u009f\u061c\u200e\u200f\u202a-\u202e\u2066-\u2069]/u);
  });
});
