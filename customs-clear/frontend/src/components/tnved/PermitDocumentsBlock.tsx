import React, { useState } from 'react';
import { api } from '../../api/client';
import { getUserFacingApiError } from '../../api/error';
import type { NormativeRequirementsBlockData } from '../../types/api.types';
import { formatUnsafeExternalUrlEvidence, getSafeExternalUrl } from '../../utils/externalUrl';
import { describePermit } from '../../utils/permitVocabulary';

const TROIS_OFFICIAL = 'https://customs.gov.ru/registers/objects-intellectual-property';
const FSA_CERT_SEARCH = 'https://pub.fsa.gov.ru/rss/certificate';
const FSA_DECL_SEARCH = 'https://pub.fsa.gov.ru/rds/declaration';

type Props = {
  hsCode: string;
  productName?: string;
  normativeBlock: NormativeRequirementsBlockData | null | undefined;
};

type VerifyRow = {
  status?: string;
  holder?: string | null;
  manual_check_url?: string;
  registry_link?: string;
  fallback_note?: string;
  registry_source?: string;
  data_as_of?: string;
  freshness_label?: string;
};

export function PermitDocumentsVerificationLink({
  manualCheckUrl,
  registryLink,
}: {
  manualCheckUrl: unknown;
  registryLink: unknown;
}) {
  const candidates = [manualCheckUrl, registryLink];
  const safeUrl = candidates.map(getSafeExternalUrl).find((value): value is string => Boolean(value)) ?? null;
  const rejectedEvidence = Array.from(new Set(
    candidates
      .filter((value): value is string => typeof value === 'string' && value.length > 0 && !getSafeExternalUrl(value))
      .map((value) => formatUnsafeExternalUrlEvidence(value))
      .filter(Boolean),
  ));

  if (!safeUrl && rejectedEvidence.length === 0) return null;
  return (
    <>
      {safeUrl ? (
        <a href={safeUrl} target="_blank" rel="noopener noreferrer" className="mt-1 inline-block text-indigo-600 hover:underline">
          Проверить на ФСА →
        </a>
      ) : null}
      {rejectedEvidence.map((evidence) => (
        <span key={evidence} data-testid="unsafe-permit-verification-url-evidence" className="mt-1 block text-slate-500">
          Адрес проверки (ссылка недоступна): <span className="break-all font-mono">{evidence}</span>
        </span>
      ))}
    </>
  );
}

export function PermitDocumentsBlock({ hsCode, productName, normativeBlock }: Props) {
  const [certNumber, setCertNumber] = useState('');
  const [verifyLoading, setVerifyLoading] = useState(false);
  const [verifyResult, setVerifyResult] = useState<VerifyRow | null>(null);
  const [verifyError, setVerifyError] = useState('');

  const required = normativeBlock?.required_documents ?? [];
  const permits = required.filter((d) => ['СС', 'ДС', 'СГР'].includes(String(d.permit_type || '').toUpperCase()));
  const hasAdvisoryOrClarificationSignals = Boolean(
    normativeBlock?.advisory_requirements?.length
      || normativeBlock?.measure_families?.some(
        (family) => family.status === 'needs_clarification'
          || family.status === 'legacy_signal'
          || (family.signals_count ?? 0) > 0,
      ),
  );

  const runVerify = async () => {
    if (!certNumber.trim()) return;
    setVerifyLoading(true);
    setVerifyError('');
    setVerifyResult(null);
    try {
      const { data } = await api.post<{ items: VerifyRow[] }>('/permits/verify', {
        permits: [{ type: 'СС', number: certNumber.trim() }],
        hs_code: hsCode.replace(/\D/g, ''),
        enrich: true,
      });
      setVerifyResult(data.items?.[0] ?? null);
    } catch (e) {
      setVerifyError(getUserFacingApiError(e, 'Не удалось проверить документ'));
    } finally {
      setVerifyLoading(false);
    }
  };

  return (
    <section className="rounded-xl border border-slate-200 bg-white p-4 text-sm shadow-sm">
      <h3 className="mb-3 text-xs font-bold uppercase tracking-wide text-slate-600">Разрешительные документы</h3>

      <p className="mb-3 text-[11px] leading-relaxed text-slate-500">
        Система определяет необходимость документа по ТН ВЭД и ТР ТС. Наличие конкретного сертификата проверяется через
        реестр ФСА.
      </p>

      {!normativeBlock ? (
        <p className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-[12px] text-amber-900">
          Нормативный блок не вернул подтверждённых данных. Проверьте требования на вкладке «Документы».
        </p>
      ) : permits.length === 0 && hasAdvisoryOrClarificationSignals ? (
        <p className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-[12px] text-amber-900">
          Обязательных документов СС/ДС/СГР в брокерском списке нет. При этом выявлены нетарифные сигналы —
          требуется уточнить их применимость на вкладке «Документы».
        </p>
      ) : permits.length === 0 ? (
        <p className="text-[12px] text-emerald-700">✅ Специальных разрешительных документов (СС/ДС/СГР) по нормативному блоку не выявлено.</p>
      ) : (
        <ul className="mb-3 space-y-2">
          {permits.map((doc, i) => {
            const p = describePermit(doc.permit_type, 'mandatory');
            return (
              <li key={i} className="rounded-lg border border-amber-200 bg-amber-50/80 px-3 py-2 text-[12px]">
                <span className="font-semibold text-amber-900">⚠️ Нужен {p.label}</span>
                {doc.tr_ts ? (
                  <span className="ml-2 text-amber-800">
                    ТР ТС {doc.tr_ts}
                    {doc.tr_ts_full_name ? ` (${doc.tr_ts_full_name})` : ''}
                  </span>
                ) : null}
                {doc.note ? <p className="mt-1 text-amber-800">{doc.note}</p> : null}
              </li>
            );
          })}
        </ul>
      )}

      <div className="flex flex-wrap gap-2 text-[12px]">
        <a href={FSA_CERT_SEARCH} target="_blank" rel="noopener noreferrer" className="cc-btn-ghost text-[11px]">
          Поиск в реестре ФСА (СС) →
        </a>
        <a href={FSA_DECL_SEARCH} target="_blank" rel="noopener noreferrer" className="cc-btn-ghost text-[11px]">
          Поиск в реестре ФСА (ДС) →
        </a>
      </div>

      <div className="mt-3 space-y-2 border-t border-slate-100 pt-3">
        <p className="text-[11px] font-medium text-slate-600">Проверить номер сертификата</p>
        <div className="flex flex-wrap gap-2">
          <input
            value={certNumber}
            onChange={(e) => setCertNumber(e.target.value)}
            placeholder="РОСС CN … / ЕАЭС …"
            className="cc-input min-w-[200px] flex-1 font-mono text-[12px]"
          />
          <button type="button" className="cc-btn-primary text-[12px]" disabled={verifyLoading} onClick={() => void runVerify()}>
            {verifyLoading ? 'Проверка…' : 'Проверить'}
          </button>
        </div>
        {verifyError ? <p className="text-[11px] text-red-600">{verifyError}</p> : null}
        {verifyResult ? (
          <div className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-[11px]">
            Статус: <strong>{verifyResult.status || '—'}</strong>
            {verifyResult.holder ? ` · ${verifyResult.holder}` : ''}
            {verifyResult.freshness_label ? (
              <p className="mt-1 text-slate-600">{verifyResult.freshness_label}</p>
            ) : verifyResult.data_as_of ? (
              <p className="mt-1 text-slate-600">Проверка по реестру ФСА (данные на {verifyResult.data_as_of})</p>
            ) : null}
            {verifyResult.registry_source ? (
              <p className="text-slate-500">Источник: {verifyResult.registry_source}</p>
            ) : null}
            {verifyResult.fallback_note ? <p className="mt-1 text-amber-700">{verifyResult.fallback_note}</p> : null}
            {(verifyResult.manual_check_url || verifyResult.registry_link) && (
              <PermitDocumentsVerificationLink
                manualCheckUrl={verifyResult.manual_check_url}
                registryLink={verifyResult.registry_link}
              />
            )}
          </div>
        ) : null}
      </div>

      <div className="mt-3 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-[11px] text-slate-600">
        <p className="font-medium text-slate-700">⚠️ ТРОИС: проверьте бренд</p>
        {productName ? (
          <p className="mt-0.5">
            Товар: <span className="text-slate-800">{productName}</span>
          </p>
        ) : null}
        <p className="mt-1 text-slate-500">
          Проверка по локальной копии реестра ТРОИС (открытые данные ФТС). Для точной проверки используйте официальный реестр.
        </p>
        <a href={TROIS_OFFICIAL} target="_blank" rel="noopener noreferrer" className="mt-1 inline-block text-indigo-600 hover:underline">
          Проверить в реестре ТРОИС →
        </a>
      </div>
    </section>
  );
}
