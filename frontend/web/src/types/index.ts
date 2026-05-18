export type Finance = {
  duty_rate: string;
  vat_rate: number;
  excise: number;
};

export type MoneyBreakdown = {
  base_duty: number;
  vat: number;
  excise: number;
  anti_dumping: number;
  customs_fee: number;
  total_payable: number;
};

export type ComplianceDocumentItem = {
  doc_type: string;
  legal_ref: string;
  title: string;
  detail: string;
  source: string;
  priority: number;
  registry_match?: string | null;
};

export type PaymentProfile = {
  status: string;
  hs_code: string;
  country?: string | null;
  breakdown: MoneyBreakdown;
  documents: ComplianceDocumentItem[];
  geo?: {
    embargo?: boolean;
    duty_override_rate?: number | null;
    document_basis?: string;
    document_link?: string;
    measure_type?: string;
  } | null;
  data_quality?: Record<string, unknown> | null;
};

export type AnalysisItem = {
  name: string;
  hs_code: string;
  hs_code_view?: string;
  finance: Finance;
  non_tariff_docs: string[];
  risks: string[];
  opi_steps: string[];
  payment_profile?: PaymentProfile | null;
  /** Опционально: артикул / бренд из инвойса (если бэкенд отдаёт) */
  article?: string;
  brand?: string;
};

export type AnalyzeResponse = {
  status: string;
  mode: "mock" | "mock_fallback" | "real_parser" | string;
  items_count: number;
  items: AnalysisItem[];
  warning?: string;
  source?: string;
};

export type HsLevel = "chapter" | "heading" | "subheading" | "item" | "section";

export type TnVedNode = {
  code: string;
  title_ru: string | null;
  /** Полный таможенный текст, собранный ETL: глава → позиция → подсубпозиция. */
  title_full?: string | null;
  level?: HsLevel | null;
  parent?: string | null;
  chapter?: string | null;
  has_children?: boolean;
  tariff?: {
    duty?: string | null;
    vat?: number | string | null;
    vat_source?: string | null;
    vat_reason?: string | null;
    add?: string | null;
  } | null;
};

export type TnVedPathItem = Pick<TnVedNode, "code" | "title_ru" | "title_full" | "level">;

export type TnVedDetail = TnVedNode & {
  path: TnVedPathItem[];
  children: TnVedNode[];
};
