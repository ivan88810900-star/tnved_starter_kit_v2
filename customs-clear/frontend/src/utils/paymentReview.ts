import type { CalculatorTariffPreference } from '../types/api.types';

export type PaymentReviewState = {
  status?: string | null;
  payments_status?: string | null;
  payment_status?: string | null;
  amounts_provisional?: boolean | null;
  payment_review_reason?: string | null;
  payment_review_reasons?: string[];
  tariff_preference?: CalculatorTariffPreference | null;
  preference?: CalculatorTariffPreference | null;
};

/** Keep review state visible even if a partially upgraded response omits one flag. */
export function hasProvisionalPayments(value?: PaymentReviewState | null): boolean {
  return value?.amounts_provisional === true
    || [value?.status, value?.payments_status, value?.payment_status].includes('REVIEW_REQUIRED')
    || (value?.tariff_preference ?? value?.preference)?.status === 'needs_review';
}

export const PAYMENT_REVIEW_MESSAGE =
  'Суммы предварительные. Итог к уплате требует проверки источников ставок и условий расчёта.';

/** An old payload without this flag cannot establish that its recorded total is final. */
export function paymentAmountNote(value?: PaymentReviewState | null): string | null {
  if (hasProvisionalPayments(value)) return 'Предварительно: требуется проверка';
  if (value?.amounts_provisional == null) return 'Статус проверки суммы не сохранён';
  const status = value.payment_status ?? value.payments_status ?? value.status;
  return status && status !== 'OK' ? 'Расчёт не завершён' : null;
}
