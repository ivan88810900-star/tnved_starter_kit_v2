import { Link } from 'react-router-dom';
import React from 'react';
import { localDutyDisplay } from './localDutyDisplay';
import { api } from '../../api/client';

type Rate = {
  hs_code: string; original_duty_text: string; original_supplementary_unit: string;
  syntax_status: string; legal_status: string; page_number: number; line_number: number;
  source_url: string; source_revision: string; pdf_sha256: string;
};
type Act = { act_code: string; short_name: string; full_title: string; source_revision: string; source_url: string };

type Props = React.PropsWithChildren<{ code: string; simplified: boolean; canCalculate: boolean }>;

export function LocalPilotEvidence({ code, simplified, children, canCalculate }: Props) {
  const [rate, setRate] = React.useState<Rate | null>();
  const [failed, setFailed] = React.useState(false);
  const [attempt, setAttempt] = React.useState(0);
  const [query, setQuery] = React.useState('');
  const [acts, setActs] = React.useState<Act[]>();
  const [registryError, setRegistryError] = React.useState(false);
  React.useEffect(() => {
    const controller = new AbortController();
    setFailed(false);
    setRate(undefined);
    api.get<{rate: Rate | null}>(`/local-ett/${code}`, {signal: controller.signal})
      .then(({data}) => { if (!controller.signal.aborted) setRate(data.rate); })
      .catch(() => { if (!controller.signal.aborted) setFailed(true); });
    return () => controller.abort();
  }, [code, attempt]);
  React.useEffect(() => {
    const controller = new AbortController();
    setActs(undefined);
    setRegistryError(false);
    if (query.trim()) {
      api.get<{items: Act[]}>('/non_tariff/tr-ts-registry', {params: {q: query.trim()}, signal: controller.signal})
        .then(({data}) => { if (!controller.signal.aborted) setActs(data.items); })
        .catch(() => { if (!controller.signal.aborted) setRegistryError(true); });
    }
    return () => controller.abort();
  }, [query]);
  const duty = rate && localDutyDisplay(rate.original_duty_text, rate.pdf_sha256);
  const unit = rate?.original_supplementary_unit.trim();
  return <section aria-label="Локальные источники" className="space-y-4">
    <div className="rounded-lg border border-cargo-border p-4">
      <h3 className="text-sm text-cargo-mid">Ввозная пошлина</h3>
      {failed ? <div role="alert">Ставку не удалось загрузить. <button className="underline" onClick={() => setAttempt(attempt + 1)}>Повторить</button></div>
        : rate === undefined ? <p role="status">Загрузка ставки…</p>
        : !rate || !duty ? <p>В подключённых партиях для этого кода ставки нет.</p>
        : <div data-testid="local-rate">
          <p className="mt-1 text-xl font-semibold">
            <span data-testid="duty-value">{duty.text}</span>{duty.note && <sup className="ml-1" aria-label={`Сноска ${duty.note}`}>{duty.note}</sup>}
          </p>
          {unit && !/^[-–—]$/.test(unit) && <p className="mt-1">Доп. единица измерения · {unit}</p>}
          <p className="mt-1 text-xs text-cargo-mid">Справочно · применимость не подтверждена.</p>
        </div>}
    </div>
    {canCalculate && <Link className="inline-block font-medium text-cargo-trust underline" to={`/calculator?code=${code}`}>
      Открыть калькулятор
    </Link>}
    <details className="border-t border-cargo-border pt-3">
      <summary className="cursor-pointer font-medium">
        Подробнее о товаре{duty?.note && ' · сноска ' + duty.note}{simplified && ' · оригинальное оформление'}
      </summary>
      <div className="mt-3 space-y-4">
        {rate && duty && <section aria-label="Источник ставки" className="space-y-1 text-xs">
          <h3 className="font-semibold">Источник ставки</h3>
          <p>Запись в ЕТТ: {rate.original_duty_text}</p>
          {duty.note && <p>Сноска {duty.note} относится к ставке. Условия её применения не проверены.</p>}
          <p>Редакция {rate.source_revision} · строка {rate.line_number} · {rate.legal_status}</p>
          <a className="underline" href={rate.source_url.split('#')[0] + '#page=' + rate.page_number} target="_blank" rel="noreferrer">PDF ЕЭК, стр. {rate.page_number}</a>
        </section>}
        {children}
        <details className="text-sm">
          <summary className="cursor-pointer">Нетарифные требования</summary>
          <div className="mt-2 space-y-2">
            <p>Применимость требований к товару не установлена.</p>
            <label className="block">Найти справочную карточку ТР по номеру или названию
              <input value={query} onChange={event => setQuery(event.target.value)} maxLength={160} className="mt-1 block rounded border p-1" /></label>
            {registryError && <p role="alert">Реестр ТР недоступен.</p>}
            {acts && (acts.length ? <>
              <ul className="space-y-2">{acts.map(a => <li key={a.act_code}>
                <p className="font-medium">{a.short_name || a.act_code}</p>
                {a.full_title && <p>{a.full_title}</p>}
                <p className="text-xs text-cargo-mid">Архивная редакция справочника · {a.source_revision}</p>
                {a.source_url.startsWith('https://') && <a className="underline" href={a.source_url} target="_blank" rel="noreferrer">Сайт из архивной карточки</a>}
              </li>)}</ul>
              <p>Обязательность и реквизиты документа на товар не установлены. Для проверки нужны характеристики товара, действующая редакция регламента и документ на конкретную продукцию.</p>
            </>
              : <p>В локальном справочнике совпадений нет. Требования к товару остаются неустановленными.</p>)}
          </div>
        </details>
      </div>
    </details>
  </section>;
}
