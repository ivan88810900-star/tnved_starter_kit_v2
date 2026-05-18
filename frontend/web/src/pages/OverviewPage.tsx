import { useEffect, useState } from "react";
import {
  Database,
  FileText,
  BarChart3,
  ShieldCheck,
  RefreshCw,
  CheckCircle2,
  AlertCircle,
} from "lucide-react";
import { cn } from "../lib/utils";

const API = import.meta.env.VITE_API_BASE_URL || "";

type DbStats = {
  ok: boolean;
  sections?: number;
  chapters?: number;
  commodities?: number;
  hs_codes?: number;
  tariff_rates?: number;
  ntm_measures?: number;
  vat_rules?: number;
  data_sources?: number;
  error?: string;
};

function StatCard({
  icon: Icon,
  label,
  value,
  sub,
  status,
}: {
  icon: React.ElementType;
  label: string;
  value: string | number;
  sub?: string;
  status?: "ok" | "empty" | "warn";
}) {
  const statusColor =
    status === "ok" ? "text-[#2ED573]"
    : status === "empty" ? "text-[#4A5166]"
    : status === "warn" ? "text-[#FFA502]"
    : "text-white";

  return (
    <div className="flex items-start gap-4 rounded-2xl border border-white/[0.07] bg-white/[0.03] p-5">
      <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border border-white/[0.08] bg-white/[0.04] text-[#8B92A8]">
        <Icon size={18} />
      </div>
      <div className="min-w-0 flex-1">
        <p className="text-[10px] uppercase tracking-widest text-[#4A5166]">{label}</p>
        <p className={cn("mt-1 text-2xl font-bold tabular-nums", statusColor)}>
          {value.toLocaleString("ru-RU")}
        </p>
        {sub && <p className="mt-0.5 text-[11px] text-[#4A5166]">{sub}</p>}
      </div>
      <div className="shrink-0">
        {status === "ok" && <CheckCircle2 size={14} className="text-[#2ED573]" />}
        {status === "empty" && <AlertCircle size={14} className="text-[#4A5166]" />}
      </div>
    </div>
  );
}

const INFO_CARDS = [
  {
    icon: "🗂️",
    title: "Дерево ТН ВЭД",
    body: "Навигатор по 21 разделу, 96 главам и 20 000+ кодам ЕАЭС с тарифами и НДС.",
    action: "Открыть реестр",
    nav: "registries",
  },
  {
    icon: "🤖",
    title: "ИИ-классификация",
    body: "Загрузите инвойс в форматах Excel, CSV, PDF — получите коды ТН ВЭД и таможенные платежи.",
    action: "Классифицировать",
    nav: "classify",
  },
  {
    icon: "⚖️",
    title: "Тарифные ставки",
    body: "16 270 тарифных ставок ЕТТ ЕАЭС с пошлинами, НДС и дополнительными сборами.",
    action: "Скоро",
    nav: null,
  },
  {
    icon: "🛡️",
    title: "Нетарифные меры",
    body: "ТР ТС/ЕАЭС, нотификации ФСБ, маркировка «Честный знак» — по профилю кода.",
    action: "Скоро",
    nav: null,
  },
];

type OverviewPageProps = {
  onNavigate: (id: string) => void;
};

export default function OverviewPage({ onNavigate }: OverviewPageProps) {
  const [stats, setStats] = useState<DbStats | null>(null);
  const [loading, setLoading] = useState(true);

  const load = () => {
    setLoading(true);
    fetch(`${API}/api/db-stats`)
      .then((r) => r.json())
      .then(setStats)
      .catch(() => setStats({ ok: false, error: "Нет соединения с API" }))
      .finally(() => setLoading(false));
  };

  useEffect(() => { load(); }, []);

  return (
    <div className="flex h-full flex-col overflow-y-auto">
      {/* Top bar */}
      <div className="shrink-0 border-b border-white/[0.06] bg-[#080810]/80 px-6 py-4 backdrop-blur-sm">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-sm font-semibold text-white">Обзор системы</h1>
            <p className="text-[11px] text-[#4A5166]">Состояние базы данных и доступных модулей</p>
          </div>
          <button
            onClick={load}
            className="flex items-center gap-1.5 rounded-lg border border-white/[0.08] px-3 py-1.5 text-xs text-[#8B92A8] transition hover:text-white"
          >
            <RefreshCw size={12} className={loading ? "animate-spin" : ""} />
            Обновить
          </button>
        </div>
      </div>

      <div className="flex flex-col gap-6 p-6">
        {/* DB status banner */}
        <div
          className={cn(
            "flex items-center gap-3 rounded-xl border px-4 py-3",
            stats?.ok
              ? "border-[#2ED573]/20 bg-[#2ED573]/[0.06]"
              : "border-[#FF4757]/20 bg-[#FF4757]/[0.06]",
          )}
        >
          {stats?.ok
            ? <CheckCircle2 size={15} className="text-[#2ED573]" />
            : <AlertCircle size={15} className="text-[#FF4757]" />}
          <p className="text-sm font-medium text-[#C8CDDC]">
            {stats?.ok
              ? "База данных подключена и работает"
              : stats?.error ?? "Соединение с API недоступно"}
          </p>
          <span className={cn(
            "ml-auto rounded-full border px-2 py-0.5 text-[10px]",
            stats?.ok
              ? "border-[#2ED573]/25 text-[#2ED573]"
              : "border-[#FF4757]/25 text-[#FF4757]",
          )}>
            {stats?.ok ? "● Онлайн" : "● Офлайн"}
          </span>
        </div>

        {/* Stats grid */}
        <div>
          <p className="mb-3 text-[10px] uppercase tracking-widest text-[#4A5166]">
            Содержимое базы данных
          </p>
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <StatCard
              icon={Database}
              label="Разделы ТН ВЭД"
              value={stats?.sections ?? "—"}
              sub="I–XXI"
              status={stats?.sections ? "ok" : "empty"}
            />
            <StatCard
              icon={FileText}
              label="Главы ТН ВЭД"
              value={stats?.chapters ?? "—"}
              sub="01–97"
              status={stats?.chapters ? "ok" : "empty"}
            />
            <StatCard
              icon={Database}
              label="Коды ТН ВЭД"
              value={stats?.hs_codes ?? stats?.commodities ?? "—"}
              sub="10-значные позиции"
              status={(stats?.hs_codes || stats?.commodities) ? "ok" : "empty"}
            />
            <StatCard
              icon={BarChart3}
              label="Тарифные ставки"
              value={stats?.tariff_rates ?? "—"}
              sub="ЕТТ ЕАЭС"
              status={stats?.tariff_rates ? "ok" : "empty"}
            />
            <StatCard
              icon={ShieldCheck}
              label="Нетарифные меры"
              value={stats?.ntm_measures ?? "—"}
              sub={stats?.ntm_measures ? "мер в реестре" : "Нет данных"}
              status={stats?.ntm_measures ? "ok" : "warn"}
            />
            <StatCard
              icon={Database}
              label="Правила НДС"
              value={stats?.vat_rules ?? "—"}
              sub="льготных ставок"
              status={stats?.vat_rules ? "ok" : "empty"}
            />
            <StatCard
              icon={FileText}
              label="Источники данных"
              value={stats?.data_sources ?? "—"}
              sub="подключено"
              status={stats?.data_sources ? "ok" : "empty"}
            />
          </div>
        </div>

        {/* Module cards */}
        <div>
          <p className="mb-3 text-[10px] uppercase tracking-widest text-[#4A5166]">
            Модули системы
          </p>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
            {INFO_CARDS.map((card) => (
              <div
                key={card.title}
                className="flex flex-col gap-3 rounded-2xl border border-white/[0.07] bg-white/[0.03] p-5"
              >
                <span className="text-2xl">{card.icon}</span>
                <div className="flex-1">
                  <p className="text-sm font-semibold text-[#C8CDDC]">{card.title}</p>
                  <p className="mt-1 text-xs leading-relaxed text-[#4A5166]">{card.body}</p>
                </div>
                {card.nav ? (
                  <button
                    type="button"
                    onClick={() => onNavigate(card.nav!)}
                    className="self-start rounded-lg border border-[#00F0FF]/20 bg-[#00F0FF]/[0.07] px-3 py-1.5 text-xs font-medium text-[#00F0FF] transition hover:bg-[#00F0FF]/[0.12]"
                  >
                    {card.action} →
                  </button>
                ) : (
                  <span className="self-start rounded-lg border border-white/[0.06] bg-white/[0.04] px-3 py-1.5 text-xs text-[#4A5166]">
                    {card.action}
                  </span>
                )}
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
