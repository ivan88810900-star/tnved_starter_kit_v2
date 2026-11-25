import { isAxiosError } from 'axios';
import { useCallback, useEffect, useState } from 'react';
import { loginCompleted, openLoginDialog } from '../AuthBar';
import { api } from '../../api/client';

type ArchiveAct = { act_code: string; short_name: string; source_revision: string };
type Block = { hs_code: string; assessment: string; empty_message: string; notes: string[]; archive_acts: ArchiveAct[]; product_review?: { product_documents: { comparison?: string }; edition: { scope_limit?: string; scope?: {locator: string; source_url: string}; decisions: { number: number; label?: string; general_effective_date?: string | null; source_url: string }[]; limit: string }; questions: string[]; source_routes: { document_type: string; condition: string; locator: string; source_url: string }[] } };
type Reply = { items: { normative_block: Block }[] };

export function LocalNormativeCheck({ code }: { code: string }) {
  const [description, setDescription] = useState('');
  const [tablewareUse, setTablewareUse] = useState('unknown');
  const [age, setAge] = useState('unknown');
  const [country, setCountry] = useState('');
  const [documentType, setDocumentType] = useState('СГР');
  const [documentNumber, setDocumentNumber] = useState('');
  const [busy, setBusy] = useState(false);
  const [block, setBlock] = useState<Block>();
  const [message, setMessage] = useState('');

  const [needsLogin, setNeedsLogin] = useState(false);

  const check = useCallback(async () => {
    setNeedsLogin(false);
    setBusy(true);
    setBlock(undefined);
    setMessage('');
    try {
      const { data } = await api.post<Reply>('/non_tariff/normative-block', { items: [{ hs_code: code, description: description.trim(),
        ...(code.startsWith('7013') && { tableware_use: tablewareUse, tableware_age: age }),
        country: country.trim() || null, permits: documentNumber.trim() ? [{ type: documentType, number: documentNumber.trim() }] : [] }] });
      const result = data.items[0]?.normative_block;
      if (result?.hs_code !== code || result.assessment !== 'INSUFFICIENT_EVIDENCE') {
        throw new Error('Unexpected local assessment');
      }
      setBlock(result);
    } catch (error) {
      const status = isAxiosError(error) ? error.response?.status : undefined;
      setNeedsLogin(status === 401);
      setMessage(status === 401 ? 'Для проверки нужен вход.'
        : status === 503 ? 'Проверка недоступна в этом профиле.'
        : 'Не удалось получить результат. Повторите проверку.');
    } finally {
      setBusy(false);
    }
  }, [code, description, country, documentType, documentNumber, tablewareUse, age]);

  useEffect(() => {
    if (!needsLogin) return;
    const repeat = () => { void check(); };
    window.addEventListener(loginCompleted, repeat);
    return () => window.removeEventListener(loginCompleted, repeat);
  }, [needsLogin, check]);

  function clearAssessment() {
    setBlock(undefined);
    setMessage('');
    setNeedsLogin(false);
  }

  return <div className="space-y-2">
    <label className="block">Характеристики товара
      <input className="cc-input mt-1 w-full" value={description} maxLength={1000} disabled={busy}
        onChange={e => { setDescription(e.target.value); clearAssessment(); }} />
    </label>
    {code.startsWith('7013') && <fieldset className="space-y-2" disabled={busy}>
      <label className="block">Назначение по маркировке изготовителя
        <select className="cc-input mt-1 block" value={tablewareUse} onChange={e => { setTablewareUse(e.target.value); setAge('unknown'); clearAssessment(); }}>
          <option value="unknown">Не указано</option>
          <option value="child_food_glass">Детская стеклянная посуда для еды или питья</option>
        </select>
      </label>
      {tablewareUse === 'child_food_glass' && <label className="block">Для какого возраста предназначено изделие
        <select className="cc-input mt-1 block" value={age} onChange={e => { setAge(e.target.value); clearAssessment(); }}>
          <option value="unknown">Возраст не указан</option>
          <option value="under_3">До 3 лет</option>
          <option value="exactly_3">Ровно 3 года</option>
          <option value="over_3">Старше 3 лет, включая подростков</option>
        </select>
      </label>}
    </fieldset>}
    <details><summary className="cursor-pointer">Страна и реквизиты для проверки</summary>
      <div className="mt-2 space-y-2">
        <label className="block">Страна происхождения
          <input className="cc-input mt-1 w-full" maxLength={100} value={country} disabled={busy} onChange={e => { setCountry(e.target.value); clearAssessment(); }} />
        </label>
        <label className="block">Вид документа
          <select value={documentType} className="cc-input mt-1 block" disabled={busy} onChange={e => { setDocumentType(e.target.value); clearAssessment(); }}>
            <option value="СГР">Свидетельство о государственной регистрации</option>
            <option value="ДС">Декларация о соответствии</option>
            <option value="СС">Сертификат соответствия</option>
          </select>
        </label>
        <label className="block">Номер {documentType}, если известен
          <input className="cc-input mt-1 w-full" maxLength={160} autoComplete="off" value={documentNumber} disabled={busy} onChange={e => { setDocumentNumber(e.target.value); clearAssessment(); }} />
        </label>
      </div>
    </details>
    <button type="button" disabled={busy} onClick={check} className="rounded border px-3 py-1">
      {busy ? 'Идёт проверка…' : 'Проверить требования к товару'}
    </button>
    <div role="status" className="space-y-1">
      {message && <p>{message}{needsLogin && <> <button type="button" className="underline" onClick={openLoginDialog}>Войти и проверить</button></>}</p>}
      {block && <>
        <p className="font-medium">{block.empty_message}</p>
        {block.notes.map(note => <p key={note}>{note}</p>)}
        {block.product_review && <section className="space-y-2">
          {block.product_review.product_documents.comparison === 'NUMBER_MATCH_ONLY' && <p>Номер найден в локальной выписке. Соответствие документа товару и поставке требует проверки.</p>}
          {block.product_review.product_documents.comparison === 'NO_NUMBER_IN_LOCAL_EXCERPT' && <p>В подключённой локальной выписке этот номер не найден.</p>}
          {block.product_review.product_documents.comparison === 'EXCERPT_NOT_CONFIGURED' && <p>В этом профиле локальная выписка для сверки номера не подключена.</p>}
          {block.product_review.questions.length > 0 && <><h4 className="font-medium">Что уточнить</h4><ul className="list-disc pl-5">{block.product_review.questions.map(q => <li key={q}>{q}</li>)}</ul></>}
          <details><summary className="cursor-pointer">Условия по официальным источникам</summary>
            <ul className="space-y-2 pt-2">{block.product_review.source_routes.map(r => <li key={r.document_type + r.locator}>
              <strong>{r.document_type}</strong> · {r.condition}
              {r.source_url.startsWith('https://') && <> · <a className="underline" href={r.source_url} target="_blank" rel="noreferrer">{r.locator}</a></>}
            </li>)}</ul>
            {block.product_review.edition.scope_limit && <p className="mt-2">{block.product_review.edition.scope_limit}
              {block.product_review.edition.scope?.source_url.startsWith('https://') && <> · <a className="underline" href={block.product_review.edition.scope.source_url} target="_blank" rel="noreferrer">{block.product_review.edition.scope.locator}</a></>}
            </p>}
            <p className="mt-2 font-medium">Общие даты вступления в силу</p>
            <ul>{block.product_review.edition.decisions.map(d => <li key={d.source_url + d.number}>
              <a className="underline" href={d.source_url} target="_blank" rel="noreferrer">{d.label || 'Решение № ' + d.number}</a> · {d.general_effective_date ? <time dateTime={d.general_effective_date}>{d.general_effective_date.split('-').reverse().join('.')}</time> : 'дата требует проверки'}
            </li>)}</ul>
            <p>{block.product_review.edition.limit}</p>
          </details>
        </section>}
        {block.archive_acts.length > 0 && <ul>{block.archive_acts.map(act =>
          <li key={act.act_code}>Архивная карточка {act.act_code} · {act.short_name} · {act.source_revision}</li>)}</ul>}
      </>}
    </div>
  </div>;
}
