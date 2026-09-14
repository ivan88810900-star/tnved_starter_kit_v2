import type { AdvisoryRequirement } from './AdvisoryRequirementsBlock';

export type NormativeDocument = {
  permit_type: string;
  tr_ts?: string | null;
  tr_ts_full_name?: string | null;
  source?: string;
  source_label?: string | null;
  applicability?: string;
  reason?: string | null;
  used_for_missing_check?: boolean;
  rule_name?: string | null;
};

export type MeasureFamilyStatus = {
  family: string;
  label: string;
  status: 'definite' | 'needs_clarification' | 'legacy_signal' | 'not_detected' | string;
  requirements_count: number;
  signals_count?: number;
  permit_types?: string[];
  regulations?: string[];
  matched_sections?: string[];
  directions?: string[];
  source_labels?: string[];
};

export type NormativeRequirementsBlockData = {
  status?: string;
  hs_code?: string;
  description?: string;
  required_documents: NormativeDocument[];
  missing_documents: NormativeDocument[];
  advisory_requirements: AdvisoryRequirement[];
  measure_families?: MeasureFamilyStatus[];
  measure_families_disclaimer?: string | null;
  official_ntm_applicability?: {
    mode?: string;
    structured_facts_received?: number;
    exact_rows_count?: number;
    definite_advisory_count?: number;
    excluded_count?: number;
    exact_needs_clarification_count?: number;
    missing_fact_keys?: string[];
    broker_effect?: boolean;
    facts_trust_boundary?: string;
  } | null;
  official_ntm_resolved_exclusions?: Array<Record<string, unknown>>;
  official_ntm_catch_all?: {
    status?: string;
    applicability?: string;
    reason?: string;
    recommended_action?: string;
    missing_facts?: string[];
    source_url?: string | null;
    source_revision?: string | null;
    automatic_document_requirement?: boolean;
  } | null;
  curated_enforcement_audit?: {
    enabled?: boolean;
    default?: boolean;
    allowlist_version?: string;
    applied_rule_ids?: string[];
    broker_changed?: boolean;
  } | null;
  sources_summary?: string[];
  empty_message?: string | null;
  tr_ts?: string[];
  notes?: string[];
};

export function hasNormativeContent(block: NormativeRequirementsBlockData | null | undefined): boolean {
  if (!block) return false;
  return (
    (block.required_documents?.length ?? 0) > 0 ||
    (block.missing_documents?.length ?? 0) > 0 ||
    (block.advisory_requirements?.length ?? 0) > 0 ||
    Boolean(
      block.official_ntm_catch_all?.status
      && block.official_ntm_catch_all.status !== 'not_applicable_direction',
    )
  );
}

export function normativeBlockFromNonTariff(nonTariff: {
  normative_block?: NormativeRequirementsBlockData;
  required_permit_types?: string[];
  missing_permit_types?: string[];
  advisory_requirements?: AdvisoryRequirement[];
  status?: string;
  hs_code?: string;
  description?: string;
  tr_ts?: string[];
  notes?: string[];
  required_permits?: Array<{ permit_type?: string; tr_ts?: string | null; tr_ts_full_name?: string | null; description?: string; legal_ref?: string; trigger?: string; source?: string; applicability?: string }>;
} | null | undefined): NormativeRequirementsBlockData | null {
  if (!nonTariff) return null;
  if (nonTariff.normative_block) {
    return {
      required_documents: nonTariff.normative_block.required_documents ?? [],
      missing_documents: nonTariff.normative_block.missing_documents ?? [],
      advisory_requirements: nonTariff.normative_block.advisory_requirements ?? [],
      measure_families: nonTariff.normative_block.measure_families ?? [],
      measure_families_disclaimer: nonTariff.normative_block.measure_families_disclaimer,
      official_ntm_applicability: nonTariff.normative_block.official_ntm_applicability,
      official_ntm_resolved_exclusions: nonTariff.normative_block.official_ntm_resolved_exclusions,
      official_ntm_catch_all: nonTariff.normative_block.official_ntm_catch_all,
      curated_enforcement_audit: nonTariff.normative_block.curated_enforcement_audit,
      sources_summary: nonTariff.normative_block.sources_summary,
      empty_message: nonTariff.normative_block.empty_message,
      status: nonTariff.normative_block.status ?? nonTariff.status,
      hs_code: nonTariff.normative_block.hs_code ?? nonTariff.hs_code,
      description: nonTariff.normative_block.description ?? nonTariff.description,
      tr_ts: nonTariff.normative_block.tr_ts ?? nonTariff.tr_ts,
      notes: nonTariff.normative_block.notes ?? nonTariff.notes,
    };
  }
  const required = (nonTariff.required_permits ?? []).map((r) => ({
    permit_type: r.permit_type ?? '',
    tr_ts: r.tr_ts ?? null,
    tr_ts_full_name: r.tr_ts_full_name ?? null,
    source: r.source,
    source_label: r.source,
    applicability: r.applicability ?? 'definite',
    reason: [r.description, r.legal_ref, r.trigger ? `Триггер: ${r.trigger}` : null].filter(Boolean).join(' · ') || null,
    used_for_missing_check: true,
  })).filter((d) => d.permit_type);
  const missingSet = new Set(nonTariff.missing_permit_types ?? []);
  const missing = (nonTariff.missing_permit_types ?? []).map((pt) => ({
    permit_type: pt,
    tr_ts: required.find((r) => r.permit_type === pt)?.tr_ts ?? null,
    reason: 'Документ не указан среди предоставленных разрешений',
    used_for_missing_check: true,
  }));
  return {
    status: nonTariff.status,
    hs_code: nonTariff.hs_code,
    description: nonTariff.description,
    required_documents: required.length ? required : (nonTariff.required_permit_types ?? []).map((pt) => ({
      permit_type: pt,
      applicability: 'definite',
      used_for_missing_check: true,
    })),
    missing_documents: missing,
    advisory_requirements: nonTariff.advisory_requirements ?? [],
    empty_message: !required.length && !missingSet.size && !(nonTariff.advisory_requirements?.length)
      ? 'Для данной позиции не выявлено нормативных требований к разрешительным документам.'
      : null,
    tr_ts: nonTariff.tr_ts,
    notes: nonTariff.notes,
  };
}

export function countNormativeGroups(block: NormativeRequirementsBlockData | null | undefined): {
  required: number;
  missing: number;
  advisory: number;
} {
  return {
    required: block?.required_documents?.length ?? 0,
    missing: block?.missing_documents?.length ?? 0,
    advisory: block?.advisory_requirements?.filter((item) => !item.transaction_level).length ?? 0,
  };
}
