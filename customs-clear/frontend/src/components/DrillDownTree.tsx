import React from 'react';
import { Search } from 'lucide-react';
import { AnimatePresence, motion } from 'framer-motion';
import {
  fetchTnvedBreadcrumb,
  fetchTnvedChildren,
  formatCode,
  isFullTnvedCode,
  searchTnved,
  type TnvedBreadcrumbItem,
  type TnvedChildItem,
  type TnvedSearchHit,
} from '../api/tnvedCatalog';
import { PremiumCard } from './PremiumCard';
import { HierarchyView } from './tnved/HierarchyView';
import { RateBadges } from './tnved/RateBadges';
import { formatTnvedCommodityName, TNVED_COMMODITY_NAME_CLASS } from '../utils/tnvedDisplayText';
import { normalizeDutyRate } from '../utils/dutyRate';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type DrillLevel = 'root' | 'section' | 'chapter' | 'heading' | 'subheading' | 'leaf';

export type PathSegment = {
  code: string;
  label: string;
  name?: string;
  level: DrillLevel;
  sectionId?: number;
  chapterId?: number;
};

export type DrillNode = {
  code: string;
  name: string;
  displayCode: string;
  level: DrillLevel;
  sectionId?: number;
  chapterId?: number;
  importDuty?: string;
  vatRate?: number | null;
  hasChildren: boolean;
  isLeaf: boolean;
  isCodeless?: boolean;
};

type Props = {
  selectedCode: string | null;
  onSelectCode: (code: string) => void;
  initialSearchQuery?: string;
};

const DEBOUNCE_MS = 300;

function digitsOnly(s: string): string {
  return s.replace(/\D/g, '');
}

function isRomanSection(code: string): boolean {
  return /^[IVXLCDM]+$/i.test(code.trim());
}

function inferLevel(code: string): DrillLevel {
  if (isRomanSection(code)) return 'section';
  const d = digitsOnly(code);
  if (d.length <= 2) return 'chapter';
  if (d.length <= 4) return 'heading';
  if (d.length <= 6) return 'subheading';
  return 'leaf';
}

function displayCodeFor(code: string, level: DrillLevel): string {
  if (level === 'section') return code;
  if (level === 'chapter') return code;
  return formatCode(digitsOnly(code));
}

function childToDrillNode(item: TnvedChildItem, sectionId?: number): DrillNode {
  const level = (item.level as DrillLevel) || inferLevel(item.code);
  const duty = normalizeDutyRate(item.duty_rate || item.import_duty);
  return {
    code: item.code,
    name: item.name || '',
    displayCode: item.display_code || displayCodeFor(item.code, level),
    level,
    sectionId: item.section_id ?? sectionId,
    chapterId: item.chapter_id,
    importDuty: duty || undefined,
    vatRate: item.vat_rate,
    hasChildren: item.has_children,
    isLeaf: item.is_leaf,
    isCodeless: item.is_codeless,
  };
}

function drillNodeToPathSegment(node: DrillNode): PathSegment {
  const label =
    node.level === 'section'
      ? `Раздел ${node.code}`
      : node.level === 'chapter'
        ? `Группа ${node.code}`
        : node.displayCode;
  return {
    code: node.code,
    label,
    name: (node.name || '').trim() || undefined,
    level: node.level,
    sectionId: node.sectionId,
    chapterId: node.chapterId,
  };
}

function depthLabel(path: PathSegment[], sectionCount: number, itemCount?: number): string {
  if (path.length === 0) {
    const count = itemCount ?? sectionCount;
    return `Разделы · ${count}`;
  }
  const last = path[path.length - 1]?.level;
  let base: string;
  if (last === 'section') base = 'Группы';
  else if (last === 'chapter') base = 'Позиции';
  else if (last === 'heading') base = 'Субпозиции';
  else base = 'Субпозиции — листья';
  return itemCount != null ? `${base} · ${itemCount}` : base;
}

function levelHeaderTitle(segment: PathSegment): string {
  if (segment.level === 'section') return `Раздел ${segment.code}`;
  if (segment.level === 'chapter') return `Группа ${segment.code}`;
  return segment.label;
}

function DrillLevelHeader({ segment, depthText }: { segment: PathSegment; depthText: string }) {
  return (
    <div className="mb-2 flex flex-wrap items-end justify-between gap-2 border-b border-cargo-border/50 pb-2">
      <div className="min-w-0">
        <p className="font-mono text-base font-semibold text-cargo-deep">{levelHeaderTitle(segment)}</p>
        {segment.name ? (
          <p className={`mt-0.5 text-[12px] uppercase tracking-wide text-cargo-mid ${TNVED_COMMODITY_NAME_CLASS}`}>
            {formatTnvedCommodityName(segment.name)}
          </p>
        ) : null}
      </div>
      <span className="shrink-0 text-[11px] font-medium uppercase tracking-[0.06em] text-cargo-light">{depthText}</span>
    </div>
  );
}

function formatBreadcrumbPath(items: TnvedBreadcrumbItem[]): string {
  return items
    .map((b) => {
      if (isRomanSection(b.hs_code)) return `Раздел ${b.hs_code}`;
      const d = digitsOnly(b.hs_code);
      if (d.length === 2) return `Группа ${d}`;
      return formatCode(d);
    })
    .join(' › ');
}

function useHierarchyView(path: PathSegment[]): boolean {
  const last = path[path.length - 1];
  if (!last) return false;
  if (last.level === 'leaf') return false;
  if (last.level === 'heading' || last.level === 'subheading') return true;
  return digitsOnly(last.code).length >= 4 && !isRomanSection(last.code);
}

function useIsMobile(breakpoint = 640): boolean {
  const [isMobile, setIsMobile] = React.useState(false);
  React.useEffect(() => {
    const mq = window.matchMedia(`(max-width: ${breakpoint}px)`);
    const update = () => setIsMobile(mq.matches);
    update();
    mq.addEventListener('change', update);
    return () => mq.removeEventListener('change', update);
  }, [breakpoint]);
  return isMobile;
}

// ---------------------------------------------------------------------------
// Breadcrumb
// ---------------------------------------------------------------------------

type DrillBreadcrumbProps = {
  path: PathSegment[];
  onNavigate: (index: number) => void;
};

export function DrillBreadcrumb({ path, onNavigate }: DrillBreadcrumbProps) {
  const isMobile = useIsMobile();
  const root = { code: 'root', label: 'ТН ВЭД', level: 'root' as const };
  const all = [root, ...path];

  const visible =
    isMobile && all.length > 3
      ? [all[0], { code: '…', label: '…', level: 'root' as const }, ...all.slice(-2)]
      : all;

  return (
    <nav aria-label="Навигация по ТН ВЭД" className="flex min-w-0 flex-wrap items-center gap-1 text-sm">
      {visible.map((seg, idx) => {
        const isEllipsis = seg.code === '…';
        const isLast = idx === visible.length - 1;
        const realIndex =
          isEllipsis ? -1 : seg.code === 'root' ? -1 : path.findIndex((p) => p.code === seg.code);

        return (
          <React.Fragment key={`${seg.code}-${idx}`}>
            {idx > 0 ? <span className="text-cargo-light">›</span> : null}
            {isLast || isEllipsis ? (
              <span className={`truncate ${isLast ? 'font-medium text-cargo-deep' : 'text-cargo-light'}`}>
                {seg.label}
              </span>
            ) : (
              <button
                type="button"
                onClick={() => onNavigate(realIndex)}
                className="truncate text-cargo-mid transition-colors hover:text-cargo-trust"
              >
                {seg.label}
              </button>
            )}
          </React.Fragment>
        );
      })}
    </nav>
  );
}

// ---------------------------------------------------------------------------
// Card row
// ---------------------------------------------------------------------------

function DrillCard({
  node,
  index,
  onDrill,
  onSelectLeaf,
}: {
  node: DrillNode;
  index: number;
  onDrill: (node: DrillNode) => void;
  onSelectLeaf: (code: string) => void;
}) {
  const clickable = node.hasChildren || node.isLeaf;
  const codeClass =
    node.level === 'section'
      ? 'font-mono text-lg font-semibold text-cargo-deep'
      : node.isLeaf
        ? 'font-mono text-base font-semibold text-cargo-clear'
        : 'font-mono text-base font-semibold text-cargo-trust';

  const handleClick = () => {
    if (node.isCodeless && !node.hasChildren) return;
    if (node.isLeaf) {
      onSelectLeaf(digitsOnly(node.code));
      return;
    }
    if (node.hasChildren) onDrill(node);
  };

  if (node.isCodeless && !node.hasChildren) {
    return (
      <div
        className="tree-node tree-node--header pointer-events-none col-span-full px-2 py-1 text-[12px] italic text-cargo-light"
        aria-hidden
      >
        <span className={`tree-header-label ${TNVED_COMMODITY_NAME_CLASS}`}>
          {formatTnvedCommodityName(node.name)}
        </span>
      </div>
    );
  }

  if (node.isCodeless && node.hasChildren) {
    return (
      <button
        type="button"
        onClick={() => onDrill(node)}
        className="tree-node tree-node--header group col-span-full flex w-full items-center gap-2 px-2 py-1.5 text-left text-[12px] italic text-cargo-light transition hover:text-cargo-mid"
      >
        <span className={`tree-header-label min-w-0 flex-1 ${TNVED_COMMODITY_NAME_CLASS}`}>
          {formatTnvedCommodityName(node.name)}
        </span>
        <span className="shrink-0 not-italic text-base text-cargo-light/70 group-hover:text-cargo-mid" aria-hidden>
          ›
        </span>
      </button>
    );
  }

  return (
    <PremiumCard index={index} onClick={clickable ? handleClick : undefined} glow={clickable}>
      <div className="relative flex items-start justify-between gap-3 p-4">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className={codeClass}>{node.displayCode}</span>
            {node.isLeaf ? <RateBadges dutyRate={node.importDuty} vatRate={node.vatRate} /> : null}
          </div>
          {node.name ? (
            <p className={`mt-1 text-[13px] leading-snug text-cargo-mid ${TNVED_COMMODITY_NAME_CLASS}`}>
              {formatTnvedCommodityName(node.name)}
            </p>
          ) : null}
        </div>
        {node.hasChildren ? (
          <span className="shrink-0 pt-1 text-lg text-cargo-light" aria-hidden>
            ›
          </span>
        ) : null}
      </div>
    </PremiumCard>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export const DrillDownTree: React.FC<Props> = ({ onSelectCode, initialSearchQuery }) => {
  const [path, setPath] = React.useState<PathSegment[]>([]);
  const [currentChildren, setCurrentChildren] = React.useState<DrillNode[]>([]);
  const [loading, setLoading] = React.useState(true);
  const [loadErr, setLoadErr] = React.useState<string | null>(null);
  const [sectionCount, setSectionCount] = React.useState(21);

  const [search, setSearch] = React.useState('');
  const [searchHits, setSearchHits] = React.useState<TnvedSearchHit[]>([]);
  const [searchPaths, setSearchPaths] = React.useState<Record<string, string>>({});
  const [searchLoading, setSearchLoading] = React.useState(false);
  const [searchErr, setSearchErr] = React.useState<string | null>(null);
  const [activeSearchIdx, setActiveSearchIdx] = React.useState(-1);

  const sectionsRef = React.useRef<TnvedChildItem[]>([]);
  const inputRef = React.useRef<HTMLInputElement>(null);
  const appliedInitialSearch = React.useRef(false);

  const trimmed = search.trim();
  const isSearching = trimmed.length >= 2;
  const currentLevelId = path.map((p) => p.code).join('/') || 'root';
  const showHierarchy = useHierarchyView(path);

  React.useEffect(() => {
    const q = initialSearchQuery?.trim();
    if (!q || appliedInitialSearch.current) return;
    appliedInitialSearch.current = true;
    setSearch(q);
  }, [initialSearchQuery]);

  const loadChildrenForPath = React.useCallback(async (segments: PathSegment[]): Promise<DrillNode[]> => {
    const sectionId = segments.find((s) => s.level === 'section')?.sectionId;
    if (segments.length === 0) {
      const res = await fetchTnvedChildren(undefined, 'direct');
      sectionsRef.current = res.items;
      setSectionCount(res.items.length);
      return res.items.map((item) => childToDrillNode(item));
    }
    const last = segments[segments.length - 1];
    const res = await fetchTnvedChildren(last.code, 'direct');
    return res.items.map((item) => childToDrillNode(item, sectionId ?? last.sectionId));
  }, []);

  const refreshAtPath = React.useCallback(
    async (segments: PathSegment[]) => {
      setLoading(true);
      setLoadErr(null);
      try {
        const children = await loadChildrenForPath(segments);
        setCurrentChildren(children);
      } catch {
        setLoadErr('Не удалось загрузить уровень');
        setCurrentChildren([]);
      } finally {
        setLoading(false);
      }
    },
    [loadChildrenForPath],
  );

  React.useEffect(() => {
    if (isSearching) return;
    void refreshAtPath(path);
  }, [path, isSearching, refreshAtPath]);

  React.useEffect(() => {
    if (trimmed.length < 2) {
      setSearchHits([]);
      setSearchPaths({});
      setSearchErr(null);
      setSearchLoading(false);
      return;
    }

    let cancelled = false;
    setSearchLoading(true);
    const t = window.setTimeout(() => {
      searchTnved(trimmed)
        .then(async (rows) => {
          if (cancelled) return;
          setSearchHits(rows);
          setSearchErr(null);
          const paths: Record<string, string> = {};
          await Promise.all(
            rows.slice(0, 24).map(async (hit) => {
              try {
                const crumb = await fetchTnvedBreadcrumb(hit.code);
                paths[hit.code] = formatBreadcrumbPath(crumb);
              } catch {
                const d = digitsOnly(hit.code);
                paths[hit.code] = d.length >= 2 ? `Группа ${d.slice(0, 2)} › ${formatCode(d)}` : formatCode(d);
              }
            }),
          );
          if (!cancelled) setSearchPaths(paths);
        })
        .catch(() => {
          if (!cancelled) {
            setSearchHits([]);
            setSearchErr('Ошибка поиска');
          }
        })
        .finally(() => {
          if (!cancelled) setSearchLoading(false);
        });
    }, DEBOUNCE_MS);

    return () => {
      cancelled = true;
      window.clearTimeout(t);
    };
  }, [trimmed]);

  React.useEffect(() => {
    setActiveSearchIdx(searchHits.length ? 0 : -1);
  }, [searchHits]);

  const clearSearch = React.useCallback(() => {
    setSearch('');
    setSearchHits([]);
    setSearchPaths({});
    setSearchErr(null);
    setActiveSearchIdx(-1);
    inputRef.current?.focus();
  }, []);

  const navigateToIndex = React.useCallback(
    (index: number) => {
      if (index < 0) {
        setPath([]);
        return;
      }
      setPath((prev) => prev.slice(0, index + 1));
    },
    [],
  );

  const drillInto = React.useCallback(
    (node: DrillNode) => {
      if (node.isLeaf) {
        onSelectCode(digitsOnly(node.code));
        return;
      }
      setPath((prev) => [...prev, drillNodeToPathSegment(node)]);
    },
    [onSelectCode],
  );

  const drillIntoChild = React.useCallback(
    (item: TnvedChildItem) => {
      if (item.is_leaf) {
        onSelectCode(digitsOnly(item.code));
        return;
      }
      setPath((prev) => [...prev, drillNodeToPathSegment(childToDrillNode(item, prev.find((p) => p.sectionId)?.sectionId))]);
    },
    [onSelectCode],
  );

  const buildPathFromBreadcrumb = React.useCallback(async (crumb: TnvedBreadcrumbItem[]): Promise<PathSegment[]> => {
    const segments: PathSegment[] = [];
    for (const item of crumb) {
      if (isRomanSection(item.hs_code)) {
        const section = sectionsRef.current.find((s) => s.code === item.hs_code);
        segments.push({
          code: item.hs_code,
          label: `Раздел ${item.hs_code}`,
          name: (item.title || '').trim() || undefined,
          level: 'section',
          sectionId: section?.section_id,
        });
        continue;
      }
      const d = digitsOnly(item.hs_code);
      if (d.length === 2) {
        segments.push({
          code: d,
          label: `Группа ${d}`,
          name: (item.title || '').trim() || undefined,
          level: 'chapter',
          sectionId: segments.find((s) => s.level === 'section')?.sectionId,
        });
        continue;
      }
      const level = inferLevel(item.hs_code);
      segments.push({
        code: item.hs_code,
        label: formatCode(d),
        name: (item.title || '').trim() || undefined,
        level,
        sectionId: segments.find((s) => s.level === 'section')?.sectionId,
      });
    }
    return segments;
  }, []);

  const navigateToSearchHit = React.useCallback(
    async (hit: TnvedSearchHit) => {
      const d = digitsOnly(hit.code);
      if (hit.is_leaf === true) {
        onSelectCode(d);
        clearSearch();
        return;
      }

      try {
        const nodeRes = await fetchTnvedChildren(hit.code, 'direct');
        if (nodeRes.items.length === 0 && isFullTnvedCode(d)) {
          onSelectCode(d);
          clearSearch();
          return;
        }
        const crumb = await fetchTnvedBreadcrumb(hit.code);
        const fullPath = await buildPathFromBreadcrumb(crumb);
        setPath(fullPath);
        clearSearch();
      } catch {
        setSearchErr('Не удалось перейти к позиции');
      }
    },
    [buildPathFromBreadcrumb, clearSearch, onSelectCode],
  );

  const handleSelectHit = React.useCallback(
    (hit: TnvedSearchHit) => {
      void navigateToSearchHit(hit);
    },
    [navigateToSearchHit],
  );

  return (
    <div className="flex h-full flex-col gap-3">
      <div className="shrink-0 space-y-2">
        <div className="relative flex items-center">
          <Search className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-cargo-light" />
          <input
            ref={inputRef}
            id="tnved-search"
            type="search"
            autoComplete="off"
            placeholder="Поиск по коду или наименованию…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            onKeyDown={(e) => {
              if (trimmed.length < 2 || searchHits.length === 0) {
                if (e.key === 'Escape') clearSearch();
                return;
              }
              if (e.key === 'ArrowDown') {
                e.preventDefault();
                setActiveSearchIdx((prev) => (prev + 1) % searchHits.length);
                return;
              }
              if (e.key === 'ArrowUp') {
                e.preventDefault();
                setActiveSearchIdx((prev) => (prev <= 0 ? searchHits.length - 1 : prev - 1));
                return;
              }
              if (e.key === 'Enter') {
                e.preventDefault();
                const hit = searchHits[activeSearchIdx >= 0 ? activeSearchIdx : 0];
                if (hit) handleSelectHit(hit);
                return;
              }
              if (e.key === 'Escape') {
                e.preventDefault();
                clearSearch();
              }
            }}
            className="w-full rounded-lg border-2 border-cargo-border bg-cargo-surface py-3 pl-11 pr-10 text-[15px] text-cargo-deep placeholder:text-cargo-light focus:border-cargo-trust focus:outline-none focus:ring-2 focus:ring-cargo-trust-light"
          />
          {isSearching ? (
            <button
              type="button"
              onClick={clearSearch}
              className="absolute right-2.5 top-1/2 -translate-y-1/2 rounded p-0.5 text-cargo-light hover:text-cargo-mid"
              aria-label="Очистить"
            >
              ×
            </button>
          ) : null}
        </div>
      </div>

      {isSearching ? (
        <div className="min-h-0 flex-1 space-y-2 overflow-y-auto">
          {searchLoading ? (
            <p className="py-6 text-center text-sm text-cargo-mid">Поиск…</p>
          ) : searchHits.length === 0 ? (
            <p className="py-6 text-center text-sm text-cargo-mid">{searchErr || 'Ничего не найдено'}</p>
          ) : (
            <>
              <p className="text-[11px] text-cargo-light">Найдено: {searchHits.length}</p>
              <div className="grid gap-2 sm:grid-cols-2">
                {searchHits.map((hit, idx) => (
                  <PremiumCard
                    key={`${hit.code}-${idx}`}
                    index={idx}
                    onClick={() => handleSelectHit(hit)}
                  >
                    <div className="p-4">
                      <div className="flex items-start justify-between gap-2">
                        <span className="font-mono text-base font-semibold text-cargo-trust">{formatCode(hit.code)}</span>
                        {hit.is_leaf === false ? (
                          <span className="shrink-0 rounded bg-cargo-cloud px-1.5 py-0.5 text-[10px] text-cargo-mid">
                            группа
                          </span>
                        ) : null}
                      </div>
                      <p className={`mt-1 text-[13px] text-cargo-deep ${TNVED_COMMODITY_NAME_CLASS}`}>
                        {formatTnvedCommodityName(hit.name || '') || 'Описание отсутствует'}
                      </p>
                      {searchPaths[hit.code] ? (
                        <p className="mt-2 truncate text-[11px] text-cargo-light">{searchPaths[hit.code]}</p>
                      ) : null}
                    </div>
                  </PremiumCard>
                ))}
              </div>
            </>
          )}
        </div>
      ) : (
        <>
          <div className="flex shrink-0 flex-wrap items-center justify-between gap-2">
            <DrillBreadcrumb path={path} onNavigate={navigateToIndex} />
            {path.length === 0 ? (
              <span className="shrink-0 text-[11px] font-medium uppercase tracking-[0.06em] text-cargo-light">
                {depthLabel(path, sectionCount, currentChildren.length)}
              </span>
            ) : null}
          </div>

          {path.length > 0 && !showHierarchy ? (
            <DrillLevelHeader
              segment={path[path.length - 1]}
              depthText={depthLabel(path, sectionCount, currentChildren.length)}
            />
          ) : null}

          <div className="relative min-h-0 flex-1 overflow-y-auto">
            {loadErr ? (
              <div className="rounded-lg border border-cargo-alert/30 bg-cargo-alert-light px-3 py-2 text-xs text-cargo-alert">
                {loadErr}
              </div>
            ) : null}

            {loading ? (
              <p className="py-10 text-center text-sm text-cargo-mid">Загрузка…</p>
            ) : showHierarchy && path.length > 0 ? (
              <HierarchyView
                parentCode={path[path.length - 1].code}
                onSelectCode={onSelectCode}
                onDrill={drillIntoChild}
              />
            ) : (
              <AnimatePresence mode="wait">
                <motion.div
                  key={currentLevelId}
                  initial={{ opacity: 0, x: 20 }}
                  animate={{ opacity: 1, x: 0 }}
                  exit={{ opacity: 0, x: -20 }}
                  transition={{ duration: 0.3, ease: [0.16, 1, 0.3, 1] }}
                  className="grid gap-2 sm:grid-cols-2"
                >
                  {currentChildren.length === 0 ? (
                    <p className="col-span-full py-10 text-center text-sm text-cargo-mid">Нет элементов на этом уровне</p>
                  ) : (
                    currentChildren.map((node, idx) => (
                      <DrillCard
                        key={`${currentLevelId}-${node.code}-${idx}`}
                        node={node}
                        index={idx}
                        onDrill={drillInto}
                        onSelectLeaf={onSelectCode}
                      />
                    ))
                  )}
                </motion.div>
              </AnimatePresence>
            )}
          </div>
        </>
      )}
    </div>
  );
};
