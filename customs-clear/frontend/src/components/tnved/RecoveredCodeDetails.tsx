import React from 'react';
import { fetchRecoveredCode, formatCode, type RecoveredCodeDetail } from '../../api/tnvedCatalog';

type Props = { selectedCode: string; onSelectCode: (code: string) => void };

function OriginalFragment({ url, page }: { url: string; page: number }) {
  const [failed, setFailed] = React.useState(false);
  return <figure className="rounded border border-cargo-border bg-white p-2">
    {failed ? <p role="alert">Фрагмент оригинала не загрузился. Точное оформление не подтверждено.</p> :
      <a href={url} target="_blank" rel="noreferrer"><img data-testid="source-original-fragment" src={url} alt={`Исходная строка PDF, страница ${page}; индексы и ссылки показаны как напечатано`} onError={() => setFailed(true)} className="h-auto max-w-full" /></a>}
    <figcaption className="mt-1 text-xs text-cargo-mid">Оригинальное оформление · страница {page}. Открыть изображение для увеличения.</figcaption>
  </figure>;
}

export const RecoveredCodeDetails: React.FC<Props> = ({ selectedCode, onSelectCode }) => {
  const [detail, setDetail] = React.useState<RecoveredCodeDetail | null>(null);
  const [error, setError] = React.useState(false);
  const [copied, setCopied] = React.useState(false);

  React.useEffect(() => {
    let cancelled = false;
    setDetail(null);
    setError(false);
    setCopied(false);
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
      {detail.presentation?.reasons.includes('source_small_glyphs') ? <p className="text-xs font-medium text-amber-950">Поисковая подпись: оформление упрощено. Точные индексы и ссылки показаны в оригинале ниже.</p> : null}
      <h2 className="text-xl font-semibold" data-testid="recovered-name">{detail.name}</h2>
      {detail.code && detail.selectable !== false ? <div className="flex flex-wrap items-center gap-3"><span className="font-mono">Печатный код: {detail.printed_code || detail.code}</span><button type="button" className="rounded border border-cargo-border px-3 py-1" onClick={() => { void navigator.clipboard.writeText(detail.code).then(() => setCopied(true)).catch(() => setCopied(false)); }}>{copied ? 'Код скопирован' : 'Копировать код'}</button></div> : <p>{detail.kind === 'reserved' ? 'Неактивная отметка источника. Код для расчёта не выбирается.' : 'Бескодовая строка источника. Товарный код не присваивается.'}</p>}
      {detail.navigation_alias ? <p className="rounded border border-cargo-border p-2">Переход по позиции {detail.navigation_alias.heading_code} ведёт к совмещённой печатной строке {detail.navigation_alias.printed_code}. Полный код строки: {detail.navigation_alias.resolved_code}.</p> : null}
      <div className="rounded-lg border border-amber-300 bg-amber-50 p-3 text-amber-950">
        <p className="font-semibold">Источник не проверен</p>
        <p>Действительность кода и полнота редакции не подтверждены. Даты действия не установлены.</p>
        <p className="mt-1 font-semibold">Подтверждённые ставки отсутствуют</p>
        <p>Пошлина, НДС и другие платежи по этому набору не рассчитываются.</p>
      </div>
      {detail.presentation ? <section aria-label="Оригинальное оформление источника" className="space-y-3 rounded border border-amber-300 p-3">
        <h3 className="font-semibold">Оригинальное оформление</h3>
        <p data-testid="presentation-limitation" className="text-amber-950">{detail.presentation.notice}</p>
        {detail.presentation.fragments.map(fragment => <OriginalFragment key={fragment.url} url={fragment.url} page={fragment.page} />)}
        {detail.presentation.spacing_difference ? <div data-testid="spacing-difference" className="space-y-2 border-t border-cargo-border pt-3">
          <p className="font-semibold">Различие пробелов · ограничение, не согласовано автоматически</p>
          <p><strong>Исходное написание:</strong> {detail.presentation.spacing_difference.source_text}</p>
          <p><strong>Отображаемое написание:</strong> {detail.presentation.spacing_difference.display_text}</p>
          <p><strong>Оценка влияния:</strong> {detail.presentation.spacing_difference.impact}</p>
          <p className="text-xs text-cargo-mid">Текстовая транскрипция сверяется с показанным оригиналом; правовое значение не устанавливается.</p>
        </div> : null}
        <p className="break-all text-[10px] text-cargo-mid">SHA-256 исходного PDF: {detail.presentation.source_sha256}</p>
      </section> : null}
      <section>
        <h3 className="mb-2 font-semibold">Путь в иерархии</h3>
        <nav aria-label="Путь к позиции" className="flex flex-wrap items-center gap-2">
          {detail.breadcrumb.map((row) => /^\d+$/.test(row.hs_code) || row.is_codeless ? (
            <button key={row.node_id || row.hs_code} type="button" onClick={() => onSelectCode(row.node_id || row.hs_code)} className="rounded border border-cargo-border px-2 py-1 text-left hover:bg-cargo-navy-50">
              {row.is_codeless ? 'Без кода' : formatCode(row.hs_code)} · {row.title}
            </button>
          ) : <span key={row.node_id || row.hs_code}>{row.kind === 'reserved' ? 'Отметка источника' : `Раздел ${row.hs_code}`} · {row.title}</span>)}
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
              <li key={row.node_id || row.code}>{row.kind === 'reserved' ? <div data-testid="reserved-marker-card" className="rounded border border-cargo-border bg-slate-50 p-2 text-xs">
                <p>{row.display_code} · Неактивная отметка источника</p><p>{row.format_notice}</p>
                {row.source_fragment_url ? <a href={row.source_fragment_url} target="_blank" rel="noreferrer" className="underline">Фрагмент оригинала · стр. {row.source_page}</a> : null}
                {row.source_url && /^https?:\/\//i.test(row.source_url) ? <a href={`${row.source_url}#page=${row.source_page}`} target="_blank" rel="noreferrer" className="ml-3 underline">Ссылка на PDF</a> : null}
              </div> : <button type="button" onClick={() => onSelectCode(row.node_id || row.code)} className="w-full rounded border border-cargo-border px-3 py-2 text-left hover:bg-cargo-navy-50">{row.is_codeless ? 'Без кода' : row.display_code || formatCode(row.code)} · {row.name}{row.format_notice ? ' · Оформление: см. оригинал' : ''}</button>}</li>
            ))}
          </ul>
        ) : <p>Дочерних узлов нет.</p>}
      </section>
      <section className="border-t border-cargo-border pt-3 text-xs text-cargo-mid">
        <p>Редакция: {detail.edition_id}; {detail.page == null ? 'официальный указатель' : `страница источника: ${detail.page}`}.</p>
        {sourceUrl ? <a href={sourceUrl} target="_blank" rel="noreferrer" className="underline">Открыть источник</a> : <p>Ссылка на источник отсутствует.</p>}
      </section>
    </article>
  );
};
