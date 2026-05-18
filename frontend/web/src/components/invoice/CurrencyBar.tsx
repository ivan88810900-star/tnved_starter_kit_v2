import { useEffect, useState } from "react";
import { TrendingUp, TrendingDown, Minus, RefreshCw } from "lucide-react";

type Rate = {
  code: string;
  name: string;
  value: number;
  prev: number;
  flag: string;
};

type CbrResponse = {
  Valute: Record<string, { Value: number; Previous: number; CharCode: string; Name: string }>;
};

const TARGETS = [
  { code: "USD", name: "Доллар США",  flag: "🇺🇸" },
  { code: "EUR", name: "Евро",        flag: "🇪🇺" },
  { code: "CNY", name: "Юань",        flag: "🇨🇳" },
];

// Proxy via our backend to avoid CORS / SSL issues in development
const CBR_URL = "https://www.cbr-xml-daily.ru/daily_json.js";

async function fetchRates(): Promise<Rate[]> {
  const res = await fetch(CBR_URL, { mode: "cors" });
  if (!res.ok) throw new Error("CBR fetch failed");
  const data: CbrResponse = await res.json();
  return TARGETS.map(({ code, name, flag }) => {
    const v = data.Valute[code];
    return {
      code,
      name,
      flag,
      value: v?.Value ?? 0,
      prev: v?.Previous ?? 0,
    };
  });
}

function Trend({ value, prev }: { value: number; prev: number }) {
  const diff = value - prev;
  if (Math.abs(diff) < 0.005) return <Minus size={12} className="text-[#4A5166]" />;
  if (diff > 0) return <TrendingUp  size={12} className="text-[#FF4757]" />;
  return           <TrendingDown size={12} className="text-[#2ED573]" />;
}

export function CurrencyBar() {
  const [rates, setRates] = useState<Rate[]>([]);
  const [loading, setLoading] = useState(true);
  const [updatedAt, setUpdatedAt] = useState<string>("");
  const [error, setError] = useState(false);

  const load = () => {
    setLoading(true);
    setError(false);
    fetchRates()
      .then((r) => {
        setRates(r);
        setUpdatedAt(new Date().toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" }));
      })
      .catch(() => {
        // Fallback to mock data if CBR is unreachable
        setRates([
          { code: "USD", name: "Доллар США", flag: "🇺🇸", value: 89.15, prev: 88.90 },
          { code: "EUR", name: "Евро",       flag: "🇪🇺", value: 96.42, prev: 96.88 },
          { code: "CNY", name: "Юань",       flag: "🇨🇳", value: 12.18, prev: 12.11 },
        ]);
        setError(true);
        setUpdatedAt("—");
      })
      .finally(() => setLoading(false));
  };

  useEffect(() => { load(); }, []);

  return (
    <div className="rounded-2xl border border-white/[0.07] bg-white/[0.03] px-4 py-3">
      <div className="mb-2.5 flex items-center justify-between">
        <p className="text-[10px] font-semibold uppercase tracking-widest text-[#4A5166]">
          Курс ЦБ РФ
        </p>
        <div className="flex items-center gap-2">
          {error && (
            <span className="text-[10px] text-[#4A5166]">mock</span>
          )}
          {updatedAt && !loading && (
            <span className="text-[10px] text-[#4A5166]">{updatedAt}</span>
          )}
          <button
            onClick={load}
            className="rounded p-0.5 text-[#4A5166] transition hover:text-white"
            title="Обновить"
          >
            <RefreshCw size={11} className={loading ? "animate-spin" : ""} />
          </button>
        </div>
      </div>

      <div className="flex gap-3">
        {loading
          ? TARGETS.map((t) => (
              <div key={t.code} className="flex flex-1 flex-col gap-1.5">
                <div className="h-3 animate-pulse rounded bg-white/[0.06]" />
                <div className="h-5 w-3/4 animate-pulse rounded bg-white/[0.06]" />
              </div>
            ))
          : rates.map((r) => {
              const diff = r.value - r.prev;
              const pct = r.prev > 0 ? ((diff / r.prev) * 100).toFixed(2) : "0.00";
              const isUp = diff > 0.005;
              const isDown = diff < -0.005;
              return (
                <div key={r.code} className="flex flex-1 items-start gap-2">
                  <span className="text-base">{r.flag}</span>
                  <div className="min-w-0">
                    <p className="text-[10px] text-[#4A5166]">{r.code} / RUB</p>
                    <p className="text-base font-bold tabular-nums text-white">
                      {r.value.toFixed(2)}
                    </p>
                    <div className="flex items-center gap-1">
                      <Trend value={r.value} prev={r.prev} />
                      <span
                        className={`text-[10px] tabular-nums ${
                          isUp ? "text-[#FF4757]" : isDown ? "text-[#2ED573]" : "text-[#4A5166]"
                        }`}
                      >
                        {diff > 0 ? "+" : ""}{diff.toFixed(2)} ({pct}%)
                      </span>
                    </div>
                  </div>
                </div>
              );
            })}
      </div>
    </div>
  );
}
