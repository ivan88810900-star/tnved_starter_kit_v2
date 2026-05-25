import { api } from './client';

export type PaymentLineStatus =
  | 'applied'
  | 'not_applicable'
  | 'manual_override'
  | 'manual_review_required'
  | 'unknown'
  | 'not_configured'
  | 'embargo';

export type PaymentQuoteLineItem = {
  code: string;
  label: string;
  amount_rub: number | null;
  status: PaymentLineStatus;
  reason: string;
  source: string;
  rate_label?: string | null;
};

export type PaymentQuoteWarning = {
  code: string;
  message: string;
  severity: 'info' | 'warning' | 'error';
};

export type PaymentQuoteAssumption = {
  key: string;
  label: string;
  value: string;
};

export type PaymentQuoteRequest = {
  hs_code: string;
  customs_value: number;
  invoice_currency?: string;
  freight?: number;
  insurance?: number | null;
  country?: string | null;
  quantity?: number | null;
  net_weight_kg?: number | null;
  apply_reduced_vat?: boolean;
  description?: string | null;
};

export type PaymentQuoteResponse = {
  status: string;
  hs_code: string;
  country?: string | null;
  description?: string | null;
  customs_value_rub: number;
  invoice_currency: string;
  line_items: PaymentQuoteLineItem[];
  total_payable_rub: number | null;
  total_partial_rub: number | null;
  warnings: PaymentQuoteWarning[];
  assumptions: PaymentQuoteAssumption[];
  data_quality?: Record<string, unknown> | null;
  sources?: Array<Record<string, unknown>>;
  legal_basis?: Record<string, string> | null;
  geo?: Record<string, unknown> | null;
};

export async function fetchPaymentQuote(payload: PaymentQuoteRequest): Promise<PaymentQuoteResponse> {
  const { data } = await api.post<PaymentQuoteResponse>('/payments/quote', payload);
  return data;
}
