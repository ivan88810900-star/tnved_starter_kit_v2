import React from 'react';
import { ChevronRight, Search } from 'lucide-react';
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
import { formatTnvedCommodityName, TNVED_COMMODITY_NAME_CLASS } from '../utils/tnvedDisplayText';
import { normalizeDutyRate } from '../utils/dutyRate';

type Props = {
  selectedCode: string | null;
  onSelectCode: (code: string) => void;
  initialSearchQuery?: string;
};

const DEBOUNCE_MS = 300;
const INDENT_PX = 16;

const containerVariants = {
  hidden: {},
  visible: { transition: { staggerChildren: 0.05 } },
};

const itemVariants = {
  hidden: { opacity: 0, x: -8 },
  visible: { opacity: 1, x: 0, transition: { duration: 0.2 } },
};

function digitsOnly(s: string): string {
  return s.replace(/\D/g, '');
}

function isRomanSection(code: string): boolean {
  return /^[IVXLCDM]+$/i.test(code.trim());
}

function nodeKey(item: TnvedChildItem, index: number): string {
  return `${item.code}-${item.is_codeless ? 'h' : 'n'}-${index}`;
}

function displayLabel(item: TnvedChildItem): string {
  if (item.level === 'section') return `Раздел ${item.display_code || item.code}`;
  const d = digitsOnly(item.code);
  if (d.length === 2) return item.display_code || d;
  return item.display_code || formatCode(d);
}

const BRANCH_NAME_CLASS = `min-w-0 flex-1 whitespace-normal break-words text-[13px] leading-snug text-[var(--cargo-mid)] ${TNVED_COMMODITY_NAME_CLASS}`;

function formatVatBadge(vat: number | null | undefined): string | null {
  if (vat == null || Number.isNaN(vat)) return null;
  const n = Number(vat);
  return `НДС ${Number.isInteger(n) ? n : n.toFixed(1)}%`;
}

type LeafRowProps = {
  item: TnvedChildItem;
  depth: number;
  inCodelessBranch: boolean;
  onSelectLeaf: (code: string) => void;
};

function LeafRow({ item, depth, inCodelessBranch, onSelectLeaf }: LeafRowProps) {
  const duty = normalizeDutyRate(item.duty_rate || item.import_duty);
  const vat = item.vat_rate;
  const codeDigits = digitsOnly(item.code);
  const vatLabel = formatVatBadge(item.vat_rate);

  return (
    <motion.div
      variants={itemVariants}
      style={inCodelessBranch ? undefined : { marginLeft: depth * INDENT_PX }}
    >
      <button
        type="button"
        onClick={() => onSelectLeaf(codeDigits)}
        style={inCodelessBranch ? { paddingLeft: depth * INDENT_PX + 8 } : undefined}
        className={
          inCodelessBranch
            ? 'group flex w-full items-center gap-2 rounded px-2 py-2 text-left transition-colors hover:bg-[var(--cargo-trust-light)]'
            : 'tree-node-leaf flex items-center gap-2 text-left'
        }
      >
        {inCodelessBranch ? (
          <span className="shrink-0 select-none text-[11px] font-medium text-[var(--cargo-light)]">– –</span>
        ) : null}
        <span
          className={`min-w-[110px] shrink-0 font-mono text-[13px] font-semibold text-[var(--cargo-trust)]${
            inCodelessBranch ? '' : ' tree-code leaf'
          }`}
        >
          {formatCode(codeDigits)}
        </span>
        <span
          className={`min-w-0 flex-1 truncate text-[12px] text-[var(--cargo-mid)] ${TNVED_COMMODITY_NAME_CLASS}${
            inCodelessBranch ? '' : ' tree-name'
          }`}
        >
          {formatTnvedCommodityName(item.name)}
        </span>
        <div className="ml-auto flex shrink-0 items-center gap-1.5">
          {duty ? (
            <span
              className={
                inCodelessBranch
                  ? 'rounded bg-[var(--cargo-trust-light)] px-1.5 py-0.5 text-[11px] font-bold text-[var(--cargo-trust)]'
                  : 'badge duty'
              }
            >
              {duty}
            </span>
          ) : null}
          {inCodelessBranch ? (
            vat != null && !Number.isNaN(Number(vat)) ? (
              <span className="shrink-0 text-[11px] text-[var(--cargo-light)]">
                {Number.isInteger(Number(vat)) ? vat : Number(vat).toFixed(1)}%
              </span>
            ) : null
          ) : vatLabel ? (
            <span className="badge vat shrink-0">{vatLabel}</span>
          ) : null}
          {item.has_ds ? (
            <span
              className={
                inCodelessBranch
                  ? 'rounded bg-[var(--cargo-clear-light)] px-1.5 py-0.5 text-[10px] font-bold text-[var(--cargo-clear)]'
                  : 'badge doc'
              }
            >
              ДС
            </span>
          ) : null}
          {item.has_ss ? (
            <span
              className={
                inCodelessBranch
                  ? 'rounded bg-[var(--cargo-clear-light)] px-1.5 py-0.5 text-[10px] font-bold text-[var(--cargo-clear)]'
                  : 'badge doc'
              }
            >
              СС
            </span>
          ) : null}
        </div>
      </button>
    </motion.div>
  );
}

type TreeNodeProps = {
  item: TnvedChildItem;
  index: number;
  depth: number;
  expanded: Set<string>;
  loadingNodes: Set<string>;
  childrenCache: Map<string, TnvedChildItem[]>;
  onToggle: (item: TnvedChildItem) => void;
  onSelectLeaf: (code: string) => void;
  inCodelessBranch?: boolean;
};

function CodelessDotRing() {
  return (
    <svg width="10" height="10" viewBox="0 0 10 10" className="shrink-0" aria-hidden="true">
      <circle cx="5" cy="5" r="4" fill="none" stroke="var(--cargo-light)" strokeWidth="1.5" />
    </svg>
  );
}

function CodelessDotFilled() {
  return (
    <svg width="10" height="10" viewBox="0 0 10 10" className="shrink-0" aria-hidden="true">
      <circle cx="5" cy="5" r="4.5" fill="var(--cargo-trust)" />
      <circle cx="5" cy="5" r="2" fill="white" />
    </svg>
  );
}

function TreeNode({
  item,
  index,
  depth,
  expanded,
  loadingNodes,
  childrenCache,
  onToggle,
  onSelectLeaf,
  inCodelessBranch = false,
}: TreeNodeProps) {
  const cacheKey = item.code;
  const isExpanded = expanded.has(cacheKey);
  const children = childrenCache.get(cacheKey) ?? [];
  const canExpand = !!item.has_children;
  const isLoading = loadingNodes.has(cacheKey);

  const renderChildList = (childInCodelessBranch: boolean) => {
    const childrenContent =
      isLoading ? (
        <p className="py-2 text-xs text-cargo-mid" style={{ paddingLeft: (depth + 1) * INDENT_PX + 8 }}>
          Загрузка…
        </p>
      ) : children.length === 0 ? (
        <p className="py-2 text-xs text-cargo-light" style={{ paddingLeft: (depth + 1) * INDENT_PX + 8 }}>
          Нет элементов
        </p>
      ) : (
        <motion.div variants={containerVariants} initial="hidden" animate="visible" className="pt-0.5">
          {children.map((child, idx) => (
            <TreeNode
              key={nodeKey(child, idx)}
              item={child}
              index={idx}
              depth={depth + 1}
              expanded={expanded}
              loadingNodes={loadingNodes}
              childrenCache={childrenCache}
              onToggle={onToggle}
              onSelectLeaf={onSelectLeaf}
              inCodelessBranch={childInCodelessBranch}
            />
          ))}
        </motion.div>
      );

    return (
      <AnimatePresence initial={false}>
        {isExpanded ? (
          <motion.div
            key={`${cacheKey}-children`}
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="overflow-hidden"
          >
            {childrenContent}
          </motion.div>
        ) : null}
      </AnimatePresence>
    );
  };

  if (item.is_codeless && canExpand) {
    const toggleButton = (
      <button
        type="button"
        onClick={() => onToggle(item)}
        style={{ paddingLeft: depth * INDENT_PX + 8 }}
        className={`flex w-full items-center gap-2 rounded py-1.5 transition-colors ${
          isExpanded
            ? 'bg-[var(--cargo-trust-light)]'
            : 'group hover:bg-slate-50'
        }`}
        aria-expanded={isExpanded}
      >
        {isExpanded ? <CodelessDotFilled /> : <CodelessDotRing />}
        <span
          className={`select-none font-medium ${
            isExpanded ? 'font-semibold text-[var(--cargo-trust)]' : 'text-[var(--cargo-light)]'
          }`}
        >
          –
        </span>
        <span
          className={`text-[13px] italic ${
            isExpanded
              ? 'font-medium text-[var(--cargo-trust)]'
              : 'text-[var(--cargo-mid)]'
          } ${TNVED_COMMODITY_NAME_CLASS}`}
        >
          {formatTnvedCommodityName(item.name)}
        </span>
      </button>
    );

    return (
      <motion.div variants={itemVariants}>
        {isExpanded ? (
          <div className="relative">
            {!isLoading && children.length > 0 ? (
              <div
                className="absolute top-0 bottom-0 w-px bg-[var(--cargo-trust)] opacity-20"
                style={{ left: depth * INDENT_PX + 12 }}
                aria-hidden="true"
              />
            ) : null}
            {toggleButton}
            {renderChildList(true)}
          </div>
        ) : (
          toggleButton
        )}
      </motion.div>
    );
  }

  if (item.is_codeless && !canExpand) {
    return (
      <motion.div
        variants={itemVariants}
        style={{ paddingLeft: depth * INDENT_PX + 8 }}
        className="flex items-center gap-2 py-0.5"
      >
        <CodelessDotRing />
        <span className="select-none font-medium text-[var(--cargo-light)]">–</span>
        <span className={`text-[11px] italic text-[var(--cargo-mid)] ${TNVED_COMMODITY_NAME_CLASS}`}>
          {formatTnvedCommodityName(item.name)}
        </span>
      </motion.div>
    );
  }

  if (item.is_leaf) {
    return (
      <LeafRow
        item={item}
        depth={depth}
        inCodelessBranch={inCodelessBranch}
        onSelectLeaf={onSelectLeaf}
      />
    );
  }

  return (
    <motion.div variants={itemVariants} style={{ marginLeft: depth * INDENT_PX }}>
      <button
        type="button"
        className="tree-node-branch !items-start"
        onClick={() => onToggle(item)}
        aria-expanded={isExpanded}
      >
        <ChevronRight
          size={16}
          className={`tree-chevron mt-1 shrink-0${isExpanded ? ' expanded' : ''}`}
        />
        <span className="tree-code">{displayLabel(item)}</span>
        <span className={BRANCH_NAME_CLASS}>
          {formatTnvedCommodityName(item.name)}
        </span>
      </button>

      {renderChildList(inCodelessBranch)}
    </motion.div>
  );
}

export const TnvedAccordionTree: React.FC<Props> = ({ onSelectCode, initialSearchQuery }) => {
  const [sections, setSections] = React.useState<TnvedChildItem[]>([]);
  const [loadingRoot, setLoadingRoot] = React.useState(true);
  const [loadErr, setLoadErr] = React.useState<string | null>(null);
  const [expanded, setExpanded] = React.useState<Set<string>>(() => new Set());
  const [childrenCache, setChildrenCache] = React.useState<Map<string, TnvedChildItem[]>>(() => new Map());
  const [loadingNodes, setLoadingNodes] = React.useState<Set<string>>(() => new Set());

  const [search, setSearch] = React.useState('');
  const [searchHits, setSearchHits] = React.useState<TnvedSearchHit[]>([]);
  const [searchPaths, setSearchPaths] = React.useState<Record<string, string>>({});
  const [searchLoading, setSearchLoading] = React.useState(false);
  const [searchErr, setSearchErr] = React.useState<string | null>(null);
  const [activeSearchIdx, setActiveSearchIdx] = React.useState(-1);

  const inputRef = React.useRef<HTMLInputElement>(null);
  const appliedInitialSearch = React.useRef(false);

  const trimmed = search.trim();
  const isSearching = trimmed.length >= 2;

  React.useEffect(() => {
    const q = initialSearchQuery?.trim();
    if (!q || appliedInitialSearch.current) return;
    appliedInitialSearch.current = true;
    setSearch(q);
  }, [initialSearchQuery]);

  const loadChildren = React.useCallback(async (code?: string): Promise<TnvedChildItem[]> => {
    const cacheKey = code ?? '';
    const cached = childrenCache.get(cacheKey);
    if (cached) return cached;

    setLoadingNodes((prev) => new Set(prev).add(code ?? ''));
    try {
      const res = await fetchTnvedChildren(code, 'direct');
      const items = res.items ?? [];
      setChildrenCache((prev) => {
        const next = new Map(prev);
        next.set(code ?? '', items);
        return next;
      });
      return items;
    } finally {
      setLoadingNodes((prev) => {
        const next = new Set(prev);
        next.delete(code ?? '');
        return next;
      });
    }
  }, [childrenCache]);

  React.useEffect(() => {
    let cancelled = false;
    setLoadingRoot(true);
    setLoadErr(null);
    void fetchTnvedChildren(undefined, 'direct')
      .then((res) => {
        if (cancelled) return;
        setSections(res.items ?? []);
        setChildrenCache((prev) => {
          const next = new Map(prev);
          next.set('', res.items ?? []);
          return next;
        });
      })
      .catch(() => {
        if (!cancelled) setLoadErr('Не удалось загрузить разделы');
      })
      .finally(() => {
        if (!cancelled) setLoadingRoot(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const handleToggle = React.useCallback(
    (item: TnvedChildItem) => {
      const key = item.code;
      setExpanded((prev) => {
        const next = new Set(prev);
        if (next.has(key)) {
          next.delete(key);
        } else {
          next.add(key);
        }
        return next;
      });
      if (!childrenCache.has(key)) {
        void loadChildren(key);
      }
    },
    [childrenCache, loadChildren],
  );

  const expandAlongPath = React.useCallback(
    async (crumb: TnvedBreadcrumbItem[]) => {
      const codes = crumb.map((c) => c.hs_code);
      await loadChildren(undefined);
      for (const code of codes) {
        await loadChildren(code);
      }
      setExpanded(new Set(codes));
    },
    [loadChildren],
  );

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
        .then(async (hits) => {
          if (cancelled) return;
          setSearchHits(hits);
          setSearchErr(null);
          const paths: Record<string, string> = {};
          await Promise.all(
            hits.slice(0, 8).map(async (hit) => {
              try {
                const crumb = await fetchTnvedBreadcrumb(hit.code);
                paths[hit.code] = crumb.map((b) => b.title || b.hs_code).join(' › ');
              } catch {
                /* ignore */
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

  const navigateToSearchHit = React.useCallback(
    async (hit: TnvedSearchHit) => {
      const d = digitsOnly(hit.code);
      if (hit.is_leaf === true || isFullTnvedCode(d)) {
        try {
          const nodeRes = await fetchTnvedChildren(hit.code, 'direct');
          if (nodeRes.items.length === 0 && isFullTnvedCode(d)) {
            onSelectCode(d);
            clearSearch();
            return;
          }
        } catch {
          /* fall through */
        }
      }

      try {
        const crumb = await fetchTnvedBreadcrumb(hit.code);
        await expandAlongPath(crumb);
        clearSearch();
        if (hit.is_leaf === true || isFullTnvedCode(d)) {
          onSelectCode(d);
        }
      } catch {
        setSearchErr('Не удалось перейти к позиции');
      }
    },
    [clearSearch, expandAlongPath, onSelectCode],
  );

  return (
    <div className="flex h-full flex-col gap-3">
      <div className="relative shrink-0">
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
              if (hit) void navigateToSearchHit(hit);
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
                  <PremiumCard key={`${hit.code}-${idx}`} index={idx} onClick={() => void navigateToSearchHit(hit)}>
                    <div className="p-4">
                      <div className="flex items-start justify-between gap-2">
                        <span className="font-mono text-base font-semibold text-cargo-trust">{formatCode(hit.code)}</span>
                        {hit.is_leaf === false ? (
                          <span className="shrink-0 rounded bg-cargo-cloud px-1.5 py-0.5 text-[10px] text-cargo-mid">группа</span>
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
        <div className="min-h-0 flex-1 overflow-y-auto">
          {loadErr ? (
            <div className="mb-2 rounded-lg border border-cargo-alert/30 bg-cargo-alert-light px-3 py-2 text-xs text-cargo-alert">
              {loadErr}
            </div>
          ) : null}

          {loadingRoot ? (
            <p className="py-10 text-center text-sm text-cargo-mid">Загрузка…</p>
          ) : (
            <>
              <p className="mb-2 text-[11px] font-medium uppercase tracking-[0.06em] text-cargo-light">
                Разделы · {sections.length}
              </p>
              <motion.div variants={containerVariants} initial="hidden" animate="visible" className="pb-4">
                {sections.map((section, idx) => (
                  <TreeNode
                    key={nodeKey(section, idx)}
                    item={section}
                    index={idx}
                    depth={0}
                    expanded={expanded}
                    loadingNodes={loadingNodes}
                    childrenCache={childrenCache}
                    onToggle={handleToggle}
                    onSelectLeaf={onSelectCode}
                  />
                ))}
              </motion.div>
            </>
          )}
        </div>
      )}
    </div>
  );
};

export default TnvedAccordionTree;
