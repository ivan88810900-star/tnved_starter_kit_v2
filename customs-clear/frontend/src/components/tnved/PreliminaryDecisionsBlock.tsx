import React from 'react';
import { ExternalLink, Scale } from 'lucide-react';
import type {
  TnvedClassificationDecision,
  TnvedPreliminaryDecisionItem,
  TnvedPreliminaryDecisionsBlock,
} from '../../api/tnvedCatalog';
import { formatCode } from '../../api/tnvedCatalog';

type Props = {
  block: TnvedPreliminaryDecisionsBlock | null | undefined;
  loading?: boolean;
};

function truncate(text: string, max = 280): string {
  const t = text.trim();
  if (t.length <= max) return t;
  return `${t.slice(0, max - 1)}…`;
}

function ClassificationCard({ item }: { item: TnvedClassificationDecision }) {
  const title = item.target_entity || item.product_name || 'Без наименования';
  return (
    <article className="rounded-xl border border-indigo-100 bg-indigo-50/40 px-4 py-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="flex items-center gap-2">
          <Scale className="h-4 w-4 shrink-0 text-indigo-700" aria-hidden />
          <p className="text-sm font-semibold text-gray-900">{title}</p>
        </div>
        {item.decision_number ? (
          <span className="rounded-full bg-white px-2 py-0.5 font-mono text-[11px] text-indigo-800 ring-1 ring-indigo-100">
            № {item.decision_number}
          </span>
        ) : null}
      </div>
      <div className="mt-2 flex flex-wrap gap-2 text-[11px] text-gray-600">
        {item.issue_date ? <span>от {item.issue_date}</span> : null}
        {item.hs_code ? (
          <span>
            код <span className="font-mono text-indigo-800">{formatCode(item.hs_code)}</span>
          </span>
        ) : null}
        <span className="rounded bg-white/80 px-1.5 py-0.5 uppercase tracking-wide text-gray-500">ФТС</span>
      </div>
      {item.description ? (
        <p className="mt-2 whitespace-pre-wrap text-sm leading-relaxed text-gray-700">
          {truncate(item.description)}
        </p>
      ) : null}
    </article>
  );
}

function PreliminaryCard({ item }: { item: TnvedPreliminaryDecisionItem }) {
  return (
    <article className="rounded-xl border border-slate-200 bg-slate-50 px-4 py-3">
      <div className="flex flex-wrap items-center gap-2 text-[11px] text-gray-600">
        {item.hs_code ? (
          <span>
            код <span className="font-mono text-slate-800">{formatCode(item.hs_code)}</span>
          </span>
        ) : null}
        <span className="rounded bg-white px-1.5 py-0.5 uppercase tracking-wide text-gray-500">
          {item.source || 'ifcg'}
        </span>
      </div>
      <p className="mt-2 whitespace-pre-wrap text-sm leading-relaxed text-gray-800">
        {truncate(item.description || 'Описание отсутствует')}
      </p>
    </article>
  );
}

export const PreliminaryDecisionsBlock: React.FC<Props> = ({ block, loading = false }) => {
  if (loading) {
    return (
      <div className="rounded-xl border border-gray-200 bg-gray-50 px-4 py-3 text-sm text-gray-500">
        Загрузка предварительных решений…
      </div>
    );
  }

  if (!block) {
    return (
      <div className="rounded-xl border border-dashed border-gray-200 bg-gray-50 px-4 py-3 text-sm italic text-gray-500">
        Данные о предварительных решениях недоступны.
      </div>
    );
  }

  const classification = block.classification_decisions ?? [];
  const preliminary = block.preliminary_decisions ?? [];
  const hasAny = (block.total_count ?? 0) > 0 || classification.length > 0 || preliminary.length > 0;

  if (!hasAny) {
    return (
      <div className="rounded-xl border border-dashed border-gray-200 bg-gray-50 px-4 py-4 text-sm text-gray-600">
        <p className="font-medium text-gray-700">Предварительные решения не найдены</p>
        <p className="mt-1 text-gray-500">
          {block.empty_message ||
            'По этому коду в базе нет связанных предварительных или классификационных решений.'}
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {classification.length > 0 ? (
        <section>
          <h4 className="mb-2 text-[11px] font-bold uppercase tracking-wide text-indigo-800">
            Решения ФТС по классификации
          </h4>
          <div className="space-y-3">
            {classification.map((item) => (
              <ClassificationCard key={`cls-${item.id}`} item={item} />
            ))}
          </div>
        </section>
      ) : null}

      {preliminary.length > 0 ? (
        <section>
          <h4 className="mb-2 text-[11px] font-bold uppercase tracking-wide text-slate-700">
            Прочие предварительные решения
          </h4>
          <div className="space-y-3">
            {preliminary.map((item) => (
              <PreliminaryCard key={`pre-${item.id}`} item={item} />
            ))}
          </div>
        </section>
      ) : null}

      <p className="text-[11px] text-gray-500">
        Показаны решения, привязанные к коду или его префиксу. Для полной практики см.{' '}
        <a
          href="https://customs.gov.ru/"
          target="_blank"
          rel="noreferrer"
          className="inline-flex items-center gap-0.5 text-indigo-700 hover:underline"
        >
          портал ФТС
          <ExternalLink className="h-3 w-3" aria-hidden />
        </a>
        .
      </p>
    </div>
  );
};
