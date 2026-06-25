import React, { useCallback, useState } from 'react';
import { api } from '../api/client';
import { getUserFacingApiError } from '../api/error';
import { PackingListUploader } from '../components/PackingListUploader';

type InvoiceLine = {
  description: string;
  hs_code: string;
  customs_value: number;
  currency: string;
  duty: number;
  vat: number;
  rop: { total_rop_rub?: number };
  total_payable: number;
};

type BatchResult = {
  lines: InvoiceLine[];
  totals: Record<string, number>;
};

export function InvoicePage() {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [result, setResult] = useState<BatchResult | null>(null);
  const [dragOver, setDragOver] = useState(false);

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
    const header = ['Описание', 'HS', 'Стоимость', 'Валюта', 'Пошлина', 'НДС', 'РОП', 'ИТОГО'];
    const rows = result.lines.map((ln) => [
      ln.description,
      ln.hs_code || '',
      String(ln.customs_value),
      ln.currency,
      String(ln.duty),
      String(ln.vat),
      String(ln.rop?.total_rop_rub || 0),
      String(ln.total_payable),
    ]);
    rows.push(['ИТОГО', '', '', '', '', '', '', String(result.totals.total_payable)]);
    const csv = [header, ...rows].map((r) => r.map((c) => `"${String(c).replace(/"/g, '""')}"`).join(';')).join('\n');
    const blob = new Blob(['\ufeff' + csv], { type: 'text/csv;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'invoice_calculation.csv';
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-2">
        <button type="button" className="cc-btn cc-btn-secondary" onClick={() => void downloadTemplate()}>
          Скачать шаблон Excel
        </button>
      </div>

      <div
        className={`rounded-xl border-2 border-dashed p-8 text-center transition-colors ${
          dragOver ? 'border-indigo-500 bg-indigo-50' : 'border-slate-300 bg-white'
        }`}
        onDragOver={(e) => {
          e.preventDefault();
          setDragOver(true);
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={onDrop}
      >
        <p className="text-sm text-slate-600">Перетащите файл .xlsx / .csv или выберите вручную</p>
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

      {loading ? <p className="text-sm text-slate-500">Расчёт платежей…</p> : null}
      {error ? <p className="text-sm text-red-600">{error}</p> : null}

      {result ? (
        <div className="space-y-2">
          <button type="button" className="cc-btn cc-btn-secondary text-sm" onClick={exportExcel}>
            Экспорт в Excel (CSV)
          </button>
        <div className="overflow-x-auto rounded-xl border border-slate-200 bg-white">
          <table className="min-w-[720px] w-full text-left text-sm">
            <thead className="bg-slate-50 text-xs uppercase text-slate-500">
              <tr>
                <th className="px-3 py-2">Описание</th>
                <th className="px-3 py-2">HS</th>
                <th className="px-3 py-2">Стоимость</th>
                <th className="px-3 py-2">Пошлина</th>
                <th className="px-3 py-2">НДС</th>
                <th className="px-3 py-2">РОП</th>
                <th className="px-3 py-2">ИТОГО</th>
              </tr>
            </thead>
            <tbody>
              {result.lines.map((ln, i) => (
                <tr key={i} className="border-t border-slate-100">
                  <td className="px-3 py-2">{ln.description}</td>
                  <td className="px-3 py-2 font-mono">{ln.hs_code || '—'}</td>
                  <td className="px-3 py-2">{ln.customs_value.toLocaleString('ru-RU')} {ln.currency}</td>
                  <td className="px-3 py-2">{Number(ln.duty).toLocaleString('ru-RU')}</td>
                  <td className="px-3 py-2">{Number(ln.vat).toLocaleString('ru-RU')}</td>
                  <td className="px-3 py-2">{Number(ln.rop?.total_rop_rub || 0).toLocaleString('ru-RU')}</td>
                  <td className="px-3 py-2 font-semibold">{Number(ln.total_payable).toLocaleString('ru-RU')}</td>
                </tr>
              ))}
            </tbody>
            <tfoot className="bg-slate-50 font-semibold">
              <tr>
                <td className="px-3 py-2" colSpan={6}>
                  ИТОГО
                </td>
                <td className="px-3 py-2">{Number(result.totals.total_payable).toLocaleString('ru-RU')} ₽</td>
              </tr>
            </tfoot>
          </table>
        </div>
        </div>
      ) : null}

      <section className="mt-8 border-t border-slate-200 pt-8">
        <h2 className="mb-4 text-xl font-semibold text-slate-900">Классификация пакинг-листа</h2>
        <p className="mb-4 text-sm text-gray-500">
          Загрузите пакинг-лист .xlsx — AI определит коды ТН ВЭД по названиям на китайском и фотографиям товаров
        </p>
        <PackingListUploader />
      </section>
    </div>
  );
}
