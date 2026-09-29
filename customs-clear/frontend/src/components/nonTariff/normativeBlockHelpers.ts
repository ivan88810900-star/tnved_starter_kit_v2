import type { AdvisoryRequirement } from './AdvisoryRequirementsBlock';

export type NormativeDocument = {
  permit_type: string;
  tr_ts?: string | null;
  tr_ts_full_name?: string | null;
  source?: string;
  source_label?: string | null;
  applicability?: string;
  reason?: string | null;
  note?: string | null;
  used_for_missing_check?: boolean;
  rule_name?: string | null;
};

export type NormativeDataFreshness = {
  state: 'fresh' | 'stale' | 'unknown';
  tone: 'neutral' | 'amber';
  source_name: string | null;
  source_code: string | null;
  synced_at: string | null;
  revision: string | null;
  is_stale: boolean;
  scope: 'technical_source_status_only';
  affects_applicability: false;
  affects_required_documents: false;
  affects_missing_documents: false;
  ntm_coverage_verified: false;
};

export type NormativeRequirementsBlockData = {
  status?: string;
  hs_code?: string;
  description?: string;
  required_documents: NormativeDocument[];
  missing_documents: NormativeDocument[];
  advisory_requirements: AdvisoryRequirement[];
  measure_families?: Array<{
    family: string;
    label: string;
    status: 'definite' | 'needs_clarification' | 'legacy_signal' | 'not_detected' | string;
    requirements_count: number;
    signals_count?: number;
  }>;
  data_freshness?: NormativeDataFreshness;
  sources_summary?: string[];
  empty_message?: string | null;
  tr_ts?: string[];
  notes?: string[];
};

function optionalText(value: unknown): string | null {
  return typeof value === 'string' && value.trim() ? value.trim() : null;
}

function validatedSyncTimestamp(value: unknown): string | null {
  const candidate = optionalText(value);
  if (!candidate || candidate.length > 120 || !candidate.includes('T')) return null;
  const parsed = Date.parse(candidate);
  return Number.isFinite(parsed) && parsed <= Date.now() ? candidate : null;
}

export function normalizeNormativeDataFreshness(value: unknown): NormativeDataFreshness {
  const raw = value && typeof value === 'object'
    ? value as Record<string, unknown>
    : {};
  const sourceName = optionalText(raw.source_name);
  const sourceCode = optionalText(raw.source_code);
  const syncedAt = validatedSyncTimestamp(raw.synced_at);
  const revision = optionalText(raw.revision);
  const completeSourceStatus = Boolean(sourceName && sourceCode && syncedAt && revision);
  const hasExplicitState = Object.prototype.hasOwnProperty.call(raw, 'state');

  let state: NormativeDataFreshness['state'] = 'unknown';
  if (raw.state === 'stale' || (!hasExplicitState && raw.is_stale === true)) {
    state = 'stale';
  } else if (
    ((raw.state === 'fresh' && raw.is_stale === false)
      || (!hasExplicitState && raw.is_stale === false))
    && completeSourceStatus
  ) {
    state = 'fresh';
  }

  return {
    state,
    tone: state === 'fresh' ? 'neutral' : 'amber',
    source_name: sourceName,
    source_code: sourceCode,
    synced_at: syncedAt,
    revision,
    is_stale: state !== 'fresh',
    scope: 'technical_source_status_only',
    affects_applicability: false,
    affects_required_documents: false,
    affects_missing_documents: false,
    ntm_coverage_verified: false,
  };
}

export function hasNormativeContent(block: NormativeRequirementsBlockData | null | undefined): boolean {
  if (!block) return false;
  return (
    (block.required_documents?.length ?? 0) > 0 ||
    (block.missing_documents?.length ?? 0) > 0 ||
    (block.advisory_requirements?.length ?? 0) > 0
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
  data_freshness?: unknown;
  required_permits?: Array<{ permit_type?: string; tr_ts?: string | null; tr_ts_full_name?: string | null; description?: string; legal_ref?: string; trigger?: string; source?: string; applicability?: string }>;
} | null | undefined): NormativeRequirementsBlockData | null {
  if (!nonTariff) return null;
  if (nonTariff.normative_block) {
    return {
      required_documents: nonTariff.normative_block.required_documents ?? [],
      missing_documents: nonTariff.normative_block.missing_documents ?? [],
      advisory_requirements: nonTariff.normative_block.advisory_requirements ?? [],
      data_freshness: normalizeNormativeDataFreshness(
        nonTariff.normative_block.data_freshness ?? nonTariff.data_freshness,
      ),
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
    data_freshness: normalizeNormativeDataFreshness(nonTariff.data_freshness),
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
    advisory: block?.advisory_requirements?.length ?? 0,
  };
}
