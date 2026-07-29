import { api } from './client';

const PREFIX = '/v1/tnved';

// ---------------------------------------------------------------------------
// Типы
// ---------------------------------------------------------------------------

export type TnvedSectionRow = {
  id: number;
  roman_number: string;
  title: string;
  notes: string;
  chapters_count: number;
};

export type TnvedChapterRow = {
  id: number;
  section_id: number;
  code: string;
  title: string;
  notes: string;
};

export type TnvedCommodityRow = {
  id: number;
  chapter_id: number;
  code: string;
  description: string;
  unit: string;
  supp_unit?: string;
  weight_coeff?: number;
  import_duty: string;
};

export type TnvedSearchHit = {
  code: string;
  name: string;
  /** Реальный декларируемый лист (не групповой заголовок). */
  is_leaf?: boolean;
  match_reason?: 'code_prefix' | 'name_match' | 'domain_dictionary' | 'typo_correction' | 'full_text';
  canonical_anchor?: CanonicalAnchor;
};

export type TnvedSearchResponse = {
  results: TnvedSearchHit[];
  guided_routes: TnvedGuidedSearchRoute[];
  suggestions: Array<{ term: string; hint: string }>;
  search: {
    strategy: string;
    corrected_query: string | null;
    effective_query: string;
  } | null;
};

export type TnvedGuidedSearchRoute = {
  heading: string;
  title: string;
  candidate_count: number;
  best_match_reason: NonNullable<TnvedSearchHit['match_reason']>;
  first_result_rank: number;
  canonical_anchor: CanonicalAnchor;
  guided_href: string;
};

export type CanonicalAnchor = {
  stable_id: string;
  snapshot_id: string;
  code: string | null;
  node_type: string;
};

export type GuidedTnvedNode = {
  id: string;
  kind:
    | 'heading'
    | 'classification_group'
    | 'classification_subgroup'
    | 'commodity'
    | 'leaf';
  role: 'semantic_choice' | 'code_branch' | 'declarable_code';
  title: string;
  code: string | null;
  is_leaf: boolean;
  result_count: number;
  code_count: number;
  confidence: 'high' | 'medium' | null;
  canonical_anchor: CanonicalAnchor | null;
  children: GuidedTnvedNode[];
};

export type GuidedTnvedResponse = {
  status: 'OK' | 'DEGRADED';
  engine: {
    name: 'guided_tnved';
    version: string;
    mode: 'canonical_semantic_overlay' | 'safe_fallback';
    snapshot_id: string | null;
  };
  heading: {
    code: string;
    title: string;
    canonical_anchor: CanonicalAnchor | null;
  };
  prompt: string;
  choices: GuidedTnvedNode[];
  integrity: {
    complete: boolean;
    expected_real_codes?: number;
    reachable_real_codes?: number;
    canonical_bound_codes?: number;
    canonical_coverage?: number;
    fake_codes?: number;
    critical_issues: string[];
    semantic_groups?: number;
    semantic_subgroups?: number;
    semantic_max_depth?: number;
    nesting_fallbacks?: number;
    rejected_unsafe_groups?: number;
    pruned_empty_groups?: number;
  };
  explanation?: {
    structure_source: string;
    semantic_source: string;
    groups_have_codes: boolean;
    final_choices_are_real_codes: boolean;
  };
  reason?: string;
  message?: string;
  fallback: {
    type: string;
    href: string;
    label: string;
  };
};

export type TnvedPreview = {
  status: string;
  code: string;
  name: string;
  payments: {
    duty: string;
    vat_rates: number[];
    excise: string;
  };
  non_tariff: {
    has_ban: boolean;
    measure_types: string[];
    measure_badges: string[];
    empty_message: string;
  };
  features: string[];
  special_duties?: {
    has_measures: boolean;
    countries: string[];
    warning: string;
  };
  trois?: {
    has_protected_brands: boolean;
    brands: string[];
    items: Array<{
      id: number;
      brand_name: string;
      hs_code_prefix: string;
      reg_number: string;
      right_holder: string;
    }>;
    warning: string;
  };
};

export type TnvedCommodityDetail = {
  status: string;
  code: string;
  name?: string;
  description: string;
  unit: string;
  import_duty: string;
  notes?: string;
  notes_combined?: string;
  non_tariff_measures?: Array<{
    id: number;
    commodity_code: string;
    measure_type: string;
    description: string;
    document_required: string;
    regulatory_act: string;
    type_label?: string;
    permit_type?: string;
  }>;
  intellectual_properties?: Array<{
    id: number;
    brand_name: string;
    hs_code_prefix: string;
    reg_number: string;
    right_holder: string;
  }>;
  chapter: { id: number; code: string; title: string; notes: string };
  section: { id: number; roman_number: string; title: string; notes: string };
  preliminary_decisions?: TnvedPreliminaryDecisionsBlock;
  /** Устойчивая ссылка для AI/RAG и следующих модулей; не влияет на отображение. */
  canonical_anchor?: CanonicalAnchor | null;
};

export type TnvedClassificationDecision = {
  id: number;
  kind: 'classification';
  hs_code: string;
  decision_number: string;
  issue_date: string;
  product_name: string;
  target_entity: string;
  description: string;
  source: string;
};

export type TnvedPreliminaryDecisionItem = {
  id: number;
  kind: 'preliminary';
  hs_code: string;
  description: string;
  source: string;
};

export type TnvedPreliminaryDecisionsBlock = {
  classification_decisions: TnvedClassificationDecision[];
  preliminary_decisions: TnvedPreliminaryDecisionItem[];
  total_count: number;
  empty_message: string;
};

export type TnvedImportReference = {
  status: string;
  title: string;
  fields: Array<{ label: string; value: string }>;
  sections: Array<{
    title: string;
    items: string[];
    sources?: Array<{ title: string; url: string }>;
  }>;
};

/**
 * Узел дерева ТН ВЭД.
 * Бэкенд возвращает: 4-значные папки → 6-значные подпапки → 10-значные листья.
 * code — строка, нули НЕ теряются.
 */
export type TnvedHierarchyNode = {
  code: string;
  name: string;
  title_ru?: string;
  import_duty: string;
  notes: string;
  /** Терминальный 10-значный декларируемый код (кликабельный). */
  is_leaf?: boolean;
  /** Бескодовая субпозиция — промежуточный уровень, только текст (не кликабельный). */
  is_codeless?: boolean;
  /** Раздел / группа / товарная позиция (раскрываемый заголовок). */
  is_group?: boolean;
  /** Код без пробелов (только цифры). */
  display_code?: string;
  children: TnvedHierarchyNode[];
};

// ---------------------------------------------------------------------------
// API-функции
// ---------------------------------------------------------------------------

export async function fetchSections(): Promise<TnvedSectionRow[]> {
  const { data } = await api.get<{ status: string; sections: TnvedSectionRow[] }>(`${PREFIX}/sections`);
  return data.sections ?? [];
}

export async function fetchChapters(sectionId: number): Promise<TnvedChapterRow[]> {
  const { data } = await api.get<{ status: string; chapters: TnvedChapterRow[] }>(
    `${PREFIX}/sections/${sectionId}/chapters`,
  );
  return data.chapters ?? [];
}

export async function fetchCommodities(chapterId: number): Promise<TnvedCommodityRow[]> {
  const { data } = await api.get<{ status: string; commodities: TnvedCommodityRow[] }>(
    `${PREFIX}/chapters/${chapterId}/commodities`,
  );
  return data.commodities ?? [];
}

export async function fetchCommodityByCode(code: string): Promise<TnvedCommodityDetail> {
  const norm = code.replace(/\D/g, '');
  const { data } = await api.get<TnvedCommodityDetail>(`${PREFIX}/${encodeURIComponent(norm)}`);
  return data;
}

export type TnvedChildItem = {
  code: string;
  display_code: string;
  name: string;
  level: string;
  is_leaf: boolean;
  is_codeless: boolean;
  is_group?: boolean;
  has_children: boolean;
  import_duty?: string;
  duty_rate?: string;
  vat_rate?: number | null;
  children_count?: number;
  section_id?: number;
  chapter_id?: number;
  has_ds?: boolean;
  has_ss?: boolean;
};

export async function fetchTnvedChildren(
  code?: string,
  depth: 'direct' | 'all' = 'direct',
): Promise<{ status: string; code: string; depth: string; items: TnvedChildItem[] }> {
  const qs = `depth=${encodeURIComponent(depth)}`;
  const url = code?.trim()
    ? `/tnved/children/${encodeURIComponent(code.trim())}?${qs}`
    : `/tnved/children?${qs}`;
  const { data } = await api.get<{ status: string; code: string; depth: string; items: TnvedChildItem[] }>(url);
  return data;
}

export async function fetchTnvedNode(code: string): Promise<TnvedChildItem & { children?: TnvedChildItem[] }> {
  const norm = code.replace(/\D/g, '').slice(0, 10);
  const { data } = await api.get<{ status: string; node: TnvedChildItem & { children?: TnvedChildItem[] } }>(
    `/tnved/node/${encodeURIComponent(norm || code.trim())}`,
  );
  return data.node;
}

export async function fetchGuidedTnvedNavigation(heading: string): Promise<GuidedTnvedResponse> {
  const norm = heading.replace(/\D/g, '').slice(0, 4);
  if (norm.length !== 4) {
    throw new Error('Для умного маршрута нужна 4-значная товарная позиция');
  }
  const { data } = await api.get<GuidedTnvedResponse>(
    `${PREFIX}/guided/${encodeURIComponent(norm)}`,
  );
  return data;
}

export async function fetchHierarchyTree(prefix?: string): Promise<TnvedHierarchyNode[]> {
  const p = (prefix ?? '').replace(/\D/g, '').slice(0, 10);
  const qs = p ? `?prefix=${p}` : '';
  const { data } = await api.get<{ status: string; tree: TnvedHierarchyNode[] }>(
    `${PREFIX}/hierarchy-tree${qs}`,
  );
  return data.tree ?? [];
}

export type TnvedBreadcrumbItem = {
  hs_code: string;
  title: string;
  level: number;
};

export async function fetchTnvedBreadcrumb(code: string): Promise<TnvedBreadcrumbItem[]> {
  const norm = code.replace(/\D/g, '').slice(0, 10);
  if (!norm) return [];
  const { data } = await api.get<{ status: string; breadcrumb: TnvedBreadcrumbItem[] }>(
    `/tnved/breadcrumb/${encodeURIComponent(norm)}`,
  );
  return data.breadcrumb ?? [];
}

export async function searchTnved(q: string): Promise<TnvedSearchResponse> {
  const query = (q ?? '').trim();
  if (query.length < 2) {
    return { results: [], suggestions: [], guided_routes: [], search: null };
  }
  const { data } = await api.get<{
    status: string;
    results: TnvedSearchHit[];
    suggestions?: Array<{ term: string; hint: string }>;
    guided_routes?: TnvedGuidedSearchRoute[];
    search?: TnvedSearchResponse['search'];
  }>(
    `${PREFIX}/search?q=${encodeURIComponent(query)}`,
  );
  return {
    results: data.results ?? [],
    suggestions: data.suggestions ?? [],
    guided_routes: data.guided_routes ?? [],
    search: data.search ?? null,
  };
}

export async function fetchTnvedPreview(code: string): Promise<TnvedPreview> {
  const norm = code.replace(/\D/g, '');
  const { data } = await api.get<TnvedPreview>(`${PREFIX}/preview/${encodeURIComponent(norm)}`);
  return data;
}

export async function fetchTnvedImportReference(code: string, country = ''): Promise<TnvedImportReference> {
  const norm = code.replace(/\D/g, '');
  const qs = country ? `?country=${encodeURIComponent(country.toUpperCase())}` : '';
  const { data } = await api.get<TnvedImportReference>(`${PREFIX}/reference/${encodeURIComponent(norm)}${qs}`);
  return data;
}

export async function fetchPreliminaryDecisions(code: string): Promise<TnvedPreliminaryDecisionsBlock> {
  const norm = code.replace(/\D/g, '');
  const { data } = await api.get<{ status: string; preliminary_decisions: TnvedPreliminaryDecisionsBlock }>(
    `${PREFIX}/${encodeURIComponent(norm)}/preliminary-decisions`,
  );
  return data.preliminary_decisions ?? {
    classification_decisions: [],
    preliminary_decisions: [],
    total_count: 0,
    empty_message: '',
  };
}

// ---------------------------------------------------------------------------
// Утилиты форматирования
// ---------------------------------------------------------------------------

/**
 * formatCode — визуальный вид кода ТН ВЭД.
 * 10 цифр → «XXXX XX XXX X» (например 0101 21 000 0).
 *  6 цифр → «XXXX XX»        (например 0101 21).
 *  4 цифры → «XXXX»           без изменений.
 */
export function formatCode(code: string): string {
  const d = code.replace(/\D/g, '');
  if (d.length === 10) {
    return `${d.slice(0, 4)} ${d.slice(4, 6)} ${d.slice(6, 9)} ${d.slice(9)}`;
  }
  if (d.length === 6) {
    return `${d.slice(0, 4)} ${d.slice(4, 6)}`;
  }
  return code.trim();
}

/** @deprecated используйте formatCode */
export const formatCustomsCode = formatCode;

/** Полный товарный код (ровно 10 цифр). */
export function isFullTnvedCode(code: string): boolean {
  return code.replace(/\D/g, '').length === 10;
}

/** Код для карточки: 4 или 10 цифр. */
export function isCatalogDetailCode(code: string): boolean {
  const n = code.replace(/\D/g, '').length;
  return n === 4 || n === 10;
}

/** Сноски к тарифной таблице в PDF: 63С), 563С), 1363С) — не показываем. */
function stripDutyFootnotes(raw: string): string {
  return raw.replace(/\d+[СC]\)/g, '').replace(/\s+/g, ' ').trim();
}

/** Нормализация ставки пошлины для отображения. */
export function formatImportDutyPercent(raw: string): string {
  const t = stripDutyFootnotes((raw || '').trim());
  if (!t) return '';
  if (/%|‰/.test(t)) return t.replace(/\s*%/g, '%').replace(/\s+/g, ' ').trim();
  const compact = t.replace(/\s/g, '').replace(',', '.');
  if (/^\d+\.?\d*$/.test(compact)) {
    const num = Number(compact);
    if (!Number.isFinite(num)) return t;
    return Number.isInteger(num) ? `${num}%` : `${num}%`;
  }
  return t;
}
