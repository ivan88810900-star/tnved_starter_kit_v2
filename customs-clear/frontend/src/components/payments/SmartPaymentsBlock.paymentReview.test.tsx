import React from 'react';
import { render, screen, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { SmartPaymentsBlock } from './SmartPaymentsBlock';
import { fetchPaymentQuote, type PaymentQuoteResponse } from '../../api/paymentQuote';

vi.mock('../../api/paymentQuote', () => ({ fetchPaymentQuote: vi.fn() }));

const base: PaymentQuoteResponse = {
  status: 'REVIEW_REQUIRED', hs_code: '8509400000', customs_value_rub: 100000,
  invoice_currency: 'RUB', total_payable_rub: null, total_partial_rub: 1000,
  warnings: [], assumptions: [], line_items: [
    { code: 'duty', label: 'Ввозная пошлина', amount_rub: null, status: 'manual_review_required', reason: 'Право на преференцию требует проверки', source: '' },
    { code: 'vat', label: 'НДС', amount_rub: null, status: 'manual_review_required', reason: 'НДС зависит от неопределённой пошлины', source: '' },
    { code: 'fee', label: 'Таможенный сбор', amount_rub: 1000, status: 'applied', reason: '', source: '' },
  ],
};

describe('Quote totals with uncertain eligibility', () => {
  it('keeps unknown duty and VAT separate from a known partial total', async () => {
    vi.mocked(fetchPaymentQuote).mockResolvedValue(base);
    render(<SmartPaymentsBlock hsCode="8509400000" />);
    const table = await screen.findByRole('table');
    const rows = within(table).getAllByRole('row');
    for (const row of rows.slice(1, 3)) {
      expect(within(row).getByText('Ручная проверка')).toBeInTheDocument();
      expect(within(row).getByTitle('Сумма не определена')).toHaveTextContent('—');
    }
    expect(within(table).getByText('не определено')).toBeInTheDocument();
    expect(screen.getByText('Подтверждённая часть')).toBeInTheDocument();
    expect(within(table).getByText(/частичная сумма:/)).toHaveTextContent(/1\s000,00 ₽/);
    expect(within(table).queryByText('0,00 ₽')).not.toBeInTheDocument();
  });

  it('renders an explicitly determined zero total as zero rather than unknown', async () => {
    vi.mocked(fetchPaymentQuote).mockResolvedValue({ ...base, status: 'OK', total_payable_rub: 0, total_partial_rub: 0,
      line_items: base.line_items.map((item) => ({ ...item, status: 'not_applicable', amount_rub: 0 })) });
    render(<SmartPaymentsBlock hsCode="8509400000" />);
    const table = await screen.findByRole('table');
    expect(within(table).queryByText('не определено')).not.toBeInTheDocument();
    expect(screen.queryByText('Подтверждённая часть')).not.toBeInTheDocument();
    expect(within(table).getAllByText('0,00 ₽')).toHaveLength(4);
  });
});
