import React, { useState } from 'react';
import { api } from '../../api/client';
import { getUserFacingApiError } from '../../api/error';
import type { ScenarioCompareResponse } from '../../types/api.types';

type ScenarioRow = {
  name: string;
  country_of_origin: string;
  hs_code: string;
  procedure_code: string;
};

type Props = {
  baseHsCode: string;
  customsValue: number;
  currency: string;
  weightGrossKg: string;
  weightNetKg: string;
  defaultCountry: string;
};

function emptyScenario(i: number): ScenarioRow {
  return {
    name: `Сценарий ${i}`,
    country_of_origin: '',
    hs_code: '',
    procedure_code: '',
  };
}

export function CalculatorScenarioCompareSection({
  baseHsCode,
  customsValue,
  currency,
  weightGrossKg,
  weightNetKg,
  defaultCountry,
}: Props) {
  const [scenarios, setScenarios] = useState<ScenarioRow[]>([
    { ...emptyScenario(1), country_of_origin: 'CN' },
    { ...emptyScenario(2), country_of_origin: 'DE' },
  ]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<ScenarioCompareResponse | null>(null);

  const updateScenario = (idx: number, patch: Partial<ScenarioRow>) => {
    setScenarios((prev) => prev.map((s, i) => (i === idx ? { ...s, ...patch } : s)));
  };

  const addScenario = () => {
    if (scenarios.length >= 8) return;
    setScenarios((prev) => [...prev, emptyScenario(prev.length + 1)]);
  };

  const removeScenario = (idx: number) => {
    if (scenarios.length <= 2) return;
    setScenarios((prev) => prev.filter((_, i) => i !== idx));
  };

  const exportCsv = () => {
    if (!result?.scenarios?.length) return;
    const header = ['Сценарий', 'ТН ВЭД', 'Страна', 'Пошлина', 'НДС', 'Сбор', 'РОП', 'ИТОГО', 'Экономия'];
    const worstTotal = Math.max(...result.scenarios.map((s) => s.total));
    const rows = result.scenarios.map((s) => [
      s.name,
      s.hs_code,
      s.country_of_origin || '',
      String(s.duty),
      String(s.vat),
      String(s.fee),
      String(s.rop),
      String(s.total),
      String(Math.round((worstTotal - s.total) * 100) / 100),
    ]);
    const csv = [header, ...rows].map((r) => r.join(';')).join('\n');
    const blob = new Blob(['\ufeff' + csv], { type: 'text/csv;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'scenario_compare.csv';
    a.click();
    URL.revokeObjectURL(url);
  };

  const handleCompare = async () => {
    if (customsValue <= 0) {
      setError('Укажите таможенную стоимость > 0 в форме расчёта.');
      return;
    }
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const body = {
        base: {
          hs_code: baseHsCode.replace(/\D/g, '').slice(0, 10),
          customs_value: customsValue,
          currency: currency.toUpperCase(),
          weight_gross_kg: weightGrossKg ? parseFloat(weightGrossKg) : undefined,
          weight_net_kg: weightNetKg ? parseFloat(weightNetKg) : undefined,
          country: defaultCountry.trim().toUpperCase() || undefined,
        },
        scenarios: scenarios.map((s) => ({
          name: s.name.trim() || 'Сценарий',
          country_of_origin: s.country_of_origin.trim().toUpperCase() || undefined,
          hs_code: s.hs_code.replace(/\D/g, '').slice(0, 10) || undefined,
          procedure_code: s.procedure_code.trim().toUpperCase() || undefined,
        })),
      };
      const { data } = await api.post<ScenarioCompareResponse>('/calculator/compare-scenarios', body);
      setResult(data);
    } catch (e) {
      setError(getUserFacingApiError(e, 'Не удалось сравнить сценарии.'));
    } finally {
      setLoading(false);
    }
  };

  return (
    <details className="cc-disclosure">
      <summary>Сравнение сценариев (страны, коды, процедуры)</summary>
      <div className="cc-disclosure-body space-y-3 text-[12px] text-slate-600">
        <p>
          Базовые параметры (стоимость, вес, код по умолчанию) берутся из формы расчёта. Добавьте от 2 до 8 сценариев с
          разными странами, кодами или процедурами.
        </p>
        <div className="space-y-2">
          {scenarios.map((sc, idx) => (
            <div key={idx} className="grid gap-2 rounded-lg border border-slate-200 bg-white p-2 sm:grid-cols-5">
              <input
                value={sc.name}
                onChange={(e) => updateScenario(idx, { name: e.target.value })}
                placeholder="Название"
                className="cc-input text-sm"
              />
              <input
                value={sc.country_of_origin}
                onChange={(e) => updateScenario(idx, { country_of_origin: e.target.value })}
                placeholder="Страна (CN, DE…)"
                className="cc-input cc-mono text-sm"
              />
              <input
                value={sc.hs_code}
                onChange={(e) => updateScenario(idx, { hs_code: e.target.value })}
                placeholder="ТН ВЭД (опц.)"
                className="cc-input cc-mono text-sm"
              />
              <input
                value={sc.procedure_code}
                onChange={(e) => updateScenario(idx, { procedure_code: e.target.value })}
                placeholder="Процедура (опц.)"
                className="cc-input cc-mono text-sm"
              />
              <button
                type="button"
                className="cc-btn-ghost text-xs"
                disabled={scenarios.length <= 2}
                onClick={() => removeScenario(idx)}
              >
                Удалить
              </button>
            </div>
          ))}
        </div>
        <div className="flex flex-wrap gap-2">
          <button type="button" className="cc-btn-ghost text-sm" disabled={scenarios.length >= 8} onClick={addScenario}>
            + Сценарий
          </button>
          <button type="button" disabled={loading} onClick={() => void handleCompare()} className="cc-btn-primary text-sm">
            {loading ? 'Считаем…' : 'Сравнить сценарии'}
          </button>
          {result?.scenarios?.length ? (
            <button type="button" className="cc-btn-ghost text-sm" onClick={exportCsv}>
              Экспорт CSV
            </button>
          ) : null}
        </div>
        {error ? <div className="rounded-lg border border-red-200 bg-red-50 px-2 py-1.5 text-red-700">{error}</div> : null}
        {result?.scenarios?.length ? (
          <div className="space-y-2">
            <p className="text-[11px] text-slate-500">
              Лучший: <strong className="text-emerald-700">{result.best_scenario}</strong>
              {result.savings_vs_worst > 0 ? (
                <span>
                  {' '}
                  · экономия vs худший: {result.savings_vs_worst.toLocaleString('ru-RU')} ₽
                </span>
              ) : null}
            </p>
            <div className="overflow-x-auto rounded-xl border border-slate-200 bg-slate-50">
              <table className="w-full min-w-[640px] text-left text-[11px]">
                <thead className="border-b border-slate-200 text-[10px] uppercase tracking-wider text-slate-500">
                  <tr>
                    <th className="p-2">Сценарий</th>
                    <th className="p-2">Пошлина</th>
                    <th className="p-2">НДС</th>
                    <th className="p-2">Сбор</th>
                    <th className="p-2">РОП</th>
                    <th className="p-2">ИТОГО</th>
                    <th className="p-2">Экономия</th>
                  </tr>
                </thead>
                <tbody className="text-slate-700">
                  {result.scenarios.map((s, i) => {
                    const worst = Math.max(...result.scenarios.map((x) => x.total));
                    const savings = Math.round((worst - s.total) * 100) / 100;
                    const isBest = s.name === result.best_scenario;
                    return (
                      <tr
                        key={i}
                        className={`border-b border-slate-200 ${isBest ? 'bg-emerald-50 font-medium text-emerald-900' : ''}`}
                      >
                        <td className="p-2">{s.name}</td>
                        <td className="p-2">{Number(s.duty).toLocaleString('ru-RU')}</td>
                        <td className="p-2">{Number(s.vat).toLocaleString('ru-RU')}</td>
                        <td className="p-2">{Number(s.fee).toLocaleString('ru-RU')}</td>
                        <td className="p-2">{Number(s.rop).toLocaleString('ru-RU')}</td>
                        <td className="p-2">{Number(s.total).toLocaleString('ru-RU')}</td>
                        <td className="p-2 text-slate-500">{savings.toLocaleString('ru-RU')}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
        ) : null}
      </div>
    </details>
  );
}
