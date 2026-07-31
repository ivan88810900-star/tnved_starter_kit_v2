import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { Dictionary } from './Dictionary';

const apiMocks = vi.hoisted(() => ({
  fetchTnvedBreadcrumb: vi.fn(),
  fetchTnvedChildren: vi.fn(),
  fetchGuidedTnvedNavigation: vi.fn(),
  searchTnved: vi.fn(),
}));

vi.mock('../api/tnvedCatalog', async () => {
  const actual = await vi.importActual<typeof import('../api/tnvedCatalog')>(
    '../api/tnvedCatalog',
  );
  return {
    ...actual,
    ...apiMocks,
  };
});

vi.mock('../components/tnved/ProductDetails', () => ({
  ProductDetails: ({ selectedCode }: { selectedCode: string }) => (
    <p>Загружена карточка {selectedCode}</p>
  ),
}));

const canonicalAnchor = {
  stable_id: 'commodity:8517130000',
  snapshot_id: 'acceptance-snapshot',
  code: '8517130000',
  node_type: 'commodity',
};

describe('Dictionary smart TN VED journey', () => {
  beforeEach(() => {
    sessionStorage.clear();
    document.body.style.overflow = '';

    apiMocks.fetchTnvedChildren.mockResolvedValue({
      status: 'OK',
      code: '',
      depth: 'direct',
      items: [],
    });
    apiMocks.fetchTnvedBreadcrumb.mockResolvedValue([]);
    apiMocks.searchTnved.mockResolvedValue({
      results: [
        {
          code: '8517',
          name: 'Телефонные аппараты, включая смартфоны',
          is_leaf: false,
          match_reason: 'domain_dictionary',
          canonical_anchor: { ...canonicalAnchor, code: '8517' },
        },
      ],
      guided_routes: [
        {
          heading: '8517',
          title: 'Телефонные аппараты, включая смартфоны',
          candidate_count: 1,
          best_match_reason: 'domain_dictionary',
          first_result_rank: 1,
          canonical_anchor: { ...canonicalAnchor, code: '8517' },
          guided_href: '/v1/tnved/guided/8517',
        },
      ],
      suggestions: [],
      search: {
        strategy: 'domain_dictionary',
        corrected_query: null,
        effective_query: 'смартфон',
      },
    });
    apiMocks.fetchGuidedTnvedNavigation.mockResolvedValue({
      status: 'OK',
      engine: {
        name: 'guided_tnved',
        version: '1',
        mode: 'canonical_semantic_overlay',
        snapshot_id: 'acceptance-snapshot',
      },
      heading: {
        code: '8517',
        title: 'Телефонные аппараты, включая смартфоны',
        canonical_anchor: { ...canonicalAnchor, code: '8517' },
      },
      prompt: 'Что именно вы ввозите?',
      choices: [
        {
          id: 'smartphones',
          kind: 'classification_subgroup',
          role: 'semantic_choice',
          title: 'Мобильные телефоны и смартфоны',
          code: null,
          is_leaf: false,
          result_count: 1,
          code_count: 1,
          confidence: 'high',
          canonical_anchor: null,
          children: [
            {
              id: 'commodity:8517130000',
              kind: 'leaf',
              role: 'declarable_code',
              title: 'Смартфоны',
              code: '8517130000',
              is_leaf: true,
              result_count: 1,
              code_count: 1,
              confidence: 'high',
              canonical_anchor: canonicalAnchor,
              children: [],
            },
          ],
        },
      ],
      integrity: {
        complete: true,
        canonical_coverage: 1,
        critical_issues: [],
      },
      fallback: {
        type: 'legacy_tree',
        href: '/tnved/children/8517',
        label: 'Обычное дерево',
      },
    });
  });

  it('opens a guided candidate from search and reaches a real product card', async () => {
    const user = userEvent.setup();
    render(<Dictionary />);

    await user.type(
      screen.getByRole('searchbox', { name: 'Поиск по ТН ВЭД' }),
      'смартфон',
    );

    const guidedSectionTitle = await screen.findByText('Подобрать точный код по вопросам');
    const guidedSection = guidedSectionTitle.closest('section');
    expect(guidedSection).not.toBeNull();

    await user.click(within(guidedSection as HTMLElement).getByRole('button', { name: /8517/ }));

    const guidedDialog = await screen.findByRole('dialog', {
      name: 'Умная структура ТН ВЭД',
    });
    expect(apiMocks.fetchGuidedTnvedNavigation).toHaveBeenCalledWith('8517');
    expect(document.body).toHaveStyle({ overflow: 'hidden' });
    expect(
      within(guidedDialog).getByRole('button', { name: 'Закрыть умный маршрут' }),
    ).toHaveFocus();

    await user.click(
      within(guidedDialog).getByRole('button', {
        name: /Мобильные телефоны и смартфоны/,
      }),
    );
    await user.click(
      within(guidedDialog).getByRole('button', {
        name: /8517 13 000 0.*Смартфоны/,
      }),
    );

    const productDialog = await screen.findByRole('dialog', { name: 'Карточка товара' });
    expect(screen.queryByRole('dialog', { name: 'Умная структура ТН ВЭД' })).not.toBeInTheDocument();
    expect(within(productDialog).getByText('Загружена карточка 8517130000')).toBeInTheDocument();
    expect(within(productDialog).getByRole('button', { name: 'Закрыть' })).toHaveFocus();

    await user.click(within(productDialog).getByRole('button', { name: 'Закрыть' }));
    await waitFor(() => {
      expect(screen.queryByRole('dialog', { name: 'Карточка товара' })).not.toBeInTheDocument();
      expect(document.body).not.toHaveStyle({ overflow: 'hidden' });
    });
  });
});
