import React from 'react';
import { ExternalLink, Scale } from 'lucide-react';
import { api } from '../../api/client';
import { formatCode } from '../../api/tnvedCatalog';
import { getUserFacingApiError } from '../../api/error';

export type ClassificationRulingItem = {
  ruling_number: string;
  ruling_date: string;
  agency: string;
  goods_description: string;
  assigned_hs_code: string;
  rationale: string;
  source_url: string;
  is_official: boolean;
};

export type ClassificationRulingsResponse = {
  status: string;
  hs_code: string;
  official_rulings: ClassificationRulingItem[];
  reference_rulings: ClassificationRulingItem[];
  official_count: number;
  reference_count: number;
  total: number;
};

type Props = {
  hsCode: string;
};

function RulingCard({ item }: { item: ClassificationRulingItem }) {
  return (
    <article className="rounded-xl border border-slate-200 bg-white px-4 py-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <p className="text-sm font-semibold text-gray-900">{item.goods_description || 'Без описания'}</p>
        {item.ruling_number ? (
          <span className="rounded-full bg-slate-100 px-2 py-0.5 font-mono text-[11px] text-slate-700">
            {item.ruling_number}
          </span>
        ) : null}
      </div>
      <div className="mt-2 flex flex-wrap gap-2 text-[11px] text-gray-600">
        {item.agency ? <span>{item.agency}</span> : null}
        {item.ruling_date ? <span>от {item.ruling_date}</span> : null}
        {item.assigned_hs_code ? (
          <span>
            код <span className="font-mono text-indigo-800">{formatCode(item.assigned_hs_code)}</span>
          </span>
        ) : null}
      </div>
      {item.rationale ? (
        <p className="mt-2 text-xs leading-relaxed text-gray-700">{item.rationale}</p>
      ) : null}
      {item.source_url ? (
        <a
          href={item.source_url}
          target="_blank"
          rel="noopener noreferrer"
          className="mt-2 inline-flex items-center gap-1 text-[11px] text-blue-700 hover:underline"
        >
          Источник
          <ExternalLink className="h-3 w-3" aria-hidden />
        </a>
      ) : null}
    </article>
  );
}

export const ClassificationRulingsBlock: React.FC<Props> = ({ hsCode }) => {
  const [data, setData] = React.useState<ClassificationRulingsResponse | null>(null);
  const [loading, setLoading] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    if (!hsCode || hsCode.replace(/\D/g, '').length < 4) {
      setData(null);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    void api
      .get<ClassificationRulingsResponse>(`/non_tariff/classification/rulings/${hsCode.replace(/\D/g, '')}`)
      .then((res) => {
        if (!cancelled) setData(res.data);
      })
      .catch((e: unknown) => {
        if (!cancelled) {
          setData(null);
          setError(getUserFacingApiError(e, 'Не удалось загрузить решения по классификации.'));
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [hsCode]);

  if (loading) {
    return <p className="text-sm text-gray-500">Загрузка решений по классификации…</p>;
  }
  if (error) {
    return (
      <div className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">{error}</div>
    );
  }
  if (!data || data.total === 0) {
    return (
      <p className="rounded-xl border border-gray-200 bg-gray-50 px-4 py-3 text-sm text-gray-600">
        Решения по классификации для этого кода не найдены.
      </p>
    );
  }

  return (
    <div className="space-y-6">
      <section>
        <h4 className="mb-2 flex items-center gap-2 text-xs font-bold uppercase tracking-wide text-indigo-800">
          <Scale className="h-4 w-4" aria-hidden />
          Официальные решения ФТС/ЕЭК ({data.official_count})
        </h4>
        {data.official_rulings.length === 0 ? (
          <p className="text-sm text-gray-500">Официальных решений для этого кода не найдено.</p>
        ) : (
          <div className="space-y-2">
            {data.official_rulings.map((item) => (
              <RulingCard key={item.ruling_number} item={item} />
            ))}
          </div>
        )}
      </section>

      {data.reference_count > 0 ? (
        <section>
          <h4 className="mb-2 text-xs font-bold uppercase tracking-wide text-slate-600">
            Справочные привязки ({data.reference_count})
          </h4>
          <p className="mb-3 rounded-lg border border-amber-100 bg-amber-50 px-3 py-2 text-xs text-amber-900">
            Справочные привязки не являются официальными решениями таможенных органов и носят информационный характер.
          </p>
          <div className="space-y-2">
            {data.reference_rulings.map((item) => (
              <RulingCard key={item.ruling_number} item={item} />
            ))}
          </div>
        </section>
      ) : null}
    </div>
  );
};
