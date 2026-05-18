import { useCallback, useEffect, useRef, useState } from "react";
import {
  ChevronRight,
  Search,
  X,
  ArrowLeft,
  ExternalLink,
  Tag,
  Percent,
  Info,
  Loader2,
  Hash,
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
import { Copy, Check, Clock, Trash2, CornerDownRight } from "lucide-react";

const API = import.meta.env.VITE_API_BASE_URL || "";

const NOMENCLATURE_TEXT =
  "whitespace-normal break-words text-left [overflow-wrap:anywhere] hyphens-auto";

/* ── Types ───────────────────────────────────────────────────────── */
type Section = {
  name: string;
  chapters: string[];
};
type Chapter = {
  code: string;
  title_ru: string;
  title_full?: string | null;
};
type CodeNode = {
  code: string;
  title_ru: string | null;
  title_full?: string | null;
  level?: string;
  parent?: string;
  has_children?: boolean;
  tariff?: {
    duty?: string;
    vat?: number | string;
    vat_reason?: string;
    add?: string;
  };
  children?: CodeNode[];
};
type CodeDetail = CodeNode & {
  path: { code: string; title_ru: string | null; title_full?: string | null; level: string }[];
};

function Highlight({ text, query }: { text: string; query: string }) {
  const chunks = buildHighlightChunks(text, query);
  return (
    <>
      {chunks.map((c, i) =>
        c.match ? (
          <mark key={i} className="rounded-sm bg-[#00F0FF]/20 px-0.5 text-[#00F0FF]">
            {c.text}
          </mark>
        ) : (
          <span key={i}>{c.text}</span>
        ),
      )}
    </>
  );
}

function pathCodes(code: string): string[] {
  const d = (code || "").replace(/\D/g, "");
  const res: string[] = [];
  for (const n of [2, 4, 6, 8, 10]) {
    if (d.length >= n) res.push(d.slice(0, n));
  }
  return res;
}

function CopyCodeButton({ value }: { value: string }) {
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

/* ── Section icons (emoji) ───────────────────────────────────────── */
const SECTION_ICON: Record<string, string> = {
  I: "🐄", II: "🌾", III: "🫙", IV: "🍷", V: "⛏️", VI: "🧪",
  VII: "🧴", VIII: "👜", IX: "🪵", X: "📄", XI: "🧵", XII: "👟",
  XIII: "🏺", XIV: "💎", XV: "⚙️", XVI: "🔌", XVII: "🚗", XVIII: "🔭",
  XIX: "🎯", XX: "🛋️", XXI: "🖼️",
};

const SECTION_ORDER = [
  "I","II","III","IV","V","VI","VII","VIII","IX","X",
  "XI","XII","XIII","XIV","XV","XVI","XVII","XVIII","XIX","XX","XXI",
];

/* ── Level label ─────────────────────────────────────────────────── */
function levelLabel(code: string) {
  const L = code.replace(/\D/g, "").length;
  if (L <= 2) return "Глава";
  if (L === 4) return "Позиция";
  if (L === 6) return "Субпозиция";
  return "Товар";
}

/* ── Small components ────────────────────────────────────────────── */
function Spinner() {
  return <Loader2 size={16} className="animate-spin text-[#00F0FF]" />;
}

function EmptyMsg({ text }: { text: string }) {
  return <p className="py-8 text-center text-sm text-[#4A5166]">{text}</p>;
}

/* ── Code Detail Panel ───────────────────────────────────────────── */
function DetailPanel({
  code,
  onClose,
  onRecentPush,
}: {
  code: string;
  onClose: () => void;
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
        const resolved = resolvedNomenclatureTitle(
          d?.code || code,
          d?.title_ru,
          d?.title_full,
        );
        onRecentPush(d?.code || code, resolved);
      })
      .catch(() => setData(null))
      .finally(() => setLoading(false));
  }, [code, onRecentPush]);

  return (
    <div className="flex h-full flex-col overflow-hidden rounded-2xl border border-white/[0.07] bg-white/[0.03]">
      {/* Header */}
      <div className="flex shrink-0 items-center justify-between border-b border-white/[0.06] px-4 py-3">
        <div className="flex items-center gap-2">
          <Hash size={14} className="text-[#00F0FF]" />
          <span className="text-[11px] font-semibold uppercase tracking-widest text-[#4A5166]">
            Справка по коду
          </span>
        </div>
        <button
          onClick={onClose}
          className="rounded-lg p-1 text-[#4A5166] transition hover:bg-white/[0.06] hover:text-white"
        >
          <X size={14} />
        </button>
      </div>

      <div className="flex-1 overflow-y-auto p-4">
        {loading ? (
          <div className="flex items-center justify-center py-12">
            <Spinner />
          </div>
        ) : !data ? (
          <EmptyMsg text="Данные не найдены" />
        ) : (
          <div className="flex flex-col gap-4">
            {/* HS code + title */}
            <div
              className="rounded-xl border border-[#00F0FF]/20 bg-[#00F0FF]/[0.05] p-4"
              style={{ boxShadow: "0 0 20px rgba(0,240,255,0.06)" }}
            >
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <p className="text-[10px] uppercase tracking-widest text-[#00F0FF]/60">
                    ТН ВЭД ЕАЭС
                  </p>
                  <p
                    className="mt-1 font-mono text-2xl font-bold tracking-wider text-[#00F0FF]"
                    style={{ textShadow: "0 0 10px rgba(0,240,255,0.5)" }}
                  >
                    {data.code}
                  </p>
                </div>
                <CopyCodeButton value={data.code} />
              </div>
              {(() => {
                const own = cleanTitle(data.title_ru);
                const pathTitles = (data.path ?? [])
                  .map((p) => resolvedNomenclatureTitle(p.code, p.title_ru, p.title_full))
                  .filter(Boolean);
                const displayName =
                  (data.title_full && data.title_full.trim()) ||
                  getLocalFullTitle(data.code) ||
                  own ||
                  (pathTitles.length >= 2
                    ? `${pathTitles[pathTitles.length - 2]} — ${pathTitles[pathTitles.length - 1]}`
                    : pathTitles[pathTitles.length - 1]) ||
                  null;
                return displayName ? (
                  <p
                    className={cn(
                      "mt-3 text-sm leading-relaxed text-[#C8CDDC]",
                      NOMENCLATURE_TEXT,
                    )}
                  >
                    {displayName}
                  </p>
                ) : null;
              })()}
              <span className="mt-2 inline-block rounded-md border border-white/[0.08] bg-white/[0.04] px-2 py-0.5 text-[10px] text-[#8B92A8]">
                {levelLabel(data.code)}
              </span>
            </div>

            {/* Breadcrumb path */}
            {data.path && data.path.length > 0 && (
              <div>
                <p className="mb-2 text-[10px] uppercase tracking-widest text-[#4A5166]">Путь в номенклатуре</p>
                <div className="flex flex-col gap-1">
                  {data.path.map((p, i) => {
                    const t = resolvedNomenclatureTitle(p.code, p.title_ru, p.title_full);
                    return (
                      <div key={p.code} className="flex items-start gap-2 py-0.5">
                        <span className="mt-0.5 shrink-0 font-mono text-xs text-[#4A5166]">
                          {"  ".repeat(i)}{p.code}
                        </span>
                        {t && (
                          <span className={cn("text-xs leading-relaxed text-[#8B92A8]", NOMENCLATURE_TEXT)}>
                            {t}
                          </span>
                        )}
                      </div>
                    );
                  })}
                </div>
              </div>
            )}

            {/* Tariff block — only for 10-digit codes */}
            {data.tariff && (
              <div>
                <p className="mb-2 text-[10px] uppercase tracking-widest text-[#4A5166]">Таможенные платежи</p>
                <div className="grid grid-cols-2 gap-2">
                  <TariffCell
                    icon={<Percent size={13} />}
                    label="Ввозная пошлина"
                    value={data.tariff.duty || "—"}
                    accent="cyan"
                  />
                  <TariffCell
                    icon={<Tag size={13} />}
                    label="НДС"
                    value={data.tariff.vat != null ? `${data.tariff.vat}%` : "—"}
                    accent="default"
                  />
                  {data.tariff.add && (
                    <TariffCell
                      icon={<Info size={13} />}
                      label="Доп. сбор"
                      value={data.tariff.add}
                      accent="amber"
                      className="col-span-2"
                    />
                  )}
                </div>
                {data.tariff.vat_reason && (
                  <p className="mt-2 text-[11px] text-[#4A5166]">
                    Основание льготной ставки НДС: {data.tariff.vat_reason}
                  </p>
                )}
              </div>
            )}

            {/* Children if any */}
            {data.children && data.children.length > 0 && (
              <div>
                <p className="mb-2 text-[10px] uppercase tracking-widest text-[#4A5166]">
                  Дочерние коды ({data.children.length})
                </p>
                <div className="flex flex-col gap-2">
                  {mergeNodesWithLocalTitles(data.children.slice(0, 20)).map((c) => {
                    const t = resolvedNomenclatureTitle(c.code, c.title_ru, c.title_full);
                    return (
                      <div
                        key={c.code}
                        className="flex flex-col items-start gap-1 rounded-lg border border-white/[0.06] bg-black/20 px-3 py-3 text-xs sm:flex-row sm:gap-3"
                      >
                        <span className="shrink-0 font-mono text-[#00F0FF]">{c.code}</span>
                        {t && (
                          <span className={cn("text-[#8B92A8]", NOMENCLATURE_TEXT)}>{t}</span>
                        )}
                      </div>
                    );
                  })}
                  {data.children.length > 20 && (
                    <p className="text-[11px] text-[#4A5166]">
                      и ещё {data.children.length - 20} позиций…
                    </p>
                  )}
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

function TariffCell({
  icon, label, value, accent, className,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  accent: "cyan" | "amber" | "default";
  className?: string;
}) {
  const color =
    accent === "cyan" ? "text-[#00F0FF]"
    : accent === "amber" ? "text-[#FFA502]"
    : "text-white";
  return (
    <div className={cn("rounded-xl border border-white/[0.06] bg-black/20 px-3 py-2.5", className)}>
      <div className="mb-1 flex items-center gap-1 text-[#4A5166]">
        {icon}
        <span className="text-[10px] uppercase tracking-wider">{label}</span>
      </div>
      <span className={cn("text-base font-bold tabular-nums", color)}>{value}</span>
    </div>
  );
}

/* ── Code Row (in list) ──────────────────────────────────────────── */
function CodeRow({
  node,
  depth = 0,
  onSelect,
  selected,
  parentContext,
  forcedOpen,
}: {
  node: CodeNode;
  depth?: number;
  onSelect: (code: string) => void;
  selected: string | null;
  parentContext?: string | null;
  forcedOpen?: Set<string>;
}) {
  const [open, setOpen] = useState(false);
  const [children, setChildren] = useState<CodeNode[]>([]);
  const [loading, setLoading] = useState(false);
  const isLeaf = node.code.replace(/\D/g, "").length >= 10 || node.has_children === false;
  const isSelected = selected === node.code;
  const resolved = resolvedNomenclatureTitle(node.code, node.title_ru, node.title_full);
  const showTitle = resolved !== node.code;
  const otherCtx =
    parentContext &&
    isGenericOtherTitle(resolved) &&
    !resolved.includes("—") &&
    parentContextLine(parentContext);

  const loadChildren = useCallback(async () => {
    if (children.length > 0) return;
    setLoading(true);
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
      setLoading(false);
    }
  }, [children.length, node.code]);

  const toggle = async () => {
    if (isLeaf) {
      onSelect(node.code);
      return;
    }
    if (!open) await loadChildren();
    setOpen((v) => !v);
    if (!isLeaf) onSelect(node.code);
  };

  useEffect(() => {
    if (!forcedOpen) return;
    if (!isLeaf && forcedOpen.has(node.code) && !open) {
      loadChildren().then(() => setOpen(true));
    }
  }, [forcedOpen, isLeaf, node.code, open, loadChildren]);

  const hasChildren = !isLeaf;
  const indentPx = 12 + depth * 18;

  return (
    <div>
      <button
        type="button"
        onClick={toggle}
        className={cn(
          "group flex w-full items-start gap-2.5 rounded-lg px-3 py-3.5 text-left text-sm transition-all",
          isSelected
            ? "bg-[#00F0FF]/[0.08] text-white"
            : "text-[#8B92A8] hover:bg-white/[0.04] hover:text-[#C8CDDC]",
        )}
        style={{ paddingLeft: `${indentPx}px` }}
      >
        {hasChildren ? (
          <ChevronRight
            size={13}
            className={cn(
              "mt-1 shrink-0 transition-transform",
              open && "rotate-90",
              isSelected ? "text-[#00F0FF]" : "text-[#4A5166]",
            )}
          />
        ) : (
          <span className="mt-1 h-3 w-3 shrink-0" />
        )}
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span
              className={cn(
                "font-mono text-xs",
                isSelected ? "text-[#00F0FF]" : "text-[#4A5166] group-hover:text-[#8B92A8]",
              )}
            >
              {node.code}
            </span>
            {isLeaf && node.tariff?.duty && (
              <span className="rounded border border-[#00F0FF]/15 bg-[#00F0FF]/[0.06] px-1.5 py-0.5 text-[10px] text-[#00F0FF]">
                {node.tariff.duty}
              </span>
            )}
            {loading && <Loader2 size={11} className="animate-spin text-[#4A5166]" />}
          </div>
          {otherCtx && (
            <p className="mt-1.5 border-l-2 border-[#00F0FF]/35 pl-2.5 text-[10px] uppercase tracking-wide text-[#5A6278]">
              В группе: <span className="font-medium normal-case text-[#8B92A8]">{otherCtx}</span>
            </p>
          )}
          {showTitle && (
            <p className={cn("mt-1.5 text-xs leading-relaxed", NOMENCLATURE_TEXT)}>
              {resolved}
            </p>
          )}
        </div>
      </button>

      {open && children.length > 0 && (
        <div className="ml-2 border-l border-white/[0.08] pl-2">
          {children.map((ch) => (
            <CodeRow
              key={ch.code}
              node={ch}
              depth={depth + 1}
              onSelect={onSelect}
              selected={selected}
              parentContext={resolved}
              forcedOpen={forcedOpen}
            />
          ))}
        </div>
      )}
    </div>
  );
}

/* ── Chapter code list ───────────────────────────────────────────── */
function ChapterCodes({
  chapterCode,
  chapterResolvedTitle,
  selectedCode,
  onSelect,
  forcedOpen,
}: {
  chapterCode: string;
  chapterResolvedTitle: string;
  selectedCode: string | null;
  onSelect: (code: string) => void;
  forcedOpen: Set<string>;
}) {
  const [nodes, setNodes] = useState<CodeNode[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    fetch(`${API}/api/codes/children/${chapterCode}?group_next=true&include_tariff=false`)
      .then((r) => r.json())
      .then((d) => {
        const raw = Array.isArray(d) ? d : [];
        setNodes(mergeNodesWithLocalTitles(raw));
      })
      .catch(() => setNodes([]))
      .finally(() => setLoading(false));
  }, [chapterCode]);

  if (loading) {
    return (
      <div className="flex items-center justify-center py-10">
        <Spinner />
      </div>
    );
  }

  if (nodes.length === 0) {
    return <EmptyMsg text="Нет данных для этой главы" />;
  }

  return (
    <div>
      {nodes.map((n) => (
        <CodeRow
          key={n.code}
          node={n}
          depth={0}
          onSelect={onSelect}
          selected={selectedCode}
          parentContext={chapterResolvedTitle}
          forcedOpen={forcedOpen}
        />
      ))}
    </div>
  );
}

/* ── Search results ──────────────────────────────────────────────── */
function SearchResults({
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
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (!query.trim()) {
      setResults([]);
      return;
    }
    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = setTimeout(() => {
      setLoading(true);
      fetch(`${API}/api/codes/search?q=${encodeURIComponent(query)}`)
        .then((r) => r.json())
        .then((d) => {
          const raw = Array.isArray(d) ? d : [];
          setResults(mergeNodesWithLocalTitles(raw));
        })
        .catch(() => setResults([]))
        .finally(() => setLoading(false));
    }, 350);
  }, [query]);

  if (!query.trim()) return null;

  return (
    <div className="flex flex-col gap-1">
      {loading && (
        <div className="flex items-center justify-center py-6">
          <Spinner />
        </div>
      )}
      {!loading && results.length === 0 && (
        <EmptyMsg text={`По запросу «${query}» ничего не найдено`} />
      )}
      {results.map((r) => {
        const label = resolvedNomenclatureTitle(r.code, r.title_ru, r.title_full);
        const isSel = selectedCode === r.code;
        return (
          <div
            key={r.code}
            className={cn(
              "group flex items-start gap-3 rounded-lg px-3 py-3 transition",
              isSel ? "bg-[#00F0FF]/[0.08]" : "hover:bg-white/[0.04]",
            )}
          >
            <button
              type="button"
              onClick={() => onSelect(r.code)}
              className="flex min-w-0 flex-1 items-start gap-3 text-left"
            >
              <span className="mt-1 shrink-0 font-mono text-xs text-[#00F0FF]">
                <Highlight text={r.code} query={query} />
              </span>
              {label !== r.code && (
                <span className={cn("text-xs leading-relaxed text-[#8B92A8]", NOMENCLATURE_TEXT)}>
                  <Highlight text={label} query={query} />
                </span>
              )}
            </button>
            <button
              type="button"
              onClick={() => onShowInTree(r.code)}
              title="Показать в дереве"
              className="mt-0.5 shrink-0 rounded-md border border-white/10 bg-white/[0.04] p-1.5 text-[#8B92A8] opacity-0 transition group-hover:opacity-100 hover:border-[#00F0FF]/40 hover:text-[#00F0FF]"
            >
              <CornerDownRight size={11} />
            </button>
          </div>
        );
      })}
    </div>
  );
}

/* ── Chapter list (extracted to avoid TS narrowing issue) ────────── */
function ChapterList({
  chaps,
  activeChapter,
  onChapterClick,
}: {
  chaps: Chapter[];
  activeChapter: Chapter | null;
  onChapterClick: (ch: Chapter) => void;
}) {
  return (
    <div className="mb-1 ml-2">
      {chaps.map((ch) => (
        <button
          key={ch.code}
          type="button"
          onClick={() => onChapterClick(ch)}
          className={cn(
            "flex w-full items-start gap-2.5 rounded-lg px-3 py-3 text-left transition",
            activeChapter?.code === ch.code
              ? "bg-[#00F0FF]/[0.08] text-white"
              : "text-[#8B92A8] hover:bg-white/[0.04] hover:text-[#C8CDDC]",
          )}
        >
          <span className="mt-0.5 shrink-0 font-mono text-xs text-[#00F0FF]">{ch.code}</span>
          <span className={cn("min-w-0 flex-1 text-xs leading-relaxed", NOMENCLATURE_TEXT)}>
            {resolvedNomenclatureTitle(ch.code, ch.title_ru, ch.title_full)}
          </span>
          <ExternalLink size={10} className="mt-1 shrink-0 text-[#4A5166]" />
        </button>
      ))}
    </div>
  );
}

/* ── Main TnvedPage ──────────────────────────────────────────────── */
export default function TnvedPage() {
  const [sections, setSections] = useState<Record<string, Section>>({});
  const [chapters, setChapters] = useState<Chapter[]>([]);
  const [query, setQuery] = useState("");
  const [activeSection, setActiveSection] = useState<string | null>(null);
  const [activeChapter, setActiveChapter] = useState<Chapter | null>(null);
  const [selectedCode, setSelectedCode] = useState<string | null>(null);
  const [forcedOpen, setForcedOpen] = useState<Set<string>>(new Set());
  const [recent, setRecent] = useState<RecentCode[]>([]);
  const searchRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    fetch(`${API}/api/codes/sections`)
      .then((r) => r.json())
      .then(setSections)
      .catch(() => {});

    fetch(`${API}/api/codes/chapters`)
      .then((r) => r.json())
      .then((d) => setChapters(Array.isArray(d) ? d : []))
      .catch(() => {});

    setRecent(readRecentCodes());
  }, []);

  const chaptersForSection = useCallback(
    (sectionKey: string): Chapter[] => {
      const sec = sections[sectionKey];
      if (!sec) return [];
      return chapters.filter((c) => sec.chapters.includes(c.code));
    },
    [sections, chapters],
  );

  const isSearching = query.trim().length > 0;

  const handleSelectCode = (code: string) => {
    setSelectedCode(code);
  };

  const handleChapterClick = (ch: Chapter) => {
    setActiveChapter(ch);
    setSelectedCode(ch.code);
    setQuery("");
  };

  const handleShowInTree = useCallback(
    (code: string) => {
      setQuery("");
      const chap = code.replace(/\D/g, "").slice(0, 2);
      const section = Object.keys(sections).find((k) =>
        sections[k].chapters.includes(chap),
      );
      if (section) setActiveSection(section);
      const chapObj = chapters.find((c) => c.code === chap);
      if (chapObj) setActiveChapter(chapObj);
      setSelectedCode(code);
      setForcedOpen(new Set(pathCodes(code)));
    },
    [sections, chapters],
  );

  const handleRecentPush = useCallback((code: string, title: string) => {
    setRecent(pushRecentCode({ code, title }));
  }, []);

  const handleRecentClear = () => {
    clearRecentCodes();
    setRecent([]);
  };

  return (
    <div className="flex h-full flex-col overflow-hidden">
      {/* ── Top bar ── */}
      <div className="shrink-0 border-b border-white/[0.06] bg-[#080810]/80 px-6 py-4 backdrop-blur-sm">
        <div className="flex items-center justify-between gap-4">
          <div>
            <h1 className="text-sm font-semibold text-white">Дерево ТН ВЭД ЕАЭС</h1>
            <p className="text-[11px] text-[#4A5166]">
              {Object.keys(sections).length} разделов · {chapters.length} глав · 20 000+ кодов
            </p>
          </div>
          {activeChapter && !isSearching && (
            <button
              type="button"
              onClick={() => { setActiveChapter(null); setSelectedCode(null); }}
              className="flex items-center gap-1.5 rounded-lg border border-white/[0.08] px-3 py-1.5 text-xs text-[#8B92A8] transition hover:text-white"
            >
              <ArrowLeft size={12} />
              К разделам
            </button>
          )}
        </div>

        {/* Search */}
        <div className="relative mt-3">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[#4A5166]" />
          <input
            ref={searchRef}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Поиск по коду или наименованию товара…"
            className="w-full rounded-xl border border-white/[0.08] bg-black/30 py-2.5 pl-9 pr-8 text-sm text-white placeholder-[#4A5166] outline-none transition focus:border-[#00F0FF]/40 focus:ring-1 focus:ring-[#00F0FF]/20"
          />
          {query && (
            <button
              onClick={() => setQuery("")}
              className="absolute right-3 top-1/2 -translate-y-1/2 text-[#4A5166] transition hover:text-white"
            >
              <X size={13} />
            </button>
          )}
        </div>
      </div>

      {/* ── Body: 2-column ── */}
      <div className="flex flex-1 gap-4 overflow-hidden p-4">
        {/* Left: Section/Chapter browser or search results */}
        <div className="flex w-[min(420px,44vw)] shrink-0 flex-col overflow-hidden rounded-2xl border border-white/[0.07] bg-white/[0.02]">
          <div className="flex-1 overflow-y-auto">
            {isSearching ? (
              /* Search results */
              <div className="p-2">
                <p className="px-3 py-2 text-[10px] uppercase tracking-widest text-[#4A5166]">
                  Результаты поиска
                </p>
                <SearchResults
                  query={query}
                  selectedCode={selectedCode}
                  onSelect={handleSelectCode}
                  onShowInTree={handleShowInTree}
                />
              </div>
            ) : activeChapter ? (
              /* Chapter drill-down */
              <div>
                <div className="sticky top-0 border-b border-white/[0.06] bg-[#080810]/90 px-4 py-3 backdrop-blur-sm">
                  <p className="text-[10px] uppercase tracking-widest text-[#4A5166]">
                    Глава {activeChapter.code}
                  </p>
                  <p className={cn("mt-0.5 text-xs font-medium leading-relaxed text-[#C8CDDC]", NOMENCLATURE_TEXT)}>
                    {resolvedNomenclatureTitle(
                      activeChapter.code,
                      activeChapter.title_ru,
                      activeChapter.title_full,
                    )}
                  </p>
                </div>
                <div className="p-2">
                  <ChapterCodes
                    chapterCode={activeChapter.code}
                    chapterResolvedTitle={resolvedNomenclatureTitle(
                      activeChapter.code,
                      activeChapter.title_ru,
                      activeChapter.title_full,
                    )}
                    selectedCode={selectedCode}
                    onSelect={handleSelectCode}
                    forcedOpen={forcedOpen}
                  />
                </div>
              </div>
            ) : (
              /* Section/Chapter browser */
              <div className="p-2">
                {recent.length > 0 && (
                  <div className="mb-3 rounded-xl border border-white/[0.06] bg-white/[0.02] p-2.5">
                    <div className="mb-1.5 flex items-center justify-between px-1">
                      <p className="flex items-center gap-1.5 text-[10px] uppercase tracking-widest text-[#4A5166]">
                        <Clock size={11} />
                        Последние
                      </p>
                      <button
                        type="button"
                        onClick={handleRecentClear}
                        title="Очистить историю"
                        className="inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[10px] text-[#4A5166] transition hover:text-[#8B92A8]"
                      >
                        <Trash2 size={10} />
                        Очистить
                      </button>
                    </div>
                    <div className="flex flex-col gap-0.5">
                      {recent.map((r) => (
                        <button
                          key={r.code}
                          type="button"
                          onClick={() => handleShowInTree(r.code)}
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
                )}
                {SECTION_ORDER.filter((k) => sections[k]).map((key) => {
                  const sec = sections[key];
                  const chaps: Chapter[] = chaptersForSection(key);
                  const isActive = activeSection === key;
                  return (
                    <div key={key}>
                      <button
                        type="button"
                        onClick={() => setActiveSection(isActive ? null : key)}
                        className={cn(
                          "group flex w-full items-center gap-2.5 rounded-lg px-3 py-2.5 text-left transition",
                          isActive ? "bg-white/[0.05] text-white" : "text-[#8B92A8] hover:bg-white/[0.03] hover:text-[#C8CDDC]",
                        )}
                      >
                        <span className="text-base">{SECTION_ICON[key] ?? "📦"}</span>
                        <div className="min-w-0 flex-1">
                          <div className="flex items-center gap-1.5">
                            <span className="shrink-0 text-[10px] font-bold text-[#4A5166]">
                              Раздел {key}
                            </span>
                            <span className="rounded border border-white/[0.06] bg-white/[0.04] px-1 py-0.5 text-[9px] text-[#4A5166]">
                              {chaps.length} гл.
                            </span>
                          </div>
                          <p className={cn("text-xs leading-snug", NOMENCLATURE_TEXT)}>{sec.name}</p>
                        </div>
                        <ChevronRight
                          size={13}
                          className={cn(
                            "shrink-0 text-[#4A5166] transition-transform",
                            isActive && "rotate-90",
                          )}
                        />
                      </button>

                      {/* Chapters under this section */}
                      {isActive && (
                        <ChapterList
                          chaps={chaps}
                          activeChapter={activeChapter}
                          onChapterClick={handleChapterClick}
                        />
                      )}
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </div>

        {/* Right: Detail panel */}
        <div className="flex-1 overflow-hidden">
          {selectedCode ? (
            <DetailPanel
              key={selectedCode}
              code={selectedCode}
              onClose={() => setSelectedCode(null)}
              onRecentPush={handleRecentPush}
            />
          ) : (
            <div className="flex h-full flex-col items-center justify-center gap-4 rounded-2xl border border-dashed border-white/[0.07] bg-white/[0.015] text-center">
              <div className="flex h-14 w-14 items-center justify-center rounded-2xl border border-white/[0.08] bg-white/[0.04] text-2xl">
                🔍
              </div>
              <div>
                <p className="text-sm font-medium text-[#C8CDDC]">Выберите код</p>
                <p className="mt-1 text-xs text-[#4A5166]">
                  Раскройте раздел → главу → позицию,<br />
                  или воспользуйтесь поиском
                </p>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
