import React from 'react';
import { fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { CalculatorScenarioCompareSection } from './CalculatorScenarioCompareSection';
import { api } from '../../api/client';

vi.mock('../../api/client', () => ({ api: { post: vi.fn() } }));
afterEach(() => vi.restoreAllMocks());

function renderComparison(pending: boolean) {
  vi.mocked(api.post).mockResolvedValue({ data: {
    status: 'OK', best_scenario: '=1+1', savings_vs_worst: 1200,
    // Incomplete response deliberately retains stale ranking to test UI defense.
    scenarios: [
      { name: '=1+1', hs_code: '8509400000', country_of_origin: 'IN', duty: 1000, vat: 2420, fee: 100, rop: 0, total: 3520,
        payments_status: pending ? 'REVIEW_REQUIRED' : 'OK',
        preference: pending ? { applied: false, status: 'needs_review', reason: 'Не проверено; "происхождение"' } : undefined },
      { name: 'Сценарий Б', hs_code: '8509400000', country_of_origin: 'CN', duty: 2000, vat: 2420, fee: 100, rop: 0, total: 4720, payments_status: 'OK', amounts_provisional: false },
    ],
  } });
  render(<CalculatorScenarioCompareSection baseHsCode="8509400000" customsValue={100000} currency="RUB" weightGrossKg="" weightNetKg="" defaultCountry="IN" />);
  screen.getByText('Сравнение сценариев (страны, коды, процедуры)').closest('details')!.open = true;
  fireEvent.click(screen.getByRole('button', { name: 'Сравнить сценарии' }));
}

function readBlob(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result));
    reader.onerror = reject;
    reader.readAsText(blob);
  });
}

describe('Scenario review display and export', () => {
  it('does not select a winner or calculate savings from provisional amounts, including CSV', async () => {
    const createObjectURL = vi.fn((_blob: Blob) => 'blob:review-export');
    Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: createObjectURL });
    Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: vi.fn() });
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
    renderComparison(true);
    const table = await screen.findByRole('table');
    expect(screen.getByText(/Есть предварительные или неполные расчёты/)).toBeInTheDocument();
    expect(screen.queryByText('Лучший:')).not.toBeInTheDocument();
    expect(screen.queryByText(/экономия vs худший/)).not.toBeInTheDocument();
    expect(within(table).getByText('Предварительная сумма')).toBeInTheDocument();
    for (const row of within(table).getAllByRole('row').slice(1)) {
      expect(row).not.toHaveClass('bg-emerald-50');
      expect(within(row).getAllByRole('cell').at(-1)).toHaveTextContent('—');
    }
    fireEvent.click(screen.getByRole('button', { name: 'Экспорт CSV' }));
    const csv = await readBlob(createObjectURL.mock.calls[0][0] as Blob);
    expect(csv).toContain('Статус платежей;Предварительная сумма;Причина;Сравнение завершено');
    expect(csv).toContain("'=1+1;8509400000;IN;1000;2420;100;0;3520;;REVIEW_REQUIRED;true;");
    expect(csv).toContain('"Не проверено; ""происхождение""";false');
    expect(csv).not.toContain(';1200;');
  });

  it('keeps normal ranking and savings for completed scenarios', async () => {
    renderComparison(false);
    await screen.findByRole('table');
    expect(screen.getByText('Лучший:')).toBeInTheDocument();
    expect(screen.getByText(/экономия vs худший/)).toBeInTheDocument();
    expect(screen.queryByText('Предварительная сумма')).not.toBeInTheDocument();
    expect(screen.getByText('ИТОГО')).toBeInTheDocument();
  });
});
