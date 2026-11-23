import { isAxiosError } from 'axios';
import React from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { fetchRecoveredCode, formatCode, isRecoveredProduct, type RecoveredCodeDetail } from '../api/tnvedCatalog';
import { getUserFacingApiError } from '../api/error';
import { SmartPaymentsBlock } from '../components/payments/SmartPaymentsBlock';

function ProductPreview({ code }: { code: string }) {
  const [detail, setDetail] = React.useState<RecoveredCodeDetail>();
  const [error, setError] = React.useState('');
  React.useEffect(() => {
    let current = true;
    fetchRecoveredCode(code)
      .then(row => { if (current) setDetail(row); })
      .catch(reason => {
        if (!current) return;
        const status = isAxiosError(reason) ? reason.response?.status : undefined;
        if (status === 404) setError('Код не найден в локальном справочнике.');
        else if (status === 503) setError('Локальный справочник временно недоступен.');
        else setError(getUserFacingApiError(reason, 'Не удалось открыть позицию справочника.'));
      });
    return () => { current = false; };
  }, [code]);

  return <section className="space-y-4">
    <Link className="text-sm text-cargo-trust underline" to={detail ? `/tnved?code=${code}` : '/tnved'}>
      {detail ? 'Вернуться к карточке' : 'Открыть справочник'}
    </Link>
    {error ? <p role="alert">{error}</p> : !detail ? <p role="status">Загрузка позиции…</p> : <>
      <h2 className="font-semibold">{formatCode(detail.code)} · {detail.name}</h2>
      {detail.code === code && isRecoveredProduct(detail)
        ? <SmartPaymentsBlock hsCode={code} description={detail.name} localPreview />
        : <p>Выберите конечную товарную позицию в справочнике.</p>}
    </>}
  </section>;
}

export function LocalCatalogCalculator() {
  const [params] = useSearchParams();
  const code = (params.get('code') ?? '').replace(/\s/g, '');
  if (!/^\d{2,10}$/.test(code)) return <Link className="text-cargo-trust underline" to="/tnved">Выбрать товар в справочнике</Link>;
  return <ProductPreview key={code} code={code} />;
}
