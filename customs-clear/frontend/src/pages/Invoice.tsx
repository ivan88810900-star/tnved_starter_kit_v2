import React, { useCallback, useState } from 'react';
import { api } from '../api/client';
import { getUserFacingApiError } from '../api/error';
import { PackingListUploader } from '../components/PackingListUploader';
import { PageHeader } from '../components/PageHeader';
import { hasProvisionalPayments, paymentAmountNote, type PaymentReviewState } from '../utils/paymentReview';

type InvoiceLine = PaymentReviewState & {
  tariff_preference_warning?: string | null;
  description: string;
  hs_code: string;
  customs_value: number;
  currency: string;
  duty: number;
  vat: number;
  rop: { total_rop_rub?: number };
  total_payable: number;
};

type BatchResult = PaymentReviewState & {
  tariff_preference_warning?: string | null;
  lines: InvoiceLine[];
  totals: PaymentReviewState & { total_payable: number; tariff_preference_warning?: string | null };
};

export function InvoicePage() {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [result, setResult] = useState<BatchResult | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const totalNeedsReview = result != null && (paymentAmountNote(result.totals) != null || paymentAmountNote(result) != null || result.lines.some((line) => paymentAmountNote(line) != null));
  const totalLabel = totalNeedsReview ? 'Предварительная сумма' : 'ИТОГО';

  const onFile = useCallback(async (file: File) => {
    setError('');
    setLoading(true);
    try {
      const fd = new FormData();
      fd.append('file', file);
      const { data } = await api.post<BatchResult>('/invoice/upload?auto_classify=true', fd, {
        headers: { 'Content-Type': 'multipart/form-data' },
      });
      setResult(data);
    } catch (e) {
      setError(getUserFacingApiError(e));
    } finally {
      setLoading(false);
    }
  }, []);

  const onDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);
    const f = e.dataTransfer.files?.[0];
    if (f) void onFile(f);
  };

  const downloadTemplate = async () => {
    const res = await api.get('/invoice/template', { responseType: 'blob' });
    const url = URL.createObjectURL(res.data);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'invoice_template.xlsx';
    a.click();
    URL.revokeObjectURL(url);
  };

  const exportExcel = () => {
    if (!result?.lines?.length) return;
    const header = ['Описание', 'HS', 'Стоимость', 'Валюта', 'Пошлина', 'НДС', 'РОП', 'Сумма', 'Статус платежей', 'Предварительная сумма', 'Примечание', 'Причина', 'Причины проверки (коды)'];
    const rows = result.lines.map((ln) => [
      ln.description,
      ln.hs_code || '',
      String(ln.customs_value),
      ln.currency,
      String(ln.duty),
      String(ln.vat),
      String(ln.rop?.total_rop_rub || 0),
      String(ln.total_payable),
      ln.payment_status ?? ln.payments_status ?? ln.status ?? '',
      hasProvisionalPayments(ln) ? 'true' : ln.amounts_provisional == null ? '' : String(ln.amounts_provisional),
      paymentAmountNote(ln) ?? '',
      ln.payment_review_reason ?? ln.tariff_preference_warning ?? ln.tariff_preference?.reason ?? '',
      (ln.payment_review_reasons ?? []).join(', '),
    ]);
    rows.push([totalLabel, '', '', '', '', '', '', String(result.totals.total_payable),
      result.payment_status ?? result.payments_status ?? result.status ?? '',
      result.amounts_provisional == null ? '' : String(result.amounts_provisional),
      totalNeedsReview ? 'Есть предварительные суммы или суммы без сохранённого статуса проверки' : '',
      result.payment_review_reason ?? result.tariff_preference_warning ?? result.totals.payment_review_reason ?? result.totals.tariff_preference_warning ?? '',
      (result.payment_review_reasons ?? result.totals.payment_review_reasons ?? []).join(', '),
    ]);
    const escapeCell = (value: string) => {
      const safe = /^[=+@\-\t\r]/.test(value) ? "'" + value : value;
      return '"' + safe.replaceAll('"', '""') + '"';
    };
    const csv = [header, ...rows].map((row) => row.map(escapeCell).join(';')).join('\n');
    const blob = new Blob(['\ufeff' + csv], { type: 'text/csv;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'invoice_calculation.csv';
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="space-y-8">
      <PageHeader title="Инвойс и пакинг-лист" />

      <section className="space-y-4">
        <h2 className="text-base font-medium text-cargo-deep">Расчёт по инвойсу</h2>
        <div className="flex flex-wrap gap-2">
          <button type="button" className="cc-btn-secondary" onClick={() => void downloadTemplate()}>
            Скачать шаблон Excel
          </button>
        </div>

        <div
          className={`cc-dropzone ${dragOver ? 'border-cargo-trust bg-cargo-trust-light' : ''}`}
          onDragOver={(e) => {
            e.preventDefault();
            setDragOver(true);
          }}
          onDragLeave={() => setDragOver(false)}
          onDrop={onDrop}
        >
          <p className="text-sm text-cargo-mid">Перетащите файл .xlsx / .csv или выберите вручную</p>
          <input
            type="file"
            accept=".xlsx,.xls,.csv"
            className="mt-3 text-sm"
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) void onFile(f);
            }}
          />
        </div>

        {loading ? (
          <div className="flex items-center gap-2 text-sm text-cargo-mid">
            <span className="cc-spinner" /> Расчёт платежей…
          </div>
        ) : null}
        {error ? <p className="text-sm text-cargo-alert">{error}</p> : null}

        {result ? (
          <div className="space-y-2">
            <button type="button" className="cc-btn-secondary text-sm" onClick={exportExcel}>
              Экспорт в Excel (CSV)
            </button>
            {totalNeedsReview ? <p role="status" className="text-sm text-amber-800">В расчёте есть предварительные суммы или суммы без сохранённого статуса проверки. Итог к уплате не подтверждён.</p> : null}
            <div className="overflow-x-auto rounded-lg border border-cargo-border bg-cargo-surface">
              <table className="min-w-[720px] w-full text-left text-sm">
                <thead className="bg-cargo-cloud text-[11px] uppercase tracking-[0.06em] text-cargo-light">
                  <tr>
                    <th className="px-3 py-2">Описание</th>
                    <th className="px-3 py-2">HS</th>
                    <th className="px-3 py-2">Стоимость</th>
                    <th className="px-3 py-2">Пошлина</th>
                    <th className="px-3 py-2">НДС</th>
                    <th className="px-3 py-2">РОП</th>
                    <th className="px-3 py-2">Сумма</th>
                    <th className="px-3 py-2">Статус платежей</th>
                  </tr>
                </thead>
                <tbody>
                  {result.lines.map((ln, i) => (
                    <tr key={i} className={`border-t border-cargo-border ${i % 2 ? 'bg-cargo-cloud' : 'bg-cargo-surface'}`}>
                      <td className="px-3 py-2 text-cargo-deep">{ln.description}</td>
                      <td className="px-3 py-2 font-mono text-cargo-trust">{ln.hs_code || '—'}</td>
                      <td className="px-3 py-2">{ln.customs_value.toLocaleString('ru-RU')} {ln.currency}</td>
                      <td className="px-3 py-2">{Number(ln.duty).toLocaleString('ru-RU')}</td>
                      <td className="px-3 py-2">{Number(ln.vat).toLocaleString('ru-RU')}</td>
                      <td className="px-3 py-2">{Number(ln.rop?.total_rop_rub || 0).toLocaleString('ru-RU')}</td>
                      <td className="px-3 py-2 font-medium">{Number(ln.total_payable).toLocaleString('ru-RU')}</td>
                      <td className="px-3 py-2">
                        <span className={paymentAmountNote(ln) ? 'text-amber-800' : ''}>{paymentAmountNote(ln) ?? 'Расчёт выполнен'}</span>
                        {(ln.payment_review_reason ?? ln.tariff_preference_warning ?? ln.tariff_preference?.reason) ? <span className="block text-amber-800">{ln.payment_review_reason ?? ln.tariff_preference_warning ?? ln.tariff_preference?.reason}</span> : null}
                      </td>
                    </tr>
                  ))}
                </tbody>
                <tfoot className="bg-cargo-deep font-medium text-white">
                  <tr>
                    <td className="px-3 py-2" colSpan={6}>
                      {totalLabel}
                    </td>
                    <td className="px-3 py-2">{Number(result.totals.total_payable).toLocaleString('ru-RU')} ₽</td>
                    <td className="px-3 py-2">{result.payment_review_reason ?? result.tariff_preference_warning ?? result.totals.payment_review_reason ?? result.totals.tariff_preference_warning}</td>
                  </tr>
                </tfoot>
              </table>
            </div>
          </div>
        ) : null}
      </section>

      <section className="space-y-4 border-t border-cargo-border pt-8">
        <h2 className="text-base font-medium text-cargo-deep">Классификация пакинг-листа</h2>
        <p className="text-sm text-cargo-mid">
          Загрузите пакинг-лист .xlsx — AI определит коды ТН ВЭД по названиям на китайском и фотографиям товаров
        </p>
        <PackingListUploader />
      </section>
    </div>
  );
}
