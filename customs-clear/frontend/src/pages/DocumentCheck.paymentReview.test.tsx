import React from 'react';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { DocumentCheck } from './DocumentCheck';
import { api } from '../api/client';

vi.mock('../api/client', () => ({ api: { get: vi.fn(), post: vi.fn() } }));
afterEach(() => vi.restoreAllMocks());

const preference = { applied: false, status: 'needs_review', reason: 'Происхождение не проверено.' };
const input = {
  status: 'WARNING', ved_intel_status: 'OK', items: [], checks: [], summary: { errors: 0, warnings: 1, passed: 0 },
  copilot_batch: { bundles: [
    { effective_hs_code: '8509400000', payment: { status: 'REVIEW_REQUIRED', amounts_provisional: true, tariff_preference: preference, breakdown: { total_payable: 35200 } } },
    { effective_hs_code: '8509400001', payment: { status: 'REVIEW_REQUIRED', amounts_provisional: true, payment_review_reason: 'Отсутствует источник ставки.', payment_review_reasons: ['duty_source_missing'], breakdown: { total_payable: 22000 } } },
    { effective_hs_code: '8509400002', payment: { breakdown: { total_payable: 10000 } } },
    { effective_hs_code: '8509400003', payment: { status: 'OK', amounts_provisional: false, breakdown: { total_payable: 0 } } },
  ] },
};

function readBlob(blob: Blob): Promise<string> {
  return new Promise((resolve) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result));
    reader.readAsText(blob);
  });
}

describe('Document analysis payment provenance', () => {
  it('keeps per-position pending, unknown and normal status in the table and JSON/PDF requests', async () => {
    vi.mocked(api.post).mockImplementation(async (url) => ({ data: url === '/documents/ved-report-pdf' ? '%PDF-test' : input }));
    const createObjectURL = vi.fn((_blob: Blob) => 'blob:document-export');
    Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: createObjectURL });
    Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: vi.fn() });
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
    const { container } = render(<DocumentCheck />);
    fireEvent.change(container.querySelector('input[type="file"]')!, {
      target: { files: [new File(['description,total\nitem,100000'], 'invoice.csv', { type: 'text/csv' })] },
    });
    const start = await screen.findByRole('button', { name: 'Запустить ВЭД-аналитика' });
    await waitFor(() => expect(start).toBeEnabled());
    fireEvent.click(start);
    const table = await screen.findByRole('table');
    expect(within(table).getAllByText('Предварительно: требуется проверка')).toHaveLength(2);
    expect(within(table).getByText('Статус проверки суммы не сохранён')).toBeInTheDocument();
    expect(within(table).getByText('Расчёт выполнен')).toBeInTheDocument();
    expect(within(table).getByText('Отсутствует источник ставки.')).toBeInTheDocument();
    expect(within(table).getByText('Происхождение не проверено.')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Скачать отчёт (данные)' }));
    const json = JSON.parse(await readBlob(createObjectURL.mock.calls[0][0]));
    const expectedPositions = [
      expect.objectContaining({ effective_hs_code: '8509400000', total_payable: 35200, payment_status: 'REVIEW_REQUIRED', amounts_provisional: true, tariff_preference: preference, tariff_preference_warning: preference.reason }),
      expect.objectContaining({ effective_hs_code: '8509400001', total_payable: 22000, amounts_provisional: true, payment_review_reason: 'Отсутствует источник ставки.', payment_review_reasons: ['duty_source_missing'], tariff_preference: null, tariff_preference_warning: null }),
      expect.objectContaining({ effective_hs_code: '8509400002', total_payable: 10000, payment_status: null, amounts_provisional: null }),
      expect.objectContaining({ effective_hs_code: '8509400003', total_payable: 0, payment_status: 'OK', amounts_provisional: false }),
    ];
    expect(json.copilot_positions).toEqual(expectedPositions);
    fireEvent.click(screen.getByRole('button', { name: 'Скачать отчёт PDF' }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/documents/ved-report-pdf', expect.objectContaining({ copilot_positions: expectedPositions }), { responseType: 'blob' }));
  });
});
