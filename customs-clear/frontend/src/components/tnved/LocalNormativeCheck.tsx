import { isAxiosError } from 'axios';
import { useState } from 'react';
import { api } from '../../api/client';

type ArchiveAct = { act_code: string; short_name: string; source_revision: string };
type Block = { hs_code: string; assessment: string; empty_message: string; notes: string[]; archive_acts: ArchiveAct[] };
type Reply = { items: { normative_block: Block }[] };

export function LocalNormativeCheck({ code }: { code: string }) {
  const [busy, setBusy] = useState(false);
  const [block, setBlock] = useState<Block>();
  const [message, setMessage] = useState('');

  async function check() {
    setBusy(true);
    setBlock(undefined);
    setMessage('');
    try {
      const { data } = await api.post<Reply>('/non_tariff/normative-block', { items: [{ hs_code: code }] });
      const result = data.items[0]?.normative_block;
      if (result?.hs_code !== code || result.assessment !== 'INSUFFICIENT_EVIDENCE') {
        throw new Error('Unexpected local assessment');
      }
      setBlock(result);
    } catch (error) {
      const status = isAxiosError(error) ? error.response?.status : undefined;
      setMessage(status === 401 ? 'Войдите в систему и повторите проверку.'
        : status === 503 ? 'Проверка недоступна в этом профиле.'
        : 'Не удалось получить результат. Повторите проверку.');
    } finally {
      setBusy(false);
    }
  }

  return <div className="space-y-2">
    <button type="button" disabled={busy} onClick={check} className="rounded border px-3 py-1">
      {busy ? 'Идёт проверка…' : 'Проверить требования к товару'}
    </button>
    <div role="status" className="space-y-1">
      {message && <p>{message}</p>}
      {block && <>
        <p className="font-medium">{block.empty_message}</p>
        {block.notes.map(note => <p key={note}>{note}</p>)}
        {block.archive_acts.length > 0 && <ul>{block.archive_acts.map(act =>
          <li key={act.act_code}>Архивная карточка {act.act_code} · {act.short_name} · {act.source_revision}</li>)}</ul>}
      </>}
    </div>
  </div>;
}
