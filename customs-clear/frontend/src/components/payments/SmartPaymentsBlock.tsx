import React from 'react';
import { AlertTriangle, Calculator, Info } from 'lucide-react';
import {
  fetchPaymentQuote,
  type PaymentLineStatus,
  type PaymentQuoteLineItem,
  type PaymentQuoteResponse,
} from '../../api/paymentQuote';
import { getUserFacingApiError } from '../../api/error';

const STATUS_LABELS: Record<PaymentLineStatus, string> = {
  applied: 'Рассчитано',
  not_applicable: 'Не применяется',
  manual_override: 'Вручную',
  manual_review_required: 'Ручная проверка',
  unknown: 'Не определено',
  not_configured: 'Нет данных',
  embargo: 'Эмбарго',
};

const STATUS_CLASS: Record<PaymentLineStatus, string> = {
  applied: 'bg-emerald-50 text-emerald-800 border-emerald-200',
  not_applicable: 'bg-slate-50 text-slate-600 border-slate-200',
  manual_override: 'bg-blue-50 text-blue-800 border-blue-200',
  manual_review_required: 'bg-amber-50 text-amber-900 border-amber-200',
  unknown: 'bg-orange-50 text-orange-900 border-orange-200',
  not_configured: 'bg-gray-50 text-gray-700 border-gray-200',
  embargo: 'bg-red-50 text-red-800 border-red-200',
};

function formatRub(value: number | null | undefined): string {
  if (value == null) return '—';
  return `${value.toLocaleString('ru-RU', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} ₽`;
}

function LineAmount({ item }: { item: PaymentQuoteLineItem }) {
  const uncertain = ['manual_review_required', 'unknown', 'not_configured'].includes(item.status);
  if (uncertain) {
    return (
      <span className="font-mono text-sm font-semibold text-amber-800" title="Сумма не определена">
        —
      </span>
    );
  }
  return <span className="font-mono text-sm font-semibold text-gray-900">{formatRub(item.amount_rub)}</span>;
}

type Props = {
  hsCode: string;
  description?: string;
  className?: string;
};

export const SmartPaymentsBlock: React.FC<Props> = ({ hsCode, description, className }) => {
  const [customsValue, setCustomsValue] = React.useState('100000');
  const [currency, setCurrency] = React.useState('RUB');
  const [country, setCountry] = React.useState('');
  const [quantity, setQuantity] = React.useState('');
  const [loading, setLoading] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [quote, setQuote] = React.useState<PaymentQuoteResponse | null>(null);

  const loadQuote = React.useCallback(async () => {
    const value = parseFloat(customsValue.replace(/\s/g, '').replace(',', '.'));
    if (!Number.isFinite(value) || value <= 0) {
      setError('Укажите таможенную стоимость больше 0.');
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const payload = {
        hs_code: hsCode,
        customs_value: value,
        invoice_currency: currency.trim().toUpperCase() || 'RUB',
        country: country.trim().toUpperCase() || null,
        description: description?.trim() || null,
        quantity: quantity.trim() ? parseFloat(quantity.replace(',', '.')) : null,
      };
      const result = await fetchPaymentQuote(payload);
      setQuote(result);
    } catch (e: unknown) {
      setQuote(null);
      setError(getUserFacingApiError(e, 'Не удалось получить расчёт платежей.'));
    } finally {
      setLoading(false);
    }
  }, [hsCode, customsValue, currency, country, quantity, description]);

  React.useEffect(() => {
    setQuote(null);
    setError(null);
    void loadQuote();
  }, [hsCode]); // eslint-disable-line react-hooks/exhaustive-deps -- пересчёт при смене кода

  return (
    <div className={`space-y-4 ${className ?? ''}`}>
      <div className="rounded-xl border border-blue-100 bg-gradient-to-br from-blue-50 to-white px-4 py-4">
        <div className="mb-3 flex items-center gap-2">
          <Calculator className="h-5 w-5 text-blue-700" aria-hidden />
          <h3 className="text-sm font-bold uppercase tracking-wide text-blue-800">Smart Payments — расчёт платежей</h3>
        </div>
        <p className="mb-4 text-xs text-slate-600">
          Пошлина, НДС, таможенный сбор, акциз и торговые меры с явными статусами. Неопределённые суммы не показываются как ноль.
        </p>

        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <label className="block text-xs">
            <span className="mb-1 block font-medium text-slate-700">Таможенная стоимость</span>
            <input
              type="text"
              inputMode="decimal"
              value={customsValue}
              onChange={(e) => setCustomsValue(e.target.value)}
              className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm"
            />
          </label>
          <label className="block text-xs">
            <span className="mb-1 block font-medium text-slate-700">Валюта</span>
            <select
              value={currency}
              onChange={(e) => setCurrency(e.target.value)}
              className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm"
            >
              <option value="RUB">RUB</option>
              <option value="USD">USD</option>
              <option value="EUR">EUR</option>
              <option value="CNY">CNY</option>
            </select>
          </label>
          <label className="block text-xs">
            <span className="mb-1 block font-medium text-slate-700">Страна (ISO-2)</span>
            <input
              type="text"
              maxLength={2}
              placeholder="CN"
              value={country}
              onChange={(e) => setCountry(e.target.value.toUpperCase())}
              className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm uppercase"
            />
          </label>
          <label className="block text-xs">
            <span className="mb-1 block font-medium text-slate-700">Количество</span>
            <input
              type="text"
              inputMode="decimal"
              placeholder="1"
              value={quantity}
              onChange={(e) => setQuantity(e.target.value)}
              className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm"
            />
          </label>
        </div>

        <button
          type="button"
          onClick={() => void loadQuote()}
          disabled={loading}
          className="mt-3 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
        >
          {loading ? 'Расчёт…' : 'Рассчитать'}
        </button>
      </div>

      {error ? (
        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">{error}</div>
      ) : null}

      {quote ? (
        <div className="space-y-4">
          {quote.warnings.length > 0 ? (
            <ul className="space-y-2">
              {quote.warnings.map((w) => (
                <li
                  key={w.code}
                  className={`flex gap-2 rounded-lg border px-3 py-2 text-xs ${
                    w.severity === 'error'
                      ? 'border-red-200 bg-red-50 text-red-900'
                      : w.severity === 'info'
                        ? 'border-slate-200 bg-slate-50 text-slate-700'
                        : 'border-amber-200 bg-amber-50 text-amber-900'
                  }`}
                >
                  {w.severity === 'error' || w.severity === 'warning' ? (
                    <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
                  ) : (
                    <Info className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
                  )}
                  <span>{w.message}</span>
                </li>
              ))}
            </ul>
          ) : null}

          <div className="overflow-hidden rounded-xl border border-slate-200">
            <table className="w-full text-sm">
              <thead className="bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
                <tr>
                  <th className="px-4 py-2 font-semibold">Платёж</th>
                  <th className="px-4 py-2 font-semibold">Статус</th>
                  <th className="px-4 py-2 text-right font-semibold">Сумма</th>
                </tr>
              </thead>
              <tbody>
                {quote.line_items.map((item) => (
                  <tr key={item.code} className="border-t border-slate-100">
                    <td className="px-4 py-3 align-top">
                      <p className="font-medium text-slate-900">{item.label}</p>
                      {item.rate_label ? (
                        <p className="mt-0.5 text-[11px] text-slate-500">Ставка: {item.rate_label}</p>
                      ) : null}
                      {item.reason ? (
                        <p className="mt-1 text-[11px] leading-snug text-slate-600">{item.reason}</p>
                      ) : null}
                      {item.source ? (
                        <p className="mt-0.5 text-[10px] text-slate-400">Источник: {item.source}</p>
                      ) : null}
                    </td>
                    <td className="px-4 py-3 align-top">
                      <span
                        className={`inline-flex rounded-full border px-2 py-0.5 text-[10px] font-semibold ${STATUS_CLASS[item.status]}`}
                      >
                        {STATUS_LABELS[item.status]}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-right align-top">
                      <LineAmount item={item} />
                    </td>
                  </tr>
                ))}
              </tbody>
              <tfoot className="border-t-2 border-slate-200 bg-slate-50">
                <tr>
                  <td colSpan={2} className="px-4 py-3 font-semibold text-slate-800">
                    Итого к уплате
                  </td>
                  <td className="px-4 py-3 text-right font-mono text-base font-bold text-slate-900">
                    {quote.total_payable_rub != null ? (
                      formatRub(quote.total_payable_rub)
                    ) : (
                      <span className="text-sm font-normal text-amber-800" title="Есть неопределённые строки">
                        не определено
                        {quote.total_partial_rub != null ? (
                          <span className="mt-1 block text-[11px] font-normal text-slate-500">
                            частичная сумма: {formatRub(quote.total_partial_rub)}
                          </span>
                        ) : null}
                      </span>
                    )}
                  </td>
                </tr>
              </tfoot>
            </table>
          </div>

          {quote.assumptions.length > 0 ? (
            <details className="rounded-lg border border-slate-200 bg-white px-4 py-3">
              <summary className="cursor-pointer text-xs font-semibold uppercase tracking-wide text-slate-600">
                Допущения расчёта
              </summary>
              <dl className="mt-2 grid gap-2 sm:grid-cols-2">
                {quote.assumptions.map((a) => (
                  <div key={a.key} className="text-xs">
                    <dt className="text-slate-500">{a.label}</dt>
                    <dd className="font-medium text-slate-800">{a.value}</dd>
                  </div>
                ))}
              </dl>
            </details>
          ) : null}
        </div>
      ) : loading ? (
        <p className="text-sm text-slate-500">Формирование расчёта платежей…</p>
      ) : null}
    </div>
  );
};
