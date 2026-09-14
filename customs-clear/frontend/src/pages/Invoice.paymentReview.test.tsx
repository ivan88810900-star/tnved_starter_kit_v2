import React from 'react';
import { fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { InvoicePage } from './Invoice';
import { api } from '../api/client';

vi.mock('../api/client', () => ({ api: { get: vi.fn(), post: vi.fn() } }));
vi.mock('../components/PackingListUploader', () => ({ PackingListUploader: () => null }));
afterEach(() => vi.restoreAllMocks());

function readBlob(blob: Blob): Promise<string> {
  return new Promise((resolve) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result));
    reader.readAsText(blob);
  });
}

async function upload(lines: object[], metadata: object = {}) {
  vi.mocked(api.post).mockResolvedValue({ data: { ...metadata, lines, totals: { ...metadata, total_payable: 15000 } } });
  const { container } = render(<InvoicePage />);
  fireEvent.change(container.querySelector('input[type="file"]')!, { target: { files: [new File(['invoice'], 'invoice.csv', { type: 'text/csv' })] } });
  return screen.findByRole('table');
}

const line = { description: 'Товар', hs_code: '8509400000', customs_value: 100000, currency: 'RUB', duty: 10000, vat: 4000, rop: { total_rop_rub: 0 }, total_payable: 15000 };

describe('Invoice review totals and CSV', () => {
  it('preserves pending and legacy unknown status in visible totals and CSV', async () => {
    const createObjectURL = vi.fn((_blob: Blob) => 'blob:invoice-export');
    Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: createObjectURL });
    Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: vi.fn() });
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
    const table = await upload([
      { ...line, description: '=1+1', payments_status: 'REVIEW_REQUIRED', amounts_provisional: true, payment_review_reason: 'Нет источника ставки; нужна проверка.' },
      { ...line, description: 'Старый расчёт' },
    ], { payment_status: 'REVIEW_REQUIRED', amounts_provisional: true });
    expect(within(table).getByText('Предварительная сумма')).toBeInTheDocument();
    expect(within(table).getByText('Предварительно: требуется проверка')).toBeInTheDocument();
    expect(within(table).getByText('Статус проверки суммы не сохранён')).toBeInTheDocument();
    expect(within(table).getByText('Нет источника ставки; нужна проверка.')).toBeInTheDocument();
    expect(within(table).queryByText('ИТОГО')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Экспорт в Excel (CSV)' }));
    const csv = await readBlob(createObjectURL.mock.calls[0][0]);
    expect(csv).toContain('"Статус платежей";"Предварительная сумма"');
    expect(csv).toContain('"\'=1+1"');
    expect(csv).toContain('"REVIEW_REQUIRED";"true";"Предварительно: требуется проверка";"Нет источника ставки; нужна проверка."');
    expect(csv).toContain('"Статус проверки суммы не сохранён"');
    expect(csv).toContain('"Предварительная сумма";"";"";');
  });

  it('retains a final total label only with explicit nonprovisional line and aggregate metadata', async () => {
    const table = await upload([{ ...line, payments_status: 'OK', amounts_provisional: false }], { payment_status: 'OK', amounts_provisional: false });
    expect(within(table).getByText('ИТОГО')).toBeInTheDocument();
    expect(screen.queryByText('Предварительная сумма')).not.toBeInTheDocument();
  });
});
