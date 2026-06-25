import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { api } from '../api/client';
import { getAdminToken, setAdminToken as setAdminTokenMemory } from '../api/adminToken';
import { getUserFacingApiError } from '../api/error';
import { useAssistantSurfaceVisible } from '../context/ClientCapabilitiesContext';
import type {
  AssistantCalculationCurrentContext,
  CalculatorCommodityMetaInfo,
  CalculatorCompareRequest,
  CalculatorCompareResponse,
  CalculatorClarificationResponse,
  CalculatorComputeRequest,
  CalculatorComputeResponse,
  CalculatorDutyRuleInfo,
  CalculatorDutyRuleResponse,
  CalculatorHistoryExportJsonResponse,
  CalculatorHistoryListItem,
  CalculatorHistoryListResponse,
  CalculatorHistorySummaryResponse,
  CalculatorTariffPreference,
  FinanceRatesResponse,
  SearchHsItem,
  SearchHsResponse,
  SourceImportResponse,
  SourcesStatusResponse,
} from '../types/api.types';
import {
  fetchCommodityByCode,
  fetchHierarchyTree,
  formatCustomsCode,
  formatImportDutyPercent,
  type TnvedHierarchyNode,
} from '../api/tnvedCatalog';
import {
  getAssistantCalculationContext,
  requestAssistantCalculatorConsult,
  setAssistantCalculationContext,
} from '../store/calculatorAssistantBridge';
import {
  subscribeCalculatorPrefill,
  type CalculatorPrefillPayload,
} from '../store/calculatorPrefillBridge';
import { CalculatorInvoiceAnalyzeSection } from '../components/calculator/CalculatorInvoiceAnalyzeSection';
import { CalculatorScenarioCompareSection } from '../components/calculator/CalculatorScenarioCompareSection';
import { formatTnvedCommodityName, TNVED_COMMODITY_NAME_CLASS } from '../utils/tnvedDisplayText';
import { TradeRemediesDisclaimer } from '../components/payments/TradeRemediesDisclaimer';
import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip as RechartsTooltip } from 'recharts';

function normHsCode(raw: string): string {
  return raw.replace(/\D/g, '').slice(0, 10);
}

function buildAssistantCalcContext(
  data: CalculatorComputeResponse,
  measures?: Array<{
    measure_type: string;
    regulatory_act: string;
    document_required: string;
    description: string;
  }>,
): AssistantCalculationCurrentContext {
  const b = data.breakdown;
  const tv = data.tnved_context;
  const product_name =
    [tv?.title && formatTnvedCommodityName(tv.title), tv?.description && formatTnvedCommodityName(tv.description)]
      .filter(Boolean)
      .join(' — ') || undefined;
  return {
    hs_code: data.hs_code,
    product_name,
    origin_country: data.country,
    total_payable: b.total_payable,
    duty_rate_pct: typeof b.duty_rate === 'number' ? b.duty_rate : undefined,
    vat_rate_pct: typeof b.vat_rate === 'number' ? b.vat_rate : undefined,
    duty_rub: b.duty,
    vat_rub: b.vat,
    excise_rub: b.excise,
    customs_fee_rub: b.customs_fee,
    customs_value_rub: data.customs_value,
    antidumping_rub: b.antidumping,
    special_duties_rub: b.special_duties_amount,
    vat_base_rub: b.vat_base,
    non_tariff_measures: (measures || []).map((m) => ({
      measure_type: m.measure_type,
      regulatory_act: m.regulatory_act,
      document_required: m.document_required,
      description: m.description,
    })),
  };
}

function formatDate(iso: string | null) {
  if (!iso) return 'неизвестно';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString('ru-RU', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

const HISTORY_KIND_ORDER = ['compute', 'compare', 'compliance', 'copilot', 'copilot_batch'] as const;
const HISTORY_KIND_LABELS: Record<string, string> = {
  compute: 'Расчёт',
  compare: 'Сравнение',
  compliance: 'Комплаенс',
  copilot: 'Copilot',
  copilot_batch: 'Пакет',
};

const PAYMENT_COLORS = ['#1d4ed8', '#0ea5e9', '#cbd5e1', '#94a3b8', '#f59e0b'];
const COUNTRY_OPTIONS = ['CN', 'MY', 'VN', 'TR', 'IN', 'RU', 'KZ', 'BY', 'DE', 'IT', 'US', 'KR', 'JP'];

const VEHICLE_PREFIXES = ['8701', '8702', '8703', '8704', '8705', '8711'];

function isVehicleHs(hs: string): boolean {
  const d = (hs || '').replace(/\D/g, '');
  return VEHICLE_PREFIXES.some((p) => d.startsWith(p));
}

function preferenceLabel(pref?: CalculatorTariffPreference | null): string | null {
  if (!pref || !pref.applied) return null;
  const map: Record<string, string> = {
    eaeu: 'ЕАЭС',
    cis: 'СНГ',
    gsp: 'ВРС (преференция)',
    gsp_graduated: 'ВРС (исключён)',
    mfn_graduated: 'РНБ',
    ldc: 'Наименее развитые страны',
    mfn: 'РНБ',
    non_mfn: 'без РНБ',
  };
  const name = map[pref.preference_type || ''] || pref.preference_type || 'преференция';
  const coeff = pref.duty_coefficient;
  if (coeff === 0) return `${name}: пошлина 0%`;
  if (typeof coeff === 'number' && coeff !== 1) return `${name}: пошлина ×${coeff}`;
  return name;
}

function TreeNode({
  node,
  depth,
  expanded,
  onToggle,
  onSelectLeaf,
}: {
  node: TnvedHierarchyNode;
  depth: number;
  expanded: Set<string>;
  onToggle: (code: string) => void;
  onSelectLeaf: (node: TnvedHierarchyNode) => void;
}) {
  const hasChildren = node.children.length > 0;
  const isOpen = expanded.has(node.code);
  const d = node.code.replace(/\D/g, '');
  const isLeaf10 = d.length === 10;
  const codeShown = isLeaf10 ? formatCustomsCode(node.code) : node.code.trim();
  const nmRaw = (node.name || node.title_ru || '').trim();
  const nm = nmRaw ? formatTnvedCommodityName(nmRaw) : '';
  const padLeft = 8 + depth * 14;

  return (
    <div className="select-none">
      <div
        className="flex min-h-[1.6rem] items-start gap-0.5 border-l border-slate-200 text-sm leading-snug"
        style={{ paddingLeft: `${padLeft}px` }}
      >
        {hasChildren ? (
          <button
            type="button"
            className="mt-0.5 inline-flex h-5 w-5 shrink-0 items-center justify-center rounded text-slate-500 hover:bg-slate-100 hover:text-slate-700"
            aria-expanded={isOpen}
            onClick={() => onToggle(node.code)}
            title={isOpen ? 'Свернуть' : 'Развернуть'}
          >
            <span className="text-[10px]">{isOpen ? '▼' : '▶'}</span>
          </button>
        ) : (
          <span className="inline-block w-5 shrink-0" aria-hidden />
        )}
        {isLeaf10 ? (
          <button
            type="button"
            className="min-w-0 flex-1 text-left text-indigo-700 hover:underline"
            onClick={() => onSelectLeaf(node)}
          >
            <span className="cc-mono text-[12px] font-semibold">{codeShown}</span>
            {nm ? (
              <span className={`ml-1.5 text-[11px] text-slate-600 ${TNVED_COMMODITY_NAME_CLASS}`} title={nmRaw}>
                {nm.length > 72 ? `${nm.slice(0, 72)}…` : nm}
              </span>
            ) : null}
          </button>
        ) : (
          <span className="min-w-0 flex-1 text-left text-slate-700">
            <span className="cc-mono text-[12px] font-semibold">{codeShown}</span>
            {nm ? (
              <span className={`ml-1.5 text-[11px] text-slate-600 ${TNVED_COMMODITY_NAME_CLASS}`} title={nmRaw}>
                {nm.length > 72 ? `${nm.slice(0, 72)}…` : nm}
              </span>
            ) : null}
          </span>
        )}
      </div>
      {hasChildren && isOpen && (
        <div>
          {node.children.map((ch) => (
            <TreeNode
              key={`${node.code}-${ch.code}`}
              node={ch}
              depth={depth + 1}
              expanded={expanded}
              onToggle={onToggle}
              onSelectLeaf={onSelectLeaf}
            />
          ))}
        </div>
      )}
    </div>
  );
}

export const Calculator: React.FC = () => {
  const assistantVisible = useAssistantSurfaceVisible();
  const [hsCode, setHsCode] = useState('');
  const [customsValue, setCustomsValue] = useState('0');
  const [invoiceCurrency, setInvoiceCurrency] = useState('RUB');
  const [ratesMap, setRatesMap] = useState<Record<string, number>>({ RUB: 1 });
  const [ratesUpdatedAt, setRatesUpdatedAt] = useState<string | null>(null);
  const [ratesRefreshing, setRatesRefreshing] = useState(false);
  const [freight, setFreight] = useState('0');
  const [insurance, setInsurance] = useState('');
  const [dutyRate, setDutyRate] = useState('');
  const [country, setCountry] = useState('');
  const [applyReducedVat, setApplyReducedVat] = useState(false);
  const [vehicleIsNew, setVehicleIsNew] = useState(true);
  const [engineVolume, setEngineVolume] = useState('');
  const [excise, setExcise] = useState('');
  const [quantity, setQuantity] = useState('');
  const [netWeightKg, setNetWeightKg] = useState('');
  const [extraQuantity, setExtraQuantity] = useState('');
  const [dutyRuleInfo, setDutyRuleInfo] = useState<CalculatorDutyRuleInfo | null>(null);
  const [commodityMeta, setCommodityMeta] = useState<CalculatorCommodityMetaInfo | null>(null);
  const [suppQuantity, setSuppQuantity] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<CalculatorComputeResponse | null>(null);
  const [clarification, setClarification] = useState<CalculatorClarificationResponse | null>(null);
  const [importing, setImporting] = useState(false);
  const [importMsg, setImportMsg] = useState<string | null>(null);
  const [dataFreshness, setDataFreshness] = useState<{
    synced_at: string | null;
    source: string;
    is_stale: boolean;
  } | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState<SearchHsItem[]>([]);
  const [searching, setSearching] = useState(false);
  const [cmpHsA, setCmpHsA] = useState('8509400000');
  const [cmpHsB, setCmpHsB] = useState('8516108008');
  const [cmpLoading, setCmpLoading] = useState(false);
  const [cmpErr, setCmpErr] = useState<string | null>(null);
  const [cmpResult, setCmpResult] = useState<CalculatorCompareResponse | null>(null);

  const [saveHistory, setSaveHistory] = useState(true);
  const [documentId, setDocumentId] = useState(() => localStorage.getItem('cc_last_ingested_id') || '');
  const [userRef, setUserRef] = useState(() => localStorage.getItem('cc_client_id') || '');
  const [histLoading, setHistLoading] = useState(false);
  const [histKind, setHistKind] = useState<string>('');
  const [histSummary, setHistSummary] = useState<CalculatorHistorySummaryResponse | null>(null);
  const [histItems, setHistItems] = useState<CalculatorHistoryListItem[]>([]);
  const [histFrom, setHistFrom] = useState('');
  const [histTo, setHistTo] = useState('');
  const [adminToken, setAdminToken] = useState(() => getAdminToken());
  const [exportErr, setExportErr] = useState<string | null>(null);

  const [treeFilter, setTreeFilter] = useState('');
  const [treeData, setTreeData] = useState<TnvedHierarchyNode[]>([]);
  const [treeLoading, setTreeLoading] = useState(false);
  const [treeErr, setTreeErr] = useState<string | null>(null);
  const [treeExpanded, setTreeExpanded] = useState<Set<string>>(() => new Set());
  const [treeSelected, setTreeSelected] = useState<TnvedHierarchyNode | null>(null);

  const invoiceAmount = useMemo(() => parseFloat(customsValue || '0') || 0, [customsValue]);
  const invoiceFxRate = useMemo(() => {
    const code = invoiceCurrency.toUpperCase();
    return Number(ratesMap[code] ?? (code === 'RUB' ? 1 : 0));
  }, [invoiceCurrency, ratesMap]);
  const customsValueRub = useMemo(() => invoiceAmount * (invoiceFxRate || 0), [invoiceAmount, invoiceFxRate]);
  const hasSuppUnit = useMemo(() => ((commodityMeta?.supp_unit || '').trim().length > 0), [commodityMeta?.supp_unit]);
  const hasWeightCoeff = useMemo(() => Number(commodityMeta?.weight_coeff || 0) > 0, [commodityMeta?.weight_coeff]);
  const formatAutoNumber = (value: number): string =>
    Number.isFinite(value) ? value.toFixed(4).replace(/\.?0+$/, '') : '';
  const expectedWeightKg = useMemo(() => {
    const coeff = Number(commodityMeta?.weight_coeff || 0);
    const qty = Number(suppQuantity || 0);
    if (coeff <= 0 || qty <= 0) return 0;
    return coeff * qty;
  }, [commodityMeta?.weight_coeff, suppQuantity]);
  const weightWarn = useMemo(() => {
    const entered = Number(netWeightKg || 0);
    if (expectedWeightKg <= 0 || entered <= 0) return false;
    const delta = Math.abs(entered - expectedWeightKg) / expectedWeightKg;
    return delta > 0.3;
  }, [expectedWeightKg, netWeightKg]);
  const isVehicle = useMemo(() => isVehicleHs(hsCode), [hsCode]);

  const loadTnvedTree = async () => {
    setTreeLoading(true);
    setTreeErr(null);
    try {
      const t = await fetchHierarchyTree(treeFilter.trim());
      setTreeData(t);
      const rootsOpen = new Set<string>();
      for (const n of t) {
        if (n.children.length) rootsOpen.add(n.code);
      }
      setTreeExpanded(rootsOpen);
    } catch (e) {
      const msg = getUserFacingApiError(e, 'Не удалось загрузить справочник.');
      setTreeErr(msg);
      setTreeData([]);
    } finally {
      setTreeLoading(false);
    }
  };

  const toggleTreeNode = (code: string) => {
    setTreeExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(code)) next.delete(code);
      else next.add(code);
      return next;
    });
  };

  const appendHistoryFilters = (p: URLSearchParams) => {
    if (userRef.trim()) p.set('user_ref', userRef.trim());
    if (documentId.trim()) p.set('document_id', documentId.trim());
    if (histFrom.trim()) p.set('created_from', histFrom.trim());
    if (histTo.trim()) p.set('created_to', histTo.trim());
  };

  const loadHistSummary = async () => {
    try {
      const p = new URLSearchParams();
      appendHistoryFilters(p);
      const qs = p.toString();
      const { data } = await api.get<CalculatorHistorySummaryResponse>(
        `/calculator/history/summary${qs ? `?${qs}` : ''}`,
      );
      setHistSummary(data);
    } catch {
      setHistSummary(null);
    }
  };

  const loadCalcHistory = async () => {
    setHistLoading(true);
    try {
      const params = new URLSearchParams({ limit: '15' });
      appendHistoryFilters(params);
      if (histKind.trim()) params.set('kind', histKind.trim());
      const { data } = await api.get<CalculatorHistoryListResponse>(`/calculator/history?${params.toString()}`);
      setHistItems(data.items || []);
    } catch {
      setHistItems([]);
    } finally {
      setHistLoading(false);
    }
  };

  const downloadHistoryExport = async (fmt: 'csv' | 'json') => {
    setExportErr(null);
    const params = new URLSearchParams({ format: fmt, limit: '3000' });
    appendHistoryFilters(params);
    if (histKind.trim()) params.set('kind', histKind.trim());
    const headers: Record<string, string> = {};
    const adminTokenValue = adminToken.trim();
    if (adminTokenValue) headers['X-Admin-Token'] = adminTokenValue;
    try {
      if (fmt === 'csv') {
        const res = await api.get(`/calculator/history/export?${params}`, { responseType: 'blob', headers });
        const url = URL.createObjectURL(res.data as Blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = 'calculation_history.csv';
        a.click();
        URL.revokeObjectURL(url);
      } else {
        const res = await api.get<CalculatorHistoryExportJsonResponse>(`/calculator/history/export?${params}`, { headers });
        const blob = new Blob([JSON.stringify(res.data, null, 2)], { type: 'application/json' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = 'calculation_history.json';
        a.click();
        URL.revokeObjectURL(url);
      }
    } catch (e) {
      const msg = getUserFacingApiError(e, 'Не удалось выгрузить журнал.');
      setExportErr(msg);
    }
  };

  React.useEffect(() => {
    void loadHistSummary();
    void loadCalcHistory();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [histKind, userRef, documentId, histFrom, histTo]);

  React.useEffect(() => {
    void loadTnvedTree();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Загрузка актуальности данных при монтировании
  React.useEffect(() => {
    api.get<SourcesStatusResponse>('/sources/status')
      .then(({ data }) => {
        const eec = data.sources?.find((s) => s.source_code === 'EEC_ETT');
        if (!eec) return;
        setDataFreshness({
          synced_at: eec?.synced_at ?? null,
          source: eec?.source_name ?? 'Нормативные данные',
          is_stale: eec?.is_stale ?? false,
        });
      })
      .catch(() => {
        /* без всплывающих предупреждений: блок актуальности опционален */
      });
  }, []);

  React.useEffect(() => {
    api
      .get<FinanceRatesResponse>('/v1/finance/rates')
      .then(({ data }) => {
        if (data?.map && typeof data.map === 'object') {
          setRatesMap({ RUB: 1, ...data.map });
          setRatesUpdatedAt(data.updated_at ?? null);
        }
      })
      .catch(() => {
        setRatesMap({ RUB: 1, USD: 92, EUR: 100, CNY: 12.7, BYN: 28, KZT: 0.19 });
        setRatesUpdatedAt(null);
      });
  }, []);

  const refreshRatesNow = async () => {
    const adminTokenValue = adminToken.trim();
    if (!adminTokenValue) {
      setError('Чтобы записать курсы ЦБ в серверную базу, укажите X-Admin-Token в разделе «Администрирование» ниже.');
      return;
    }
    setRatesRefreshing(true);
    try {
      const { data } = await api.post<FinanceRatesResponse>('/v1/finance/rates/update', null, {
        headers: { 'X-Admin-Token': adminTokenValue },
      });
      if (data?.map && typeof data.map === 'object') {
        setRatesMap({ RUB: 1, ...data.map });
        setRatesUpdatedAt(data.updated_at ?? null);
      }
    } catch {
      /* остаются предыдущие курсы или запасные значения */
    } finally {
      setRatesRefreshing(false);
    }
  };

  React.useEffect(() => {
    const code = hsCode.replace(/\D/g, '').slice(0, 10);
    if (code.length < 4) {
      setDutyRuleInfo(null);
      setCommodityMeta(null);
      setSuppQuantity('');
      return;
    }
    let cancelled = false;
    api
      .get<CalculatorDutyRuleResponse>(
        `/calculator/duty-rule/${encodeURIComponent(code)}`,
      )
      .then(({ data }) => {
        if (!cancelled) {
          setDutyRuleInfo(data?.duty_rule ?? null);
          setCommodityMeta(data?.commodity_meta ?? null);
          if (((data?.commodity_meta?.supp_unit || '').trim().length === 0)) {
            setSuppQuantity('');
          }
        }
      })
      .catch(() => {
        if (!cancelled) {
          setDutyRuleInfo(null);
          setCommodityMeta(null);
          setSuppQuantity('');
        }
      });
    return () => {
      cancelled = true;
    };
  }, [hsCode]);

  const handleSuppQuantityChange = (raw: string) => {
    setSuppQuantity(raw);
    if (!hasWeightCoeff) return;
    const qty = Number(raw || 0);
    const coeff = Number(commodityMeta?.weight_coeff || 0);
    if (qty > 0 && coeff > 0) {
      setNetWeightKg(formatAutoNumber(qty * coeff));
    } else if (!raw.trim()) {
      setNetWeightKg('');
    }
  };

  const handleNetWeightChange = (raw: string) => {
    setNetWeightKg(raw);
    if (!hasSuppUnit || !hasWeightCoeff) return;
    const weight = Number(raw || 0);
    const coeff = Number(commodityMeta?.weight_coeff || 0);
    if (weight > 0 && coeff > 0) {
      setSuppQuantity(formatAutoNumber(weight / coeff));
    } else if (!raw.trim()) {
      setSuppQuantity('');
    }
  };

  const handleCompute = async (hsOverride?: string) => {
    if (!country.trim()) {
      setError('Выберите страну происхождения (обязательное поле).');
      return;
    }
    if (!invoiceFxRate || invoiceFxRate <= 0) {
      setError(`Нет курса ЦБ для валюты ${invoiceCurrency}`);
      return;
    }
    const codeToUse = (hsOverride ?? hsCode).replace(/\D/g, '').slice(0, 10);
    if (codeToUse.length !== 10) {
      setError('Укажите полный 10-значный код ТН ВЭД.');
      return;
    }
    setLoading(true);
    setError(null);
    setResult(null);
    setClarification(null);
    try {
      const payload: CalculatorComputeRequest = {
        hs_code: codeToUse,
        customs_value: parseFloat(customsValue || '0'),
        invoice_currency: invoiceCurrency,
        freight: parseFloat(freight || '0'),
        apply_reduced_vat: applyReducedVat,
      };
      if (insurance) payload.insurance = parseFloat(insurance);
      if (dutyRate) payload.duty_rate = parseFloat(dutyRate);
      if (excise) payload.excise = parseFloat(excise);
      if (quantity) payload.quantity = parseFloat(quantity);
      if (netWeightKg) payload.net_weight_kg = parseFloat(netWeightKg);
      if (extraQuantity) payload.extra_quantity = parseFloat(extraQuantity);
      if (country) payload.country = country.trim().toUpperCase();
      if (isVehicleHs(codeToUse)) {
        payload.vehicle_is_new = vehicleIsNew;
        if (engineVolume) payload.engine_volume = parseInt(engineVolume, 10);
      }
      payload.save_history = saveHistory;
      const did = documentId.trim();
      if (did) payload.document_id = did;
      const ur = userRef.trim();
      if (ur) {
        payload.user_ref = ur;
        localStorage.setItem('cc_client_id', ur);
      }
      const { data } = await api.post<CalculatorComputeResponse | CalculatorClarificationResponse>(
        '/calculator/compute',
        payload,
      );
      if (data.status === 'CLARIFICATION_NEEDED') {
        setClarification(data);
        if (hsOverride) setHsCode(codeToUse);
        return;
      }
      setResult(data);
      if (hsOverride) setHsCode(codeToUse);
      setAssistantCalculationContext(buildAssistantCalcContext(data));
      try {
        const detail = await fetchCommodityByCode(data.hs_code);
        const measures = detail.non_tariff_measures;
        setAssistantCalculationContext(buildAssistantCalcContext(data, measures));
      } catch {
        /* оставляем контекст без списка мер */
      }
      if (saveHistory) {
        void loadHistSummary();
        void loadCalcHistory();
      }
    } catch (e) {
      const msg = getUserFacingApiError(e, 'Не удалось выполнить расчёт платежей.');
      setError(msg);
    } finally {
      setLoading(false);
    }
  };

  const executeComputeForPrefill = useCallback(
    async (p: CalculatorPrefillPayload) => {
      const hs = p.hs_code.replace(/\D/g, '').slice(0, 10);
      const invCur = (p.invoice_currency || 'RUB').toUpperCase().slice(0, 3);
      const fx = Number(ratesMap[invCur] ?? (invCur === 'RUB' ? 1 : 0));
      if (!fx || fx <= 0) {
        setError(`Нет курса ЦБ для валюты ${invCur}. Обновите курсы или выберите другую валюту.`);
        return;
      }
      const cty = (p.country?.trim() || country.trim() || 'CN').toUpperCase();

      setHsCode(hs);
      setCustomsValue(String(p.customs_value));
      setInvoiceCurrency(invCur);
      if (p.net_weight_kg != null && Number(p.net_weight_kg) > 0) {
        setNetWeightKg(String(p.net_weight_kg));
      } else {
        setNetWeightKg('');
      }
      setCountry(cty);

      setLoading(true);
      setError(null);
      setResult(null);
      setClarification(null);
      try {
        const payload: CalculatorComputeRequest = {
          hs_code: hs,
          customs_value: p.customs_value,
          invoice_currency: invCur,
          freight: parseFloat(freight || '0'),
          apply_reduced_vat: applyReducedVat,
          country: cty,
        };
        if (insurance) payload.insurance = parseFloat(insurance);
        if (dutyRate) payload.duty_rate = parseFloat(dutyRate);
        if (excise) payload.excise = parseFloat(excise);
        if (quantity) payload.quantity = parseFloat(quantity);
        if (p.net_weight_kg != null && Number(p.net_weight_kg) > 0) {
          payload.net_weight_kg = Number(p.net_weight_kg);
        }
        if (extraQuantity) payload.extra_quantity = parseFloat(extraQuantity);
        if (isVehicleHs(hs)) {
          payload.vehicle_is_new = vehicleIsNew;
          if (engineVolume) payload.engine_volume = parseInt(engineVolume, 10);
        }
        payload.save_history = saveHistory;
        const did = documentId.trim();
        if (did) payload.document_id = did;
        const ur = userRef.trim();
        if (ur) {
          payload.user_ref = ur;
          localStorage.setItem('cc_client_id', ur);
        }
        const { data } = await api.post<CalculatorComputeResponse | CalculatorClarificationResponse>(
          '/calculator/compute',
          payload,
        );
        if (data.status === 'CLARIFICATION_NEEDED') {
          setClarification(data);
          return;
        }
        setResult(data);
        setAssistantCalculationContext(buildAssistantCalcContext(data));
        try {
          const detail = await fetchCommodityByCode(data.hs_code);
          const measures = detail.non_tariff_measures;
          setAssistantCalculationContext(buildAssistantCalcContext(data, measures));
        } catch {
          /* без мер */
        }
        if (saveHistory) {
          void loadHistSummary();
          void loadCalcHistory();
        }
      } catch (e) {
        const msg = getUserFacingApiError(e, 'Не удалось выполнить расчёт платежей.');
        setError(msg);
      } finally {
        setLoading(false);
      }
    },
    [
      ratesMap,
      freight,
      insurance,
      dutyRate,
      excise,
      quantity,
      extraQuantity,
      country,
      applyReducedVat,
      vehicleIsNew,
      engineVolume,
      saveHistory,
      documentId,
      userRef,
    ],
  );

  const prefillComputeRef = useRef(executeComputeForPrefill);
  prefillComputeRef.current = executeComputeForPrefill;

  useEffect(() => {
    return subscribeCalculatorPrefill((payload) => {
      void prefillComputeRef.current(payload);
    });
  }, []);

  const handleSearchHs = async () => {
    const q = searchQuery.replace(/\s/g, '');
    if (q.length < 2) return;
    setSearching(true);
    setSearchResults([]);
    try {
      const { data } = await api.get<SearchHsResponse>(`/search/hs?q=${encodeURIComponent(q)}&limit=30`);
      setSearchResults(data.items || []);
    } catch {
      setSearchResults([]);
    } finally {
      setSearching(false);
    }
  };

  const handleCompare = async () => {
    if (!country.trim()) {
      setCmpErr('Выберите страну происхождения (обязательное поле).');
      return;
    }
    if (!invoiceFxRate || invoiceFxRate <= 0) {
      setCmpErr(`Нет курса ЦБ для валюты ${invoiceCurrency}`);
      return;
    }
    const cv = customsValueRub;
    if (cv <= 0) {
      setCmpErr('Укажите таможенную стоимость > 0 в форме ниже (общие параметры).');
      return;
    }
    setCmpLoading(true);
    setCmpErr(null);
    setCmpResult(null);
    try {
      const shared: CalculatorCompareRequest['shared'] = {
        customs_value: cv,
        freight: parseFloat(freight || '0'),
        apply_reduced_vat: applyReducedVat,
      };
      if (country.trim()) shared.country = country.trim().toUpperCase();
      if (quantity) shared.quantity = parseFloat(quantity);
      if (netWeightKg) shared.net_weight_kg = parseFloat(netWeightKg);
      if (extraQuantity) shared.extra_quantity = parseFloat(extraQuantity);
      if (insurance) shared.insurance = parseFloat(insurance);
      const body: CalculatorCompareRequest = {
        shared,
        scenarios: [
          { hs_code: cmpHsA.replace(/\D/g, '').slice(0, 10), label: 'Вариант A' },
          { hs_code: cmpHsB.replace(/\D/g, '').slice(0, 10), label: 'Вариант B' },
        ],
        save_history: saveHistory,
      };
      const did = documentId.trim();
      if (did) body.document_id = did;
      const ur = userRef.trim();
      if (ur) {
        body.user_ref = ur;
        localStorage.setItem('cc_client_id', ur);
      }
      const { data } = await api.post<CalculatorCompareResponse>('/calculator/compare', body);
      setCmpResult(data);
      if (saveHistory) {
        void loadHistSummary();
        void loadCalcHistory();
      }
    } catch (e) {
      const msg = getUserFacingApiError(e, 'Не удалось сравнить варианты.');
      setCmpErr(msg);
    } finally {
      setCmpLoading(false);
    }
  };

  const handleImport = async (f: File | null) => {
    if (!f) return;
    setImporting(true);
    setImportMsg(null);
    try {
      const form = new FormData();
      form.append('file', f);
      const headers: Record<string, string> = {};
      const adminTokenValue = adminToken.trim();
      if (adminTokenValue) headers['X-Admin-Token'] = adminTokenValue;
      const { data } = await api.post<SourceImportResponse>('/sources/import', form, {
        headers,
      });
      if (typeof data.imported === 'object') {
        const im = data.imported;
        setImportMsg(
          `Пакет: ТН ВЭД ${im.tnved ?? 0}, ставки ${im.rates ?? 0}, нетариф ${im.non_tariff_rules ?? 0}, примечания ${im.notes ?? 0}`,
        );
      } else {
        setImportMsg(
          `Импортировано: ${Number(data.imported) || 0}, пропущено: ${Number(data.skipped) || 0}, ревизия: ${String(data.revision ?? '')}`,
        );
      }
    } catch (e) {
      const msg = getUserFacingApiError(e, 'Не удалось импортировать файл.');
      setImportMsg(`Не удалось выполнить импорт: ${msg}`);
    } finally {
      setImporting(false);
    }
  };

  return (
    <div className="space-y-4">
      <p className="text-[12px] leading-relaxed text-slate-600">
        Расчёт пошлины, НДС и сопутствующих платежей по базе приложения.
      </p>
      <div className="cc-card-soft rounded-xl px-4 py-3 text-[11px] text-slate-700">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            Курсы ЦБ на сегодня:
            <span className="ml-2">$ {Number(ratesMap.USD ?? 0).toLocaleString('ru-RU')}</span>
            <span className="ml-3">€ {Number(ratesMap.EUR ?? 0).toLocaleString('ru-RU')}</span>
            <span className="ml-3">¥ {Number(ratesMap.CNY ?? 0).toLocaleString('ru-RU')}</span>
            {ratesUpdatedAt ? <span className="ml-3 text-slate-500">({formatDate(ratesUpdatedAt)})</span> : null}
          </div>
          <button
            type="button"
            className="cc-btn-ghost !px-2 !py-1 text-[10px]"
            onClick={() => void refreshRatesNow()}
            disabled={ratesRefreshing}
          >
            {ratesRefreshing ? 'Обновление…' : 'Обновить курсы сейчас'}
          </button>
        </div>
      </div>

      <details className="cc-disclosure">
        <summary>Журнал расчётов и связь с документом</summary>
        <div className="cc-disclosure-body space-y-3">
          <label className="flex cursor-pointer items-center gap-2 text-[13px] text-slate-700">
            <input
              type="checkbox"
              className="rounded border-slate-600"
              checked={saveHistory}
              onChange={(e) => setSaveHistory(e.target.checked)}
            />
            Сохранять расчёты в истории
          </label>
          <div className="grid gap-3 sm:grid-cols-2">
            <label className="block space-y-1">
              <span className="cc-label">document_id (из «Документы» после сохранения в БД)</span>
              <input
                value={documentId}
                onChange={(e) => setDocumentId(e.target.value)}
                placeholder="Номер документа из раздела «Документы»"
                className="cc-input cc-mono text-[12px]"
              />
            </label>
            <label className="block space-y-1">
              <span className="cc-label">user_ref / фильтр журнала</span>
              <input
                value={userRef}
                onChange={(e) => setUserRef(e.target.value)}
                placeholder="Идентификатор партии/клиента"
                className="cc-input"
              />
            </label>
            <label className="block space-y-1">
              <span className="cc-label">Период (created_from)</span>
              <input type="date" value={histFrom} onChange={(e) => setHistFrom(e.target.value)} className="cc-input" />
            </label>
            <label className="block space-y-1">
              <span className="cc-label">По дату (created_to)</span>
              <input type="date" value={histTo} onChange={(e) => setHistTo(e.target.value)} className="cc-input" />
            </label>
          </div>
          <div className="flex flex-wrap items-end gap-2">
            <label className="min-w-[200px] flex-1 space-y-1">
              <span className="cc-label">Токен администратора (при необходимости расширенного доступа)</span>
              <input
                type="password"
                value={adminToken}
                onChange={(e) => {
                  const value = e.target.value;
                  setAdminToken(value);
                  setAdminTokenMemory(value);
                }}
                placeholder="для экспорта журнала"
                className="cc-input"
              />
            </label>
            <button type="button" className="cc-btn-ghost" onClick={() => void downloadHistoryExport('csv')}>
              Экспорт CSV
            </button>
            <button type="button" className="cc-btn-ghost" onClick={() => void downloadHistoryExport('json')}>
              Экспорт отчета
            </button>
          </div>
          {exportErr && <p className="text-[11px] text-amber-700">{exportErr}</p>}
          <div className="flex flex-wrap gap-2">
            <span className="w-full text-[10px] font-semibold uppercase tracking-[0.12em] text-slate-600">Тип записи</span>
            <button
              type="button"
              className={histKind === '' ? 'cc-btn-primary' : 'cc-btn-ghost'}
              onClick={() => setHistKind('')}
            >
              Все
              {histSummary?.total != null ? ` (${histSummary.total})` : ''}
            </button>
            {HISTORY_KIND_ORDER.map((k) => (
              <button
                key={k}
                type="button"
                className={histKind === k ? 'cc-btn-primary' : 'cc-btn-ghost'}
                onClick={() => setHistKind(k)}
              >
                {HISTORY_KIND_LABELS[k] || k}
                {histSummary?.by_kind?.[k] != null ? ` (${histSummary.by_kind[k]})` : ''}
              </button>
            ))}
            {histSummary != null && (histSummary.other ?? 0) > 0 && (
              <span className="self-center text-[10px] text-slate-600">прочие: {histSummary.other}</span>
            )}
          </div>
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              className="cc-btn-ghost"
              disabled={histLoading}
              onClick={() => {
                void loadHistSummary();
                void loadCalcHistory();
              }}
            >
              {histLoading ? 'Загрузка…' : 'Обновить список расчётов'}
            </button>
            <button
              type="button"
              className="cc-btn-ghost"
              onClick={() => {
                const v = localStorage.getItem('cc_last_ingested_id') || '';
                if (v) setDocumentId(v);
              }}
            >
              Подставить последний документ
            </button>
          </div>
          {histItems.length > 0 && (
            <div className="max-h-40 overflow-auto rounded-lg border border-slate-200 bg-slate-50 p-2">
            <ul className="min-w-[320px] space-y-1 text-[11px]">
              {histItems.map((h) => (
                <li key={h.id} className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-200 py-1 last:border-0">
                  <span className="cc-mono text-indigo-700">{h.id.slice(0, 8)}…</span>
                  <span className="text-slate-500">{h.kind || '—'}</span>
                  <span className="text-slate-400">{h.hs_code || '—'}</span>
                  <span className="tabular-nums text-slate-700">
                    {h.total_payable != null ? `${h.total_payable.toLocaleString('ru-RU')} ₽` : '—'}
                  </span>
                  <a
                    href={`/api/calculator/history/${encodeURIComponent(h.id)}`}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-indigo-600 hover:underline"
                  >
                    Детали
                  </a>
                </li>
              ))}
            </ul>
            </div>
          )}
        </div>
      </details>

      {dataFreshness && (
        <details className="cc-disclosure">
          <summary>Состояние нормативных данных</summary>
          <div
            className={`cc-disclosure-body ${dataFreshness.is_stale ? 'border-l-2 border-amber-500/50 pl-3' : ''}`}
          >
            <p className="text-[12px] text-slate-500">
              {dataFreshness.is_stale && <span className="font-medium text-amber-700">Рекомендуется синхронизация. </span>}
              Актуальность:{' '}
              <span className="text-slate-700">{dataFreshness.synced_at ? formatDate(dataFreshness.synced_at) : 'данные загружены'}</span>
              <span className="text-slate-500"> · {dataFreshness.source}</span>
            </p>
          </div>
        </details>
      )}

      <details className="cc-disclosure">
        <summary>Источники и импорт ставок</summary>
        <div className="cc-disclosure-body flex flex-col gap-3">
          <p className="text-[11px] leading-relaxed text-slate-500">
            Основной справочник — ваша БД. Бесплатная выгрузка ТН ВЭД + пошлины:{' '}
            <a href="https://www.tws.by/tws/tnved/download" target="_blank" rel="noreferrer" className="text-sky-400/90 hover:underline">
              TWS.BY (Excel)
            </a>{' '}
            → загрузите .xlsx через импорт. Подсказки Альта — опционально, см. классификатор.
          </p>
          <div className="flex flex-wrap gap-2">
            <a
              href="https://eec.eaeunion.org/comission/department/catr/ett/"
              target="_blank"
              rel="noreferrer"
              className="cc-btn-ghost"
            >
              ЕТТ ЕАЭС
            </a>
            <a
              href="http://sudact.ru/law/nk-rf-chast2/razdel-viii/glava-21/statia-164/"
              target="_blank"
              rel="noreferrer"
              className="cc-btn-ghost"
            >
              НК РФ, ст. 164
            </a>
            <a
              href="https://eec.eaeunion.org/comission/department/catr/trade-protect/"
              target="_blank"
              rel="noreferrer"
              className="cc-btn-ghost"
            >
              Торговая защита
            </a>
            <a href="/api/sources/template" className="cc-btn-ghost" download="normative_template.csv">
              Шаблон CSV
            </a>
            <a href="/api/sources/template/bundle" className="cc-btn-ghost" download="normative_bundle.template.json">
              Шаблон пакета
            </a>
          </div>
          <label className="cc-btn-ghost w-fit cursor-pointer">
            {importing ? 'Импорт…' : 'Загрузить файл'}
            <input
              type="file"
              accept=".csv,.json,.xml,.xlsx,.xlsm"
              className="hidden"
              onChange={(e) => handleImport(e.target.files?.[0] || null)}
            />
          </label>
          {importMsg && <p className="text-[12px] text-slate-400">{importMsg}</p>}
        </div>
      </details>

      <CalculatorInvoiceAnalyzeSection />

      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          className="cc-btn-ghost"
          onClick={() => {
            setHsCode('8509400000'); setCustomsValue('500000'); setFreight('45000');
            setInsurance(''); setDutyRate(''); setExcise(''); setQuantity(''); setCountry('CN');
            setSuppQuantity(''); setNetWeightKg('');
          }}
        >
          Бытовая техника
        </button>
        <button
          type="button"
          className="cc-btn-ghost"
          onClick={() => {
            setHsCode('7214990000'); setCustomsValue('200000'); setFreight('20000');
            setInsurance(''); setDutyRate(''); setExcise(''); setQuantity(''); setCountry('CN');
            setSuppQuantity(''); setNetWeightKg('');
          }}
        >
          Металл, антидемпинг
        </button>
        <button
          type="button"
          className="cc-btn-ghost"
          onClick={() => {
            setHsCode('0201300000'); setCustomsValue('300000'); setFreight('30000');
            setInsurance(''); setDutyRate(''); setExcise(''); setQuantity(''); setCountry('CN');
            setSuppQuantity(''); setNetWeightKg('');
          }}
        >
          НДС 10%
        </button>
      </div>

      <div className="cc-card-soft flex flex-wrap items-end gap-2 p-4">
        <div className="min-w-[140px] flex-1">
          <span className="cc-label">Поиск кода ТН ВЭД</span>
          <input
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value.replace(/\D/g, '').slice(0, 10))}
            placeholder="85…"
            className="cc-input"
          />
        </div>
        <button type="button" disabled={searchQuery.length < 2 || searching} onClick={handleSearchHs} className="cc-btn-primary">
          {searching ? 'Поиск…' : 'Найти'}
        </button>
        {searchResults.length > 0 && (
          <div className="mt-2 max-h-36 w-full overflow-auto">
            <p className="mb-1 text-[11px] text-slate-500">{searchResults.length} позиций</p>
            <div className="flex flex-wrap gap-1.5">
              {searchResults.map((r) => (
                <button
                  type="button"
                  key={r.hs_code}
                  className="cc-btn-ghost text-[11px]"
                  onClick={() => {
                    setHsCode(r.hs_code);
                    setSearchResults([]);
                    setSearchQuery('');
                  }}
                >
                  <span className="cc-mono text-sky-200/90">{r.hs_code}</span>
                  <span className="ml-1 text-slate-500">
                    {r.duty_rate}% / НДС {r.vat_rate}%
                    {r.title ? (
                      <span
                        className={`ml-1 block max-w-[220px] truncate text-slate-700 ${TNVED_COMMODITY_NAME_CLASS}`}
                        title={formatTnvedCommodityName(r.title)}
                      >
                        {formatTnvedCommodityName(r.title)}
                      </span>
                    ) : null}
                  </span>
                </button>
              ))}
            </div>
          </div>
        )}
      </div>

      <details className="cc-disclosure" open>
        <summary>Справочник ТН ВЭД: дерево 4 → 6 → 10</summary>
        <div className="cc-disclosure-body space-y-3">
          <p className="text-[11px] leading-relaxed text-slate-500">
            Иерархия из БД <span className="cc-mono text-slate-500">tnved_commodities</span> (как во ВЭД-Инфо). Узлы 4 и 6 знаков — группы;
            конечный 10-значный код открывает ставку ввозной пошлины справа.
          </p>
          <div className="flex flex-wrap items-end gap-2">
            <label className="min-w-[140px] flex-1 space-y-1">
              <span className="cc-label">Префикс (необязательно)</span>
              <input
                value={treeFilter}
                onChange={(e) => setTreeFilter(e.target.value.replace(/\D/g, '').slice(0, 10))}
                placeholder="напр. 0101"
                className="cc-input cc-mono text-sm"
              />
            </label>
            <button type="button" className="cc-btn-primary text-sm" disabled={treeLoading} onClick={() => void loadTnvedTree()}>
              {treeLoading ? 'Загрузка…' : 'Обновить дерево'}
            </button>
          </div>
          {treeErr && <p className="text-[11px] text-amber-700">{treeErr}</p>}
          <div className="grid gap-3 lg:grid-cols-[1fr_minmax(220px,280px)]">
            <div
              className="max-h-[min(28rem,70vh)] overflow-auto rounded-xl border border-slate-200 bg-white py-1 pl-1 pr-2 text-sm shadow-inner"
              style={{ backgroundImage: 'linear-gradient(to right, rgba(226,232,240,0.6) 1px, transparent 1px)' }}
            >
              {treeLoading && treeData.length === 0 ? (
                <p className="px-2 py-3 text-[12px] text-slate-500">Загрузка дерева…</p>
              ) : treeData.length === 0 ? (
                <p className="px-2 py-3 text-[12px] text-slate-500">Нет данных — импортируйте справочник или смените префикс.</p>
              ) : (
                treeData.map((n) => (
                  <TreeNode
                    key={n.code}
                    node={n}
                    depth={0}
                    expanded={treeExpanded}
                    onToggle={toggleTreeNode}
                    onSelectLeaf={(node) => {
                      setTreeSelected(node);
                      setHsCode(node.code);
                    }}
                  />
                ))
              )}
            </div>
            <div className="rounded-xl border border-slate-200 bg-slate-50 p-3 text-sm">
              <p className="mb-2 text-[10px] font-semibold uppercase tracking-wider text-slate-500">Выбранная позиция</p>
              {treeSelected && treeSelected.code.replace(/\D/g, '').length === 10 ? (
                <div className="space-y-2 text-slate-700">
                  <p className="cc-mono text-[13px] text-indigo-700">{treeSelected.code}</p>
                  {treeSelected.title_ru ? (
                    <p className={`text-[12px] leading-snug text-slate-400 ${TNVED_COMMODITY_NAME_CLASS}`}>
                      {formatTnvedCommodityName(treeSelected.title_ru)}
                    </p>
                  ) : null}
                  <div className="border-t border-slate-200 pt-2">
                    <span className="text-[10px] uppercase tracking-wider text-slate-500">Ввозная пошлина</span>
                    <p className="mt-0.5 font-medium text-slate-900">
                      {treeSelected.import_duty ? formatImportDutyPercent(treeSelected.import_duty) : '—'}
                    </p>
                  </div>
                </div>
              ) : (
                <p className="text-[12px] text-slate-500">Кликните по 10-значному коду слева — здесь появится ставка import_duty.</p>
              )}
            </div>
          </div>
        </div>
      </details>

      <details className="cc-disclosure">
        <summary>Сравнение двух кодов («что если»)</summary>
        <div className="cc-disclosure-body space-y-3 text-[12px] text-slate-600">
          <p>
            Общие <strong className="text-slate-700">стоимость</strong>, <strong className="text-slate-700">фрахт</strong> и{' '}
            <strong className="text-slate-700">страна</strong> берутся из полей формы ниже. Сравниваются итоговые платежи и ставки по двум
            ТН ВЭД.
          </p>
          <div className="grid gap-2 sm:grid-cols-2">
            <label className="space-y-1">
              <span className="cc-label">Код A</span>
              <input value={cmpHsA} onChange={(e) => setCmpHsA(e.target.value)} className="cc-input cc-mono" />
            </label>
            <label className="space-y-1">
              <span className="cc-label">Код B</span>
              <input value={cmpHsB} onChange={(e) => setCmpHsB(e.target.value)} className="cc-input cc-mono" />
            </label>
          </div>
          <button type="button" disabled={cmpLoading} onClick={() => void handleCompare()} className="cc-btn-primary">
            {cmpLoading ? 'Считаем…' : 'Сравнить'}
          </button>
          {cmpErr && <div className="rounded-lg border border-red-200 bg-red-50 px-2 py-1.5 text-red-700">{cmpErr}</div>}
          {cmpResult?.scenarios && cmpResult.scenarios.length >= 2 && (
            <div className="overflow-x-auto rounded-xl border border-slate-200 bg-slate-50">
              <table className="w-full min-w-[320px] text-left text-[11px]">
                <thead className="border-b border-slate-200 text-[10px] uppercase tracking-wider text-slate-500">
                  <tr>
                    <th className="p-2">Вариант</th>
                    <th className="p-2">ТН ВЭД</th>
                    <th className="p-2">Пошлина %</th>
                    <th className="p-2">НДС %</th>
                    <th className="p-2">К уплате ₽</th>
                    <th className="p-2">Δ к A ₽</th>
                  </tr>
                </thead>
                <tbody className="text-slate-700">
                  {cmpResult.scenarios.map((s, i) => (
                    <tr key={i} className="border-b border-slate-200">
                      <td className="p-2">{s.label}</td>
                      <td className="cc-mono p-2 text-indigo-700">{s.hs_code}</td>
                      <td className="p-2">{s.duty_rate_applied}</td>
                      <td className="p-2">{s.vat_rate_applied}</td>
                      <td className="p-2 font-medium">{s.total_payable.toLocaleString('ru-RU')}</td>
                      <td className="p-2 text-slate-500">
                        {s.delta_total_vs_first_rub == null ? '—' : s.delta_total_vs_first_rub.toLocaleString('ru-RU')}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {cmpResult.scenarios[0]?.tnved_title && (
                <p
                  className={`border-t border-slate-200 p-2 text-[11px] text-slate-600 ${TNVED_COMMODITY_NAME_CLASS}`}
                >
                  {formatTnvedCommodityName(cmpResult.scenarios[0].tnved_title)}
                </p>
              )}
            </div>
          )}
        </div>
      </details>

      <CalculatorScenarioCompareSection
        baseHsCode={hsCode}
        customsValue={invoiceAmount}
        currency={invoiceCurrency}
        weightGrossKg={netWeightKg}
        weightNetKg={netWeightKg}
        defaultCountry={country}
      />

      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          className="cc-btn-ghost"
          onClick={() => {
            setHsCode('');
            setCustomsValue('0');
            setInvoiceCurrency('RUB');
            setFreight('0');
            setInsurance('');
            setDutyRate('');
            setApplyReducedVat(false);
            setVehicleIsNew(true);
            setEngineVolume('');
            setExcise('');
            setQuantity('');
            setNetWeightKg('');
            setExtraQuantity('');
            setSuppQuantity('');
            setCountry('');
            setResult(null);
            setClarification(null);
            setSearchResults([]);
          }}
        >
          Сбросить форму
        </button>
      </div>

      <div className="grid gap-3 md:grid-cols-2">
        <label className="space-y-1">
          <span className="cc-label">ТН ВЭД</span>
          <input value={hsCode} onChange={(e) => setHsCode(e.target.value)} placeholder="8509400000" className="cc-input" />
        </label>
        <label className="space-y-1">
          <span className="cc-label">Валюта инвойса</span>
          <select value={invoiceCurrency} onChange={(e) => setInvoiceCurrency(e.target.value)} className="cc-input">
            <option value="RUB">RUB</option>
            <option value="USD">USD</option>
            <option value="EUR">EUR</option>
            <option value="CNY">CNY</option>
            <option value="BYN">BYN</option>
            <option value="KZT">KZT</option>
          </select>
        </label>
        <label className="space-y-1">
          <span className="cc-label">Инвойсная стоимость, {invoiceCurrency}</span>
          <input value={customsValue} onChange={(e) => setCustomsValue(e.target.value)} className="cc-input" />
          <p className="text-[11px] text-slate-500">
            В рублях: {customsValueRub.toLocaleString('ru-RU')} ₽
            {invoiceCurrency !== 'RUB' ? ` (курс ${invoiceFxRate.toLocaleString('ru-RU')})` : ''}
          </p>
        </label>
        <label className="space-y-1">
          <span className="cc-label">Страна происхождения (обязательно)</span>
          <select
            value={country}
            onChange={(e) => setCountry(e.target.value)}
            className="cc-input"
            required
          >
            <option value="">Выберите страну</option>
            {COUNTRY_OPTIONS.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
        </label>
        <label className="space-y-1">
          <span className="cc-label">Фрахт, ₽</span>
          <input value={freight} onChange={(e) => setFreight(e.target.value)} className="cc-input" />
        </label>
      </div>

      <label className="flex items-start gap-2 text-[12px] text-slate-400">
        <input
          type="checkbox"
          className="mt-0.5 rounded border-slate-600"
          checked={applyReducedVat}
          onChange={(e) => setApplyReducedVat(e.target.checked)}
        />
        <span>Товар входит в перечень ПП РФ №908/41/1042 (Льготный НДС 10%)</span>
      </label>

      {isVehicle && (
        <div className="cc-card-soft space-y-3 border-l-2 border-amber-400/60 p-4">
          <p className="text-[12px] font-semibold text-slate-700">
            Транспортное средство — расчёт утилизационного сбора (ПП РФ №1291)
          </p>
          <div className="grid gap-3 sm:grid-cols-2">
            <label className="space-y-1">
              <span className="cc-label">Состояние ТС</span>
              <select
                value={vehicleIsNew ? 'new' : 'used'}
                onChange={(e) => setVehicleIsNew(e.target.value === 'new')}
                className="cc-input"
              >
                <option value="new">Новое</option>
                <option value="used">Б/у (старше 3 лет)</option>
              </select>
            </label>
            <label className="space-y-1">
              <span className="cc-label">Объём двигателя, см³</span>
              <input
                value={engineVolume}
                onChange={(e) => setEngineVolume(e.target.value.replace(/\D/g, '').slice(0, 6))}
                placeholder="напр. 2500"
                className="cc-input cc-mono"
                inputMode="numeric"
              />
            </label>
          </div>
          <p className="text-[11px] text-slate-500">
            Утильсбор зависит от типа ТС, возраста и объёма двигателя и добавляется в итог отдельной строкой.
          </p>
        </div>
      )}

      <details className="cc-disclosure">
        <summary>Дополнительные параметры расчёта</summary>
        <div className="cc-disclosure-body grid gap-3 md:grid-cols-2">
          <label className="space-y-1">
            <span className="cc-label">Страховка, ₽</span>
            <input value={insurance} onChange={(e) => setInsurance(e.target.value)} placeholder="пусто — оценка 0,15%" className="cc-input" />
          </label>
          <label className="space-y-1">
            <span className="cc-label">Пошлина % (вручную)</span>
            <input value={dutyRate} onChange={(e) => setDutyRate(e.target.value)} className="cc-input" />
          </label>
          <label className="space-y-1">
            <span className="cc-label">Акциз, ₽</span>
            <input value={excise} onChange={(e) => setExcise(e.target.value)} className="cc-input" />
          </label>
          <label className="space-y-1">
            <span className="cc-label">Количество / объём</span>
            <input value={quantity} onChange={(e) => setQuantity(e.target.value)} placeholder="1" className="cc-input" />
          </label>
          {dutyRuleInfo && (dutyRuleInfo.specific_amount ?? 0) > 0 && (
            <>
              {(dutyRuleInfo.specific_uom || '').toLowerCase() === 'kg' ? (
                <label className="space-y-1">
                  <span className="cc-label">Вес нетто (кг)</span>
                  <input
                    value={netWeightKg}
                    onChange={(e) => handleNetWeightChange(e.target.value)}
                    placeholder="например, 150"
                    className={`cc-input ${weightWarn ? 'border-amber-400/80 bg-amber-950/20' : ''}`}
                  />
                  {weightWarn ? (
                    <p className="text-[11px] text-amber-300">
                      ⚠️ Вес нетипичен для данного товара
                    </p>
                  ) : null}
                </label>
              ) : (
                <label className="space-y-1">
                  <span className="cc-label">
                    {(dutyRuleInfo.specific_uom || '').toLowerCase() === 'l'
                      ? 'Объём (литры)'
                      : 'Количество (специф. ед.)'}
                  </span>
                  <input
                    value={extraQuantity}
                    onChange={(e) => setExtraQuantity(e.target.value)}
                    placeholder="например, 120"
                    className="cc-input"
                  />
                </label>
              )}
              <div className="text-[11px] text-slate-500 md:col-span-2">
                Структурированная ставка: {(dutyRuleInfo.type || '').replace('_', ' ')} ·{' '}
                {dutyRuleInfo.specific_amount} {dutyRuleInfo.specific_currency}/{dutyRuleInfo.specific_uom}
              </div>
            </>
          )}
          {hasSuppUnit && (
            <label className="space-y-1">
              <span className="cc-label">
                Количество в {(commodityMeta?.supp_unit || 'ед.').trim()}
              </span>
              <input
                value={suppQuantity}
                onChange={(e) => handleSuppQuantityChange(e.target.value)}
                placeholder="например, 100"
                className="cc-input"
              />
              {hasWeightCoeff ? (
                <p className="text-[11px] text-slate-500">
                  Средний коэффициент: 1 {(commodityMeta?.supp_unit || 'ед.').trim()} ={' '}
                  {Number(commodityMeta?.weight_coeff || 0).toLocaleString('ru-RU')} кг
                </p>
              ) : (
                <p className="text-[11px] text-amber-300">
                  Для этого кода не задан weight_coeff, автопересчёт недоступен.
                </p>
              )}
            </label>
          )}
          {(hasSuppUnit || hasWeightCoeff) &&
            (dutyRuleInfo == null || (dutyRuleInfo.specific_uom || '').toLowerCase() !== 'kg') && (
              <label className="space-y-1">
                <span className="cc-label">Вес нетто (кг)</span>
                <input
                  value={netWeightKg}
                  onChange={(e) => handleNetWeightChange(e.target.value)}
                  placeholder="например, 150"
                  className={`cc-input ${weightWarn ? 'border-amber-400/80 bg-amber-950/20' : ''}`}
                />
                {weightWarn ? (
                  <p className="text-[11px] text-amber-300">
                    ⚠️ Вес нетипичен для данного товара
                  </p>
                ) : null}
              </label>
            )}
        </div>
      </details>

      <button type="button" onClick={() => void handleCompute()} disabled={loading} className="cc-btn-primary">
        {loading ? 'Расчёт…' : 'Рассчитать'}
      </button>

      {clarification ? (
        <div className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-4 text-sm text-amber-950">
          <p className="font-semibold">{clarification.message}</p>
          <p className="mt-1 text-xs text-amber-800">
            Групповой код {formatCustomsCode(clarification.hs_code)} нельзя использовать для расчёта напрямую — выберите конкретную
            подпозицию:
          </p>
          <ul className="mt-3 max-h-64 space-y-2 overflow-y-auto">
            {clarification.suggested_codes.map((item) => (
              <li key={item.code}>
                <button
                  type="button"
                  onClick={() => void handleCompute(item.code)}
                  className="flex w-full flex-col items-start rounded-lg border border-amber-200 bg-white px-3 py-2 text-left hover:border-indigo-300 hover:bg-indigo-50"
                >
                  <span className="font-mono text-[13px] font-semibold text-indigo-800">{formatCustomsCode(item.code)}</span>
                  {item.description ? (
                    <span className={`mt-0.5 text-xs text-slate-700 ${TNVED_COMMODITY_NAME_CLASS}`}>
                      {formatTnvedCommodityName(item.description)}
                    </span>
                  ) : null}
                  {item.duty_rate ? (
                    <span className="mt-1 text-[11px] text-slate-500">Пошлина: {formatImportDutyPercent(item.duty_rate)}</span>
                  ) : null}
                </button>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {error && (
        <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
          {error}
        </div>
      )}

      {result && (
        <div className="space-y-4 text-xs">
          {assistantVisible ? (
            <div className="flex flex-wrap justify-end gap-2">
              <button
                type="button"
                className="inline-flex items-center gap-2 rounded-xl border border-indigo-200 bg-indigo-50 px-4 py-2.5 text-[12px] font-semibold text-indigo-700 shadow-sm transition-all hover:-translate-y-0.5 hover:shadow-md"
                onClick={() => {
                  const rCode = normHsCode(result.hs_code);
                  const fromBridge = getAssistantCalculationContext();
                  const ctx =
                    fromBridge && normHsCode(fromBridge.hs_code || '') === rCode
                      ? fromBridge
                      : buildAssistantCalcContext(result);
                  requestAssistantCalculatorConsult(ctx);
                }}
              >
                <span aria-hidden>✨</span>
                Консультация по расчёту
              </button>
            </div>
          ) : null}

          {result.tnved_context && (result.tnved_context.title || (result.tnved_context.notes?.length ?? 0) > 0) && (
            <details className="cc-disclosure border-emerald-200 bg-emerald-50" open>
              <summary className="text-emerald-800">ТН ВЭД: наименование и примечания из БД</summary>
              <div className="cc-disclosure-body space-y-2 text-[12px] text-slate-700">
                {result.tnved_context.title && (
                  <p>
                    <span className={`font-medium text-slate-800 ${TNVED_COMMODITY_NAME_CLASS}`}>
                      {formatTnvedCommodityName(result.tnved_context.title)}
                    </span>
                    {result.tnved_context.description && (
                      <span className={`mt-1 block text-slate-600 ${TNVED_COMMODITY_NAME_CLASS}`}>
                        {formatTnvedCommodityName(result.tnved_context.description)}
                      </span>
                    )}
                  </p>
                )}
                {result.tnved_context.breadcrumb?.length > 0 && (
                  <p className="text-[11px] text-slate-500">
                    {result.tnved_context.breadcrumb.map((b) => b.hs_code).join(' → ')}
                  </p>
                )}
                {result.tnved_context.notes?.slice(0, 5).map((n) => (
                  <div key={n.id} className="rounded-lg border border-slate-200 bg-slate-50 px-2 py-1.5">
                    <span className="font-medium text-slate-800">{n.title}</span>
                    <span className="ml-1 text-[10px] uppercase text-slate-600">{n.category}</span>
                    <p className="mt-0.5 text-slate-600">{n.body}</p>
                  </div>
                ))}
                <a
                  href={result.tnved_context.official_ett_url}
                  target="_blank"
                  rel="noreferrer"
                  className="text-indigo-600 hover:underline"
                >
                  Официальный перечень ТН ВЭД и ЕТТ (ЕЭК)
                </a>
              </div>
            </details>
          )}

          <div className="cc-card-soft space-y-4 p-4">
            <div className="flex flex-wrap gap-2">
              <span className="inline-flex items-center gap-1 rounded-full bg-blue-100 px-2.5 py-1 text-[11px] font-semibold text-blue-800">
                <Banknote className="h-3.5 w-3.5" />
                Пошлина {result.breakdown.duty_rate}%
              </span>
              <span className="inline-flex items-center rounded-full bg-emerald-100 px-2.5 py-1 text-[11px] font-semibold text-emerald-800">
                НДС {result.breakdown.vat_rate}%
              </span>
              {(result.breakdown.special_duties_amount ?? 0) > 0 ? (
                <span className="inline-flex items-center gap-1 rounded-full bg-amber-100 px-2.5 py-1 text-[11px] font-semibold text-amber-800">
                  <ShieldCheck className="h-3.5 w-3.5" />
                  Спецмеры
                </span>
              ) : null}
              {(result.breakdown.recycling_fee ?? 0) > 0 ? (
                <span className="inline-flex items-center rounded-full bg-orange-100 px-2.5 py-1 text-[11px] font-semibold text-orange-800">
                  Утильсбор
                </span>
              ) : null}
              {preferenceLabel(result.tariff_preference) ? (
                <span className="inline-flex items-center rounded-full bg-sky-100 px-2.5 py-1 text-[11px] font-semibold text-sky-800">
                  {preferenceLabel(result.tariff_preference)}
                </span>
              ) : null}
            </div>
            {(result.special_duties_warning || result.breakdown.special_duties_warning) ? (
              <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-900">
                {result.special_duties_warning || result.breakdown.special_duties_warning}
              </div>
            ) : null}
            <TradeRemediesDisclaimer />
            <div className="space-y-1 text-[12px] text-slate-700">
              <div>
                <div className="flex items-center justify-between">
                  <span>Таможенные сборы:</span>
                  <span className="font-medium">{(result.breakdown.customs_fee ?? 0).toLocaleString('ru-RU')} руб.</span>
                </div>
                <p className="text-gray-400 text-xs">Согласно ПП РФ № 863 (в ред. 2026 г.)</p>
              </div>
              <div className="flex items-center justify-between">
                <span>Ввозная пошлина:</span>
                <span className="font-medium">
                  {result.breakdown.duty.toLocaleString('ru-RU')} руб.
                </span>
              </div>
              <div>
                <div className="flex items-center justify-between">
                  <span>
                    НДС ({result.breakdown.vat_rate}%):
                    {result.breakdown.vat_decree_info ? (
                      <span
                        className="ml-1 cursor-help align-middle text-[12px]"
                        title={`Применяется льготная ставка согласно ${result.breakdown.vat_decree_info}`}
                        aria-label={`Применяется льготная ставка согласно ${result.breakdown.vat_decree_info}`}
                      >
                        📄
                      </span>
                    ) : null}
                  </span>
                  <span className="font-medium">{result.breakdown.vat.toLocaleString('ru-RU')} руб.</span>
                </div>
                <p className="text-gray-400 text-xs">
                  {result.breakdown.vat_rate === 10
                    ? 'п. 2 ст. 164 НК РФ / ПП РФ № 908/41/1042'
                    : 'п. 3 ст. 164 НК РФ'}
                </p>
              </div>
              {(result.breakdown.special_duties_amount ?? 0) > 0 && (
                <div>
                  <div className="flex items-center justify-between">
                    <span>Спецпошлины:</span>
                    <span className="font-medium">{Number(result.breakdown.special_duties_amount || 0).toLocaleString('ru-RU')} руб.</span>
                  </div>
                  <TradeRemediesDisclaimer className="mt-1" />
                </div>
              )}
              {(result.breakdown.recycling_fee ?? 0) > 0 && (
                <div>
                  <div className="flex items-center justify-between">
                    <span>Утилизационный сбор:</span>
                    <span className="font-medium">{Number(result.breakdown.recycling_fee || 0).toLocaleString('ru-RU')} руб.</span>
                  </div>
                  <p className="text-gray-400 text-xs">
                    {result.recycling_fee?.description
                      ? `${result.recycling_fee.description} · ${result.recycling_fee.legal_ref ?? 'ПП РФ №1291'}`
                      : 'ПП РФ от 26.12.2013 №1291'}
                  </p>
                </div>
              )}
              <p className="text-gray-500 text-xs">База НДС = Стоимость + Пошлина</p>
            </div>

            <div className="rounded-xl border border-slate-200 bg-slate-50 p-3">
              <p className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-slate-600">Структура платежей</p>
              <div className="h-48 w-full">
                <ResponsiveContainer width="100%" height="100%">
                  <PieChart>
                    <Pie
                      data={[
                        { name: 'Пошлина', value: Number(result.breakdown.duty || 0) },
                        { name: 'НДС', value: Number(result.breakdown.vat || 0) },
                        { name: 'Сборы', value: Number(result.breakdown.customs_fee || 0) },
                        { name: 'Утильсбор', value: Number(result.breakdown.recycling_fee || 0) },
                      ]
                        .filter((x) => x.value > 0)
                        .map((x) => ({ ...x, pct: result.breakdown.total_payable > 0 ? (x.value / result.breakdown.total_payable) * 100 : 0 }))}
                      cx="50%"
                      cy="50%"
                      innerRadius={45}
                      outerRadius={72}
                      dataKey="value"
                      paddingAngle={2}
                    >
                      {[
                        { name: 'Пошлина', value: Number(result.breakdown.duty || 0) },
                        { name: 'НДС', value: Number(result.breakdown.vat || 0) },
                        { name: 'Сборы', value: Number(result.breakdown.customs_fee || 0) },
                        { name: 'Утильсбор', value: Number(result.breakdown.recycling_fee || 0) },
                      ]
                        .filter((x) => x.value > 0)
                        .map((entry, index) => (
                          <Cell key={`pie-cell-${index}`} fill={PAYMENT_COLORS[index % PAYMENT_COLORS.length]} />
                        ))}
                    </Pie>
                    <RechartsTooltip
                      formatter={(value, name, item: any) => [
                        `${Number(value || 0).toLocaleString('ru-RU')} ₽ (${Number(item?.payload?.pct || 0).toFixed(1)}%)`,
                        String(name || ''),
                      ]}
                    />
                  </PieChart>
                </ResponsiveContainer>
              </div>
              <div className="mt-2 grid gap-1 text-[11px] text-slate-700">
                <p>Пошлина: {result.breakdown.duty.toLocaleString('ru-RU')} ₽</p>
                <p>НДС: {result.breakdown.vat.toLocaleString('ru-RU')} ₽</p>
                <p>Сборы: {(result.breakdown.customs_fee ?? 0).toLocaleString('ru-RU')} ₽</p>
                {(result.breakdown.recycling_fee ?? 0) > 0 && (
                  <p>Утильсбор: {(result.breakdown.recycling_fee ?? 0).toLocaleString('ru-RU')} ₽</p>
                )}
              </div>
            </div>

            <div className="rounded-xl border border-blue-200 bg-gradient-to-br from-blue-50 to-white p-4">
              <div className="flex flex-wrap items-end justify-between gap-3">
                <div>
                  <p className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">Итого к уплате</p>
                  <p className="mt-0.5 text-3xl font-extrabold tracking-tight text-blue-900 sm:text-4xl">
                    {result.breakdown.total_payable.toLocaleString('ru-RU')} ₽
                  </p>
                </div>
                <button
                  type="button"
                  onClick={() => window.print()}
                  className="cc-btn-ghost !px-3 !py-1.5 text-[12px] print:hidden"
                >
                  Экспорт в PDF
                </button>
              </div>
              <div className="mt-3 grid grid-cols-2 gap-x-4 gap-y-1 text-[12px] text-slate-700 sm:grid-cols-3">
                <div className="flex justify-between gap-2">
                  <span className="text-slate-500">Пошлина</span>
                  <span className="tabular-nums font-medium">{result.breakdown.duty.toLocaleString('ru-RU')}</span>
                </div>
                <div className="flex justify-between gap-2">
                  <span className="text-slate-500">НДС</span>
                  <span className="tabular-nums font-medium">{result.breakdown.vat.toLocaleString('ru-RU')}</span>
                </div>
                <div className="flex justify-between gap-2">
                  <span className="text-slate-500">Сборы</span>
                  <span className="tabular-nums font-medium">{(result.breakdown.customs_fee ?? 0).toLocaleString('ru-RU')}</span>
                </div>
                {result.breakdown.excise > 0 && (
                  <div className="flex justify-between gap-2">
                    <span className="text-slate-500">Акциз</span>
                    <span className="tabular-nums font-medium">{result.breakdown.excise.toLocaleString('ru-RU')}</span>
                  </div>
                )}
                {(result.breakdown.antidumping ?? 0) > 0 && (
                  <div className="flex justify-between gap-2">
                    <span className="text-slate-500">Антидемпинг</span>
                    <span className="tabular-nums font-medium">{result.breakdown.antidumping.toLocaleString('ru-RU')}</span>
                  </div>
                )}
                {(result.breakdown.special_duties_amount ?? 0) > 0 && (
                  <div className="flex justify-between gap-2">
                    <span className="text-slate-500">Спецпошлины</span>
                    <span className="tabular-nums font-medium">{result.breakdown.special_duties_amount.toLocaleString('ru-RU')}</span>
                  </div>
                )}
                {(result.breakdown.recycling_fee ?? 0) > 0 && (
                  <div className="flex justify-between gap-2">
                    <span className="text-orange-700">Утильсбор</span>
                    <span className="tabular-nums font-medium text-orange-800">{(result.breakdown.recycling_fee ?? 0).toLocaleString('ru-RU')}</span>
                  </div>
                )}
              </div>
              {preferenceLabel(result.tariff_preference) && (
                <p className="mt-2 text-[11px] text-sky-700">
                  Применена тарифная преференция по стране происхождения: {preferenceLabel(result.tariff_preference)}
                  {result.tariff_preference?.legal_ref ? ` (${result.tariff_preference.legal_ref})` : ''}
                </p>
              )}
            </div>

            {(result.breakdown.selected_rule || result.breakdown.fx_rate || result.breakdown.ad_valorem_amount != null || result.breakdown.specific_amount_rub != null) && (
              <div className="text-xs text-gray-500">
                <p className="mb-0.5 font-medium uppercase tracking-wide text-[10px]">Детали расчета</p>
                <p>Пошлина: {result.breakdown.duty.toLocaleString('ru-RU')} руб. ({result.breakdown.duty_rate}%).</p>
                {result.breakdown.ad_valorem_amount != null && (
                  <p>По адвалорной ставке: {result.breakdown.ad_valorem_amount.toLocaleString('ru-RU')} руб.</p>
                )}
                {result.breakdown.specific_amount_rub != null && (
                  <p>По специфической ставке: {result.breakdown.specific_amount_rub.toLocaleString('ru-RU')} руб.</p>
                )}
                {result.breakdown.fx_rate ? (
                  <p>
                    {result.breakdown.specific_amount_rub != null &&
                    dutyRuleInfo?.specific_amount != null &&
                    result.breakdown.specific_qty_used != null ? (
                      <>
                        Специфическая ставка: {dutyRuleInfo.specific_amount.toLocaleString('ru-RU')} {result.breakdown.fx_currency || 'EUR'} ×{' '}
                        {result.breakdown.specific_qty_used.toLocaleString('ru-RU')} {result.breakdown.specific_uom || ''} ×{' '}
                        {result.breakdown.fx_rate.toLocaleString('ru-RU')} руб = {result.breakdown.specific_amount_rub.toLocaleString('ru-RU')} руб.
                        {' '}
                      </>
                    ) : null}
                    Расчет по курсу ЦБ РФ: 1 {result.breakdown.fx_currency || 'EUR'} = {result.breakdown.fx_rate.toLocaleString('ru-RU')} руб. Выбрана{' '}
                    {(result.breakdown.selected_rule || '').includes('specific') ? 'специфическая' : 'адвалорная'} ставка (
                    {result.breakdown.duty.toLocaleString('ru-RU')} руб.).
                  </p>
                ) : (
                  <p>
                    Выбрана {(result.breakdown.selected_rule || '').includes('specific') ? 'специфическая' : 'адвалорная'} ставка (
                    {result.breakdown.duty.toLocaleString('ru-RU')} руб.).
                  </p>
                )}
              </div>
            )}

            <p className="text-[11px] text-slate-500">
              База НДС: таможенная стоимость + пошлина = {result.breakdown.vat_base.toLocaleString('ru-RU')} ₽ (таможенные сборы в базу НДС не включаются)
            </p>

          </div>

          <details className="cc-disclosure">
            <summary>Обоснование ставок</summary>
            <div className="cc-disclosure-body space-y-3 text-[12px] text-slate-400">
              <div>
                <span className="cc-label mb-1 !normal-case">НДС {result.breakdown.vat_rate}%</span>
                {result.breakdown.vat_reason}
              </div>
              <div>
                <span className="cc-label mb-1 !normal-case">Пошлина {result.breakdown.duty_rate}%</span>
                {result.legal_basis?.duty}
              </div>
              {result.breakdown.excise > 0 && (
                <div>
                  <span className="cc-label mb-1 !normal-case">Акциз</span>
                  {result.breakdown.excise_reason}
                </div>
              )}
              {(result.breakdown.antidumping > 0 || result.breakdown.antidumping_status === 'manual_review') && (
                <div>
                  <span className="cc-label mb-1 !normal-case">
                    Антидемпинг
                    {result.breakdown.antidumping_status === 'manual_review' && (
                      <span className="ml-2 font-normal normal-case text-orange-300">— проверка по стране</span>
                    )}
                  </span>
                  {result.breakdown.antidumping_reason}
                  {result.auto_detected.antidumping_countries && (
                    <span className="mt-1 block text-slate-500">{result.auto_detected.antidumping_countries}</span>
                  )}
                </div>
              )}
            </div>
          </details>
        </div>
      )}
    </div>
  );
};
