import React from 'react';
import { Search } from 'lucide-react';
import type { TnvedHierarchyNode, TnvedSearchHit } from '../../api/tnvedCatalog';
import { fetchHierarchyTree, formatCode, isFullTnvedCode, searchTnved } from '../../api/tnvedCatalog';
import { MeasureHoverCard } from './MeasureHoverCard';
import { formatTnvedCommodityName, TNVED_COMMODITY_NAME_CLASS } from '../../utils/tnvedDisplayText';

type Props = {
  selectedCode: string | null;
  onSelectCode: (code: string) => void;
  /** Подставить строку поиска один раз (например, с главной страницы) */
  initialSearchQuery?: string;
};

// ---------------------------------------------------------------------------
// Иконки
// ---------------------------------------------------------------------------

const SectionIcon = () => (
  <svg width="15" height="15" viewBox="0 0 24 24" fill="currentColor" className="shrink-0 text-blue-600" aria-hidden>
    <path d="M4 6h16v2H4zm0 5h16v2H4zm0 5h16v2H4z" />
  </svg>
);

const FolderIcon = ({ depth }: { depth: number }) => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"
    className={`shrink-0 ${depth === 1 ? 'text-amber-500' : 'text-amber-400'}`} aria-hidden>
    <path d="M10 4H4c-1.1 0-2 .9-2 2v12c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V8c0-1.1-.9-2-2-2h-8l-2-2z" />
  </svg>
);

const FileIcon = () => (
  <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"
    className="shrink-0 text-gray-400" aria-hidden>
    <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
    <polyline points="14 2 14 8 20 8" />
  </svg>
);

// Маркер бескодовой субпозиции (только текст, без кода)
const CodelessIcon = () => (
  <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"
    className="shrink-0 text-gray-300" aria-hidden>
    <line x1="5" y1="12" x2="19" y2="12" />
  </svg>
);

const ChevronIcon = ({ open }: { open: boolean }) => (
  <svg width="11" height="11" viewBox="0 0 24 24" fill="none"
    stroke="currentColor" strokeWidth="2.5"
    className="shrink-0 text-gray-400 transition-transform duration-150"
    style={{ transform: open ? 'rotate(90deg)' : 'rotate(0deg)' }}
    aria-hidden>
    <polyline points="9 18 15 12 9 6" />
  </svg>
);

// ---------------------------------------------------------------------------
// Определение уровня по коду
// ---------------------------------------------------------------------------

type NodeLevel = 'section' | 'chapter' | 'heading' | 'subheading' | 'item';

function getLevel(code: string): NodeLevel {
  const d = code.replace(/\D/g, '');
  if (d.length === 0) return 'section';
  if (d.length <= 2)  return 'chapter';
  if (d.length <= 4)  return 'heading';
  if (d.length <= 6)  return 'subheading';
  return 'item';
}

function codeLabel(code: string, level: NodeLevel): string {
  const d = code.replace(/\D/g, '');
  if (level === 'section') return `Раздел ${code}`;
  if (level === 'chapter') return `Группа ${d}`;
  return formatCode(code);
}

// ---------------------------------------------------------------------------
// Подсветка совпадений в тексте
// ---------------------------------------------------------------------------

function Highlight({ text, query }: { text: string; query: string }): React.ReactElement {
  const q = query.trim();
  if (!q || /^\d+$/.test(q)) return <>{text}</>;

  const parts: React.ReactNode[] = [];
  let last = 0;
  const regex = new RegExp(q.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'gi');
  let match: RegExpExecArray | null;

  while ((match = regex.exec(text)) !== null) {
    if (match.index > last) parts.push(text.slice(last, match.index));
    parts.push(
      <mark key={match.index} className="bg-yellow-200 text-yellow-900 rounded-sm px-0.5 font-medium not-italic">
        {match[0]}
      </mark>
    );
    last = match.index + match[0].length;
  }
  if (last < text.length) parts.push(text.slice(last));

  return <>{parts}</>;
}

// ---------------------------------------------------------------------------
// Утилиты фильтрации
// ---------------------------------------------------------------------------

function digitsOnly(s: string): string {
  return s.replace(/\D/g, '');
}

function countLeaves(nodes: TnvedHierarchyNode[]): number {
  let n = 0;
  for (const node of nodes) {
    if (node.children.length === 0) n++;
    else n += countLeaves(node.children);
  }
  return n;
}

function filterTree(nodes: TnvedHierarchyNode[], query: string): TnvedHierarchyNode[] {
  const qLow = query.trim().toLowerCase();
  const qDig = digitsOnly(query);
  if (!qLow && !qDig) return nodes;

  const matches = (n: TnvedHierarchyNode): boolean => {
    if (qDig && digitsOnly(n.code).startsWith(qDig)) return true;
    if (qLow && (n.name || '').toLowerCase().includes(qLow)) return true;
    if (qLow && (n.code || '').toLowerCase().includes(qLow)) return true;
    return false;
  };

  const walk = (arr: TnvedHierarchyNode[]): TnvedHierarchyNode[] => {
    const out: TnvedHierarchyNode[] = [];
    for (const n of arr) {
      if (matches(n)) { out.push({ ...n, children: n.children }); continue; }
      const ch = walk(n.children);
      if (ch.length) out.push({ ...n, children: ch });
    }
    return out;
  };
  return walk(nodes);
}

function allParentCodes(nodes: TnvedHierarchyNode[], acc = new Set<string>()): Set<string> {
  for (const n of nodes) {
    if (n.children.length) {
      acc.add(n.code);
      allParentCodes(n.children, acc);
    }
  }
  return acc;
}

// ---------------------------------------------------------------------------
// Строка дерева
// ---------------------------------------------------------------------------

type RowProps = {
  node: TnvedHierarchyNode;
  depth: number;
  expanded: Set<string>;
  toggle: (code: string) => void;
  selectedCode: string | null;
  onSelectCode: (code: string) => void;
  searchQuery: string;
};

const TreeRow: React.FC<RowProps> = ({
  node, depth, expanded, toggle, selectedCode, onSelectCode, searchQuery,
}) => {
  const level       = getLevel(node.code);
  const d           = digitsOnly(node.code);
  const nodeKey     = node.code;
  const hasChildren = node.children.length > 0;
  // Классификация приходит с бэкенда; fallback на эвристику для старых ответов.
  const isCodeless  = node.is_codeless === true;
  const isLeaf      = node.is_leaf ?? (isFullTnvedCode(d) && !hasChildren);
  const open        = expanded.has(nodeKey);
  const active      = isLeaf && selectedCode === d;
  const clickable   = hasChildren || isLeaf;

  // Отступ: 4px + 16px на уровень
  const pl = 8 + depth * 18;

  const handleClick = () => {
    if (hasChildren) {
      toggle(nodeKey);
      return;
    }
    if (!isLeaf && isFullTnvedCode(d)) {
      return;
    }
    if (isLeaf) onSelectCode(d);
  };

  // Стили кода по уровню
  const codeClass =
    level === 'section'    ? 'text-[14px] font-semibold text-gray-900' :
    level === 'chapter'    ? 'text-[13px] font-semibold text-gray-800' :
    level === 'heading'    ? 'text-[13px] font-semibold text-gray-800' :
    level === 'subheading' ? 'text-[12.5px] font-medium text-gray-700' :
                             'text-[12.5px] font-medium text-gray-800';

  // Стили названия по уровню. Бескодовые субпозиции — серый курсив.
  const nameClass =
    isCodeless       ? `text-[12px] italic text-gray-400 ${TNVED_COMMODITY_NAME_CLASS}` :
    active           ? `text-[12.5px] text-blue-700 ${TNVED_COMMODITY_NAME_CLASS}` :
    level === 'section'  ? `text-[12.5px] text-gray-700 ${TNVED_COMMODITY_NAME_CLASS}` :
    level === 'chapter'  ? `text-[12px] text-gray-600 ${TNVED_COMMODITY_NAME_CLASS}` :
    level === 'heading'  ? `text-[12px] text-gray-600 ${TNVED_COMMODITY_NAME_CLASS}` :
    level === 'subheading' ? `text-[12px] text-gray-500 ${TNVED_COMMODITY_NAME_CLASS}` :
                             `text-[12px] text-gray-500 ${TNVED_COMMODITY_NAME_CLASS}`;

  return (
    <div>
      <button
        type="button"
        onClick={handleClick}
        disabled={!clickable}
        style={{ paddingLeft: pl }}
        className={[
          'flex w-full items-start gap-2 rounded-xl py-3 pr-3.5 text-left',
          'border border-transparent transition-all duration-150',
          clickable ? 'cursor-pointer hover:-translate-y-[1px] hover:bg-slate-50' : 'cursor-default opacity-40',
          active ? 'border-indigo-200 bg-indigo-50 shadow-sm' : '',
        ].join(' ')}
      >
        {/* Шеврон */}
        <span className="mt-[3px] shrink-0">
          {hasChildren ? <ChevronIcon open={open} /> : <span className="inline-block w-[11px]" />}
        </span>

        {/* Иконка */}
        <span className="mt-[2px] shrink-0">
          {level === 'section' ? <SectionIcon />
            : isCodeless ? <CodelessIcon />
            : hasChildren ? <FolderIcon depth={depth} />
            : <FileIcon />}
        </span>

        {/* Бескодовая субпозиция — только текст. Иначе: код + название. */}
        <span className="min-w-0 flex-1">
          {isCodeless ? (
            <span className={`block ${nameClass} break-words`}>
              <Highlight text={`— ${formatTnvedCommodityName(node.name)}`} query={searchQuery} />
            </span>
          ) : (
            <>
              <MeasureHoverCard code={node.code} fallbackName={node.name}>
                <span className={`font-mono block ${codeClass} ${active ? 'text-blue-800' : ''}`}>
                  {codeLabel(node.code, level)}
                </span>
              </MeasureHoverCard>
              {node.name ? (
                <span className={`block ${nameClass} mt-0.5 break-words`}>
                  <Highlight text={formatTnvedCommodityName(node.name)} query={searchQuery} />
                </span>
              ) : isLeaf ? (
                <span className="mt-0.5 block text-[12px] italic text-gray-400">Описание отсутствует</span>
              ) : null}
            </>
          )}
        </span>
      </button>

      {/* Дети */}
      {hasChildren && open && (
        <div className="border-l border-slate-200" style={{ marginLeft: pl + 8 }}>
          {node.children.map((ch) => (
            <TreeRow
              key={ch.code}
              node={ch}
              depth={depth + 1}
              expanded={expanded}
              toggle={toggle}
              selectedCode={selectedCode}
              onSelectCode={onSelectCode}
              searchQuery={searchQuery}
            />
          ))}
        </div>
      )}
    </div>
  );
};

// ---------------------------------------------------------------------------
// Контейнер TnvedTree
// ---------------------------------------------------------------------------

const DEBOUNCE_MS = 300;

export const TnvedTree: React.FC<Props> = ({ selectedCode, onSelectCode, initialSearchQuery }) => {
  const [fullTree, setFullTree]       = React.useState<TnvedHierarchyNode[]>([]);
  const [displayTree, setDisplayTree] = React.useState<TnvedHierarchyNode[]>([]);
  const [search, setSearch]           = React.useState('');
  const [loadErr, setLoadErr]         = React.useState<string | null>(null);
  const [loading, setLoading]         = React.useState(true);
  const [prefixLoading, setPrefixLoading] = React.useState(false);
  const [expanded, setExpanded]       = React.useState<Set<string>>(() => new Set());
  const [searchHits, setSearchHits]   = React.useState<TnvedSearchHit[]>([]);
  const [searchLoading, setSearchLoading] = React.useState(false);
  const [searchErr, setSearchErr]     = React.useState<string | null>(null);
  const [activeSearchIdx, setActiveSearchIdx] = React.useState(-1);
  const inputRef = React.useRef<HTMLInputElement>(null);
  const appliedInitialSearch = React.useRef(false);

  React.useEffect(() => {
    const q = initialSearchQuery?.trim();
    if (!q || appliedInitialSearch.current) return;
    appliedInitialSearch.current = true;
    setSearch(q);
  }, [initialSearchQuery]);

  const trimmed       = search.trim();
  const isDigitSearch = trimmed.length > 0 && /^[\d\s]+$/.test(trimmed);
  const isSearching   = trimmed.length > 0;

  // Первичная загрузка
  React.useEffect(() => {
    setLoading(true);
    fetchHierarchyTree()
      .then((t) => { setFullTree(t); setDisplayTree(t); })
      .catch(() => setLoadErr('Не удалось загрузить справочник'))
      .finally(() => setLoading(false));
  }, []);

  const fullTreeRef = React.useRef<TnvedHierarchyNode[]>([]);
  React.useEffect(() => { fullTreeRef.current = fullTree; }, [fullTree]);

  // Текстовая фильтрация
  React.useEffect(() => {
    if (!trimmed) { setDisplayTree(fullTree); return; }
    if (isDigitSearch) return;
    setDisplayTree(filterTree(fullTree, trimmed));
  }, [fullTree, trimmed, isDigitSearch]);

  // Универсальный API-поиск (код + наименование), debounce 300ms.
  React.useEffect(() => {
    if (trimmed.length < 2) {
      setSearchHits([]);
      setSearchErr(null);
      setSearchLoading(false);
      return;
    }

    let cancelled = false;
    setSearchLoading(true);
    const t = window.setTimeout(() => {
      searchTnved(trimmed)
        .then((rows) => {
          if (!cancelled) {
            setSearchHits(rows);
            setSearchErr(null);
          }
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

  // Поиск по цифровому префиксу — API
  React.useEffect(() => {
    if (!isDigitSearch || !trimmed) { setPrefixLoading(false); return; }
    const d = digitsOnly(trimmed);
    if (!d) { setDisplayTree(fullTreeRef.current); return; }
    setPrefixLoading(true);
    let cancelled = false;
    const t = window.setTimeout(() => {
      fetchHierarchyTree(d)
        .then((tree) => { if (!cancelled) { setDisplayTree(tree); setLoadErr(null); } })
        .catch(() => { if (!cancelled) setLoadErr('Ошибка загрузки'); })
        .finally(() => { if (!cancelled) setPrefixLoading(false); });
    }, DEBOUNCE_MS);
    return () => { cancelled = true; window.clearTimeout(t); setPrefixLoading(false); };
  }, [trimmed, isDigitSearch]);

  // Авторазворачивание при поиске
  React.useEffect(() => {
    if (!trimmed) { setExpanded(new Set()); return; }
    if (isDigitSearch && prefixLoading) return;
    setExpanded(allParentCodes(displayTree));
  }, [trimmed, displayTree, isDigitSearch, prefixLoading]);

  const toggle = React.useCallback((code: string) => {
    setExpanded((prev) => {
      const s = new Set(prev);
      s.has(code) ? s.delete(code) : s.add(code);
      return s;
    });
  }, []);

  const clearSearch = React.useCallback(() => {
    setSearch('');
    setSearchHits([]);
    setSearchErr(null);
    setActiveSearchIdx(-1);
    inputRef.current?.focus();
  }, []);

  const handleSelectHit = React.useCallback((hit: TnvedSearchHit) => {
    const digits = digitsOnly(hit.code);
    if (hit.is_leaf === false) {
      setSearch(hit.code);
      return;
    }
    if (hit.is_leaf === true || isFullTnvedCode(digits)) {
      onSelectCode(digits);
      clearSearch();
    }
  }, [onSelectCode, clearSearch]);

  // Подсчёт найденных листьев при поиске
  const resultCount = isSearching ? countLeaves(displayTree) : 0;

  // ---------------------------------------------------------------------------
  // Рендер
  // ---------------------------------------------------------------------------

  if (loadErr && !loading && fullTree.length === 0) {
    return <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">{loadErr}</div>;
  }
  if (!loading && fullTree.length === 0) {
    return (
      <p className="rounded-xl border border-gray-200 bg-gray-50 p-4 text-sm text-gray-600">
        База данных пуста. Выполните импорт справочника ТН ВЭД.
      </p>
    );
  }

  return (
    <div className="flex h-full flex-col gap-3 bg-white">

      {/* ─── Поиск ─── */}
      <div className="shrink-0 space-y-2">
        <div className="relative flex items-center">
          <span className="pointer-events-none absolute left-3.5 top-1/2 -translate-y-1/2 rounded-full bg-indigo-100 p-1 text-indigo-700">
            <Search size={14} className="text-indigo-700" />
          </span>
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
                const idx = activeSearchIdx >= 0 ? activeSearchIdx : 0;
                const hit = searchHits[idx];
                if (hit) handleSelectHit(hit);
                return;
              }
              if (e.key === 'Escape') {
                e.preventDefault();
                clearSearch();
              }
            }}
            className="w-full rounded-xl border border-slate-200 bg-white py-3 pl-12 pr-10 text-[15px] text-gray-900 placeholder:text-slate-400 shadow-sm focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-200"
          />
          {isSearching && (
            <button
              type="button"
              onClick={clearSearch}
              className="absolute right-2.5 top-1/2 -translate-y-1/2 rounded p-0.5 text-gray-400 hover:text-gray-700"
              aria-label="Очистить"
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                <line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" />
              </svg>
            </button>
          )}
        </div>

        {trimmed.length >= 2 && (
          <div className="max-h-64 overflow-y-auto rounded-xl border border-slate-200 bg-white shadow-sm">
            {searchLoading ? (
              <p className="px-3 py-2 text-sm text-gray-500">Поиск...</p>
            ) : searchHits.length === 0 ? (
              <p className="px-3 py-2 text-sm text-gray-500">
                {searchErr || 'Ничего не найдено'}
              </p>
            ) : (
              searchHits.map((hit, idx) => {
                const isActive = idx === activeSearchIdx;
                return (
                  <MeasureHoverCard key={`${hit.code}-${hit.name}`} code={hit.code} fallbackName={hit.name}>
                    <button
                      type="button"
                      onMouseEnter={() => setActiveSearchIdx(idx)}
                      onClick={() => handleSelectHit(hit)}
                      className={`flex w-full flex-col items-start border-b border-slate-100 px-3 py-2.5 text-left last:border-b-0 hover:bg-slate-50 ${
                        isActive ? 'bg-indigo-50' : ''
                      }`}
                    >
                      <span className="font-mono text-[13px] font-medium text-gray-800">
                        {formatCode(hit.code)}
                        {hit.is_leaf === false ? (
                          <span className="ml-2 text-[10px] font-normal text-amber-700">группа</span>
                        ) : null}
                      </span>
                      <span className={`text-[14px] text-gray-800 ${TNVED_COMMODITY_NAME_CLASS}`}>
                        {formatTnvedCommodityName(hit.name || '') || 'Описание отсутствует'}
                      </span>
                    </button>
                  </MeasureHoverCard>
                );
              })
            )}
          </div>
        )}

        {/* Строка подсказки / результаты */}
        {isSearching && !prefixLoading && (
          <p className="px-1 text-[11px] text-gray-500">
            {resultCount === 0
              ? 'Ничего не найдено'
              : `Найдено позиций: ${resultCount}`}
          </p>
        )}
        {isSearching && prefixLoading && (
          <p className="px-1 text-[11px] text-gray-400">Поиск…</p>
        )}
        {loadErr && (
          <div className="rounded border border-amber-200 bg-amber-50 px-2 py-1 text-xs text-amber-900">
            {loadErr}
          </div>
        )}
      </div>

      {/* ─── Дерево ─── */}
        <div className={`relative min-h-0 flex-1 overflow-x-auto overflow-y-auto rounded-xl border border-slate-100 bg-white p-1 pr-2 transition-opacity ${prefixLoading ? 'opacity-50' : 'opacity-100'}`}>
        {loading ? (
          <p className="py-10 text-center text-sm text-gray-500">Загрузка справочника…</p>
        ) : displayTree.length === 0 ? (
          <div className="py-10 text-center">
            <p className="text-sm text-gray-500">Ничего не найдено</p>
            {isSearching && (
              <button onClick={clearSearch} className="mt-2 text-xs text-blue-600 hover:underline">
                Сбросить поиск
              </button>
            )}
          </div>
        ) : (
          displayTree.map((n) => (
            <TreeRow
              key={n.code}
              node={n}
              depth={0}
              expanded={expanded}
              toggle={toggle}
              selectedCode={selectedCode}
              onSelectCode={onSelectCode}
              searchQuery={trimmed}
            />
          ))
        )}
      </div>
    </div>
  );
};
