import React from 'react';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { Calculator } from './Calculator';
import { api } from '../api/client';
import { setAssistantCalculationContext } from '../store/calculatorAssistantBridge';

vi.mock('../api/client', () => ({ api: { get: vi.fn(), post: vi.fn() } }));
vi.mock('../api/tnvedCatalog', () => ({
  fetchCommodityByCode: vi.fn().mockResolvedValue({ non_tariff_measures: [] }),
  fetchHierarchyTree: vi.fn().mockResolvedValue([]),
  formatCustomsCode: (s: string) => s,
  formatImportDutyPercent: (s: string) => s,
}));
vi.mock('../store/calculatorAssistantBridge', () => ({
  getAssistantCalculationContext: vi.fn(), requestAssistantCalculatorConsult: vi.fn(),
  setAssistantCalculationContext: vi.fn(),
}));
vi.mock('recharts', () => ({
  Cell: () => null, Pie: () => null, PieChart: () => null,
  ResponsiveContainer: () => null, Tooltip: () => null,
}));
vi.mock('../components/AnimatedNumber', () => ({ AnimatedNumber: ({ value }: { value: number }) => <span>{value} ₽</span> }));

const reason = 'Не проверены товарный перечень и происхождение.';
const pendingPreference = { applied: false, status: 'needs_review', reason, eligibility_verified: false, duty_coefficient: 1, candidate_duty_coefficient: 0.75, preference_type: 'gsp' };
function rawResult(pending: boolean) {
  return {
    status: pending ? 'REVIEW_REQUIRED' : 'OK', amounts_provisional: pending,
    hs_code: '8509400000', country: 'IN', customs_value: 100000,
    auto_detected: {}, legal_basis: {}, data_quality: {}, sources: [], special_duties: [],
    tariff_preference: pending ? pendingPreference : { applied: false, duty_coefficient: 1 },
    breakdown: { duty: 10000, duty_rate: 10, vat: 24200, vat_rate: 22, customs_fee: 1000, total_payable: 35200, vat_base: 110000, excise: 0, antidumping: 0 },
  };
}
function renderCalculator() {
  render(<MemoryRouter><Calculator /></MemoryRouter>);
}
function fillBase() {
  fireEvent.change(screen.getByPlaceholderText('8509400000'), { target: { value: '8509400000' } });
  fireEvent.change(screen.getByLabelText(/Инвойсная стоимость, RUB/), { target: { value: '100000' } });
  fireEvent.change(screen.getByLabelText('Страна происхождения (обязательно)'), { target: { value: 'IN' } });
}

beforeEach(() => {
  vi.mocked(api.get).mockImplementation(async (url) => {
    if (String(url).startsWith('/calculator/history?')) return { data: { items: [] } };
    if (url === '/v1/finance/rates') return { data: { map: { RUB: 1 } } };
    return { data: {} };
  });
});

describe('Calculator provisional payments', () => {
  it('labels both raw totals as estimates and preserves review provenance for the assistant', async () => {
    vi.mocked(api.post).mockResolvedValue({ data: rawResult(true) });
    renderCalculator(); fillBase();
    fireEvent.click(screen.getByRole('button', { name: 'Рассчитать платежи' }));
    expect(await screen.findByText(reason)).toBeInTheDocument();
    expect(screen.getAllByText('Предварительная сумма')).toHaveLength(2);
    expect(screen.queryByText('Итого к уплате')).not.toBeInTheDocument();
    expect(screen.queryByText(/Применена тарифная преференция/)).not.toBeInTheDocument();
    expect(screen.queryByText(/пошлина ×0.75/)).not.toBeInTheDocument();
    await waitFor(() => expect(setAssistantCalculationContext).toHaveBeenCalledWith(expect.objectContaining({
      payment_status: 'REVIEW_REQUIRED', amounts_provisional: true,
      tariff_preference: pendingPreference, total_payable: 35200,
    })));
  });

  it('describes missing rate sources without attributing the problem to a tariff preference', async () => {
    vi.mocked(api.post).mockResolvedValue({ data: { ...rawResult(true), tariff_preference: { applied: false },
      payment_review_reason: 'Не найден источник ставки пошлины.', payment_review_reasons: ['duty_source_missing'] } });
    renderCalculator(); fillBase();
    fireEvent.click(screen.getByRole('button', { name: 'Рассчитать платежи' }));
    expect(await screen.findByText('Не найден источник ставки пошлины.')).toBeInTheDocument();
    expect(screen.getAllByText('Предварительная сумма')).toHaveLength(2);
    expect(screen.queryByText(/Право на тарифную преференцию не подтверждено/)).not.toBeInTheDocument();
    await waitFor(() => expect(setAssistantCalculationContext).toHaveBeenCalledWith(expect.objectContaining({
      payment_review_reason: 'Не найден источник ставки пошлины.', payment_review_reasons: ['duty_source_missing'],
    })));
  });

  it('retains normal total labels for an ordinary calculation', async () => {
    vi.mocked(api.post).mockResolvedValue({ data: rawResult(false) });
    renderCalculator(); fillBase();
    fireEvent.click(screen.getByRole('button', { name: 'Рассчитать платежи' }));
    expect(await screen.findAllByText('Итого к уплате')).toHaveLength(2);
    expect(screen.queryByText('Предварительная сумма')).not.toBeInTheDocument();
  });

  it.each([true, false])('suppresses two-code deltas exactly when a scenario needs review: %s', async (pending) => {
    vi.mocked(api.post).mockResolvedValue({ data: {
      status: 'OK', scenarios: [
        { label: 'A', delta_total_vs_first_rub: 0, profile: { hs_code: '8509400000', status: pending ? 'REVIEW_REQUIRED' : 'OK', amounts_provisional: pending, tariff_preference: pending ? pendingPreference : null, breakdown: { base_duty: 10000, vat: 24200, excise: 0, anti_dumping: 0, customs_fee: 1000, total_payable: 35200 } } },
        { label: 'B', delta_total_vs_first_rub: -6100, profile: { hs_code: '8516108008', status: 'OK', amounts_provisional: false, tariff_preference: null, breakdown: { base_duty: 5000, vat: 23100, excise: 0, anti_dumping: 0, customs_fee: 1000, total_payable: 29100 } } },
      ],
    } });
    renderCalculator(); fillBase();
    const summary = screen.getByText('Сравнение двух кодов («что если»)');
    summary.closest('details')!.open = true;
    fireEvent.click(screen.getByRole('button', { name: 'Сравнить' }));
    const table = await within(summary.closest('details')!).findByRole('table');
    expect(within(table).getByText(pending ? 'Предварительно ₽' : 'К уплате ₽')).toBeInTheDocument();
    expect(within(table).getByText('Пошлина ₽')).toBeInTheDocument();
    expect(within(table).getByText('8516108008')).toBeInTheDocument();
    const rows = within(table).getAllByRole('row');
    expect(within(rows[2]).getAllByRole('cell').at(-1)).toHaveTextContent(pending ? '—' : /-6\s100/);
  });

  it('distinguishes a pending history estimate from older history without verification metadata', async () => {
    vi.mocked(api.get).mockImplementation(async (url) => ({ data: String(url).startsWith('/calculator/history?') ? { items: [
      { id: 'pending-history', total_payable: 35200, amounts_provisional: true, payment_status: 'REVIEW_REQUIRED', tariff_preference_warning: reason },
      { id: 'old-history', total_payable: 24000, amounts_provisional: null, payment_status: null },
    ] } : {} }));
    renderCalculator();
    expect(await screen.findByText('Предварительно: требуется проверка')).toBeInTheDocument();
    expect(screen.getByText('Статус проверки суммы не сохранён')).toBeInTheDocument();
    expect(screen.getByText(reason)).toBeInTheDocument();
  });
});
