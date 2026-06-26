import React, { useCallback, useState } from 'react';
import { useDropzone } from 'react-dropzone';
import { CloudUpload, FileSpreadsheet, Loader2, Sparkles } from 'lucide-react';
import { api } from '../../api/client';
import { getUserFacingApiError } from '../../api/error';
import type { InvoiceAnalyzeItem, InvoiceAnalyzeResponse } from '../../types/api.types';
import { requestCalculatorPrefill } from '../../store/calculatorPrefillBridge';

export const CalculatorInvoiceAnalyzeSection: React.FC = () => {
  const [analyzing, setAnalyzing] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [preview, setPreview] = useState<InvoiceAnalyzeItem[] | null>(null);
  const [applyBusy, setApplyBusy] = useState<number | null>(null);

  const runAnalyze = useCallback(async (file: File) => {
    setAnalyzing(true);
    setErr(null);
    setPreview(null);
    const form = new FormData();
    form.append('file', file);
    try {
      const { data } = await api.post<InvoiceAnalyzeResponse>('/v1/documents/analyze', form, {
        headers: { 'Content-Type': 'multipart/form-data' },
      });
      if (data.status !== 'OK') {
        setErr(data.error || 'Не удалось разобрать документ.');
        setPreview(Array.isArray(data.items) ? data.items : []);
        return;
      }
      const items = data.items || [];
      if (items.length === 0) {
        setErr('ИИ не нашёл товарных строк в файле. Попробуйте другой документ или более чёткое изображение.');
        setPreview([]);
        return;
      }
      setPreview(items);
    } catch (e) {
      setErr(getUserFacingApiError(e, 'Ошибка при загрузке или анализе файла.'));
      setPreview(null);
    } finally {
      setAnalyzing(false);
    }
  }, []);

  const onDrop = useCallback(
    (accepted: File[]) => {
      const f = accepted[0];
      if (f) void runAnalyze(f);
    },
    [runAnalyze],
  );

  const dz = useDropzone({
    onDrop,
    disabled: analyzing,
    maxFiles: 1,
    accept: {
      'application/pdf': ['.pdf'],
      'image/png': ['.png'],
      'image/jpeg': ['.jpg', '.jpeg'],
      'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': ['.xlsx'],
      'application/vnd.ms-excel': ['.xls'],
      'text/csv': ['.csv'],
      'application/csv': ['.csv'],
    },
  });

  const fmtMoney = (n: number, cur: string) =>
    `${n.toLocaleString('ru-RU', { minimumFractionDigits: 0, maximumFractionDigits: 2 })} ${cur}`;

  return (
    <div className="cc-card-soft space-y-3 p-4">
      <div className="flex flex-wrap items-center gap-2">
        <Sparkles className="h-4 w-4 text-indigo-600" aria-hidden />
        <span className="text-[11px] font-semibold uppercase tracking-[0.14em] text-slate-500">
          Инвойс → строки (ИИ)
        </span>
      </div>
      <div className="relative">
        <div
          {...dz.getRootProps()}
          className={`cc-dropzone relative min-h-[140px] ${analyzing ? 'pointer-events-none' : ''}`}
        >
          <input {...dz.getInputProps()} />
          <div className="mx-auto mb-2 flex items-center justify-center gap-3 text-indigo-500">
            <CloudUpload className="h-10 w-10 shrink-0" aria-hidden />
            <span className="inline-flex shrink-0" aria-label="Поддержка Excel и CSV">
              <FileSpreadsheet className="h-10 w-10 text-emerald-600" aria-hidden />
            </span>
          </div>
          <p className="text-[13px] font-medium text-slate-800">Перетащите файл сюда или нажмите для выбора</p>
          <p className="mt-1 text-[11px] text-slate-500">
            .pdf · .png · .jpg · <span className="font-medium text-emerald-700">.xlsx · .xls</span> · .csv — до 15 МБ
          </p>
        </div>
        {analyzing ? (
          <div className="absolute inset-0 z-10 flex flex-col items-center justify-center rounded-2xl bg-white/88 backdrop-blur-[2px]">
            <Loader2 className="h-8 w-8 animate-spin text-indigo-600" aria-hidden />
            <p className="mt-3 text-[13px] font-medium text-slate-800">ИИ анализирует документ…</p>
            <p className="mt-1 max-w-sm text-center text-[11px] text-slate-500">Извлечение таблицы товаров и кодов ТН ВЭД</p>
          </div>
        ) : null}
      </div>

      {err ? (
        <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-[12px] text-amber-900">{err}</div>
      ) : null}

      {preview && preview.length > 0 ? (
        <div className="overflow-x-auto rounded-xl border border-slate-200 bg-white">
          <table className="w-full min-w-[520px] border-collapse text-left text-[12px]">
            <thead>
              <tr className="border-b border-slate-200 bg-slate-50 text-[10px] font-semibold uppercase tracking-wider text-slate-500">
                <th className="px-3 py-2">Товар</th>
                <th className="px-3 py-2">Предложенный ТН ВЭД</th>
                <th className="px-3 py-2">Стоимость</th>
                <th className="px-3 py-2 w-[1%] whitespace-nowrap" />
              </tr>
            </thead>
            <tbody>
              {preview.map((row, idx) => (
                <tr key={`${row.suggested_hs_code}-${idx}`} className="border-b border-slate-100 last:border-0">
                  <td className="px-3 py-2 text-slate-800">{row.name}</td>
                  <td className="cc-mono px-3 py-2 text-indigo-800">{row.suggested_hs_code}</td>
                  <td className="px-3 py-2 tabular-nums text-slate-700">{fmtMoney(row.price, row.currency)}</td>
                  <td className="px-3 py-2">
                    <button
                      type="button"
                      className="cc-btn-primary whitespace-nowrap px-3 py-1.5 text-[11px]"
                      disabled={applyBusy === idx}
                      onClick={() => {
                        setApplyBusy(idx);
                        requestCalculatorPrefill({
                          hs_code: row.suggested_hs_code,
                          customs_value: row.price,
                          invoice_currency: row.currency || 'RUB',
                          net_weight_kg: row.net_weight_kg,
                        });
                        window.setTimeout(() => setApplyBusy(null), 800);
                      }}
                    >
                      {applyBusy === idx ? '…' : 'Применить в калькулятор'}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </div>
  );
};
