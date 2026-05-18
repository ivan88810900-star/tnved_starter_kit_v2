import type { AnalysisItem, MoneyBreakdown } from "../types";

export type InvoicePaymentTotals = {
  duty: number;
  vat: number;
  customsFee: number;
  excise: number;
  antiDumping: number;
  totalPayable: number;
  /** Сколько позиций дали числа из payment_profile.breakdown */
  itemsWithBreakdown: number;
  /** Есть ли хотя бы одна позиция с осмысленным fallback из finance */
  usedFinanceFallback: boolean;
};

function num(v: unknown): number {
  if (typeof v === "number" && Number.isFinite(v)) return v;
  if (typeof v === "string" && v.trim() !== "") {
    const n = Number(v.replace(/\s/g, "").replace(",", "."));
    return Number.isFinite(n) ? n : 0;
  }
  return 0;
}

function breakdownFromProfile(item: AnalysisItem): MoneyBreakdown | null {
  const b = item.payment_profile?.breakdown;
  if (!b || typeof b !== "object") return null;
  return b as MoneyBreakdown;
}

/**
 * Суммирует таможенные платежи по позициям: в приоритете ``payment_profile.breakdown``,
 * иначе частичный fallback на ``finance`` (акциз как сумма, если задан числом).
 */
export function aggregateInvoicePaymentTotals(items: AnalysisItem[]): InvoicePaymentTotals {
  let duty = 0;
  let vat = 0;
  let customsFee = 0;
  let excise = 0;
  let antiDumping = 0;
  let totalPayable = 0;
  let itemsWithBreakdown = 0;
  let usedFinanceFallback = false;

  for (const item of items) {
    const bd = breakdownFromProfile(item);
    if (bd) {
      duty += num(bd.base_duty);
      vat += num(bd.vat);
      customsFee += num(bd.customs_fee);
      excise += num(bd.excise);
      antiDumping += num(bd.anti_dumping);
      totalPayable += num(bd.total_payable);
      itemsWithBreakdown += 1;
    } else {
      const ex = num(item.finance?.excise);
      if (ex !== 0) {
        excise += ex;
        usedFinanceFallback = true;
      }
    }
  }

  return {
    duty,
    vat,
    customsFee,
    excise,
    antiDumping,
    totalPayable,
    itemsWithBreakdown,
    usedFinanceFallback,
  };
}

export function formatRub(value: number): string {
  if (!Number.isFinite(value)) return "—";
  return `${value.toLocaleString("ru-RU", { maximumFractionDigits: 2 })} ₽`;
}
