export type ApiStatus = 'OK' | 'ERROR' | 'WARNING' | 'SKIPPED' | 'NOT_FOUND' | 'REJECTED';

export type JsonPrimitive = string | number | boolean | null;
export interface JsonObject {
  [key: string]: JsonValue;
}
export type JsonValue = JsonPrimitive | JsonObject | JsonValue[];

export interface ApiValidationErrorDetail {
  loc: Array<string | number>;
  msg: string;
  type: string;
}

export interface ApiErrorResponse {
  detail?: string | ApiValidationErrorDetail[];
  message?: string;
  error?: string;
}

// ---------------------------------------------------------------------------
// Auth
// ---------------------------------------------------------------------------

export interface AuthLoginResponse {
  status: 'OK';
  token_type: 'cookie';
  username: string;
  role: string;
}

export interface AuthSessionResponse {
  status: 'OK';
  authenticated: boolean;
  username: string;
  role: string;
}

// ---------------------------------------------------------------------------
// TN VED preview/context
// ---------------------------------------------------------------------------

export interface TnvedPreviewTroisItem {
  id: number;
  brand_name: string;
  hs_code_prefix: string;
  reg_number: string;
  right_holder: string;
}

export interface TnvedPreviewResponse {
  status: 'OK';
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
  special_duties: {
    has_measures: boolean;
    countries: string[];
    warning: string;
  };
  trois: {
    has_protected_brands: boolean;
    brands: string[];
    items: TnvedPreviewTroisItem[];
    warning: string;
  };
}

export interface TnvedContextBreadcrumbItem {
  hs_code: string;
  title: string;
  level: number;
}

export interface TnvedContextNote {
  id: number;
  scope_type: string;
  scope_value: string;
  category: string;
  title: string;
  body: string;
  source_url: string;
  source_revision: string;
  sort_order: number;
}

export interface TnvedContext {
  hs_code: string;
  title: string;
  description: string;
  breadcrumb: TnvedContextBreadcrumbItem[];
  notes: TnvedContextNote[];
  official_ett_url: string;
  source_revision: string;
}

// ---------------------------------------------------------------------------
// Finance / search / sources
// ---------------------------------------------------------------------------

export interface FinanceRateRow {
  currency_code: string;
  rate: number;
  nominal: number;
  updated_at: string | null;
}

export interface FinanceRatesRefresh {
  status: 'OK';
  source: 'CBRF' | 'fallback';
  date: string;
  updated: number;
}

export interface FinanceRatesResponse {
  status: 'OK';
  base: 'RUB';
  updated_at: string | null;
  rates: FinanceRateRow[];
  map: Record<string, number>;
  refresh?: FinanceRatesRefresh;
}

export interface SearchHsItem {
  hs_code: string;
  hs_prefix: string;
  duty_rate: number;
  vat_rate: number;
  vat_rule: string;
  title?: string;
  tnved_in_db?: boolean;
}

export interface SearchHsResponse {
  status: 'OK';
  query: string;
  items: SearchHsItem[];
  count: number;
}

export interface SourceStatusItem {
  source_code: string;
  source_name: string;
  source_url: string;
  revision: string;
  synced_at: string | null;
  is_stale: boolean;
  fallback: boolean;
  note: string;
}

export interface IntegratedDataStats {
  hs_rates_count: number;
  non_tariff_rules_count: number;
  tnved_entries_count: number;
  normative_notes_count: number;
  tr_ts_acts_count: number;
  ingested_documents_count: number;
  tnved_embeddings_count: number;
  customs_calculation_history_count: number;
}

export interface NormativeDataHint {
  level: 'info' | 'warning' | 'error' | string;
  code: string;
  text: string;
}

export interface SourcesStatusResponse {
  status: 'OK';
  sources: SourceStatusItem[];
  stats: IntegratedDataStats;
  hints: NormativeDataHint[];
}

export interface SourceImportSimpleResponse {
  status: 'OK';
  imported: number;
  skipped: number;
  revision: string;
}

export interface SourceImportBundleResponse {
  status: 'OK';
  revision: string;
  imported: {
    tnved: number;
    rates: number;
    non_tariff_rules: number;
    notes: number;
  };
  skipped: {
    tnved: number;
    rates: number;
    non_tariff: number;
    notes: number;
  };
}

export type SourceImportResponse = SourceImportSimpleResponse | SourceImportBundleResponse;

export type TamdocCandidateStatus = 'pending' | 'error' | 'skipped' | 'approved' | 'rejected';

export interface TamdocSyncCandidate {
  id: number;
  doc_url: string;
  doc_title: string;
  doc_type: string;
  status: TamdocCandidateStatus;
  hs_prefix: string;
  country_codes: string;
  vat_rates: string;
  percent_rates: string;
  measure_type_hint: string;
  excerpt: string;
  error_message: string;
  created_at: string | null;
  updated_at: string | null;
}

export interface TamdocCandidatesResponse {
  status: 'OK';
  items: TamdocSyncCandidate[];
}

// ---------------------------------------------------------------------------
// Calculator
// ---------------------------------------------------------------------------

/** Ответ POST /v1/documents/analyze — разбор инвойса ИИ */
export interface InvoiceAnalyzeItem {
  name: string;
  suggested_hs_code: string;
  price: number;
  net_weight_kg: number | null;
  currency: string;
  image_paths?: string[];
  ai_visual_description?: string;
}

export interface InvoiceAnalyzeResponse {
  status: 'OK' | 'ERROR';
  items: InvoiceAnalyzeItem[];
  error?: string;
  error_code?: string;
  source?: string;
  model?: string;
  items_count?: number;
  raw_preview?: string;
}

export interface CalculatorComputeRequest {
  hs_code: string;
  customs_value: number;
  invoice_currency?: string;
  freight?: number;
  insurance?: number | null;
  duty_rate?: number | null;
  vat_rate?: number | null;
  excise?: number | null;
  country?: string | null;
  quantity?: number | null;
  net_weight_kg?: number | null;
  extra_quantity?: number | null;
  apply_reduced_vat?: boolean;
  save_history?: boolean;
  document_id?: string | null;
  user_ref?: string;
}

export interface CalculatorDataQuality {
  confidence: 'high' | 'medium' | 'low' | 'none';
  matched_prefix: string;
  match_length: number;
  source_code: string | null;
  antidumping_status: string;
}

export interface CalculatorSpecialDutyItem {
  hs_code_prefix: string;
  origin_country: string;
  rate_percent: number;
  rate_specific: number;
  currency_code: string;
  fx_rate: number;
  regulatory_act: string;
  amount: number;
  match_len: number;
}

export interface CalculatorAutoDetected {
  duty_rate: number;
  duty_rule_type: string;
  duty_rule_code: string;
  duty_rule_match_len: number;
  vat_rate: number;
  apply_reduced_vat: boolean;
  vat_rule: string;
  vat_pref_match_len: number;
  excise_type: string;
  excise_value: number;
  antidumping_type: string;
  antidumping_value: number;
  antidumping_condition: string;
  antidumping_countries: string;
}

export interface CalculatorBreakdown {
  customs_fee: number;
  duty_rate: number;
  duty: number;
  ad_valorem_amount: number | null;
  specific_amount_rub: number | null;
  selected_rule: string;
  fx_rate: number | null;
  fx_currency: string;
  specific_qty_used: number | null;
  specific_uom: string;
  excise: number;
  excise_reason: string;
  antidumping: number;
  antidumping_reason: string;
  antidumping_status: string;
  special_duties_amount: number;
  vat_rate: number;
  vat_reason: string;
  vat_decree_info: string;
  vat_pref_comment: string;
  vat_base: number;
  vat: number;
  total_payable: number;
}

export interface CalculatorLegalBasis {
  vat: string;
  duty: string;
  customs_fee: string;
  antidumping: string;
  excise: string;
}

export interface CalculatorSourceLayer {
  name: string;
  integrated: boolean;
  data_info: string;
  revision: string;
  url?: string;
}

export interface CalculatorInvoiceInfo {
  currency: string;
  amount: number;
  fx_rate: number;
  customs_value_rub: number;
}

export interface CalculatorComputeResponse {
  status: 'OK';
  hs_code: string;
  country: string | null;
  customs_value: number;
  freight: number;
  insurance: number;
  auto_detected: CalculatorAutoDetected;
  breakdown: CalculatorBreakdown;
  legal_basis: CalculatorLegalBasis;
  data_quality: CalculatorDataQuality;
  sources: CalculatorSourceLayer[];
  tnved_context: TnvedContext;
  special_duties: CalculatorSpecialDutyItem[];
  special_duties_amount: number;
  invoice?: CalculatorInvoiceInfo;
  fx_source?: string;
}

export interface CalculatorDutyRuleInfo {
  commodity_code: string;
  type: string;
  ad_valorem_pct: number | null;
  specific_amount: number | null;
  specific_currency: string;
  specific_uom: string;
  match_len: number;
}

export interface CalculatorCommodityMetaInfo {
  commodity_code: string;
  supp_unit: string;
  weight_coeff: number;
  match_len: number;
}

export interface CalculatorDutyRuleResponse {
  status: 'OK';
  hs_code: string;
  duty_rule: CalculatorDutyRuleInfo | null;
  commodity_meta: CalculatorCommodityMetaInfo | null;
}

export interface CalculatorCompareSharedInput {
  customs_value: number;
  invoice_currency?: string;
  freight?: number;
  insurance?: number | null;
  country?: string | null;
  quantity?: number | null;
  net_weight_kg?: number | null;
  extra_quantity?: number | null;
  apply_reduced_vat?: boolean;
}

export interface CalculatorCompareScenarioInput {
  hs_code: string;
  label?: string | null;
  duty_rate?: number | null;
  vat_rate?: number | null;
  excise?: number | null;
}

export interface CalculatorCompareRequest {
  shared: CalculatorCompareSharedInput;
  scenarios: CalculatorCompareScenarioInput[];
  save_history?: boolean;
  document_id?: string | null;
  user_ref?: string;
}

export interface CalculatorCompareSharedEconomic {
  customs_value: number;
  freight: number;
  insurance?: number;
  country?: string;
  quantity?: number;
  _fx_rates?: Record<string, number>;
}

export interface CalculatorCompareScenarioResult {
  label: string;
  hs_code: string;
  delta_total_vs_first_rub: number | null;
  total_payable: number;
  duty: number;
  vat: number;
  excise: number;
  antidumping: number;
  duty_rate_applied: number;
  vat_rate_applied: number;
  data_quality: CalculatorDataQuality;
  tnved_title: string;
}

export interface CalculatorCompareResponse {
  status: 'OK';
  shared_economic: CalculatorCompareSharedEconomic;
  scenarios: CalculatorCompareScenarioResult[];
  invoice?: CalculatorInvoiceInfo;
  fx_source?: string;
}

export type CalculationHistoryKind = 'compute' | 'compare' | 'compliance' | 'copilot' | 'copilot_batch';

export interface CalculatorHistorySummaryResponse {
  status: 'OK';
  total: number;
  by_kind: Record<CalculationHistoryKind, number>;
  other: number;
  kinds: CalculationHistoryKind[];
}

export interface CalculatorHistoryListItem {
  id: string;
  document_id: string | null;
  user_ref: string;
  currency: string;
  created_at: string | null;
  hs_code: string | null;
  kind: CalculationHistoryKind | null;
  total_payable: number | null;
}

export interface CalculatorHistoryListResponse {
  status: 'OK';
  items: CalculatorHistoryListItem[];
}

export interface CalculatorHistoryExportJsonResponse {
  status: 'OK';
  count: number;
  items: CalculatorHistoryListItem[];
}

// ---------------------------------------------------------------------------
// TROIS
// ---------------------------------------------------------------------------

export interface TroisSuggestion {
  key: string;
  label: string;
  note?: string;
  score?: number;
}

export interface TroisSuggestResponse {
  status: 'OK';
  suggestions: TroisSuggestion[];
}

export interface TroisCheckDetail {
  cols?: Array<string | number>;
}

export interface TroisCheckResponse {
  status: 'OK' | 'ERROR';
  found: boolean;
  details: TroisCheckDetail[];
  error?: string;
  note?: string;
}

export interface TroisSyncResponse {
  status: 'OK' | 'WARNING';
  source: 'TROIS_SYNC';
  parsed_records: number;
  dedup_records: number;
  created: number;
  updated: number;
  skipped: number;
  errors: string[];
}

// ---------------------------------------------------------------------------
// Assistant / staging / decisions
// ---------------------------------------------------------------------------

export interface PermitInput {
  type: string;
  number: string;
}

export interface PermitHsCodeCheck {
  hs_match: 'ok' | 'partial' | 'mismatch' | 'unknown';
  detail: string;
  matched_registry_code?: string | null;
}

export interface PermitVerificationResult {
  type: string;
  status: 'VALID' | 'NOT_FOUND' | 'UNKNOWN' | 'SKIPPED' | string;
  number: string;
  holder?: string | null;
  valid_from?: string | null;
  valid_to?: string | null;
  registry_link?: string | null;
  raw?: JsonObject | null;
  note?: string;
  error?: string;
  verified_at?: string;
  registry_source?: string;
  hs_code_check?: PermitHsCodeCheck;
}

export interface AssistantRuleSource {
  name: string;
  integrated: boolean;
  data_info: string;
  required_permits: string[];
  revision: string;
  hs_prefix: string;
  priority: number;
  tr_ts_edition?: string;
  exception_note?: string;
}

export interface AssistantDataFreshness {
  source_name: string;
  source_code: string;
  synced_at: string | null;
  is_stale: boolean;
  revision: string;
}

export interface AssistantTrTsRegistryItem {
  act_code: string;
  short_name: string;
  full_title: string;
  edition_note: string;
  source_url: string;
  source_revision: string;
}

export type AdvisoryRequirement = {
  permit_type: string;
  tr_ts?: string | null;
  applicability: 'possible' | 'needs_clarification' | 'definite' | string;
  source: string;
  source_label?: string | null;
  used_for_missing_check: false;
  requires_manual_review: boolean;
  hs_prefix?: string | null;
  rule_name?: string | null;
  reason: string;
  note?: string | null;
};

export type NormativeDocument = {
  permit_type: string;
  tr_ts?: string | null;
  source?: string;
  source_label?: string | null;
  applicability?: string;
  reason?: string | null;
  used_for_missing_check?: boolean;
  rule_name?: string | null;
};

export type NormativeRequirementsBlockData = {
  status?: string;
  hs_code?: string;
  description?: string;
  required_documents: NormativeDocument[];
  missing_documents: NormativeDocument[];
  advisory_requirements: AdvisoryRequirement[];
  sources_summary?: string[];
  empty_message?: string | null;
  tr_ts?: string[];
  notes?: string[];
};

export interface AssistantNonTariffResult {
  status: 'OK' | 'WARNING' | 'ERROR' | 'UNKNOWN' | string;
  hs_code: string;
  description?: string;
  country?: string | null;
  tr_ts?: string[];
  tr_ts_act_codes?: string[];
  tr_ts_registry?: AssistantTrTsRegistryItem[];
  required_permit_types?: string[];
  permits?: PermitVerificationResult[];
  missing_permit_types?: string[];
  normative_block?: NormativeRequirementsBlockData;
  advisory_requirements?: AdvisoryRequirement[];
  notes?: string[];
  rule_sources?: AssistantRuleSource[];
  data_freshness?: AssistantDataFreshness;
  note?: string;
}

export interface AssistantClassificationVariant {
  hs_code?: string;
  code?: string;
  tnved?: string;
  name?: string;
  import_duty?: string;
  required_permit_types?: string[];
  reason?: string;
  recommended?: boolean;
}

export interface AssistantClassificationResult {
  status?: string;
  query?: string;
  note?: string;
  provider?: string;
  error?: string;
  raw_response?: JsonObject;
  recommended?: string | AssistantClassificationVariant;
  results?: AssistantClassificationVariant[];
  variants?: AssistantClassificationVariant[];
}

export interface AssistantPipelineStep {
  step: 'classification' | 'non_tariff' | 'payment' | 'registry' | string;
  ok?: boolean;
  skipped?: boolean;
  detail?: string;
  total?: number;
  status?: string;
  count?: number;
}

export interface AssistantCopilotBundle {
  effective_hs_code: string;
  description: string;
  country?: string | null;
  pipeline: AssistantPipelineStep[];
  classification?: AssistantClassificationResult | null;
  non_tariff?: AssistantNonTariffResult;
  payment?: CalculatorComputeResponse | null;
  permits_input?: PermitInput[];
  permits_verification?: PermitVerificationResult[] | null;
  tnved_context?: TnvedContext | null;
}

export interface AssistantCopilotAi {
  status?: string;
  provider?: string;
  summary?: string;
  classification_advice?: string;
  payment_comment?: string;
  non_tariff_comment?: string;
  documents_comment?: string;
  risks?: string[];
  next_steps?: string[];
  disclaimer?: string;
  note?: string;
  conclusion?: string;
  raw?: string;
}

export interface AssistantCopilotResponse {
  status: 'OK';
  bundle: AssistantCopilotBundle;
  context_for_ai: JsonObject;
  ai: AssistantCopilotAi;
}

/** Контекст расчёта калькулятора для POST /v1/assistant/chat */
export interface AssistantChatNonTariffMeasureContext {
  measure_type?: string;
  regulatory_act?: string;
  document_required?: string;
  description?: string;
}

export interface AssistantCalculationCurrentContext {
  hs_code?: string;
  product_name?: string;
  origin_country?: string | null;
  total_payable?: number;
  non_tariff_measures?: AssistantChatNonTariffMeasureContext[];
  /** Снимок ключевых сумм из breakdown (не выдумывать ставки вне этого блока) */
  duty_rate_pct?: number;
  vat_rate_pct?: number;
  duty_rub?: number;
  vat_rub?: number;
  excise_rub?: number;
  customs_fee_rub?: number;
  customs_value_rub?: number;
  antidumping_rub?: number;
  special_duties_rub?: number;
  vat_base_rub?: number;
}

export interface AssistantChatHistoryItem {
  role: 'user' | 'assistant';
  /** Текст реплики (предпочтительно для API). */
  content: string;
  /** Устаревший алиас; сервер принимает и `content`, и `text`. */
  text?: string;
}

export interface AssistantChatRequest {
  message: string;
  history: AssistantChatHistoryItem[];
  /** Предпочтительное имя поля для снимка калькулятора */
  context?: AssistantCalculationCurrentContext | null;
  current_context?: AssistantCalculationCurrentContext | null;
}

export interface AssistantChatResponse {
  status: string;
  answer: string;
}

export interface AssistantCopilotBatchResponse {
  status: 'OK';
  bundles: AssistantCopilotBundle[];
  context_for_ai: JsonObject;
  ai: AssistantCopilotAi;
}

export interface AssistantAnalyzeResponse {
  status: string;
  items: AssistantNonTariffResult[];
  ai: {
    status?: string;
    provider?: string;
    hs_code_ok?: boolean;
    tr_ts?: string[];
    documents_sufficient?: boolean;
    risks?: string[];
    conclusion?: string;
    note?: string;
    raw?: string;
  };
}

export interface AssistantDecisionLogResponse {
  status: 'OK';
}

export interface AssistantDecisionRecord {
  ts?: string;
  description?: string;
  suggested_hs?: string;
  confirmed_hs?: string;
  source?: string;
  notes?: string;
  client_id?: string;
  audit_subject?: string;
}

export interface AssistantDecisionsRecentResponse {
  status: 'OK';
  items: AssistantDecisionRecord[];
}

export interface AssistantDecisionHintItem {
  description?: string;
  suggested_hs?: string;
  confirmed_hs?: string;
  ts?: string;
  similarity?: number;
  similarity_base?: number;
  client_match?: boolean;
}

export interface AssistantHsSuggestionItem {
  hs_code: string;
  weight: number;
  count: number;
  best_similarity: number;
  sample_description: string;
  client_boosted_rows?: number;
}

export interface AssistantDecisionHintsResponse {
  status: 'OK';
  similar: AssistantDecisionHintItem[];
  hs_suggestions: AssistantHsSuggestionItem[];
  prefer_client_id?: string | null;
}

export interface AssistantJournalStatsResponse {
  status?: 'OK' | 'ERROR';
  message?: string;
  journal_path?: string;
  file_exists?: boolean;
  records_in_index?: number;
  unique_confirmed_hs_codes?: number;
  unique_client_ids?: number;
  first_ts?: string | null;
  last_ts?: string | null;
  top_confirmed_hs?: Array<{ hs_code: string; count: number }>;
  by_source?: Array<{ source: string; count: number }>;
}
