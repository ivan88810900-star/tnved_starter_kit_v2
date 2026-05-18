import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  X,
  Search,
  ChevronRight,
  ChevronDown,
  Loader2,
  Hash,
  Percent,
  Tag,
  ArrowLeft,
  Keyboard,
  Copy,
  Check,
  Clock,
  Trash2,
  CornerDownRight,
} from "lucide-react";
import {
  buildHighlightChunks,
  cn,
  cleanTitle,
  isGenericOtherTitle,
  parentContextLine,
} from "../lib/utils";
import {
  getLocalFullTitle,
  mergeNodesWithLocalTitles,
  resolvedNomenclatureTitle,
} from "../data/mockTnVedTree";
import {
  clearRecentCodes,
  pushRecentCode,
  readRecentCodes,
  type RecentCode,
} from "../lib/recentCodes";

const API = import.meta.env.VITE_API_BASE_URL || "";

/** Многострочное наименование — никогда не обрезается. */
const NOMENCLATURE_TEXT =
  "whitespace-normal break-words text-left [overflow-wrap:anywhere] hyphens-auto";

/* ── Types ─────────────────────────────────────────────────────── */
type Chapter = { code: string; title_ru: string; title_full?: string | null };
type CodeNode = {
  code: string;
  title_ru: string | null;
  title_full?: string | null;
  level?: string;
  has_children?: boolean;
  tariff?: { duty?: string; vat?: number | string; vat_reason?: string };
};
type CodeDetail = CodeNode & {
  path: { code: string; title_ru: string | null; title_full?: string | null }[];
  children?: CodeNode[];
};

/* ── Highlight renderer ───────────────────────────────────────── */
function Highlight({ text, query }: { text: string; query: string }) {
  const chunks = useMemo(() => buildHighlightChunks(text, query), [text, query]);
  return (
    <>
      {chunks.map((c, i) =>
        c.match ? (
          <mark
            key={i}
            className="rounded-sm bg-[#00F0FF]/20 px-0.5 text-[#00F0FF]"
          >
            {c.text}
          </mark>
        ) : (
          <span key={i}>{c.text}</span>
        ),
      )}
    </>
  );
}

/* ── Tree node with lazy children ───────────────────────────────── */
function TreeNode({
  node,
  depth,
  selectedCode,
  onSelect,
  parentContext,
  forcedOpen,
}: {
  node: CodeNode;
  depth: number;
  selectedCode: string | null;
  onSelect: (code: string) => void;
  parentContext?: string | null;
  /** Набор кодов, которые должны быть раскрыты программно (путь к выбранному). */
  forcedOpen?: Set<string>;
}) {
  const [open, setOpen] = useState(false);
  const [children, setChildren] = useState<CodeNode[]>([]);
  const [childLoading, setChildLoading] = useState(false);

  const digits = node.code.replace(/\D/g, "");
  const isLeaf = digits.length >= 10 || node.has_children === false;
  const isSelected = selectedCode === node.code;

  const resolved = resolvedNomenclatureTitle(node.code, node.title_ru, node.title_full);
  const showTitle = resolved !== node.code;
  const otherCtx =
    parentContext &&
    isGenericOtherTitle(resolved) &&
    !resolved.includes("—") &&
    parentContextLine(parentContext);

  const loadChildren = useCallback(async () => {
    if (children.length > 0) return;
    setChildLoading(true);
    try {
      const res = await fetch(
        `${API}/api/codes/children/${node.code}?group_next=true&include_tariff=true`,
      );
      const data = await res.json();
      const raw = Array.isArray(data) ? data : [];
      setChildren(mergeNodesWithLocalTitles(raw));
    } catch {
      setChildren([]);
    } finally {
      setChildLoading(false);
    }
  }, [children.length, node.code]);

  const handleClick = async () => {
    onSelect(node.code);
    if (isLeaf) return;
    if (!open) await loadChildren();
    setOpen((v) => !v);
  };

  // Программное раскрытие пути (из результата поиска).
  useEffect(() => {
    if (!forcedOpen) return;
    if (!isLeaf && forcedOpen.has(node.code) && !open) {
      loadChildren().then(() => setOpen(true));
    }
  }, [forcedOpen, isLeaf, node.code, open, loadChildren]);

  const indentPx = 12 + depth * 18;

  return (
    <div>
      <button
        type="button"
        onClick={handleClick}
        style={{ paddingLeft: `${indentPx}px` }}
        className={cn(
          "group flex w-full items-start gap-2.5 rounded-lg py-3.5 pr-3 text-left text-[13px] transition-all",
          isSelected
            ? "bg-[#00F0FF]/[0.09] text-white"
            : "text-[#8B92A8] hover:bg-white/[0.04] hover:text-[#C8CDDC]",
        )}
      >
        {!isLeaf ? (
          childLoading ? (
            <Loader2 size={13} className="mt-1 shrink-0 animate-spin text-[#4A5166]" />
          ) : open ? (
            <ChevronDown
              size={13}
              className={cn("mt-1 shrink-0", isSelected ? "text-[#00F0FF]" : "text-[#4A5166]")}
            />
          ) : (
            <ChevronRight
              size={13}
              className={cn("mt-1 shrink-0", isSelected ? "text-[#00F0FF]" : "text-[#4A5166]")}
            />
          )
        ) : (
          <span className="mt-1.5 h-2.5 w-2.5 shrink-0 rounded-full border border-[#00F0FF]/30 bg-[#00F0FF]/10" />
        )}

        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span
              className={cn(
                "font-mono text-xs",
                isLeaf ? "text-[#00F0FF]" : isSelected ? "text-white/70" : "text-[#4A5166]",
              )}
            >
              {node.code}
            </span>
            {isLeaf && node.tariff?.duty && node.tariff.duty !== "—" && (
              <span className="rounded border border-[#00F0FF]/15 bg-[#00F0FF]/[0.06] px-1 py-0.5 text-[9px] text-[#00F0FF]">
                {node.tariff.duty}
              </span>
            )}
          </div>
          {otherCtx && (
            <p className="mt-1.5 border-l-2 border-[#00F0FF]/35 pl-2.5 text-[10px] uppercase tracking-wide text-[#5A6278]">
              В группе:{" "}
              <span className="font-medium normal-case text-[#8B92A8]">{otherCtx}</span>
            </p>
          )}
          {showTitle && (
            <p
              className={cn(
                "mt-1.5 text-[12px] leading-relaxed text-[#8B92A8] group-hover:text-[#C8CDDC]",
                NOMENCLATURE_TEXT,
              )}
            >
              {resolved}
            </p>
          )}
        </div>
      </button>

      {open && children.length > 0 && (
        <div className="ml-2 border-l border-white/[0.08] pl-2">
          {children.map((ch) => (
            <TreeNode
              key={ch.code}
              node={ch}
              depth={depth + 1}
              selectedCode={selectedCode}
              onSelect={onSelect}
              parentContext={resolved}
              forcedOpen={forcedOpen}
            />
          ))}
        </div>
      )}
    </div>
  );
}

/* ── Small "copy to clipboard" button ─────────────────────────── */
function CopyButton({ value }: { value: string }) {
  const [done, setDone] = useState(false);
  const onCopy = async () => {
    try {
      await navigator.clipboard.writeText(value);
      setDone(true);
      setTimeout(() => setDone(false), 1400);
    } catch {
      /* ignore */
    }
  };
  return (
    <button
      type="button"
      onClick={onCopy}
      title="Скопировать код"
      className={cn(
        "inline-flex items-center gap-1.5 rounded-lg border px-2.5 py-1 text-[11px] font-medium transition",
        done
          ? "border-emerald-400/40 bg-emerald-400/10 text-emerald-300"
          : "border-white/10 bg-white/[0.04] text-[#8B92A8] hover:border-[#00F0FF]/40 hover:text-[#00F0FF]",
      )}
    >
      {done ? <Check size={11} /> : <Copy size={11} />}
      {done ? "Скопировано" : "Копировать код"}
    </button>
  );
}

/* ── Code detail (inline, compact) ─────────────────────────────── */
function InlineDetail({
  code,
  onBack,
  onShowInTree,
  onRecentPush,
}: {
  code: string;
  onBack: () => void;
  onShowInTree: (code: string) => void;
  onRecentPush: (code: string, title: string) => void;
}) {
  const [data, setData] = useState<CodeDetail | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    fetch(`${API}/api/codes/${code}`)
      .then((r) => r.json())
      .then((d) => {
        setData(d);
        const resolved = resolvedNomenclatureTitle(d?.code || code, d?.title_ru, d?.title_full);
        onRecentPush(d?.code || code, resolved);
      })
      .catch(() => setData(null))
      .finally(() => setLoading(false));
  }, [code, onRecentPush]);

  if (loading) {
    return (
      <div className="flex items-center justify-center py-10">
        <Loader2 size={16} className="animate-spin text-[#00F0FF]" />
      </div>
    );
  }

  if (!data) {
    return <p className="py-8 text-center text-sm text-[#4A5166]">Данные не найдены</p>;
  }

  const ownTitle = cleanTitle(data.title_ru);
  const pathResolved = (data.path ?? []).map((p) =>
    resolvedNomenclatureTitle(p.code, p.title_ru, p.title_full),
  );

  const displayName =
    (data.title_full && data.title_full.trim()) ||
    getLocalFullTitle(data.code) ||
    ownTitle ||
    (pathResolved.length >= 2
      ? `${pathResolved[pathResolved.length - 2]} — ${pathResolved[pathResolved.length - 1]}`
      : pathResolved[pathResolved.length - 1]) ||
    data.code;

  return (
    <div className="flex flex-col gap-4">
      <button
        type="button"
        onClick={onBack}
        className="flex items-center gap-1.5 text-[11px] text-[#4A5166] transition hover:text-white"
      >
        <ArrowLeft size={12} />
        Назад к дереву
      </button>

      <div
        className="rounded-xl border border-[#00F0FF]/20 bg-[#00F0FF]/[0.05] p-4"
        style={{ boxShadow: "0 0 24px rgba(0,240,255,0.07)" }}
      >
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <p className="text-[10px] uppercase tracking-widest text-[#00F0FF]/50">
              ТН ВЭД ЕАЭС
            </p>
            <p
              className="mt-1 font-mono text-2xl font-bold leading-none tracking-wider text-[#00F0FF]"
              style={{ textShadow: "0 0 10px rgba(0,240,255,0.5)" }}
            >
              {data.code}
            </p>
          </div>
          <div className="flex shrink-0 flex-col items-end gap-1.5">
            <CopyButton value={data.code} />
            <button
              type="button"
              onClick={() => onShowInTree(data.code)}
              className="inline-flex items-center gap-1.5 rounded-lg border border-white/10 bg-white/[0.04] px-2.5 py-1 text-[11px] font-medium text-[#8B92A8] transition hover:border-[#00F0FF]/40 hover:text-[#00F0FF]"
            >
              <CornerDownRight size={11} />
              Показать в дереве
            </button>
          </div>
        </div>
        <p className={cn("mt-3 text-[13px] leading-relaxed text-[#C8CDDC]", NOMENCLATURE_TEXT)}>
          {displayName}
        </p>
      </div>

      {data.path && data.path.length > 0 && (
        <div className="flex flex-col gap-1">
          <p className="text-[10px] uppercase tracking-widest text-[#4A5166]">
            Путь в номенклатуре
          </p>
          {data.path.map((p, i) => {
            const t = resolvedNomenclatureTitle(p.code, p.title_ru, p.title_full);
            return (
              <div key={p.code} className="flex items-start gap-2 py-0.5">
                <span className="mt-0.5 shrink-0 font-mono text-[11px] text-[#4A5166]">
                  {"  ".repeat(i)}
                  {p.code}
                </span>
                {t && (
                  <span
                    className={cn(
                      "text-[11px] leading-relaxed text-[#8B92A8]",
                      NOMENCLATURE_TEXT,
                    )}
                  >
                    {t}
                  </span>
                )}
              </div>
            );
          })}
        </div>
      )}

      {data.tariff && (
        <div>
          <p className="mb-2 text-[10px] uppercase tracking-widest text-[#4A5166]">
            Таможенные платежи
          </p>
          <div className="grid grid-cols-2 gap-2">
            <div className="rounded-xl border border-white/[0.06] bg-black/20 px-3 py-2.5">
              <div className="mb-1 flex items-center gap-1 text-[10px] uppercase tracking-wider text-[#4A5166]">
                <Percent size={11} />
                Пошлина
              </div>
              <span className="text-base font-bold text-[#00F0FF]">
                {data.tariff.duty ?? "—"}
              </span>
            </div>
            <div className="rounded-xl border border-white/[0.06] bg-black/20 px-3 py-2.5">
              <div className="mb-1 flex items-center gap-1 text-[10px] uppercase tracking-wider text-[#4A5166]">
                <Tag size={11} />
                НДС
              </div>
              <span className="text-base font-bold text-white">
                {data.tariff.vat != null ? `${data.tariff.vat}%` : "—"}
              </span>
            </div>
          </div>
          {data.tariff.vat_reason && (
            <p className="mt-1.5 text-[11px] text-[#4A5166]">
              Льгота: {data.tariff.vat_reason}
            </p>
          )}
        </div>
      )}
    </div>
  );
}

/* ── Search panel ────────────────────────────────────────────────── */
function SearchPanel({
  query,
  selectedCode,
  onSelect,
  onShowInTree,
}: {
  query: string;
  selectedCode: string | null;
  onSelect: (code: string) => void;
  onShowInTree: (code: string) => void;
}) {
  const [results, setResults] = useState<CodeNode[]>([]);
  const [loading, setLoading] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (!query.trim()) {
      setResults([]);
      return;
    }
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => {
      setLoading(true);
      fetch(`${API}/api/codes/search?q=${encodeURIComponent(query)}`)
        .then((r) => r.json())
        .then((d) => {
          const arr = Array.isArray(d) ? d.slice(0, 30) : [];
          setResults(mergeNodesWithLocalTitles(arr));
        })
        .catch(() => setResults([]))
        .finally(() => setLoading(false));
    }, 300);
  }, [query]);

  if (!query.trim()) return null;

  return (
    <div className="flex flex-col gap-1">
      {loading && (
        <div className="flex justify-center py-6">
          <Loader2 size={15} className="animate-spin text-[#00F0FF]" />
        </div>
      )}
      {!loading && results.length === 0 && (
        <p className="py-8 text-center text-sm text-[#4A5166]">
          По запросу «{query}» ничего не найдено
        </p>
      )}
      {results.map((r) => {
        const label = resolvedNomenclatureTitle(r.code, r.title_ru, r.title_full);
        const isSel = selectedCode === r.code;
        return (
          <div
            key={r.code}
            className={cn(
              "group flex items-start gap-3 rounded-lg px-3 py-3 transition",
              isSel ? "bg-[#00F0FF]/[0.09]" : "hover:bg-white/[0.04]",
            )}
          >
            <Hash size={13} className="mt-1 shrink-0 text-[#00F0FF]" />
            <button
              type="button"
              onClick={() => onSelect(r.code)}
              className="min-w-0 flex-1 text-left"
            >
              <span className="font-mono text-[12px] text-[#00F0FF]">
                <Highlight text={r.code} query={query} />
              </span>
              {label !== r.code && (
                <p
                  className={cn(
                    "mt-1.5 text-[12px] leading-relaxed text-[#8B92A8]",
                    NOMENCLATURE_TEXT,
                  )}
                >
                  <Highlight text={label} query={query} />
                </p>
              )}
            </button>
            <button
              type="button"
              onClick={() => onShowInTree(r.code)}
              title="Показать в дереве"
              className="shrink-0 self-start rounded-md border border-white/10 bg-white/[0.04] p-1.5 text-[#8B92A8] opacity-0 transition group-hover:opacity-100 hover:border-[#00F0FF]/40 hover:text-[#00F0FF]"
            >
              <CornerDownRight size={11} />
            </button>
          </div>
        );
      })}
    </div>
  );
}

/* ── Chapter tree panel ──────────────────────────────────────────── */
function TreePanel({
  selectedCode,
  onSelect,
  forcedOpen,
}: {
  selectedCode: string | null;
  onSelect: (code: string) => void;
  forcedOpen: Set<string>;
}) {
  const [chapters, setChapters] = useState<Chapter[]>([]);
  const [loading, setLoading] = useState(true);
  const [openChapters, setOpenChapters] = useState<Record<string, CodeNode[]>>({});
  const [loadingChapters, setLoadingChapters] = useState<Set<string>>(new Set());

  useEffect(() => {
    fetch(`${API}/api/codes/chapters`)
      .then((r) => r.json())
      .then((d) => setChapters(Array.isArray(d) ? d : []))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  const loadChapter = useCallback(async (code: string) => {
    setLoadingChapters((prev) => new Set(prev).add(code));
    try {
      const res = await fetch(
        `${API}/api/codes/children/${code}?group_next=true&include_tariff=false`,
      );
      const data = await res.json();
      const raw = Array.isArray(data) ? data : [];
      setOpenChapters((prev) => ({ ...prev, [code]: mergeNodesWithLocalTitles(raw) }));
    } catch {
      setOpenChapters((prev) => ({ ...prev, [code]: [] }));
    } finally {
      setLoadingChapters((prev) => {
        const n = new Set(prev);
        n.delete(code);
        return n;
      });
    }
  }, []);

  const toggleChapter = async (ch: Chapter) => {
    onSelect(ch.code);
    if (openChapters[ch.code]) {
      setOpenChapters((prev) => {
        const n = { ...prev };
        delete n[ch.code];
        return n;
      });
      return;
    }
    await loadChapter(ch.code);
  };

  // Программное раскрытие пути: если главе предписано открыться, а она ещё не открыта — открываем.
  useEffect(() => {
    for (const ch of chapters) {
      if (forcedOpen.has(ch.code) && !openChapters[ch.code] && !loadingChapters.has(ch.code)) {
        loadChapter(ch.code);
      }
    }
  }, [chapters, forcedOpen, openChapters, loadingChapters, loadChapter]);

  if (loading) {
    return (
      <div className="flex justify-center py-10">
        <Loader2 size={16} className="animate-spin text-[#00F0FF]" />
      </div>
    );
  }

  return (
    <div>
      {chapters.map((ch) => {
        const isOpen = ch.code in openChapters;
        const isChapSelected = selectedCode === ch.code;
        const isLoading = loadingChapters.has(ch.code);
        const chapterResolved = resolvedNomenclatureTitle(ch.code, ch.title_ru, ch.title_full);
        return (
          <div key={ch.code}>
            <button
              type="button"
              onClick={() => toggleChapter(ch)}
              className={cn(
                "flex w-full items-start gap-2.5 rounded-lg px-3 py-3.5 text-left transition",
                isChapSelected
                  ? "bg-white/[0.05] text-white"
                  : "text-[#8B92A8] hover:bg-white/[0.03] hover:text-[#C8CDDC]",
              )}
            >
              <div className="mt-0.5 flex shrink-0 items-center gap-2">
                {isLoading ? (
                  <Loader2 size={13} className="animate-spin text-[#4A5166]" />
                ) : isOpen ? (
                  <ChevronDown size={13} className="text-[#4A5166]" />
                ) : (
                  <ChevronRight size={13} className="text-[#4A5166]" />
                )}
                <span className="font-mono text-xs text-[#4A5166]">{ch.code}</span>
              </div>
              <span
                className={cn(
                  "min-w-0 flex-1 text-[12px] font-medium leading-relaxed text-[#C8CDDC]",
                  NOMENCLATURE_TEXT,
                )}
              >
                {chapterResolved}
              </span>
            </button>

            {isOpen && openChapters[ch.code].length > 0 && (
              <div className="ml-1 border-l border-white/[0.08] pl-2">
                {openChapters[ch.code].map((node) => (
                  <TreeNode
                    key={node.code}
                    node={node}
                    depth={1}
                    selectedCode={selectedCode}
                    onSelect={onSelect}
                    parentContext={chapterResolved}
                    forcedOpen={forcedOpen}
                  />
                ))}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

/* ── Recent codes block ──────────────────────────────────────────── */
function RecentCodesBlock({
  items,
  onSelect,
  onClear,
}: {
  items: RecentCode[];
  onSelect: (code: string) => void;
  onClear: () => void;
}) {
  if (!items.length) return null;
  return (
    <div className="mb-3 rounded-xl border border-white/[0.06] bg-white/[0.02] p-2.5">
      <div className="mb-1.5 flex items-center justify-between px-1">
        <p className="flex items-center gap-1.5 text-[10px] uppercase tracking-widest text-[#4A5166]">
          <Clock size={11} />
          Последние
        </p>
        <button
          type="button"
          onClick={onClear}
          title="Очистить историю"
          className="inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[10px] text-[#4A5166] transition hover:text-[#8B92A8]"
        >
          <Trash2 size={10} />
          Очистить
        </button>
      </div>
      <div className="flex flex-col gap-0.5">
        {items.map((r) => (
          <button
            key={r.code}
            type="button"
            onClick={() => onSelect(r.code)}
            className="flex items-start gap-2 rounded-md px-2 py-1.5 text-left hover:bg-white/[0.04]"
          >
            <span className="mt-0.5 shrink-0 font-mono text-[11px] text-[#00F0FF]">
              {r.code}
            </span>
            <span
              className={cn(
                "line-clamp-2 text-[11px] leading-snug text-[#8B92A8]",
                NOMENCLATURE_TEXT,
              )}
            >
              {r.title}
            </span>
          </button>
        ))}
      </div>
    </div>
  );
}

/* ── Main Drawer component ───────────────────────────────────────── */
type TnVedDrawerProps = {
  open: boolean;
  onClose: () => void;
};

function pathCodes(code: string): string[] {
  const d = (code || "").replace(/\D/g, "");
  const res: string[] = [];
  for (const n of [2, 4, 6, 8, 10]) {
    if (d.length >= n) res.push(d.slice(0, n));
  }
  return res;
}

export function TnVedDrawer({ open, onClose }: TnVedDrawerProps) {
  const [query, setQuery] = useState("");
  const [selectedCode, setSelectedCode] = useState<string | null>(null);
  const [showDetail, setShowDetail] = useState(false);
  const [forcedOpen, setForcedOpen] = useState<Set<string>>(new Set());
  const [recent, setRecent] = useState<RecentCode[]>([]);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (open) {
      setTimeout(() => inputRef.current?.focus(), 80);
      setRecent(readRecentCodes());
    } else {
      setQuery("");
      setShowDetail(false);
      setForcedOpen(new Set());
    }
  }, [open]);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape" && open) onClose();
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [open, onClose]);

  const handleSelectCode = (code: string) => {
    setSelectedCode(code);
    if (code.replace(/\D/g, "").length === 10) {
      setShowDetail(true);
    } else {
      setShowDetail(false);
    }
  };

  const handleShowInTree = useCallback((code: string) => {
    setQuery("");
    setShowDetail(false);
    setSelectedCode(code);
    setForcedOpen(new Set(pathCodes(code)));
  }, []);

  const handleRecentPush = useCallback((code: string, title: string) => {
    const next = pushRecentCode({ code, title });
    setRecent(next);
  }, []);

  const handleRecentClear = () => {
    clearRecentCodes();
    setRecent([]);
  };

  const isSearching = query.trim().length > 0;

  return (
    <>
      <div
        aria-hidden
        onClick={onClose}
        className={cn(
          "fixed inset-0 z-40 bg-black/60 backdrop-blur-sm transition-opacity duration-300",
          open ? "opacity-100 pointer-events-auto" : "opacity-0 pointer-events-none",
        )}
      />

      <div
        role="dialog"
        aria-modal="true"
        aria-label="Справочник ТН ВЭД ЕАЭС"
        className={cn(
          "fixed bottom-0 right-0 top-0 z-50 flex w-[42%] min-w-[400px] flex-col border-l border-white/[0.07] bg-[#0d0d1a] shadow-[−8px_0_48px_rgba(0,0,0,0.6)] transition-transform duration-300 ease-out",
          open ? "translate-x-0" : "translate-x-full",
        )}
      >
        <div className="flex shrink-0 items-center justify-between border-b border-white/[0.07] px-5 py-4">
          <div>
            <h2 className="text-sm font-semibold text-white">Справочник ТН ВЭД ЕАЭС</h2>
            <p className="text-[11px] text-[#4A5166]">21 раздел · 96 глав · 20 000+ кодов</p>
          </div>
          <div className="flex items-center gap-2">
            <span className="hidden items-center gap-1 rounded-md border border-white/[0.07] bg-white/[0.03] px-2 py-1 text-[10px] text-[#4A5166] sm:flex">
              <Keyboard size={10} />
              Esc — закрыть
            </span>
            <button
              onClick={onClose}
              className="flex h-7 w-7 items-center justify-center rounded-lg border border-white/[0.08] text-[#4A5166] transition hover:bg-white/[0.06] hover:text-white"
            >
              <X size={14} />
            </button>
          </div>
        </div>

        <div className="shrink-0 border-b border-white/[0.06] px-4 py-3">
          <div className="relative">
            <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[#4A5166]" />
            <input
              ref={inputRef}
              value={query}
              onChange={(e) => {
                setQuery(e.target.value);
                setShowDetail(false);
              }}
              placeholder="Поиск по коду или наименованию товара…"
              className="w-full rounded-xl border border-white/[0.09] bg-black/30 py-2.5 pl-9 pr-8 text-sm text-white placeholder-[#4A5166] outline-none transition focus:border-[#00F0FF]/40 focus:ring-1 focus:ring-[#00F0FF]/15"
            />
            {query && (
              <button
                onClick={() => {
                  setQuery("");
                  setShowDetail(false);
                }}
                className="absolute right-3 top-1/2 -translate-y-1/2 text-[#4A5166] transition hover:text-white"
              >
                <X size={13} />
              </button>
            )}
          </div>
        </div>

        <div className="flex-1 overflow-y-auto">
          {showDetail && selectedCode ? (
            <div className="p-4">
              <InlineDetail
                key={selectedCode}
                code={selectedCode}
                onBack={() => setShowDetail(false)}
                onShowInTree={handleShowInTree}
                onRecentPush={handleRecentPush}
              />
            </div>
          ) : (
            <div className="p-2">
              {isSearching ? (
                <>
                  <p className="px-3 py-2 text-[10px] uppercase tracking-widest text-[#4A5166]">
                    Результаты
                  </p>
                  <SearchPanel
                    query={query}
                    selectedCode={selectedCode}
                    onSelect={handleSelectCode}
                    onShowInTree={handleShowInTree}
                  />
                </>
              ) : (
                <>
                  <RecentCodesBlock
                    items={recent}
                    onSelect={handleSelectCode}
                    onClear={handleRecentClear}
                  />
                  <p className="px-3 py-2 text-[10px] uppercase tracking-widest text-[#4A5166]">
                    Дерево номенклатуры
                  </p>
                  <TreePanel
                    selectedCode={selectedCode}
                    onSelect={handleSelectCode}
                    forcedOpen={forcedOpen}
                  />
                </>
              )}
            </div>
          )}
        </div>

        <div className="shrink-0 border-t border-white/[0.05] px-5 py-2.5">
          <p className="text-[10px] text-[#2A2E3E]">
            Нажмите на 10-значный код для просмотра тарифа и НДС · Cmd/Ctrl+K — быстрый вызов
          </p>
        </div>
      </div>
    </>
  );
}
