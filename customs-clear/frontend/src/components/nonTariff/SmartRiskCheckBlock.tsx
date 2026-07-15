import React from 'react';
import axios from 'axios';
import { Building2, Search, ShieldCheck } from 'lucide-react';
import { fetchRiskCheck } from '../../api/riskCheck';
import { getUserFacingApiError } from '../../api/error';
import type { SanctionsRiskBlockData } from '../../types/api.types';
import { SanctionsRiskBlock } from './SanctionsRiskBlock';

type Props = {
  hsCode: string;
  description?: string;
  className?: string;
};

export const SmartRiskCheckBlock: React.FC<Props> = ({ hsCode, description, className = '' }) => {
  const [country, setCountry] = React.useState('');
  const [counterparty, setCounterparty] = React.useState('');
  const [result, setResult] = React.useState<SanctionsRiskBlockData | null>(null);
  const [loading, setLoading] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  const runCheck = React.useCallback(async (inputs?: { country: string; counterparty: string }) => {
    const countryCode = (inputs?.country ?? country).trim().toUpperCase();
    const party = (inputs?.counterparty ?? counterparty).trim();
    if (countryCode && !/^[A-Z]{2}$/.test(countryCode)) {
      setError('Страна происхождения указывается двумя латинскими буквами, например CN или DE.');
      return;
    }
    if (party && party.length < 3) {
      setError('Для проверки контрагента укажите не менее трёх символов.');
      return;
    }

    setLoading(true);
    setError(null);
    try {
      const data = await fetchRiskCheck({
        hs_code: hsCode,
        description: description?.trim() || '',
        country: countryCode || null,
        counterparty_name: party || null,
      });
      setResult(data);
    } catch (e: unknown) {
      setResult(null);
      if (axios.isAxiosError(e) && e.response?.status === 401) {
        setError('Войдите в систему, чтобы выполнить санкционную проверку.');
      } else {
        setError(getUserFacingApiError(e, 'Не удалось выполнить санкционную проверку.'));
      }
    } finally {
      setLoading(false);
    }
  }, [country, counterparty, description, hsCode]);

  React.useEffect(() => {
    setCountry('');
    setCounterparty('');
    setResult(null);
    setError(null);
    void runCheck({ country: '', counterparty: '' });
  }, [hsCode]); // eslint-disable-line react-hooks/exhaustive-deps -- новый код запускает базовую HS-проверку

  return (
    <div className={`space-y-4 ${className}`}>
      <section className="rounded-xl border border-indigo-100 bg-gradient-to-br from-indigo-50 to-white px-4 py-4">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <ShieldCheck className="h-5 w-5 text-indigo-700" aria-hidden />
            <h3 className="text-sm font-bold uppercase tracking-wide text-indigo-900">Санкционный скрининг</h3>
          </div>
          <span className="rounded-full border border-indigo-200 bg-white px-2.5 py-1 text-[10px] font-semibold uppercase tracking-wide text-indigo-700">
            Диагностическая проверка
          </span>
        </div>
        <p className="mb-4 text-xs leading-relaxed text-slate-600">
          Код проверяется автоматически. Добавьте страну происхождения и наименование контрагента или производителя,
          чтобы проверить страновые ограничения, эмбарго и локальные списки OFAC/ЕС.
        </p>

        <div className="grid gap-3 md:grid-cols-[minmax(0,180px)_minmax(0,1fr)_auto] md:items-end">
          <label className="block text-xs">
            <span className="mb-1 block font-medium text-slate-700">Страна происхождения</span>
            <input
              type="text"
              maxLength={2}
              placeholder="CN"
              value={country}
              onChange={(e) => setCountry(e.target.value.toUpperCase())}
              className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm uppercase"
            />
            <span className="mt-1 block text-[10px] text-slate-500">ISO-2, например CN или DE</span>
          </label>
          <label className="block text-xs">
            <span className="mb-1 block font-medium text-slate-700">Контрагент или производитель</span>
            <div className="relative">
              <Building2 className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-slate-400" aria-hidden />
              <input
                type="text"
                placeholder="Полное наименование организации"
                value={counterparty}
                onChange={(e) => setCounterparty(e.target.value)}
                className="w-full rounded-lg border border-slate-200 py-2 pl-9 pr-3 text-sm"
              />
            </div>
            <span className="mt-1 block text-[10px] text-slate-500">Предварительное текстовое сопоставление, не KYC-заключение</span>
          </label>
          <button
            type="button"
            onClick={() => void runCheck()}
            disabled={loading}
            className="inline-flex items-center justify-center gap-2 rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50"
          >
            <Search className="h-4 w-4" aria-hidden />
            {loading ? 'Проверка…' : 'Проверить'}
          </button>
        </div>
      </section>

      {error ? (
        <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">{error}</div>
      ) : null}

      {result ? (
        <SanctionsRiskBlock block={result} title="Результат санкционной проверки" />
      ) : loading ? (
        <p className="text-sm text-slate-500">Проверка кода и доступных источников…</p>
      ) : null}
    </div>
  );
};
