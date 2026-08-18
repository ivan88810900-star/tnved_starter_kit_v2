import React, { useState } from 'react';
import { api } from '../api/client';
import { getUserFacingApiError } from '../api/error';
import { CC_NORMATIVE_PREFILL_KEY } from '../constants/homeNav';
import { NonTariffBlock } from '../components/nonTariff/NonTariffBlock';
import { SanctionsRiskBlock } from '../components/nonTariff/SanctionsRiskBlock';
import { sanitizeNonTariffLine } from '../utils/nonTariffUiFilter';
import type { AdvisoryRequirement, NormativeRequirementsBlockData, SanctionsRiskBlockData } from '../types/api.types';

/**
 * Сырые служебные «Мера (тип): <сырой текст TKS>» дублируют структурированный
 * NonTariffBlock и нарушают принцип #107 (никакого сырого TKS в UI). Скрываем их;
 * остальные заметки (запреты, оговорки) показываем после очистки fallback-шума.
 */
const RAW_MEASURE_DUMP_RE = /^\s*Мера\s*\(/i;
const PROHIBITION_RE = /^\s*Запретительная мера\s*:/i;
const PROHIBITION_CLEAN =
  'Запретительная мера: возможен запрет или ограничение ввоза — проверьте нормативное основание.';

function visibleNotes(notes: string[] | undefined): string[] {
  if (!notes?.length) return [];
  const out: string[] = [];
  const seen = new Set<string>();
  for (const note of notes) {
    // Сырой дамп «Мера (тип): <текст TKS>» дублирует структурированный блок — скрываем.
    if (RAW_MEASURE_DUMP_RE.test(note)) continue;
    // Запретительные меры показываем нормализованной формулировкой (без сырого хвоста).
    if (PROHIBITION_RE.test(note)) {
      if (!seen.has(PROHIBITION_CLEAN)) {
        seen.add(PROHIBITION_CLEAN);
        out.push(PROHIBITION_CLEAN);
      }
      continue;
    }
    const clean = sanitizeNonTariffLine(note);
    if (!clean || seen.has(clean)) continue;
    seen.add(clean);
    out.push(clean);
  }
  return out;
}

function visibleRisks(risks: string[] | undefined): string[] {
  if (!risks?.length) return [];
  const out: string[] = [];
  const seen = new Set<string>();
  for (const risk of risks) {
    const clean = sanitizeNonTariffLine(risk);
    if (!clean || seen.has(clean)) continue;
    seen.add(clean);
    out.push(clean);
  }
  return out;
}

type Permit = { type: string; number: string };
type BooleanFactChoice = '' | 'yes' | 'no';
type MovementDirection = 'import' | 'export' | 'transit';
type TransitRoute = '' | 'border_to_border' | 'arrival_to_internal' | 'internal_to_exit';
type CryptoExemptionRule = '' | 'test_sim_cards' | 'personal_use_appendix_5';
type CryptoExemptionPayload = {
  rule_id: Exclude<CryptoExemptionRule, ''>;
  verified?: boolean;
  source_url?: string;
  quantity?: number;
  importer_role?: string;
  purpose?: string;
  personal_use?: boolean;
  natural_person?: boolean;
  category?: string;
};

function optionalBoolean(value: BooleanFactChoice): boolean | undefined {
  if (value === 'yes') return true;
  if (value === 'no') return false;
  return undefined;
}

function splitFactList(value: string): string[] {
  return value
    .split(/[;,\n]/)
    .map((item) => item.trim())
    .filter(Boolean);
}

type FrequencyFact = number | { min: number; max: number };

export function parseFrequencyFacts(value: string): FrequencyFact[] {
  const rows: FrequencyFact[] = [];
  for (const raw of value.split(/[;\n]/)) {
    const part = raw.trim();
    if (!part) continue;
    const range = part.match(/^([0-9]+(?:[.,][0-9]+)?)\s*[-–—]\s*([0-9]+(?:[.,][0-9]+)?)$/);
    if (range) {
      const min = Number(range[1].replace(',', '.'));
      const max = Number(range[2].replace(',', '.'));
      if (Number.isFinite(min) && Number.isFinite(max) && min >= 0 && min <= max) rows.push({ min, max });
      continue;
    }
    const point = Number(part.replace(',', '.'));
    if (Number.isFinite(point) && point >= 0) rows.push(point);
  }
  return rows;
}

export function normalizeIsoCountryCode(value: string): string {
  return value.trim().toUpperCase();
}

export function isIsoCountryCode(value: string): boolean {
  return /^[A-Z]{2,3}$/.test(normalizeIsoCountryCode(value));
}

export function validateCountryFacts(
  direction: MovementDirection,
  originCountry: string,
  destinationCountry: string,
): string | null {
  const origin = normalizeIsoCountryCode(originCountry);
  const destination = normalizeIsoCountryCode(destinationCountry);
  if (origin && !isIsoCountryCode(origin)) {
    return 'Страна происхождения: укажите код ISO Alpha-2 или Alpha-3, например CN или CHN.';
  }
  if (destination && !isIsoCountryCode(destination)) {
    return 'Страна назначения: укажите код ISO Alpha-2 или Alpha-3, например DE или DEU.';
  }
  if (direction === 'export' && !destination) {
    return 'Для вывоза обязательно укажите страну назначения кодом ISO Alpha-2 или Alpha-3.';
  }
  return null;
}

export function parsePositiveInteger(value: string): number | null {
  const normalized = value.trim();
  if (!/^\d+$/.test(normalized)) return null;
  const parsed = Number(normalized);
  return Number.isSafeInteger(parsed) && parsed > 0 ? parsed : null;
}

function BooleanFactField({
  label,
  value,
  onChange,
}: {
  label: string;
  value: BooleanFactChoice;
  onChange: (value: BooleanFactChoice) => void;
}) {
  return (
    <label className="space-y-1">
      <span className="cc-label">{label}</span>
      <select
        className="cc-input"
        value={value}
        onChange={(event) => onChange(event.target.value as BooleanFactChoice)}
      >
        <option value="">не указано</option>
        <option value="yes">да</option>
        <option value="no">нет</option>
      </select>
    </label>
  );
}

type DataFreshness = {
  source_name: string;
  source_code: string;
  synced_at: string | null;
  is_stale: boolean;
  revision: string;
};

type DataQuality = {
  confidence: 'high' | 'medium' | 'low' | 'none';
  matched_prefix: string;
  match_length: number;
  antidumping_status: string;
};

type ComplianceItem = {
  hs_code: string;
  description: string;
  country: string | null;
  documents?: { required: string[]; provided: string[]; missing: string[] };
  risks?: string[];
  payment: {
    status?: string;
    not_applicable_direction?: string;
    breakdown: {
      duty: number;
      vat: number;
      excise: number;
      antidumping: number;
      total_payable: number;
      vat_rate: number;
      duty_rate: number;
      vat_reason: string;
      excise_reason: string;
      antidumping_reason: string;
      antidumping_status: string;
    };
    auto_detected: {
      duty_rate: number;
      vat_rate: number;
      antidumping_type: string;
      antidumping_value: number;
      antidumping_condition?: string;
      antidumping_countries?: string;
    };
    data_quality: DataQuality;
    sources: { name: string; integrated?: boolean; data_info?: string; revision?: string }[];
  };
  non_tariff: {
    status: string;
    movement_direction?: string;
    legacy_import_broker_applied?: boolean;
    hs_code: string;
    description: string;
    country: string | null;
    tr_ts: string[];
    required_permit_types: string[];
    permits: PermitRegistryRow[];
    missing_permit_types: string[];
    normative_block?: NormativeRequirementsBlockData;
    risk_block?: SanctionsRiskBlockData;
    advisory_requirements?: AdvisoryRequirement[];
    notes: string[];
    rule_sources: {
      name: string;
      integrated?: boolean;
      data_info?: string;
      required_permits?: string[];
      revision?: string;
      hs_prefix?: string;
      priority?: number;
      tr_ts_edition?: string;
      exception_note?: string;
    }[];
    data_freshness: DataFreshness;
  };
  permits_verification?: {
    registry: string;
    documents: PermitRegistryRow[];
    summary: { checked: number; valid: number; not_found: number; hs_mismatch: number };
  };
};

type PermitRegistryRow = {
  type: string;
  status: string;
  number: string;
  registry_link?: string;
  registry_source?: string;
  verified_at?: string;
  holder?: string | null;
  valid_to?: string | null;
  hs_code_check?: { hs_match: string; detail?: string };
  error?: string;
};

type ComplianceResponse = {
  status: string;
  items: ComplianceItem[];
  meta?: {
    generated_at: string;
    data_confidence: string[];
    any_stale_source: boolean;
    any_manual_review: boolean;
  };
};

function formatDate(iso: string | null) {
  if (!iso) return 'неизвестно';
  try {
    return new Date(iso).toLocaleString('ru-RU', { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' });
  } catch {
    return iso;
  }
}

const CONFIDENCE_LABELS: Record<string, string> = {
  high: 'Высокая (10–8 зн.)',
  medium: 'Средняя (6 зн.)',
  low: 'Низкая (4 зн.)',
  none: 'Код не найден',
};

export const NonTariff: React.FC = () => {
  const [hsCode, setHsCode] = useState('');
  const [description, setDescription] = useState('');
  const [country, setCountry] = useState('');
  const [direction, setDirection] = useState<MovementDirection>('import');
  const [transitRoute, setTransitRoute] = useState<TransitRoute>('');
  const [destinationCountry, setDestinationCountry] = useState('');
  const [intendedUse, setIntendedUse] = useState('');
  const [endUser, setEndUser] = useState('');
  const [composition, setComposition] = useState('');
  const [casNumbers, setCasNumbers] = useState('');
  const [productNameVerified, setProductNameVerified] = useState<BooleanFactChoice>('');
  const [manufacturerDocumentsVerified, setManufacturerDocumentsVerified] = useState<BooleanFactChoice>('');
  const [firstImport, setFirstImport] = useState<BooleanFactChoice>('');
  const [foodContact, setFoodContact] = useState<BooleanFactChoice>('');
  const [drinkingWaterContact, setDrinkingWaterContact] = useState<BooleanFactChoice>('');
  const [disinfectantUse, setDisinfectantUse] = useState<BooleanFactChoice>('');
  const [veterinaryUse, setVeterinaryUse] = useState<BooleanFactChoice>('');
  const [processingMethod, setProcessingMethod] = useState('');
  const [packaging, setPackaging] = useState('');
  const [embeddedRadio, setEmbeddedRadio] = useState<BooleanFactChoice>('');
  const [radioTechnology, setRadioTechnology] = useState('');
  const [radioRegistryExemption, setRadioRegistryExemption] = useState<BooleanFactChoice>('');
  const [radioRegistryEvidenceUrl, setRadioRegistryEvidenceUrl] = useState('');
  const [frequencyMhz, setFrequencyMhz] = useState('');
  const [transmitterPowerMw, setTransmitterPowerMw] = useState('');
  const [cryptographyPresent, setCryptographyPresent] = useState<BooleanFactChoice>('');
  const [cryptoFunctions, setCryptoFunctions] = useState('');
  const [massMarket, setMassMarket] = useState<BooleanFactChoice>('');
  const [notificationNumber, setNotificationNumber] = useState('');
  const [notificationVerified, setNotificationVerified] = useState<BooleanFactChoice>('');
  const [notificationEvidenceUrl, setNotificationEvidenceUrl] = useState('');
  const [cryptoExemptionRule, setCryptoExemptionRule] = useState<CryptoExemptionRule>('');
  const [cryptoExemptionVerified, setCryptoExemptionVerified] = useState<BooleanFactChoice>('');
  const [cryptoExemptionSourceUrl, setCryptoExemptionSourceUrl] = useState('');
  const [cryptoExemptionQuantity, setCryptoExemptionQuantity] = useState('');
  const [cryptoExemptionImporterRole, setCryptoExemptionImporterRole] = useState('');
  const [cryptoExemptionPurpose, setCryptoExemptionPurpose] = useState('');
  const [cryptoPersonalUse, setCryptoPersonalUse] = useState<BooleanFactChoice>('');
  const [cryptoNaturalPerson, setCryptoNaturalPerson] = useState<BooleanFactChoice>('');
  const [cryptoPersonalUseCategory, setCryptoPersonalUseCategory] = useState('');
  const [animalOrigin, setAnimalOrigin] = useState<BooleanFactChoice>('');
  const [feedUse, setFeedUse] = useState<BooleanFactChoice>('');
  const [phytoRiskTier, setPhytoRiskTier] = useState<'' | 'high' | 'low' | 'not_listed'>('');
  const [isWaste, setIsWaste] = useState<BooleanFactChoice>('');
  const [hazardousWaste, setHazardousWaste] = useState<BooleanFactChoice>('');
  const [wasteClass, setWasteClass] = useState('');
  const [contamination, setContamination] = useState('');
  const [exportListItem, setExportListItem] = useState('');
  const [technicalParametersConfirmed, setTechnicalParametersConfirmed] = useState<BooleanFactChoice>('');
  const [sealedContainer, setSealedContainer] = useState<BooleanFactChoice>('');
  const [packageVolumeMl, setPackageVolumeMl] = useState('');
  const [packageMassG, setPackageMassG] = useState('');
  const [catchAllRisk, setCatchAllRisk] = useState<'' | 'none' | 'unknown' | 'indicators_present' | 'confirmed'>('');
  const [permits, setPermits] = useState<Permit[]>([{ type: 'ДС', number: '' }]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<ComplianceResponse | null>(null);
  const [saveComplianceHistory, setSaveComplianceHistory] = useState(false);
  const [complianceDocId, setComplianceDocId] = useState(() => localStorage.getItem('cc_last_ingested_id') || '');
  const [complianceUserRef, setComplianceUserRef] = useState(() => localStorage.getItem('cc_client_id') || '');

  React.useEffect(() => {
    try {
      const raw = sessionStorage.getItem(CC_NORMATIVE_PREFILL_KEY);
      if (!raw) return;
      sessionStorage.removeItem(CC_NORMATIVE_PREFILL_KEY);
      const parsed = JSON.parse(raw) as { hs_code?: string; description?: string };
      if (parsed.hs_code?.trim()) setHsCode(parsed.hs_code.trim());
      if (parsed.description?.trim()) setDescription(parsed.description.trim());
    } catch {
      /* ignore */
    }
  }, []);

  const addPermit = () => setPermits((p) => [...p, { type: 'ДС', number: '' }]);
  const removePermit = (i: number) => setPermits((p) => p.filter((_, j) => j !== i));
  const updatePermit = (i: number, field: 'type' | 'number', v: string) =>
    setPermits((p) => p.map((x, j) => (j === i ? { ...x, [field]: v } : x)));

  const handleCheck = async () => {
    if (!hsCode.trim()) return;
    const countryError = validateCountryFacts(direction, country, destinationCountry);
    if (countryError) {
      setResult(null);
      setError(countryError);
      return;
    }
    const hasSimQuantity = cryptoExemptionQuantity.trim().length > 0;
    const simQuantity = cryptoExemptionRule === 'test_sim_cards' && hasSimQuantity
      ? parsePositiveInteger(cryptoExemptionQuantity)
      : undefined;
    if (cryptoExemptionRule === 'test_sim_cards' && hasSimQuantity && simQuantity === null) {
      setResult(null);
      setError('Количество тестовых SIM-карт должно быть целым положительным числом.');
      return;
    }
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const originCountry = normalizeIsoCountryCode(country);
      const destination = normalizeIsoCountryCode(destinationCountry);
      const facts: Record<string, unknown> = { direction };
      if (direction === 'transit' && transitRoute) facts.transit_route = transitRoute;
      if (originCountry) facts.origin_country = originCountry;
      if (destination) facts.destination_country = destination;
      if (intendedUse.trim()) facts.intended_use = intendedUse.trim();
      if (endUser.trim()) facts.end_user = endUser.trim();
      const compositionRows = splitFactList(composition);
      if (compositionRows.length) facts.composition = compositionRows;
      const casRows = splitFactList(casNumbers);
      if (casRows.length) facts.cas_numbers = casRows;
      if (processingMethod.trim()) facts.processing_method = processingMethod.trim();
      if (packaging.trim()) facts.packaging = packaging.trim();
      const radioTechnologies = splitFactList(radioTechnology);
      if (radioTechnologies.length) facts.radio_technology = radioTechnologies;
      if (radioRegistryEvidenceUrl.trim()) facts.radio_registry_evidence_url = radioRegistryEvidenceUrl.trim();
      const cryptoFunctionRows = splitFactList(cryptoFunctions);
      if (cryptoFunctionRows.length) facts.crypto_functions = cryptoFunctionRows;
      if (wasteClass.trim()) facts.waste_class = wasteClass.trim();
      const contaminationRows = splitFactList(contamination);
      if (contaminationRows.length) facts.contamination = contaminationRows;
      const frequencyRows = parseFrequencyFacts(frequencyMhz);
      if (frequencyRows.length === 1) facts.frequency_mhz = frequencyRows[0];
      if (frequencyRows.length > 1) facts.frequency_mhz = frequencyRows;
      const power = Number(transmitterPowerMw.replace(',', '.'));
      if (transmitterPowerMw.trim() && Number.isFinite(power) && power >= 0) {
        facts.transmitter_power_mw = power;
      }
      const volumeMl = Number(packageVolumeMl.replace(',', '.'));
      if (packageVolumeMl.trim() && Number.isFinite(volumeMl) && volumeMl >= 0) {
        facts.package_volume_ml = volumeMl;
      }
      const massG = Number(packageMassG.replace(',', '.'));
      if (packageMassG.trim() && Number.isFinite(massG) && massG >= 0) {
        facts.package_mass_g = massG;
      }
      const booleanFacts: Array<[string, BooleanFactChoice]> = [
        ['product_name_matches_official_row', productNameVerified],
        ['manufacturer_documents_verified', manufacturerDocumentsVerified],
        ['first_import', firstImport],
        ['food_contact', foodContact],
        ['drinking_water_contact', drinkingWaterContact],
        ['disinfectant_use', disinfectantUse],
        ['veterinary_use', veterinaryUse],
        ['embedded_radio', embeddedRadio],
        ['radio_registry_exemption', radioRegistryExemption],
        ['cryptography_present', cryptographyPresent],
        ['mass_market', massMarket],
        ['notification_registry_verified', notificationVerified],
        ['animal_origin', animalOrigin],
        ['feed_use', feedUse],
        ['is_waste', isWaste],
        ['hazardous_waste', hazardousWaste],
        ['technical_parameters_confirmed', technicalParametersConfirmed],
        ['sealed_container', sealedContainer],
      ];
      for (const [key, value] of booleanFacts) {
        const parsed = optionalBoolean(value);
        if (parsed !== undefined) facts[key] = parsed;
      }
      if (notificationNumber.trim()) facts.notification_registry_number = notificationNumber.trim();
      if (notificationEvidenceUrl.trim()) facts.registry_evidence_url = notificationEvidenceUrl.trim();
      if (cryptoExemptionRule) {
        const exemption: CryptoExemptionPayload = { rule_id: cryptoExemptionRule };
        const verified = optionalBoolean(cryptoExemptionVerified);
        if (verified !== undefined) exemption.verified = verified;
        if (cryptoExemptionSourceUrl.trim()) exemption.source_url = cryptoExemptionSourceUrl.trim();
        if (cryptoExemptionRule === 'test_sim_cards') {
          if (simQuantity != null) exemption.quantity = simQuantity;
          if (cryptoExemptionImporterRole.trim()) exemption.importer_role = cryptoExemptionImporterRole.trim();
          if (cryptoExemptionPurpose.trim()) exemption.purpose = cryptoExemptionPurpose.trim();
        } else {
          const personalUse = optionalBoolean(cryptoPersonalUse);
          if (personalUse !== undefined) exemption.personal_use = personalUse;
          const naturalPerson = optionalBoolean(cryptoNaturalPerson);
          if (naturalPerson !== undefined) exemption.natural_person = naturalPerson;
          if (cryptoPersonalUseCategory) exemption.category = cryptoPersonalUseCategory;
        }
        facts.crypto_exemption = exemption;
      }
      if (phytoRiskTier) facts.phytosanitary_risk_tier = phytoRiskTier;
      if (exportListItem.trim()) facts.export_control_list_item = exportListItem.trim();
      if (catchAllRisk) facts.catch_all_risk = catchAllRisk;
      const ur = complianceUserRef.trim();
      if (ur) localStorage.setItem('cc_client_id', ur);
      const { data } = await api.post<ComplianceResponse>('/compliance/check', {
        items: [{
          hs_code: hsCode.trim(),
          description: description.trim(),
          country: originCountry || null,
          permits: permits.filter((p) => p.number.trim()),
          facts,
          customs_value: 0,
          freight: 0,
        }],
        save_history: saveComplianceHistory,
        document_id: complianceDocId.trim() || undefined,
        user_ref: ur || undefined,
      });
      setResult(data);
    } catch (e: unknown) {
      setError(getUserFacingApiError(e, 'Не удалось выполнить проверку. Попробуйте позже.'));
    } finally {
      setLoading(false);
    }
  };

  const meta = result?.meta;

  return (
    <div className="space-y-4">
      <p className="text-[12px] leading-relaxed text-slate-600">
        Проверка нетарифных мер и разрешений.
      </p>
      <details className="cc-disclosure">
        <summary>Журнал расчётов (комплаенс)</summary>
        <div className="cc-disclosure-body space-y-3 text-[12px]">
          <label className="flex cursor-pointer items-center gap-2 text-slate-700">
            <input
              type="checkbox"
              className="rounded border-slate-600"
              checked={saveComplianceHistory}
              onChange={(e) => setSaveComplianceHistory(e.target.checked)}
            />
            Сохранить результат проверки в историю расчётов (тип «комплаенс»)
          </label>
          <div className="grid gap-3 sm:grid-cols-2">
            <label className="block space-y-1">
              <span className="cc-label">document_id (опционально)</span>
              <input
                value={complianceDocId}
                onChange={(e) => setComplianceDocId(e.target.value)}
                placeholder="UUID после сохранения документа"
                className="cc-input cc-mono text-[11px]"
              />
            </label>
            <label className="block space-y-1">
              <span className="cc-label">user_ref</span>
              <input
                value={complianceUserRef}
                onChange={(e) => setComplianceUserRef(e.target.value)}
                placeholder="как Client ID в документах"
                className="cc-input"
              />
            </label>
          </div>
          <p className="text-[10px] text-slate-600">
            Список записей: раздел «Платежи» → журнал расчётов или{' '}
            <a href="/api/calculator/history?limit=20" className="text-indigo-600 hover:underline" target="_blank" rel="noreferrer">
              API
            </a>
            .
          </p>
        </div>
      </details>

      <details className="cc-disclosure">
        <summary>Нормативные источники</summary>
        <div className="cc-disclosure-body flex flex-wrap gap-2">
          <a href="https://eec.eaeunion.org/comission/department/catr/ett/" target="_blank" rel="noreferrer" className="cc-btn-ghost">
            ЕТТ ЕАЭС
          </a>
          <a href="https://eec.eaeunion.org/comission/department/nts/" target="_blank" rel="noreferrer" className="cc-btn-ghost">
            Нетарифные меры ЕЭК
          </a>
        </div>
      </details>

      <div className="grid gap-3 md:grid-cols-2 text-xs">
        <label className="space-y-1">
          <span className="cc-label">Код ТН ВЭД</span>
          <input
            value={hsCode}
            onChange={(e) => setHsCode(e.target.value)}
            placeholder="8509400000"
            className="cc-input"
          />
        </label>
        <label className="space-y-1">
          <span className="cc-label">Страна происхождения (ISO)</span>
          <input
            className="cc-input uppercase"
            value={country}
            onChange={(event) => setCountry(event.target.value.toUpperCase())}
            placeholder="CN или CHN"
            maxLength={3}
            pattern="[A-Za-z]{2,3}"
            autoCapitalize="characters"
            aria-invalid={Boolean(country.trim()) && !isIsoCountryCode(country)}
          />
          <span className="block text-[10px] text-slate-500">Любой код ISO Alpha-2 или Alpha-3; поле можно оставить пустым.</span>
        </label>
      </div>

      <label className="block space-y-1 text-xs">
        <span className="cc-label">Описание товара</span>
        <textarea
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          placeholder="Краткое описание"
          className="cc-input min-h-[72px]"
        />
      </label>

      <details className="cc-disclosure">
        <summary>Характеристики для точной применимости мер</summary>
        <div className="cc-disclosure-body space-y-3 text-[12px]">
          <p className="text-[11px] leading-relaxed text-slate-600">
            Неуказанный факт считается неизвестным. Код или ключевое слово сами по себе не превращают условие
            «из» в обязательное требование.
          </p>
          <div className="grid gap-3 md:grid-cols-2">
            <label className="space-y-1">
              <span className="cc-label">Направление перемещения</span>
              <select className="cc-input" value={direction} onChange={(event) => setDirection(event.target.value as MovementDirection)}>
                <option value="import">ввоз</option>
                <option value="export">вывоз</option>
                <option value="transit">транзит</option>
              </select>
            </label>
            {direction === 'transit' && (
              <label className="space-y-1">
                <span className="cc-label">Маршрут транзита</span>
                <select className="cc-input" value={transitRoute} onChange={(event) => setTransitRoute(event.target.value as TransitRoute)}>
                  <option value="">не указан</option>
                  <option value="border_to_border">от места прибытия до места убытия</option>
                  <option value="arrival_to_internal">от места прибытия во внутренний пункт</option>
                  <option value="internal_to_exit">из внутреннего пункта до места убытия</option>
                </select>
              </label>
            )}
            <label className="space-y-1">
              <span className="cc-label">
                Страна назначения (ISO){direction === 'export' ? ' — обязательно' : ''}
              </span>
              <input
                className="cc-input uppercase"
                value={destinationCountry}
                onChange={(event) => setDestinationCountry(event.target.value.toUpperCase())}
                placeholder="DE или DEU"
                maxLength={3}
                pattern="[A-Za-z]{2,3}"
                autoCapitalize="characters"
                required={direction === 'export'}
                aria-required={direction === 'export'}
                aria-invalid={
                  (direction === 'export' && !destinationCountry.trim())
                  || (Boolean(destinationCountry.trim()) && !isIsoCountryCode(destinationCountry))
                }
              />
              <span className="block text-[10px] text-slate-500">
                Любой код ISO Alpha-2 или Alpha-3; для вывоза поле обязательно.
              </span>
            </label>
            <label className="space-y-1">
              <span className="cc-label">Назначение / конечное применение</span>
              <input className="cc-input" value={intendedUse} onChange={(event) => setIntendedUse(event.target.value)} placeholder="например: питьевое водоснабжение" />
            </label>
            <label className="space-y-1">
              <span className="cc-label">Конечный пользователь</span>
              <input className="cc-input" value={endUser} onChange={(event) => setEndUser(event.target.value)} placeholder="наименование и роль" />
            </label>
            <label className="space-y-1 md:col-span-2">
              <span className="cc-label">Состав / вещества</span>
              <input className="cc-input" value={composition} onChange={(event) => setComposition(event.target.value)} placeholder="через запятую; при наличии укажите CAS" />
            </label>
            <label className="space-y-1 md:col-span-2">
              <span className="cc-label">Номера CAS</span>
              <input className="cc-input" value={casNumbers} onChange={(event) => setCasNumbers(event.target.value)} placeholder="например: 118-74-1" />
            </label>
            <BooleanFactField label="Наименование сверено с точной строкой перечня" value={productNameVerified} onChange={setProductNameVerified} />
            <BooleanFactField label="Документы изготовителя проверены" value={manufacturerDocumentsVerified} onChange={setManufacturerDocumentsVerified} />
            <BooleanFactField label="Первый ввоз продукции" value={firstImport} onChange={setFirstImport} />
            <BooleanFactField label="Контактирует с пищевой продукцией" value={foodContact} onChange={setFoodContact} />
            <BooleanFactField label="Для питьевого водоснабжения" value={drinkingWaterContact} onChange={setDrinkingWaterContact} />
            <BooleanFactField label="Дезинфицирующее назначение" value={disinfectantUse} onChange={setDisinfectantUse} />
            <BooleanFactField label="Ветеринарное назначение" value={veterinaryUse} onChange={setVeterinaryUse} />
            <label className="space-y-1">
              <span className="cc-label">Способ переработки</span>
              <input className="cc-input" value={processingMethod} onChange={(event) => setProcessingMethod(event.target.value)} placeholder="жареный, сушёный, замороженный…" />
            </label>
            <label className="space-y-1">
              <span className="cc-label">Упаковка / вид партии</span>
              <input className="cc-input" value={packaging} onChange={(event) => setPackaging(event.target.value)} />
            </label>
            <BooleanFactField label="Есть встроенный радиомодуль" value={embeddedRadio} onChange={setEmbeddedRadio} />
            <label className="space-y-1">
              <span className="cc-label">Радиотехнологии</span>
              <input className="cc-input" value={radioTechnology} onChange={(event) => setRadioTechnology(event.target.value)} placeholder="Wi-Fi; Bluetooth; DECT" />
            </label>
            <BooleanFactField label="По вашим данным, исключение найдено в реестре РЭС/ВЧУ" value={radioRegistryExemption} onChange={setRadioRegistryExemption} />
            <label className="space-y-1">
              <span className="cc-label">Ссылка на запись реестра РЭС/ВЧУ</span>
              <input className="cc-input" value={radioRegistryEvidenceUrl} onChange={(event) => setRadioRegistryEvidenceUrl(event.target.value)} placeholder="https://portal.eaeunion.org/…" />
            </label>
            <label className="space-y-1">
              <span className="cc-label">Частота или диапазон, МГц</span>
              <input className="cc-input" value={frequencyMhz} onChange={(event) => setFrequencyMhz(event.target.value)} placeholder="2400–2483,5; 5150–5350" />
            </label>
            <label className="space-y-1">
              <span className="cc-label">Мощность передатчика, мВт</span>
              <input className="cc-input" inputMode="decimal" value={transmitterPowerMw} onChange={(event) => setTransmitterPowerMw(event.target.value)} />
            </label>
            <BooleanFactField label="Есть криптографические функции" value={cryptographyPresent} onChange={setCryptographyPresent} />
            <label className="space-y-1">
              <span className="cc-label">Криптографические функции</span>
              <input className="cc-input" value={cryptoFunctions} onChange={(event) => setCryptoFunctions(event.target.value)} placeholder="AES; TLS; VPN" />
            </label>
            <BooleanFactField label="Массовый рынок" value={massMarket} onChange={setMassMarket} />
            <label className="space-y-1">
              <span className="cc-label">Номер нотификации ФСБ</span>
              <input className="cc-input" value={notificationNumber} onChange={(event) => setNotificationNumber(event.target.value)} />
            </label>
            <BooleanFactField label="Вы вручную сверили нотификацию в реестре" value={notificationVerified} onChange={setNotificationVerified} />
            <label className="space-y-1 md:col-span-2">
              <span className="cc-label">Ссылка на запись реестра нотификаций</span>
              <input className="cc-input" value={notificationEvidenceUrl} onChange={(event) => setNotificationEvidenceUrl(event.target.value)} placeholder="https://portal.eaeunion.org/…" />
            </label>
            <label className="space-y-1">
              <span className="cc-label">Точное исключение для криптографии</span>
              <select className="cc-input" value={cryptoExemptionRule} onChange={(event) => setCryptoExemptionRule(event.target.value as typeof cryptoExemptionRule)}>
                <option value="">не указано</option>
                <option value="test_sim_cards">тестовые SIM-карты (пункт 6)</option>
                <option value="personal_use_appendix_5">личное использование (приложение 5)</option>
              </select>
            </label>
            <BooleanFactField label="Вы вручную сверили точную строку исключения" value={cryptoExemptionVerified} onChange={setCryptoExemptionVerified} />
            {cryptoExemptionRule && (
              <label className="space-y-1 md:col-span-2">
                <span className="cc-label">Официальный источник исключения</span>
                <input className="cc-input" value={cryptoExemptionSourceUrl} onChange={(event) => setCryptoExemptionSourceUrl(event.target.value)} placeholder="https://eec.eaeunion.org/…" />
              </label>
            )}
            {cryptoExemptionRule === 'test_sim_cards' && (
              <>
                <label className="space-y-1">
                  <span className="cc-label">Количество тестовых SIM-карт</span>
                  <input
                    className="cc-input"
                    type="number"
                    inputMode="numeric"
                    min={1}
                    step={1}
                    value={cryptoExemptionQuantity}
                    onChange={(event) => setCryptoExemptionQuantity(event.target.value)}
                    aria-invalid={Boolean(cryptoExemptionQuantity.trim()) && parsePositiveInteger(cryptoExemptionQuantity) === null}
                  />
                </label>
                <label className="space-y-1">
                  <span className="cc-label">Роль импортёра</span>
                  <input className="cc-input" value={cryptoExemptionImporterRole} onChange={(event) => setCryptoExemptionImporterRole(event.target.value)} placeholder="cellular operator" />
                </label>
                <label className="space-y-1 md:col-span-2">
                  <span className="cc-label">Назначение ввоза SIM-карт</span>
                  <input className="cc-input" value={cryptoExemptionPurpose} onChange={(event) => setCryptoExemptionPurpose(event.target.value)} placeholder="international exchange" />
                </label>
              </>
            )}
            {cryptoExemptionRule === 'personal_use_appendix_5' && (
              <>
                <BooleanFactField label="Ввоз для личного использования" value={cryptoPersonalUse} onChange={setCryptoPersonalUse} />
                <BooleanFactField label="Получатель — физическое лицо" value={cryptoNaturalPerson} onChange={setCryptoNaturalPerson} />
                <label className="space-y-1">
                  <span className="cc-label">Категория приложения 5</span>
                  <select className="cc-input" value={cryptoPersonalUseCategory} onChange={(event) => setCryptoPersonalUseCategory(event.target.value)}>
                    <option value="">не указана</option>
                    <option value="mass_market_software">ПО массового рынка</option>
                    <option value="electronic_signature">электронная подпись</option>
                    <option value="computer">компьютер</option>
                    <option value="smartphone">смартфон</option>
                    <option value="smart_watch">умные часы</option>
                    <option value="bank_or_sim_card">банковская/SIM-карта</option>
                  </select>
                </label>
              </>
            )}
            <BooleanFactField label="Товар животного происхождения" value={animalOrigin} onChange={setAnimalOrigin} />
            <BooleanFactField label="Предназначен для кормления животных" value={feedUse} onChange={setFeedUse} />
            <label className="space-y-1">
              <span className="cc-label">Фитосанитарный риск по перечню</span>
              <select className="cc-input" value={phytoRiskTier} onChange={(event) => setPhytoRiskTier(event.target.value as typeof phytoRiskTier)}>
                <option value="">не указан</option>
                <option value="high">высокий</option>
                <option value="low">низкий</option>
                <option value="not_listed">не входит в перечень</option>
              </select>
            </label>
            <BooleanFactField label="Является отходом" value={isWaste} onChange={setIsWaste} />
            <BooleanFactField label="Опасный отход подтверждён" value={hazardousWaste} onChange={setHazardousWaste} />
            <label className="space-y-1">
              <span className="cc-label">Класс / код отхода</span>
              <input className="cc-input" value={wasteClass} onChange={(event) => setWasteClass(event.target.value)} />
            </label>
            <label className="space-y-1">
              <span className="cc-label">Загрязнение / опасные компоненты</span>
              <input className="cc-input" value={contamination} onChange={(event) => setContamination(event.target.value)} />
            </label>
            <label className="space-y-1">
              <span className="cc-label">Позиция контрольного списка ФСТЭК</span>
              <input className="cc-input" value={exportListItem} onChange={(event) => setExportListItem(event.target.value)} />
            </label>
            <BooleanFactField label="Технические параметры подтверждены" value={technicalParametersConfirmed} onChange={setTechnicalParametersConfirmed} />
            <BooleanFactField label="Герметичная тара подтверждена" value={sealedContainer} onChange={setSealedContainer} />
            <label className="space-y-1">
              <span className="cc-label">Объём единицы, мл</span>
              <input className="cc-input" inputMode="decimal" value={packageVolumeMl} onChange={(event) => setPackageVolumeMl(event.target.value)} />
            </label>
            <label className="space-y-1">
              <span className="cc-label">Масса единицы, г</span>
              <input className="cc-input" inputMode="decimal" value={packageMassG} onChange={(event) => setPackageMassG(event.target.value)} />
            </label>
            <label className="space-y-1">
              <span className="cc-label">Всеобъемлющий экспортный контроль</span>
              <select className="cc-input" value={catchAllRisk} onChange={(event) => setCatchAllRisk(event.target.value as typeof catchAllRisk)}>
                <option value="">не проверен</option>
                <option value="none">индикаторов нет</option>
                <option value="unknown">недостаточно данных</option>
                <option value="indicators_present">есть индикаторы</option>
                <option value="confirmed">риск подтверждён</option>
              </select>
            </label>
          </div>
        </div>
      </details>

      <details className="cc-disclosure">
        <summary>Сверка с реестрами</summary>
        <div className="cc-disclosure-body text-[12px] leading-relaxed text-slate-500">
          При указании номера выполняется запрос к реестрам; при ответе возможна сверка кодов ТН ВЭД с декларацией.
        </div>
      </details>

      <div className="cc-card-soft space-y-2 p-3">
        <div className="flex items-center justify-between">
          <span className="cc-label mb-0">Разрешительные документы</span>
          <button type="button" onClick={addPermit} className="cc-btn-ghost">+ Добавить</button>
        </div>
        {permits.map((p, i) => (
          <div key={i} className="flex gap-2 items-center">
            <select
              value={p.type}
              onChange={(e) => updatePermit(i, 'type', e.target.value)}
              className="cc-input w-24 text-xs"
            >
              <option value="СС">СС</option>
              <option value="ДС">ДС</option>
              <option value="СГР">СГР</option>
              <option value="РУ">РУ</option>
            </select>
            <input
              value={p.number}
              onChange={(e) => updatePermit(i, 'number', e.target.value)}
              placeholder="Номер документа"
              className="cc-input flex-1 text-xs"
            />
            <button type="button" onClick={() => removePermit(i)} className="cc-btn-ghost text-red-600">×</button>
          </div>
        ))}
      </div>

      <button type="button" disabled={!hsCode.trim() || loading} onClick={handleCheck} className="cc-btn-primary">
        {loading ? 'Проверка…' : 'Выполнить проверку'}
      </button>

      {loading && (
        <div className="space-y-2">
          <div className="cc-skeleton h-5 w-44" />
          <div className="cc-skeleton h-16 w-full" />
          <div className="cc-skeleton h-24 w-full" />
        </div>
      )}

      {error && (
        <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
          {error}
        </div>
      )}

      {result && (
        <div className="space-y-3 text-xs">
          {/* Meta / stale warning */}
          {meta?.any_stale_source && (
            <div className="rounded-xl border border-amber-200 bg-amber-50 px-3 py-2.5 text-[12px] text-amber-800">
              Для части позиций используется архивная редакция нормативных данных.
            </div>
          )}
          {meta?.any_manual_review && (
            <div className="rounded-xl border border-orange-200 bg-orange-50 px-3 py-2.5 text-[12px] text-orange-800">
              По позициям возможна ручная проверка антидемпинговых мер (страна не задана или не сопоставлена).
            </div>
          )}

          {/* Overall status */}
          <div
            className={`rounded-lg border px-3 py-2 ${
              result.status === 'ERROR'
                ? 'border-red-200 bg-red-50 text-red-700'
                : result.status === 'WARNING'
                ? 'border-amber-200 bg-amber-50 text-amber-800'
                : 'border-emerald-200 bg-emerald-50 text-emerald-800'
            }`}
          >
            Статус: <strong>{result.status}</strong>
            {meta?.generated_at && (
              <span className="ml-3 text-[10px] opacity-70">
                сформировано {formatDate(meta.generated_at)}
              </span>
            )}
          </div>

          {result.items?.map((item, idx) => {
            const dq = item.payment.data_quality;
            const paymentNotApplicable = item.payment.status === 'NOT_APPLICABLE';
            const freshness = item.non_tariff.data_freshness;
            const cleanRisks = visibleRisks(item.risks);
            const cleanNotes = visibleNotes(item.non_tariff.notes);
            return (
              <div key={idx} className="cc-card-soft p-3 space-y-2">
                {/* Header row */}
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-mono text-indigo-700">{item.hs_code}</span>
                  {item.non_tariff.tr_ts?.length > 0 && (
                    <span className="flex flex-wrap gap-1">
                      {item.non_tariff.tr_ts.map((t) => (
                        <span key={t} className="rounded-full bg-purple-100 px-2 py-0.5 text-[10px] text-purple-800">
                          ТР ТС {t}
                        </span>
                      ))}
                    </span>
                  )}
                  {/* Confidence badge */}
                  {dq && !paymentNotApplicable && (
                    <span className={`rounded-full border px-2 py-0.5 text-[10px] ${
                      dq.confidence === 'high' ? 'border-emerald-200 bg-emerald-100 text-emerald-800'
                      : dq.confidence === 'medium' ? 'border-amber-200 bg-amber-100 text-amber-800'
                      : dq.confidence === 'low' ? 'border-orange-200 bg-orange-100 text-orange-800'
                      : 'border-red-200 bg-red-100 text-red-700'
                    }`}>
                      Уровень детализации: {CONFIDENCE_LABELS[dq.confidence] ?? dq.confidence}
                    </span>
                  )}
                </div>

                {/* Description */}
                <div className="text-slate-700">{item.description || item.non_tariff.description || '—'}</div>

                {/* Data freshness */}
                <div className={`rounded-lg px-2.5 py-1.5 text-[11px] ${freshness.is_stale ? 'border border-amber-200 bg-amber-50 text-amber-800' : 'border border-slate-200 bg-slate-50 text-slate-600'}`}>
                  {freshness.source_name}
                  {freshness.synced_at ? ` · ${formatDate(freshness.synced_at)}` : ''}
                </div>

                {/* Суммы платежей — в калькуляторе */}
                {paymentNotApplicable ? (
                  <div className="rounded-lg border border-slate-200 bg-slate-50 px-2.5 py-2 text-[11px] text-slate-700">
                    Платежи ввоза не рассчитывались: направление —{' '}
                    {item.payment.not_applicable_direction === 'export' ? 'вывоз' : 'транзит'}.
                  </div>
                ) : (
                  <div className="rounded-lg border border-indigo-100 bg-indigo-50 px-2.5 py-2 text-[11px] text-indigo-800">
                    Суммы пошлины, НДС и акциза рассчитываются в{' '}
                    <a href={`/calculator?code=${encodeURIComponent(item.hs_code.replace(/\D/g, '').slice(0, 10))}`} className="font-medium underline-offset-2 hover:underline">
                      калькуляторе платежей
                    </a>
                    .
                  </div>
                )}

                {/* Universal non-tariff requirements block */}
                <NonTariffBlock nonTariff={item.non_tariff} />

                {/* Sanctions / risk block */}
                <SanctionsRiskBlock block={item.non_tariff.risk_block} />

                {/* Проверка реестра */}
                {item.permits_verification && item.permits_verification.summary.checked > 0 && (
                  <div className="rounded-lg border border-cyan-200 bg-cyan-50 px-2 py-2 text-[11px] text-cyan-800">
                    <div className="font-medium text-cyan-800 mb-1">Реестр разрешительных документов</div>
                    <div className="text-cyan-700 text-[10px] mb-1">{item.permits_verification.registry}</div>
                    <div className="flex flex-wrap gap-2 text-[10px]">
                      <span>найдено (VALID): {item.permits_verification.summary.valid}</span>
                      <span>не найдено: {item.permits_verification.summary.not_found}</span>
                      {item.permits_verification.summary.hs_mismatch > 0 && (
                        <span className="text-orange-700">расхождение ТН ВЭД: {item.permits_verification.summary.hs_mismatch}</span>
                      )}
                    </div>
                  </div>
                )}

                {/* Permits + детали ФСА */}
                {item.non_tariff.permits?.map((p, i) => (
                  <div key={i} className="rounded border border-slate-200 bg-white px-2 py-1.5 space-y-0.5">
                    <div className="flex flex-wrap items-center gap-2 text-slate-700">
                      <span className="font-medium">{p.type}</span>
                      <span className="font-mono text-xs">{p.number}</span>
                      <span className={`text-[10px] rounded px-1.5 py-0.5 ${
                        p.status === 'VALID' ? 'bg-emerald-100 text-emerald-800'
                          : p.status === 'NOT_FOUND' ? 'bg-red-100 text-red-700'
                          : 'bg-slate-100 text-slate-700'
                      }`}>{p.status}</span>
                      {p.registry_link && (
                        <span className="text-[10px] text-slate-500">{p.registry_source || 'реестр'}</span>
                      )}
                    </div>
                    {p.holder && <div className="text-[10px] text-slate-600">Заявитель: {p.holder}</div>}
                    {p.valid_to && <div className="text-[10px] text-slate-600">Действует до: {p.valid_to}</div>}
                    {p.hs_code_check && p.hs_code_check.hs_match !== 'unknown' && (
                      <div className={`text-[10px] ${
                        p.hs_code_check.hs_match === 'ok' ? 'text-emerald-700'
                          : p.hs_code_check.hs_match === 'mismatch' ? 'text-orange-700'
                          : 'text-amber-700'
                      }`}>
                        ТН ВЭД: {p.hs_code_check.detail}
                      </div>
                    )}
                    {p.registry_link && (
                      <a href={p.registry_link} target="_blank" rel="noreferrer" className="inline-block text-[10px] text-indigo-600 hover:underline">
                        Открыть в реестре
                      </a>
                    )}
                  </div>
                ))}

                {/* Risks */}
                {cleanRisks.length > 0 && (
                  <div className="rounded-lg border border-orange-200 bg-orange-50 px-2 py-1.5 space-y-1">
                    <span className="text-orange-800 font-medium text-[10px]">Риски:</span>
                    {cleanRisks.map((r, i) => (
                      <div key={i} className="text-orange-700 text-[10px]">{r}</div>
                    ))}
                  </div>
                )}

                {/* Notes (очищенные, без сырых дампов мер) */}
                {cleanNotes.map((n, i) => (
                  <div key={i} className="text-amber-700">{n}</div>
                ))}

              </div>
            );
          })}
        </div>
      )}
    </div>
  );
};
