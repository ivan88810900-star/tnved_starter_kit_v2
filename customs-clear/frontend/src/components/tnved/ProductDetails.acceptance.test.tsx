import { act, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ProductDetails } from './ProductDetails';

const catalogMocks = vi.hoisted(() => ({
  fetchCommodityByCode: vi.fn(),
  fetchTnvedImportReference: vi.fn(),
  fetchTnvedPreview: vi.fn(),
}));

const productApiMocks = vi.hoisted(() => ({
  apiPost: vi.fn(),
  fetchPaymentQuote: vi.fn(),
  fetchRiskCheck: vi.fn(),
  requestAssistantWithPrefill: vi.fn(),
}));

vi.mock('../../api/tnvedCatalog', async () => {
  const actual = await vi.importActual<typeof import('../../api/tnvedCatalog')>(
    '../../api/tnvedCatalog',
  );
  return {
    ...actual,
    ...catalogMocks,
  };
});

vi.mock('../../api/paymentQuote', async () => {
  const actual = await vi.importActual<typeof import('../../api/paymentQuote')>(
    '../../api/paymentQuote',
  );
  return {
    ...actual,
    fetchPaymentQuote: productApiMocks.fetchPaymentQuote,
  };
});

vi.mock('../../api/riskCheck', () => ({
  fetchRiskCheck: productApiMocks.fetchRiskCheck,
}));

vi.mock('../../api/client', () => ({
  api: {
    post: productApiMocks.apiPost,
  },
}));

vi.mock('../../context/ClientCapabilitiesContext', () => ({
  useAssistantSurfaceVisible: () => true,
}));

vi.mock('../../store/calculatorAssistantBridge', () => ({
  requestAssistantWithPrefill: productApiMocks.requestAssistantWithPrefill,
}));

type Deferred<T> = {
  promise: Promise<T>;
  resolve: (value: T) => void;
  reject: (reason: unknown) => void;
};

function deferred<T>(): Deferred<T> {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((promiseResolve, promiseReject) => {
    resolve = promiseResolve;
    reject = promiseReject;
  });
  return { promise, resolve, reject };
}

const detail = {
  status: 'OK',
  code: '8517130000',
  name: 'Смартфоны',
  description: 'Смартфоны',
  unit: 'шт',
  import_duty: '0%',
  non_tariff_measures: [],
  intellectual_properties: [],
  chapter: {
    id: 85,
    code: '85',
    title: 'Электрические машины и оборудование',
    notes: '',
  },
  section: {
    id: 16,
    roman_number: 'XVI',
    title: 'Машины и оборудование',
    notes: '',
  },
  canonical_anchor: {
    stable_id: 'commodity:8517130000',
    snapshot_id: 'acceptance-snapshot',
    code: '8517130000',
    node_type: 'commodity',
  },
};

const preview = {
  status: 'OK',
  code: '8517130000',
  name: 'Смартфоны',
  payments: {
    duty: '0%',
    vat_rates: [22],
    excise: '',
  },
  non_tariff: {
    has_ban: false,
    measure_types: [],
    measure_badges: [],
    empty_message: '',
  },
  features: [],
  special_duties: {
    has_measures: false,
    countries: [],
    warning: '',
  },
};

const normativeBlock = {
  status: 'OK',
  hs_code: '8517130000',
  description: 'Смартфоны',
  required_documents: [
    {
      permit_type: 'ДС',
      tr_ts: '020/2011',
      tr_ts_full_name: 'Электромагнитная совместимость технических средств',
      applicability: 'definite',
      source_label: 'ЕЭК',
      reason: 'Требование подтверждено нормативным правилом.',
    },
  ],
  missing_documents: [],
  advisory_requirements: [],
  sources_summary: ['ЕЭК'],
  empty_message: null,
};

const paymentQuote = {
  status: 'OK',
  hs_code: '8517130000',
  country: null,
  description: 'Смартфоны',
  customs_value_rub: 100000,
  invoice_currency: 'RUB',
  line_items: [
    {
      code: 'duty',
      label: 'Ввозная пошлина',
      amount_rub: 0,
      status: 'applied',
      reason: 'Ставка для выбранного кода.',
      source: 'ЕТТ ЕАЭС',
      rate_label: '0%',
      basis_label: 'Таможенная стоимость',
      basis_amount_rub: 100000,
    },
    {
      code: 'vat',
      label: 'НДС',
      amount_rub: 22000,
      status: 'applied',
      reason: 'Стандартная ставка.',
      source: 'НК РФ',
      rate_label: '22%',
      basis_label: 'Налоговая база',
      basis_amount_rub: 100000,
    },
  ],
  total_payable_rub: 22000,
  total_partial_rub: 22000,
  warnings: [],
  assumptions: [
    {
      key: 'currency',
      label: 'Валюта',
      value: 'RUB',
    },
  ],
  data_quality: {
    confidence: 'high',
    matched_prefix: '8517130000',
  },
  canonical_anchor: detail.canonical_anchor,
};

const riskBlock = {
  status: 'OK',
  overall_severity: 'clear',
  hs_code: '8517130000',
  signals: [],
  warnings: [],
  source_coverage: [
    {
      source_id: 'local_hs',
      title: 'Локальный реестр ограничений',
      coverage_status: 'present',
      record_count: 10,
      manual_review_required: false,
    },
  ],
  screening_scope: [
    {
      code: 'hs_code',
      label: 'Код ТН ВЭД',
      status: 'checked',
      value: '8517130000',
      explanation: 'Проверено по коду.',
    },
  ],
  coverage_complete: true,
  empty_message: 'Санкционных сигналов по коду не выявлено.',
  disclaimer: 'Диагностическая проверка.',
};

describe('ProductDetails integrated product card', () => {
  let previewDeferred: Deferred<typeof preview>;
  let normativeDeferred: Deferred<{ data: { status: string; items: Array<{ normative_block: typeof normativeBlock }> } }>;

  beforeEach(() => {
    previewDeferred = deferred();
    normativeDeferred = deferred();

    catalogMocks.fetchCommodityByCode.mockResolvedValue(detail);
    catalogMocks.fetchTnvedImportReference.mockResolvedValue({
      status: 'OK',
      title: 'Справка',
      fields: [],
      sections: [],
    });
    catalogMocks.fetchTnvedPreview.mockImplementation(() => previewDeferred.promise);
    productApiMocks.fetchPaymentQuote.mockResolvedValue(paymentQuote);
    productApiMocks.fetchRiskCheck.mockResolvedValue(riskBlock);
    productApiMocks.apiPost.mockImplementation((url: string) => {
      if (url === '/non_tariff/normative-block') return normativeDeferred.promise;
      return Promise.reject(new Error(`Unexpected POST ${url}`));
    });
  });

  it('loads evidence eagerly and lets the user inspect payments, documents, risk, and assistant', async () => {
    const user = userEvent.setup();
    render(
      <MemoryRouter>
        <ProductDetails selectedCode="8517130000" />
      </MemoryRouter>,
    );

    await screen.findByText('8517 13 000 0');
    const summary = screen.getByRole('region', { name: 'Сводка по товару' });
    expect(within(summary).getAllByText('Проверяем…').length).toBeGreaterThan(0);
    expect(within(summary).queryByText('22%')).not.toBeInTheDocument();
    expect(screen.getByText('Определяем обязательные документы по нормативному блоку…')).toBeInTheDocument();
    expect(screen.queryByText('Особых разрешительных документов не выявлено.')).not.toBeInTheDocument();
    expect(
      screen.queryByText(/Специальных разрешительных документов .* не выявлено/),
    ).not.toBeInTheDocument();

    expect((await screen.findAllByText('22 000,00 ₽')).length).toBeGreaterThan(0);
    expect(productApiMocks.fetchPaymentQuote).toHaveBeenCalledWith(
      expect.objectContaining({
        hs_code: '8517130000',
        customs_value: 100000,
      }),
    );

    await act(async () => {
      previewDeferred.resolve(preview);
      normativeDeferred.resolve({
        data: {
          status: 'OK',
          items: [{ normative_block: normativeBlock }],
        },
      });
    });

    await screen.findByText('⚠️ Требуется: Декларация о соответствии');
    expect(within(summary).getByText('ДС')).toBeInTheDocument();
    expect(within(summary).getByText('22%')).toBeInTheDocument();
    expect(
      within(summary).getByText('Требуются разрешительные документы: ДС.'),
    ).toBeInTheDocument();

    const tabList = screen.getByRole('tablist', { name: 'Разделы карточки товара' });
    expect(within(tabList).getByRole('tab', { name: 'Платежи' })).toHaveAttribute(
      'aria-selected',
      'true',
    );
    within(tabList).getByRole('tab', { name: 'Платежи' }).focus();
    await user.keyboard('[ArrowRight]');
    expect(within(tabList).getByRole('tab', { name: 'Нетарифка' })).toHaveAttribute(
      'aria-selected',
      'true',
    );
    await user.keyboard('[ArrowLeft]');
    expect(within(tabList).getByRole('tab', { name: 'Платежи' })).toHaveAttribute(
      'aria-selected',
      'true',
    );

    await user.click(within(tabList).getByRole('tab', { name: 'Документы' }));
    const documentsPanel = screen.getByRole('tabpanel', { name: 'Документы' });
    expect(within(documentsPanel).getByText('Обязательные документы')).toBeInTheDocument();
    expect(within(documentsPanel).getByText('Декларация о соответствии')).toBeInTheDocument();

    await user.click(within(tabList).getByRole('tab', { name: 'Риски' }));
    const riskPanel = screen.getByRole('tabpanel', { name: 'Риски' });
    await within(riskPanel).findByText('Санкционных сигналов по коду не выявлено.');
    expect(productApiMocks.fetchRiskCheck).toHaveBeenCalledWith(
      expect.objectContaining({ hs_code: '8517130000' }),
    );

    await user.click(screen.getByRole('button', { name: 'Спросить помощника' }));
    expect(productApiMocks.requestAssistantWithPrefill).toHaveBeenCalledWith(
      expect.stringMatching(/8517130000.*платежи.*документы.*риски/i),
    );
  });

  it('never presents unavailable evidence as a confirmed clean result', async () => {
    const user = userEvent.setup();
    render(
      <MemoryRouter>
        <ProductDetails selectedCode="8517130000" />
      </MemoryRouter>,
    );

    await screen.findByText('8517 13 000 0');
    await act(async () => {
      previewDeferred.reject(new Error('preview unavailable'));
      normativeDeferred.reject(new Error('normative unavailable'));
    });

    await screen.findByText('Не удалось подтвердить наличие или отсутствие разрешительных документов.');
    const summary = screen.getByRole('region', { name: 'Сводка по товару' });
    expect(within(summary).queryByText('22%')).not.toBeInTheDocument();
    expect(screen.getAllByText('Нет данных').length).toBeGreaterThan(0);
    expect(screen.getByText(/Отсутствие разрешительных документов не подтверждено/)).toBeInTheDocument();
    expect(screen.queryByText('Особых разрешительных документов не выявлено.')).not.toBeInTheDocument();
    expect(
      screen.queryByText(/Специальных разрешительных документов .* не выявлено/),
    ).not.toBeInTheDocument();
    expect(screen.queryByText('Документы не требуются.')).not.toBeInTheDocument();

    await user.click(screen.getByRole('tab', { name: 'Нетарифка' }));
    expect(
      screen.getByText('Не удалось подтвердить наличие или отсутствие специальных торговых мер.'),
    ).toBeInTheDocument();
  });

  it('keeps a confirmed normative requirement visible when preview evidence fails', async () => {
    render(
      <MemoryRouter>
        <ProductDetails selectedCode="8517130000" />
      </MemoryRouter>,
    );

    await screen.findByText('8517 13 000 0');
    await act(async () => {
      previewDeferred.reject(new Error('preview unavailable'));
      normativeDeferred.resolve({
        data: {
          status: 'OK',
          items: [{ normative_block: normativeBlock }],
        },
      });
    });

    await screen.findByText('⚠️ Требуется: Декларация о соответствии');
    const summary = screen.getByRole('region', { name: 'Сводка по товару' });
    expect(within(summary).getByText('ДС')).toBeInTheDocument();
    expect(
      within(summary).getByText('Требуются разрешительные документы: ДС.'),
    ).toBeInTheDocument();
    expect(
      within(summary).queryByText('Особых разрешительных документов не выявлено.'),
    ).not.toBeInTheDocument();
  });
});
