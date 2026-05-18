import type { ElementType } from "react";
import { Package, CheckCircle2, ShieldAlert, TrendingUp, Banknote, Receipt, Landmark, Wallet } from "lucide-react";
import type { AnalysisItem } from "../../types";
import { aggregateInvoicePaymentTotals, formatRub } from "../../lib/invoiceTotals";

type KpiCardProps = {
  icon: ElementType;
  label: string;
  value: string | number;
  sub?: string;
  accent?: "cyan" | "red" | "green" | "default" | "amber";
};

const ACCENT = {
  cyan: { text: "text-[#00F0FF]", icon: "bg-[#00F0FF]/10 text-[#00F0FF]", glow: "0 0 20px rgba(0,240,255,0.12)", border: "border-[#00F0FF]/15" },
  red: { text: "text-[#FF4757]", icon: "bg-[#FF4757]/10 text-[#FF4757]", glow: "0 0 20px rgba(255,71,87,0.12)", border: "border-[#FF4757]/15" },
  green: { text: "text-[#2ED573]", icon: "bg-[#2ED573]/10 text-[#2ED573]", glow: "0 0 20px rgba(46,213,115,0.10)", border: "border-[#2ED573]/15" },
  amber: { text: "text-[#FFA502]", icon: "bg-[#FFA502]/10 text-[#FFA502]", glow: "0 0 20px rgba(255,165,2,0.10)", border: "border-[#FFA502]/15" },
  default: { text: "text-white", icon: "bg-white/[0.06] text-[#8B92A8]", glow: "none", border: "border-white/[0.06]" },
};

function KpiCard({ icon: Icon, label, value, sub, accent = "default" }: KpiCardProps) {
  const a = ACCENT[accent];
  return (
    <div
      className={`flex min-w-[140px] flex-1 items-center gap-4 rounded-xl border bg-white/[0.03] px-5 py-4 ${a.border}`}
      style={{ boxShadow: a.glow }}
    >
      <div className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-xl ${a.icon}`}>
        <Icon size={18} />
      </div>
      <div className="min-w-0">
        <p className="text-[11px] uppercase tracking-widest text-[#4A5166]">{label}</p>
        <p className={`text-2xl font-bold tabular-nums leading-tight ${a.text}`}>{value}</p>
        {sub && <p className="mt-0.5 text-[11px] text-[#4A5166]">{sub}</p>}
      </div>
    </div>
  );
}

type SummaryBarProps = {
  total: number;
  validCodes: number;
  totalRisks: number;
  mode?: string;
  /** Позиции инвойса — для суммирования ``payment_profile.breakdown`` */
  items?: AnalysisItem[];
};

export function SummaryBar({ total, validCodes, totalRisks, mode, items }: SummaryBarProps) {
  const accuracy = total > 0 ? Math.round((validCodes / total) * 100) : 0;
  const list = items ?? [];
  const pay = aggregateInvoicePaymentTotals(list);
  const hasBreakdown = pay.itemsWithBreakdown > 0;
  const partialFallback = !hasBreakdown && pay.usedFinanceFallback;

  const dutyDisplay = hasBreakdown ? formatRub(pay.duty + pay.antiDumping) : "—";
  const vatDisplay = hasBreakdown ? formatRub(pay.vat) : "—";
  const feeDisplay = hasBreakdown ? formatRub(pay.customsFee) : "—";

  let totalDisplay = "—";
  if (hasBreakdown) {
    const sumComponents = pay.duty + pay.vat + pay.customsFee + pay.excise + pay.antiDumping;
    const useTotal = pay.totalPayable > 0 ? pay.totalPayable : sumComponents;
    totalDisplay = formatRub(useTotal);
  } else if (partialFallback && pay.excise !== 0) {
    totalDisplay = formatRub(pay.excise);
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap gap-3">
        <KpiCard icon={Package} label="Позиций" value={total} sub="в инвойсе" accent="default" />
        <KpiCard icon={CheckCircle2} label="Коды ТН ВЭД" value={validCodes} sub="валидных (10 знаков)" accent="cyan" />
        <KpiCard icon={TrendingUp} label="Точность" value={`${accuracy}%`} sub={mode ? `режим: ${mode}` : undefined} accent="green" />
        <KpiCard
          icon={ShieldAlert}
          label="Риски"
          value={totalRisks}
          sub={totalRisks > 0 ? "требуют внимания" : "—"}
          accent={totalRisks > 0 ? "red" : "default"}
        />
      </div>

      {list.length > 0 && (
        <div className="rounded-2xl border border-white/[0.06] bg-white/[0.02] p-4">
          <p className="mb-3 text-[10px] uppercase tracking-widest text-[#4A5166]">
            Таможенные платежи · итого по позициям
          </p>
          <div className="flex flex-wrap gap-3">
            <KpiCard
              icon={Banknote}
              label="Итого пошлина"
              value={dutyDisplay}
              sub={
                hasBreakdown && pay.antiDumping > 0
                  ? "вкл. антидемпинг / спецпошлина"
                  : hasBreakdown
                    ? `позиций с расчётом: ${pay.itemsWithBreakdown}`
                    : "нет данных payment_profile"
              }
              accent="cyan"
            />
            <KpiCard
              icon={Receipt}
              label="Итого НДС"
              value={vatDisplay}
              sub={hasBreakdown ? undefined : "fallback: только ставка в карточке"}
              accent="amber"
            />
            <KpiCard
              icon={Landmark}
              label="Таможенный сбор"
              value={feeDisplay}
              sub={undefined}
              accent="default"
            />
            <KpiCard
              icon={Wallet}
              label="Общая сумма к уплате"
              value={totalDisplay}
              sub={
                partialFallback && !hasBreakdown
                  ? "оценка по finance.excise (нет breakdown)"
                  : hasBreakdown && pay.totalPayable <= 0 && pay.duty + pay.vat + pay.customsFee + pay.excise + pay.antiDumping === 0
                    ? "в т.ч. эмбарго / нулевой профиль"
                    : undefined
              }
              accent="green"
            />
          </div>
        </div>
      )}
    </div>
  );
}
