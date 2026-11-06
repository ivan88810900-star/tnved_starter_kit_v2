import React from 'react';
import { fetchRecoveredCode, formatCode, type RecoveredCodeDetail } from '../../api/tnvedCatalog';

type Props = { selectedCode: string; onSelectCode: (code: string) => void };

export const RecoveredCodeDetails: React.FC<Props> = ({ selectedCode, onSelectCode }) => {
  const [detail, setDetail] = React.useState<RecoveredCodeDetail | null>(null);
  const [error, setError] = React.useState(false);

  React.useEffect(() => {
    let cancelled = false;
    setDetail(null);
    setError(false);
    fetchRecoveredCode(selectedCode)
      .then((value) => { if (!cancelled) setDetail(value); })
      .catch(() => { if (!cancelled) setError(true); });
    return () => { cancelled = true; };
  }, [selectedCode]);

  if (error) return <p role="alert">Не удалось прочитать позицию восстановленного справочника.</p>;
  if (!detail) return <p role="status">Загрузка позиции…</p>;
  const sourceUrl = /^https?:\/\//i.test(detail.source_url) ? detail.source_url : undefined;

  return (
    <article className="space-y-5 text-sm text-cargo-deep" aria-label="Позиция восстановленного справочника">
      <h2 className="text-xl font-semibold" data-testid="recovered-name">{detail.name}</h2>
      <div className="rounded-lg border border-amber-300 bg-amber-50 p-3 text-amber-950">
        <p className="font-semibold">Источник не проверен</p>
        <p>Действительность кода и полнота редакции не подтверждены. Даты действия не установлены.</p>
        <p className="mt-1 font-semibold">Подтверждённые ставки отсутствуют</p>
        <p>Пошлина, НДС и другие платежи по этому набору не рассчитываются.</p>
      </div>
      <section>
        <h3 className="mb-2 font-semibold">Путь в иерархии</h3>
        <nav aria-label="Путь к позиции" className="flex flex-wrap items-center gap-2">
          {detail.breadcrumb.map((row) => /^\d+$/.test(row.hs_code) ? (
            <button key={row.hs_code} type="button" onClick={() => onSelectCode(row.hs_code)} className="rounded border border-cargo-border px-2 py-1 text-left hover:bg-cargo-navy-50">
              {formatCode(row.hs_code)} · {row.title}
            </button>
          ) : <span key={row.hs_code}>Раздел {row.hs_code} · {row.title}</span>)}
        </nav>
        <ol className="mt-3 list-inside list-decimal space-y-1" aria-label="Полный путь из источника">
          {detail.path.map((label, index) => <li key={index}>{label}</li>)}
        </ol>
      </section>
      <section>
        <h3 className="mb-2 font-semibold">Дочерние узлы</h3>
        {detail.children.length ? (
          <ul className="space-y-1">
            {detail.children.map((row) => (
              <li key={row.code}><button type="button" onClick={() => onSelectCode(row.code)} className="w-full rounded border border-cargo-border px-3 py-2 text-left hover:bg-cargo-navy-50">{formatCode(row.code)} · {row.name}</button></li>
            ))}
          </ul>
        ) : <p>Дочерних узлов нет.</p>}
      </section>
      <section className="border-t border-cargo-border pt-3 text-xs text-cargo-mid">
        <p>Редакция: {detail.edition_id}; страница источника: {detail.page}.</p>
        {sourceUrl ? <a href={sourceUrl} target="_blank" rel="noreferrer" className="underline">Открыть источник</a> : <p>Ссылка на источник отсутствует.</p>}
      </section>
    </article>
  );
};
