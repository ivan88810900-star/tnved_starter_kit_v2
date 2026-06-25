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

export async function searchTnved(q: string): Promise<TnvedSearchHit[]> {
  const query = (q ?? '').trim();
  if (query.length < 2) return [];
  const { data } = await api.get<{ status: string; results: TnvedSearchHit[] }>(
    `${PREFIX}/search?q=${encodeURIComponent(query)}`,
  );
  return data.results ?? [];
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
