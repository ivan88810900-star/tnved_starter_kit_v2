import { isAxiosError } from 'axios';
import { FormEvent, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../api/client';
import { loginCompleted, logoutCompleted, openLoginDialog } from '../components/AuthBar';

type Line = { line: number; description: string; quantity?: number | null; unit?: string | null; selected_code: string | null };
type Draft = { draft_id: string; lines: Line[] };
type Match = { code: string; label: string; path: string[] };
type Choice = { candidates: Match[]; question: { text: string; options: { value: string; label: string }[] } | null; limited: boolean; selected_code: string | null };

function errorText(error: unknown) {
  const detail = isAxiosError(error) && error.response?.data?.detail;
  if (typeof detail === 'string') return detail;
  return 'Действие не выполнено. Проверьте вход и повторите попытку.';
}

function InvoiceLine({ draftId, item, onSaved }: { draftId: string; item: Line; onSaved: (line: Line) => void }) {
  const [choices, setChoices] = useState<Choice>();
  const [answers, setAnswers] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const path = '/local-invoice/drafts/' + draftId + '/lines/' + item.line;

  async function search(next: string[]) {
    setBusy(true);
    setError('');
    try {
      const { data } = await api.post<Choice>(path + '/candidates', { answers: next });
      setAnswers(next);
      setChoices(data);
    } catch (e) { setError(errorText(e)); }
    finally { setBusy(false); }
  }

  async function save(code: string) {
    setBusy(true);
    setError('');
    try {
      const { data } = await api.put<Draft>(path + '/choice', { code, answers });
      const saved = data.lines.find(row => row.line === item.line);
      if (!saved) throw new Error('Missing invoice line');
      onSaved(saved);
      setChoices(undefined);
      setAnswers([]);
    } catch (e) { setError(errorText(e)); }
    finally { setBusy(false); }
  }

  return <section className="space-y-3 rounded-lg border border-cargo-border p-4" aria-label={'Строка ' + item.line}>
    <h3 className="font-semibold">{item.description}</h3>
    {item.quantity != null && <p>{item.quantity} {item.unit}</p>}
    <p>{item.selected_code ? <>Выбранный код · <Link className="underline" to={'/tnved?code=' + item.selected_code}>{item.selected_code}</Link></> : 'Код ещё не выбран'}</p>
    {!choices && <button type="button" disabled={busy} className="cc-btn-secondary" onClick={() => void search([])}>{item.selected_code ? 'Изменить выбор' : 'Подобрать код'}</button>}
    {choices && <div className="space-y-3">
      {choices.question && <fieldset disabled={busy}>
        <legend className="font-medium">{choices.question.text}</legend>
        <div className="mt-2 flex flex-wrap gap-2">{choices.question.options.map(o => <button type="button" className="cc-btn-secondary" key={o.value} onClick={() => void search([...answers, o.value])}>{o.label}</button>)}</div>
      </fieldset>}
      {answers.length > 0 && <button className="underline" disabled={busy} onClick={() => void search(answers.slice(0, -1))}>Вернуться к предыдущему ответу</button>}
      {choices.limited && <p>Показана часть совпадений. Уточните характеристики товара.</p>}
      {!choices.candidates.length && !choices.question && <p>По описанию в справочнике не удалось подобрать код.</p>}
      <ul className="divide-y divide-cargo-border">{choices.candidates.map(c => <li key={c.code} className="space-y-1 py-2">
        <Link to={'/tnved?code=' + c.code} className="font-medium underline">{c.code} · {c.label}</Link>
        <p className="text-sm text-cargo-mid">{c.path.join(' › ')}</p>
        <button type="button" className="cc-btn-secondary" disabled={busy} onClick={() => void save(c.code)}>Выбрать {c.code}</button>
      </li>)}</ul>
    </div>}
    {error && <p role="alert">{error}</p>}
  </section>;
}

function DraftEditor({ username }: { username: string }) {
  const storageKey = 'tariff:local-invoice:' + username;
  const [draft, setDraft] = useState<Draft>();
  const [busy, setBusy] = useState(true);
  const [message, setMessage] = useState('');
  const [description, setDescription] = useState('');
  const [file, setFile] = useState<File>();
  useEffect(() => {
    const controller = new AbortController();
    const id = sessionStorage.getItem(storageKey);
    if (!id) { setBusy(false); return; }
    api.get<Draft>('/local-invoice/drafts/' + encodeURIComponent(id), { signal: controller.signal })
      .then(({ data }) => { if (!controller.signal.aborted) setDraft(data); })
      .catch(e => {
        if (controller.signal.aborted) return;
        if (isAxiosError(e) && e.response?.status === 404) {
          sessionStorage.removeItem(storageKey);
          setMessage('Предыдущий локальный черновик недоступен. Можно начать новый.');
        } else setMessage(errorText(e));
      }).finally(() => { if (!controller.signal.aborted) setBusy(false); });
    return () => controller.abort();
  }, [storageKey]);

  async function create(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setMessage('');
    try {
      const form = new FormData();
      if (file) form.set('file', file);
      const { data } = file
        ? await api.post<Draft>('/local-invoice/drafts/upload', form)
        : await api.post<Draft>('/local-invoice/drafts', { description: description.trim() });
      sessionStorage.setItem(storageKey, data.draft_id);
      setDraft(data);
    } catch (e) { setMessage(errorText(e)); }
    finally { setBusy(false); }
  }

  return <div className="space-y-5">
    {draft ? <>
      <div className="flex items-center justify-between"><h2 className="font-semibold">Позиции инвойса</h2>
        <button className="underline" onClick={() => { sessionStorage.removeItem(storageKey); setDraft(undefined); setFile(undefined); setDescription(''); setMessage(''); }}>Начать новый инвойс</button></div>
      {draft.lines.map(item => <InvoiceLine key={draft.draft_id + '-' + item.line} draftId={draft.draft_id} item={item} onSaved={saved => setDraft(current => current && ({ ...current, lines: current.lines.map(row => row.line === saved.line ? saved : row) }))} />)}
    </> : <form className="max-w-2xl space-y-4" onSubmit={create}>
      <label className="block">Файл инвойса (.xlsx)<input type="file" accept=".xlsx" disabled={busy} className="mt-1 block" onChange={e => setFile(e.target.files?.[0])} /></label>
      {!file && <label className="block">Или описание позиции<textarea className="cc-input mt-1 w-full" rows={3} value={description} onChange={e => setDescription(e.target.value)} /></label>}
      <button type="submit" disabled={busy || (!file && !description.trim())} className="cc-btn-primary">Открыть черновик</button>
    </form>}
    {message && <p role="alert">{message}</p>}
  </div>;
}

export function LocalInvoice() {
  const [user, setUser] = useState<string | null>();
  const [role, setRole] = useState<string>();
  const [available, setAvailable] = useState<boolean>();
  const [error, setError] = useState('');
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    const refresh = () => {
      setError('');
      Promise.all([api.get<{enabled: boolean}>('/local-invoice/profile', { signal: controller.signal }),
        api.get('/auth/me', { signal: controller.signal }).catch(e => {
          if (isAxiosError(e) && [401, 404, 405].includes(e.response?.status || 0)) return { data: {} };
          throw e;
        })]).then(([profile, session]) => {
        if (controller.signal.aborted) return;
        setAvailable(profile.data.enabled);
        setRole(session.data.role);
        setUser(session.data.authenticated ? session.data.username : null);
      }).catch(() => { if (!controller.signal.aborted) setError('Не удалось открыть локальный профиль инвойсов.'); });
    };
    refresh();
    const logout = () => { setUser(null); };
    window.addEventListener(loginCompleted, refresh);
    window.addEventListener(logoutCompleted, logout);
    return () => { controller.abort(); window.removeEventListener(loginCompleted, refresh); window.removeEventListener(logoutCompleted, logout); };
  }, [attempt]);
  return <section className="cc-page space-y-4">
    <h1 className="text-2xl font-semibold">Инвойс</h1>
    {error ? <p role="alert">{error} <button className="underline" onClick={() => setAttempt(attempt + 1)}>Повторить</button></p>
      : available === undefined ? <p role="status">Загрузка…</p>
      : !available ? <p>Для работы с инвойсом откройте локальный профиль с входом.{window.location.hostname === '127.0.0.1' && window.location.port === '18016' && <> <a className="underline" href="http://127.0.0.1:18018/invoice">Открыть инвойс</a></>}</p>
      : !user ? <button className="cc-btn-primary" onClick={openLoginDialog}>Войти для работы с инвойсом</button>
      : role !== 'admin' && role !== 'declarant' ? <p>Для работы с черновиком войдите как декларант или администратор.</p>
      : <><p className="text-sm text-cargo-mid">Черновик хранится на этом Mac до остановки локального профиля.</p><DraftEditor key={user} username={user} /></>}
  </section>;
}
