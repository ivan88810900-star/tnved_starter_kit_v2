import React from 'react';
import * as HoverCard from '@radix-ui/react-hover-card';
import { AlertTriangle, Banknote, Info } from 'lucide-react';
import { fetchTnvedPreview, formatCode, type TnvedPreview } from '../../api/tnvedCatalog';
import { getApiErrorMessage } from '../../api/error';
import { formatTnvedCommodityName, TNVED_COMMODITY_NAME_CLASS } from '../../utils/tnvedDisplayText';
import { TradeRemediesDisclaimer } from '../payments/TradeRemediesDisclaimer';

type Props = {
  code: string;
  fallbackName?: string;
  children: React.ReactElement;
};

const previewCache = new Map<string, TnvedPreview | null>();
const previewInflight = new Map<string, Promise<TnvedPreview | null>>();
const previewErrors = new Map<string, string>();

async function loadPreview(code: string): Promise<TnvedPreview | null> {
  const key = code.replace(/\D/g, '');
  if (!key || key.length < 4) return null;
  if (previewCache.has(key)) return previewCache.get(key) ?? null;
  if (previewInflight.has(key)) return previewInflight.get(key) ?? null;

  const p = fetchTnvedPreview(key)
    .then((d) => {
      previewCache.set(key, d);
      previewErrors.delete(key);
      return d;
    })
    .catch((e) => {
      previewCache.set(key, null);
      previewErrors.set(key, getApiErrorMessage(e, 'Не удалось загрузить данные по коду ТН ВЭД'));
      return null;
    })
    .finally(() => {
      previewInflight.delete(key);
    });
  previewInflight.set(key, p);
  return p;
}

const dutyPercent = (raw: string): number | null => {
  const m = (raw || '').match(/(\d+(?:[.,]\d+)?)\s*%/);
  if (!m) return null;
  const n = Number(m[1].replace(',', '.'));
  return Number.isFinite(n) ? n : null;
};

export const MeasureHoverCard: React.FC<Props> = ({ code, fallbackName = '', children }) => {
  const [preview, setPreview] = React.useState<TnvedPreview | null>(null);
  const [loading, setLoading] = React.useState(false);
  const [loadError, setLoadError] = React.useState<string | null>(null);

  const norm = code.replace(/\D/g, '');
  const canPreview = norm.length >= 4;

  const prefetch = React.useCallback(() => {
    if (!canPreview) return;
    if (previewCache.has(norm)) {
      setPreview(previewCache.get(norm) ?? null);
      setLoadError(previewErrors.get(norm) ?? null);
      return;
    }
    setLoading(true);
    void loadPreview(norm).then((res) => {
      setPreview(res);
      setLoadError(previewErrors.get(norm) ?? null);
      setLoading(false);
    });
  }, [canPreview, norm]);

  if (!canPreview) return children;

  const p = preview;
  const badges = p?.non_tariff.measure_badges ?? [];
  const hasBan = Boolean(p?.non_tariff.has_ban);
  const duty = p?.payments.duty ?? '';
  const dutyPct = dutyPercent(duty);
  const dutyGreen = dutyPct !== null && dutyPct === 0;

  return (
    <HoverCard.Root openDelay={400} closeDelay={120}>
      <HoverCard.Trigger asChild onMouseEnter={prefetch}>
        {children}
      </HoverCard.Trigger>
      <HoverCard.Portal>
        <HoverCard.Content
          side="right"
          align="start"
          sideOffset={8}
          className={`z-50 w-[360px] rounded-xl border bg-white p-4 shadow-xl ${
            hasBan ? 'border-red-400' : 'border-gray-200'
          }`}
        >
          {loading && !p ? (
            <div className="animate-pulse space-y-3">
              <div className="space-y-2">
                <div className="h-3 w-32 rounded bg-gray-200" />
                <div className="h-3 w-56 rounded bg-gray-100" />
              </div>
              <div className="space-y-1">
                <div className="h-2.5 w-20 rounded bg-gray-200" />
                <div className="h-2.5 w-44 rounded bg-gray-100" />
                <div className="h-2.5 w-36 rounded bg-gray-100" />
              </div>
              <div className="space-y-1">
                <div className="h-2.5 w-20 rounded bg-gray-200" />
                <div className="h-5 w-28 rounded bg-gray-100" />
              </div>
            </div>
          ) : !p && loadError ? (
            <div className="flex items-start gap-2.5 rounded-lg border border-red-200 bg-red-50 p-3">
              <AlertTriangle size={16} className="mt-0.5 shrink-0 text-red-600" />
              <div className="space-y-1">
                <p className="text-sm font-semibold text-red-700">Ошибка загрузки данных. Попробуйте позже.</p>
                <p className="text-xs text-red-600">Не удалось загрузить справку по товару.</p>
              </div>
            </div>
          ) : (
            <div className="space-y-3">
              <div>
                <p className="font-mono text-sm font-bold text-gray-900">{formatCode(p?.code || norm)}</p>
                <p className={`mt-0.5 text-[13px] text-gray-800 ${TNVED_COMMODITY_NAME_CLASS}`}>
                  {formatTnvedCommodityName(p?.name || fallbackName || '') || 'Наименование недоступно'}
                </p>
                {hasBan && (
                  <p className="mt-2 inline-flex rounded bg-red-100 px-2 py-0.5 text-[11px] font-semibold text-red-700">
                    ВВОЗ ЗАПРЕЩЕН
                  </p>
                )}
              </div>

              <div>
                <p className="mb-1 flex items-center gap-1 text-[11px] font-semibold uppercase tracking-wide text-gray-500">
                  <Banknote size={13} /> Платежи
                </p>
                <div className="space-y-1 text-xs">
                  <p className={dutyGreen ? 'text-emerald-700 font-medium' : 'text-gray-700'}>
                    Пошлина: {duty || 'нет данных'}
                  </p>
                  <p className="text-gray-700">НДС: 22% (базовая ставка; льготные ставки — при перечневых основаниях)</p>
                  <p className="text-gray-700">Акциз: {p?.payments.excise || 'нет данных'}</p>
                </div>
              </div>

              <div>
                <p className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-gray-500">Нетарифка</p>
                {badges.length === 0 ? (
                  <p className="text-xs text-emerald-700">{p?.non_tariff.empty_message || '✅ Меры нетарифного регулирования не применяются'}</p>
                ) : (
                  <div className="flex flex-wrap gap-1">
                    {badges.map((b) => (
                      <span
                        key={b}
                        className={`rounded px-2 py-0.5 text-[11px] ${
                          hasBan ? 'bg-red-100 text-red-700' : 'bg-amber-100 text-amber-800'
                        }`}
                      >
                        {b}
                      </span>
                    ))}
                  </div>
                )}
              </div>

              {p?.special_duties?.has_measures ? (
                <div>
                  <p className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-gray-500">Спецпошлины</p>
                  <p className="text-xs text-amber-700">
                    ⚠️ {p.special_duties.warning || `Для данного кода действуют антидемпинговые меры (страны: ${p.special_duties.countries.join(', ')}).`}
                  </p>
                  <TradeRemediesDisclaimer className="mt-1.5" />
                </div>
              ) : null}

              <div>
                <p className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-gray-500">Защита бренда (ТРОИС)</p>
                {p?.trois?.has_protected_brands ? (
                  <p className="text-xs text-amber-700">
                    ⚠️ Внимание! Данный код содержит бренды под защитой ТРОИС. Проверьте наличие вашего бренда в списке:{' '}
                    {p.trois.brands.join(', ')}.
                  </p>
                ) : (
                  <p className="text-xs text-emerald-700">Совпадений с ТРОИС по коду не найдено.</p>
                )}
              </div>

              <div>
                <p className="mb-1 flex items-center gap-1 text-[11px] font-semibold uppercase tracking-wide text-gray-500">
                  <Info size={13} /> Особенности
                </p>
                {p?.features?.length ? (
                  <ul className="space-y-1 text-xs text-gray-700">
                    {p.features.map((f) => (
                      <li key={f}>{f}</li>
                    ))}
                  </ul>
                ) : (
                  <p className="text-xs text-gray-500">Дополнительных особенностей не найдено.</p>
                )}
              </div>
            </div>
          )}
        </HoverCard.Content>
      </HoverCard.Portal>
    </HoverCard.Root>
  );
};

