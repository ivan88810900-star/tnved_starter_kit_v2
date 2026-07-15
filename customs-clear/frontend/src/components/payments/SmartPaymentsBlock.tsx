import React from 'react';
import { AlertTriangle, Calculator, CheckCircle2, ExternalLink, Info, ShieldAlert } from 'lucide-react';
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

const WARNING_CLASS = {
  info: 'border-blue-200 bg-blue-50 text-blue-900',
  warning: 'border-amber-200 bg-amber-50 text-amber-900',
  error: 'border-red-200 bg-red-50 text-red-900',
} as const;

function formatRub(value: number | null | undefined): string {
  if (value == null) return '—';
  return `${value.toLocaleString('ru-RU', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} ₽`;
}

function formatRateLabel(raw?: string | null): string | null {
  if (!raw?.trim()) return null;
  const m = /^([\d.,]+)\s*%$/.exec(raw.trim());
  if (m) {
    const n = parseFloat(m[1].replace(',', '.'));
    if (Number.isFinite(n)) {
      return `${Number.isInteger(n) ? n : parseFloat(n.toFixed(1))}%`;
    }
  }
  return raw.replace(/\.0(?=%)/, '%');
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
    const countryCode = country.trim().toUpperCase();
    if (countryCode && !/^[A-Z]{2}$/.test(countryCode)) {
      setError('Страна происхождения указывается двумя латинскими буквами, например CN или DE.');
      return;
    }
    const parsedQuantity = quantity.trim() ? parseFloat(quantity.replace(',', '.')) : null;
    if (parsedQuantity != null && (!Number.isFinite(parsedQuantity) || parsedQuantity <= 0)) {
      setError('Количество должно быть числом больше 0.');
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const payload = {
        hs_code: hsCode,
        customs_value: value,
        invoice_currency: currency.trim().toUpperCase() || 'RUB',
        country: countryCode || null,
        description: description?.trim() || null,
        quantity: parsedQuantity,
      };
      const result = await fetchPaymentQuote(payload);
      if (import.meta.env.DEV && result.warnings.length > 0) {
        console.warn('[SmartPayments]', result.warnings);
      }
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
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <Calculator className="h-5 w-5 text-blue-700" aria-hidden />
            <h3 className="text-sm font-bold uppercase tracking-wide text-blue-800">Расчёт платежей</h3>
          </div>
          <span className="rounded-full border border-blue-200 bg-white px-2.5 py-1 text-[10px] font-semibold uppercase tracking-wide text-blue-700">
            Предварительный расчёт
          </span>
        </div>
        <p className="mb-4 text-xs text-slate-600">
          Пошлина, НДС, таможенный сбор, акциз и торговые меры — с формулой, статусом и источником каждой строки.
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
            <span className="mb-1 block font-medium text-slate-700">Страна происхождения</span>
            <input
              type="text"
              maxLength={2}
              placeholder="CN"
              value={country}
              onChange={(e) => setCountry(e.target.value.toUpperCase())}
              className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm uppercase"
            />
            <span className="mt-1 block text-[10px] text-slate-500">ISO-2, например CN или DE</span>
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
          {quote.status === 'EMBARGO' ? (
            <div className="flex gap-3 rounded-xl border border-red-300 bg-red-50 px-4 py-3 text-sm text-red-900">
              <ShieldAlert className="mt-0.5 h-5 w-5 shrink-0" aria-hidden />
              <div>
                <p className="font-semibold">Расчёт заблокирован ограничением на ввоз</p>
                <p className="mt-1 text-xs">Проверьте страну происхождения и нормативное основание в предупреждениях ниже.</p>
              </div>
            </div>
          ) : null}

          <div className="grid gap-3 sm:grid-cols-3">
            <div className="rounded-xl border border-slate-200 bg-white px-4 py-3">
              <p className="text-[10px] font-semibold uppercase tracking-wide text-slate-500">Таможенная стоимость</p>
              <p className="mt-1 font-mono text-base font-bold text-slate-900">{formatRub(quote.customs_value_rub)}</p>
            </div>
            <div className="rounded-xl border border-slate-200 bg-white px-4 py-3">
              <p className="text-[10px] font-semibold uppercase tracking-wide text-slate-500">Качество подбора ставки</p>
              <p className="mt-1 flex items-center gap-1.5 text-sm font-semibold text-slate-900">
                {String(quote.data_quality?.confidence ?? '').toLowerCase() === 'high' ? (
                  <CheckCircle2 className="h-4 w-4 text-emerald-600" aria-hidden />
                ) : (
                  <AlertTriangle className="h-4 w-4 text-amber-600" aria-hidden />
                )}
                {String(quote.data_quality?.confidence ?? 'не указано') === 'high' ? 'Высокое' : String(quote.data_quality?.confidence ?? 'Не указано')}
              </p>
              {quote.data_quality?.matched_prefix ? (
                <p className="mt-1 font-mono text-[10px] text-slate-500">Совпадение: {String(quote.data_quality.matched_prefix)}</p>
              ) : null}
            </div>
            <div className={`rounded-xl border px-4 py-3 ${quote.total_payable_rub == null ? 'border-amber-200 bg-amber-50' : 'border-emerald-200 bg-emerald-50'}`}>
              <p className="text-[10px] font-semibold uppercase tracking-wide text-slate-600">
                {quote.total_payable_rub == null ? 'Подтверждённая часть' : 'Итого к уплате'}
              </p>
              <p className="mt-1 font-mono text-base font-bold text-slate-900">
                {formatRub(quote.total_payable_rub ?? quote.total_partial_rub)}
              </p>
              {quote.total_payable_rub == null ? (
                <p className="mt-1 text-[10px] text-amber-800">Окончательный итог требует проверки неопределённых строк.</p>
              ) : null}
            </div>
          </div>

          <div className="overflow-x-auto rounded-xl border border-slate-200">
            <table className="w-full min-w-[480px] text-sm">
              <thead className="bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
                <tr>
                  <th className="px-4 py-2 font-semibold">Платёж</th>
                  <th className="px-4 py-2 font-semibold">Статус</th>
                  <th className="px-4 py-2 text-right font-semibold">Сумма</th>
                </tr>
              </thead>
              <tbody>
                {quote.line_items.map((item) => {
                  const rateLabel = formatRateLabel(item.rate_label);
                  return (
                    <tr key={item.code} className="border-t border-slate-100">
                      <td className="px-4 py-3 align-top">
                        <p className="font-medium text-slate-900">{item.label}</p>
                        {rateLabel ? (
                          <p className="mt-0.5 text-[11px] text-slate-500">Ставка: {rateLabel}</p>
                        ) : null}
                        <details className="mt-2 max-w-xl text-xs text-slate-600">
                          <summary className="cursor-pointer select-none font-medium text-blue-700 hover:text-blue-800">
                            Как рассчитано и на каком основании
                          </summary>
                          <div className="mt-2 space-y-1.5 rounded-lg border border-slate-100 bg-slate-50 px-3 py-2">
                            {item.basis_label ? (
                              <p>
                                <span className="font-semibold text-slate-700">База:</span> {item.basis_label}
                                {item.basis_amount_rub != null ? ` — ${formatRub(item.basis_amount_rub)}` : ''}
                              </p>
                            ) : null}
                            {item.reason ? (
                              <p><span className="font-semibold text-slate-700">Причина:</span> {item.reason}</p>
                            ) : null}
                            {item.source ? (
                              <p><span className="font-semibold text-slate-700">Источник:</span> {item.source}</p>
                            ) : null}
                          </div>
                        </details>
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
                  );
                })}
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
            <section className="rounded-xl border border-slate-200 bg-slate-50 px-4 py-3">
              <div className="mb-2 flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-slate-600">
                <Info className="h-4 w-4" aria-hidden />
                Исходные данные и допущения
              </div>
              <dl className="grid gap-x-6 gap-y-2 sm:grid-cols-2 lg:grid-cols-3">
                {quote.assumptions.map((item) => (
                  <div key={item.key} className="flex items-baseline justify-between gap-3 border-b border-slate-200 py-1 text-xs">
                    <dt className="text-slate-500">{item.label}</dt>
                    <dd className="text-right font-medium text-slate-800">{item.value}</dd>
                  </div>
                ))}
              </dl>
            </section>
          ) : null}

          {quote.warnings.length > 0 ? (
            <section className="space-y-2" aria-label="Предупреждения расчёта">
              {quote.warnings.map((warning) => (
                <div key={warning.code} className={`flex gap-2 rounded-xl border px-4 py-3 text-xs ${WARNING_CLASS[warning.severity]}`}>
                  {warning.severity === 'info' ? (
                    <Info className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
                  ) : (
                    <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
                  )}
                  <div>
                    <p>{warning.message}</p>
                    {warning.code === 'trade_remedies_disclaimer' ? (
                      <a
                        href="https://remedies.eaeunion.org/dimd/ru"
                        target="_blank"
                        rel="noreferrer"
                        className="mt-1 inline-flex items-center gap-1 font-semibold underline"
                      >
                        Реестр мер защиты рынка ЕАЭС
                        <ExternalLink className="h-3 w-3" aria-hidden />
                      </a>
                    ) : null}
                  </div>
                </div>
              ))}
            </section>
          ) : null}

          <p className="text-[11px] leading-relaxed text-slate-500">
            Расчёт носит предварительный характер. Итог зависит от подтверждённого кода ТН ВЭД, таможенной стоимости,
            страны происхождения, количества и действующих на дату декларирования мер.
          </p>
        </div>
      ) : loading ? (
        <p className="text-sm text-slate-500">Формирование расчёта платежей…</p>
      ) : null}
    </div>
  );
};
