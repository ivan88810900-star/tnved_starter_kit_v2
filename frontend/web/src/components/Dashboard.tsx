import { useState } from "react";
import {
  AlertTriangle,
  Loader2,
  ScanSearch,
  Trash2,
  Bell,
  User,
} from "lucide-react";
import { useInvoiceAnalysis } from "../hooks/useInvoiceAnalysis";
import { AppLayout } from "./layout/AppLayout";
import { UploadZone } from "./invoice/UploadZone";
import { SummaryBar } from "./invoice/SummaryBar";
import { CurrencyBar } from "./invoice/CurrencyBar";
import { ItemCard } from "./invoice/ItemCard";
import { SkeletonCard, EmptyState } from "./invoice/SkeletonCard";
import TnvedPage from "../pages/TnvedPage";
import OverviewPage from "../pages/OverviewPage";

const MODE_RU: Record<string, string> = {
  mock: "Demo",
  mock_fallback: "Fallback",
  real_parser: "Live",
};

/* ── Classify (invoice analysis) page ─────────────────────────────── */
function ClassifyPage() {
  const [file, setFile] = useState<File | null>(null);
  const { result, loading, error, stats, analyze, reset } = useInvoiceAnalysis();

  const modeTag = result?.mode ? (MODE_RU[result.mode] ?? result.mode) : null;

  return (
    <div className="flex h-full flex-col overflow-y-auto">
      {/* Top bar */}
      <div className="shrink-0 border-b border-white/[0.06] bg-[#080810]/80 px-6 py-4 backdrop-blur-sm">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-sm font-semibold text-white">Классификация и расчёт</h1>
            <p className="text-[11px] text-[#4A5166]">
              ТН ВЭД ЕАЭС · таможенные платежи · нетарифные меры
            </p>
          </div>
          <div className="flex items-center gap-3">
            {modeTag && (
              <span className="rounded-full border border-white/[0.08] bg-white/[0.04] px-2.5 py-1 text-[11px] text-[#8B92A8]">
                {modeTag}
              </span>
            )}
            <span className="flex items-center gap-1.5 rounded-full border border-[#2ED573]/25 bg-[#2ED573]/[0.07] px-2.5 py-1 text-[11px] text-[#2ED573]">
              <span className="h-1.5 w-1.5 rounded-full bg-[#2ED573]" />
              API Online
            </span>
            <button className="flex h-8 w-8 items-center justify-center rounded-lg border border-white/[0.07] bg-white/[0.03] text-[#4A5166] transition hover:text-white">
              <Bell size={14} />
            </button>
            <button className="flex h-8 w-8 items-center justify-center rounded-lg border border-white/[0.07] bg-white/[0.03] text-[#4A5166] transition hover:text-white">
              <User size={14} />
            </button>
          </div>
        </div>
      </div>

      <div className="flex flex-col gap-6 p-6">
        {/* KPI row */}
        <SummaryBar
          total={stats.total}
          validCodes={stats.validCodes}
          totalRisks={stats.totalRisks}
          mode={modeTag ?? undefined}
          items={result?.items}
        />

        {/* Upload + Currency */}
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-12">
          <div className="lg:col-span-8">
            <div className="rounded-2xl border border-white/[0.07] bg-white/[0.03] p-5">
              <div className="mb-4 flex items-center gap-2">
                <ScanSearch size={14} className="text-[#00F0FF]" />
                <h2 className="text-[11px] font-semibold uppercase tracking-widest text-[#4A5166]">
                  Загрузка инвойса
                </h2>
              </div>
              <UploadZone file={file} onFileChange={setFile} />

              {result?.warning && (
                <div className="mt-3 flex items-center gap-2 rounded-xl border border-[#FFA502]/20 bg-[#FFA502]/[0.06] px-4 py-2.5 text-[13px] text-[#FFA502]">
                  <AlertTriangle size={14} className="shrink-0" />
                  {result.warning}
                </div>
              )}
              {error && (
                <div className="mt-3 flex items-start gap-2 rounded-xl border border-[#FF4757]/20 bg-[#FF4757]/[0.06] px-4 py-3 text-[13px] text-[#FF8A95]">
                  <AlertTriangle size={14} className="mt-0.5 shrink-0 text-[#FF4757]" />
                  {error}
                </div>
              )}

              <div className="mt-4 flex flex-wrap gap-3">
                <button
                  type="button"
                  onClick={() => analyze(file)}
                  disabled={loading}
                  className="inline-flex items-center gap-2 rounded-xl bg-[#00F0FF] px-5 py-2.5 text-sm font-bold text-[#080810] transition hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-50"
                  style={{ boxShadow: "0 0 20px rgba(0,240,255,0.28)" }}
                >
                  {loading ? <Loader2 size={15} className="animate-spin" /> : <ScanSearch size={15} />}
                  {loading ? "Классифицирую…" : "Классифицировать и рассчитать"}
                </button>
                {(file || result) && (
                  <button
                    type="button"
                    onClick={() => { setFile(null); reset(); }}
                    className="inline-flex items-center gap-2 rounded-xl border border-white/[0.1] px-4 py-2.5 text-sm text-[#8B92A8] transition hover:border-white/[0.2] hover:text-white"
                  >
                    <Trash2 size={14} />
                    Сбросить
                  </button>
                )}
              </div>
            </div>
          </div>

          {/* Currency rates block */}
          <div className="lg:col-span-4">
            <CurrencyBar />
          </div>
        </div>

        {/* Results */}
        {(loading || result) && (
          <div>
            <div className="mb-4 flex items-center gap-2">
              <div className="h-px flex-1 bg-white/[0.06]" />
              <span className="text-[10px] uppercase tracking-widest text-[#4A5166]">
                Результаты классификации
              </span>
              <div className="h-px flex-1 bg-white/[0.06]" />
            </div>
            <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
              {loading ? (
                <><SkeletonCard /><SkeletonCard /></>
              ) : (result?.items?.length ?? 0) > 0 ? (
                result!.items.map((item, i) => (
                  <ItemCard key={`${item.hs_code}-${i}`} item={item} index={i} />
                ))
              ) : (
                <EmptyState />
              )}
            </div>
          </div>
        )}

        {!loading && !result && (
          <div className="grid grid-cols-1"><EmptyState /></div>
        )}

        <footer className="mt-2 border-t border-white/[0.04] pt-4 text-center text-[10px] text-[#2A2E3E]">
          VED·AI · Данные носят информационный характер · Для официальных решений обратитесь к декларанту
        </footer>
      </div>
    </div>
  );
}

/* ── Stub pages ────────────────────────────────────────────────────── */
function ComingSoon({ title }: { title: string }) {
  return (
    <div className="flex h-full items-center justify-center">
      <div className="text-center">
        <div className="mb-4 text-4xl">🚧</div>
        <p className="text-base font-semibold text-[#C8CDDC]">{title}</p>
        <p className="mt-1 text-sm text-[#4A5166]">Модуль в разработке</p>
      </div>
    </div>
  );
}

/* ── Root dashboard ────────────────────────────────────────────────── */
export default function Dashboard() {
  const [activeNav, setActiveNav] = useState("overview");

  return (
    <AppLayout activeNav={activeNav} onNavigate={setActiveNav}>
      {activeNav === "overview"    && <OverviewPage onNavigate={setActiveNav} />}
      {activeNav === "registries"  && <TnvedPage />}
      {activeNav === "classify"    && <ClassifyPage />}
      {activeNav === "compliance"  && <ComingSoon title="Комплаенс" />}
      {activeNav === "settings"    && <ComingSoon title="Настройки" />}
    </AppLayout>
  );
}
