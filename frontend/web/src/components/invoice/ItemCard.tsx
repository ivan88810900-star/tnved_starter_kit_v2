import { ShieldAlert, ShieldCheck, ChevronDown, Check, Loader2 } from "lucide-react";
import { useState } from "react";
import type { AnalysisItem } from "../../types";
import { formatHsCode, classifyDoc, cn } from "../../lib/utils";
import { approveClassification } from "../../lib/classifyFeedback";

/* ── Doc-type config ─────────────────────────────────── */
const DOC_CFG = {
  tr_ts: { label: "ТР ТС / ЕАЭС", bg: "bg-[#00F0FF]/10", text: "text-[#00F0FF]", border: "border-[#00F0FF]/20" },
  fsb: { label: "ФСБ", bg: "bg-[#FFA502]/10", text: "text-[#FFA502]", border: "border-[#FFA502]/20" },
  marking: { label: "Маркировка", bg: "bg-[#A78BFA]/10", text: "text-[#A78BFA]", border: "border-[#A78BFA]/20" },
  other: { label: "Прочее", bg: "bg-white/[0.05]", text: "text-[#8B92A8]", border: "border-white/[0.08]" },
};

/* ── Finance cell ──────────────────────────────────────── */
function FinCell({ label, value, highlight }: { label: string; value: string; highlight?: boolean }) {
  return (
    <div className="flex flex-col gap-1 px-4 py-3 first:rounded-l-xl last:rounded-r-xl">
      <span className="text-[10px] uppercase tracking-widest text-[#4A5166]">{label}</span>
      <span className={cn("text-base font-bold tabular-nums", highlight ? "text-[#00F0FF]" : "text-white")}>
        {value}
      </span>
    </div>
  );
}

/* ── Main card ─────────────────────────────────────────── */
type ItemCardProps = { item: AnalysisItem; index: number };

export function ItemCard({ item, index }: ItemCardProps) {
  const [opiOpen, setOpiOpen] = useState(false);
  const [approveState, setApproveState] = useState<"idle" | "loading" | "success" | "error">("idle");
  const [approveError, setApproveError] = useState<string>("");

  const profile = item.payment_profile ?? null;
  const isEmbargo = Boolean(profile?.geo?.embargo);
  const profileDocs = profile?.documents ?? [];
  const hasProfileDocs = profileDocs.length > 0;
  const nonTariffDocs = hasProfileDocs ? [] : (item.non_tariff_docs ?? []);

  const money = {
    duty: profile?.breakdown?.base_duty ?? null,
    vat: profile?.breakdown?.vat ?? null,
    excise: profile?.breakdown?.excise ?? null,
    antiDumping: profile?.breakdown?.anti_dumping ?? null,
    customsFee: profile?.breakdown?.customs_fee ?? null,
  };
  const fmtRub = (v: number | null) => (v === null ? "—" : `${v.toLocaleString("ru-RU")} ₽`);

  const hasRisks = (item.risks?.length ?? 0) > 0;
  const hsFormatted = item.hs_code_view || formatHsCode(item.hs_code);
  const hsDigits = (item.hs_code || "").replace(/\D/g, "").slice(0, 10);
  const canApprove = hsDigits.length === 10;

  const handleApprove = async () => {
    if (!canApprove || approveState === "loading" || approveState === "success") return;
    setApproveState("loading");
    setApproveError("");
    const ctxParts = [`Позиция ${index + 1}`];
    if (item.brand) ctxParts.push(`бренд: ${item.brand}`);
    if (item.article) ctxParts.push(`артикул: ${item.article}`);
    ctxParts.push(`код на карточке: ${hsFormatted}`);
    try {
      await approveClassification({
        original_description: item.name,
        approved_hs_code: hsDigits,
        invoice_context: ctxParts.join("; "),
        user_note: `Утверждено из UI VED·AI, позиция ${index + 1}`,
      });
      setApproveState("success");
    } catch (e) {
      setApproveState("error");
      setApproveError(e instanceof Error ? e.message : "Ошибка сохранения");
    }
  };

  return (
    <article
      className={cn(
        "flex flex-col gap-5 rounded-2xl border bg-white/[0.03] p-6 transition-all duration-200",
        hasRisks
          ? "border-[#FF4757]/20 shadow-[0_0_28px_-4px_rgba(255,71,87,0.12)]"
          : "border-white/[0.07] shadow-[0_8px_32px_rgba(0,0,0,0.4)]",
      )}
    >
      {/* ── Header ── */}
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0 flex-1">
          <p className="mb-1 text-[10px] uppercase tracking-widest text-[#4A5166]">
            Товар · позиция {index + 1}
          </p>
          <h3 className="text-[15px] font-semibold leading-snug text-white">{item.name}</h3>
        </div>

        {/* HS Code + self-learning */}
        <div className="flex shrink-0 flex-col items-end gap-2">
          <div
            className="rounded-xl border border-[#00F0FF]/20 bg-[#00F0FF]/[0.06] px-4 py-2.5 text-right"
            style={{ boxShadow: "0 0 20px rgba(0,240,255,0.08)" }}
          >
            <p className="text-[10px] uppercase tracking-widest text-[#00F0FF]/50">ТН ВЭД ЕАЭС</p>
            <p
              className="mt-0.5 font-mono text-xl font-bold leading-none tracking-wider text-[#00F0FF]"
              style={{ textShadow: "0 0 12px rgba(0,240,255,0.6)" }}
            >
              {hsFormatted}
            </p>
          </div>

          <button
            type="button"
            disabled={!canApprove || approveState === "loading" || approveState === "success"}
            onClick={() => void handleApprove()}
            className={cn(
              "inline-flex items-center justify-center gap-2 rounded-xl border px-3.5 py-2 text-[12px] font-semibold transition-all",
              approveState === "success" &&
                "cursor-default border-[#2ED573]/35 bg-[#2ED573]/15 text-[#2ED573] shadow-[0_0_16px_rgba(46,213,115,0.12)]",
              approveState === "error" &&
                "border-[#FF4757]/40 bg-[#FF4757]/10 text-[#FF8A95] hover:bg-[#FF4757]/15",
              (approveState === "idle" || approveState === "loading") &&
                "border-[#00F0FF]/25 bg-[#00F0FF]/[0.08] text-[#00F0FF] hover:border-[#00F0FF]/45 hover:bg-[#00F0FF]/15 disabled:cursor-not-allowed disabled:opacity-40",
            )}
          >
            {approveState === "loading" ? (
              <Loader2 size={16} className="animate-spin" />
            ) : (
              <Check size={16} strokeWidth={2.5} />
            )}
            {approveState === "success"
              ? "Код утверждён и сохранён в базу знаний"
              : approveState === "loading"
                ? "Сохранение…"
                : "Утвердить код"}
          </button>
          {!canApprove && (
            <p className="max-w-[220px] text-right text-[10px] text-[#4A5166]">
              Нужен 10-значный код ТН ВЭД для записи прецедента
            </p>
          )}
          {approveState === "error" && approveError && (
            <p className="max-w-[240px] text-right text-[10px] text-[#FF8A95]">{approveError}</p>
          )}
        </div>
      </div>

      {isEmbargo && (
        <div className="rounded-xl border border-[#FF4757]/35 bg-[#FF4757]/15 px-3 py-2 text-sm font-semibold text-[#FF8A95]">
          ЭМБАРГО — ввоз запрещен по геополитическим мерам
        </div>
      )}

      {/* ── Finance ── */}
      <div className="grid grid-cols-5 divide-x divide-white/[0.06] rounded-xl border border-white/[0.06] bg-black/20">
        <FinCell label="Пошлина" value={money.duty !== null ? fmtRub(money.duty) : item.finance.duty_rate} />
        <FinCell
          label="НДС"
          value={money.vat !== null ? fmtRub(money.vat) : `${item.finance.vat_rate}%`}
          highlight
        />
        <FinCell label="Сбор" value={money.customsFee !== null ? fmtRub(money.customsFee) : "—"} />
        <FinCell
          label="Акциз"
          value={
            money.excise !== null ? fmtRub(money.excise) : item.finance.excise === 0 ? "—" : String(item.finance.excise)
          }
        />
        <FinCell label="Антидемпинг" value={money.antiDumping !== null ? fmtRub(money.antiDumping) : "—"} />
      </div>

      {/* ── Compliance docs from payment_profile ── */}
      {hasProfileDocs && (
        <div>
          <p className="mb-2.5 text-[10px] uppercase tracking-widest text-[#4A5166]">
            Требуемые документы (комплаенс)
          </p>
          <div className="flex flex-col gap-2">
            {profileDocs.map((doc, i) => (
              <div
                key={`${doc.doc_type}-${doc.legal_ref}-${i}`}
                className="rounded-lg border border-white/[0.08] bg-white/[0.03] px-3 py-2"
              >
                <div className="flex items-center justify-between gap-3">
                  <span className="text-xs font-semibold text-[#C8CDDC]">{doc.title}</span>
                  <span className="text-[10px] uppercase tracking-wider text-[#8B92A8]">{doc.doc_type}</span>
                </div>
                <p className="mt-1 text-[12px] text-[#8B92A8]">{doc.detail}</p>
                <p className="mt-1 text-[11px] text-[#4A5166]">{doc.legal_ref}</p>
                {doc.registry_match ? (
                  <p className="mt-1 text-[11px] font-medium text-[#2ED573]">{doc.registry_match}</p>
                ) : null}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ── Legacy non-tariff docs fallback ── */}
      {(nonTariffDocs.length ?? 0) > 0 && (
        <div>
          <p className="mb-2.5 text-[10px] uppercase tracking-widest text-[#4A5166]">
            Нетарифное регулирование
          </p>
          <div className="flex flex-col gap-1.5">
            {nonTariffDocs.map((doc, i) => {
              const type = classifyDoc(doc);
              const cfg = DOC_CFG[type];
              return (
                <div
                  key={i}
                  className={cn("flex items-center gap-2.5 rounded-lg border px-3 py-2", cfg.bg, cfg.border)}
                >
                  <span
                    className={cn(
                      "shrink-0 rounded-md px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wider",
                      cfg.text,
                      cfg.bg,
                      cfg.border,
                      "border",
                    )}
                  >
                    {cfg.label}
                  </span>
                  <span className="text-[13px] text-[#C8CDDC]">{doc}</span>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* ── OPI accordion ── */}
      {(item.opi_steps?.length ?? 0) > 0 && (
        <div className="overflow-hidden rounded-xl border border-white/[0.06]">
          <button
            type="button"
            onClick={() => setOpiOpen((v) => !v)}
            className="flex w-full items-center justify-between bg-black/20 px-4 py-2.5 text-left transition hover:bg-black/30"
          >
            <span className="text-[10px] uppercase tracking-widest text-[#4A5166]">Обоснование по ОПИ</span>
            <ChevronDown
              size={13}
              className={cn("text-[#4A5166] transition-transform duration-200", opiOpen && "rotate-180")}
            />
          </button>
          {opiOpen && (
            <div className="flex flex-col gap-3 px-4 py-3">
              {item.opi_steps.map((step, i) => (
                <div key={i} className="flex items-start gap-3">
                  <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full border border-white/[0.1] bg-white/[0.04] text-[10px] font-bold text-[#8B92A8]">
                    {i + 1}
                  </span>
                  <p className="text-[13px] leading-relaxed text-[#8B92A8]">{step}</p>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* ── Risks ── */}
      {isEmbargo ? (
        <div className="flex items-center gap-2.5 rounded-xl border border-[#FF4757]/30 bg-[#FF4757]/[0.08] px-3 py-2.5">
          <ShieldAlert size={15} className="shrink-0 text-[#FF4757]" />
          <span className="text-[13px] text-[#FF8A95]">Позитивная оценка рисков скрыта: активен режим эмбарго</span>
        </div>
      ) : hasRisks ? (
        <div className="flex flex-col gap-1.5">
          {item.risks.map((risk, i) => (
            <div
              key={i}
              className="flex items-start gap-2.5 rounded-xl border border-[#FF4757]/20 bg-[#FF4757]/[0.06] px-3 py-2.5"
            >
              <ShieldAlert size={15} className="mt-0.5 shrink-0 text-[#FF4757]" />
              <span className="text-[13px] leading-snug text-[#FF8A95]">{risk}</span>
            </div>
          ))}
        </div>
      ) : (
        <div className="flex items-center gap-2.5 rounded-xl border border-[#2ED573]/20 bg-[#2ED573]/[0.06] px-3 py-2.5">
          <ShieldCheck size={15} className="shrink-0 text-[#2ED573]" />
          <span className="text-[13px] text-[#2ED573]">Критичных рисков не обнаружено</span>
        </div>
      )}
    </article>
  );
}
