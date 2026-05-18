import React from 'react';
import axios from 'axios';
import { api } from '../../api/client';
import type { TnvedCommodityDetail, TnvedImportReference } from '../../api/tnvedCatalog';
import { fetchCommodityByCode, fetchTnvedImportReference, formatCode, isFullTnvedCode } from '../../api/tnvedCatalog';
import {
  hasVisibleNonTariffContent,
  pickNonTariffVisibleFields,
  sanitizeNonTariffLine,
} from '../../utils/nonTariffUiFilter';
import { formatTnvedCommodityName } from '../../utils/tnvedDisplayText';
import { formatLinks, splitReadableParagraphs } from '../../utils/formatLinks';
import { getUserFacingApiError } from '../../api/error';
import { useAssistantSurfaceVisible } from '../../context/ClientCapabilitiesContext';
import { FileCheck2, FolderKanban, ShieldCheck } from 'lucide-react';

const REFERENCE_NT_SECTION_TITLES = new Set([
  'Запреты и лицензии',
  'Разрешительные документы',
  'Прочие особенности',
]);

type Props = {
  selectedCode: string | null;
};

export const ProductDetails: React.FC<Props> = ({ selectedCode }) => {
  type ChatMsg = { role: 'user' | 'assistant'; text: string };
  const [detail, setDetail] = React.useState<TnvedCommodityDetail | null>(null);
  const [loading, setLoading] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [chatInput, setChatInput] = React.useState('');
  const [chatLoading, setChatLoading] = React.useState(false);
  const [chatMessages, setChatMessages] = React.useState<ChatMsg[]>([]);
  const [chatError, setChatError] = React.useState<string | null>(null);
  const [reference, setReference] = React.useState<TnvedImportReference | null>(null);
  const [referenceLoading, setReferenceLoading] = React.useState(false);
  const [activeTab, setActiveTab] = React.useState<'payments' | 'nonTariff' | 'notes'>('payments');
  const assistantVisible = useAssistantSurfaceVisible();

  const chatStorageKey = React.useMemo(
    () => (detail?.code ? `ai_chat_${detail.code}` : null),
    [detail?.code],
  );

  React.useEffect(() => {
    if (!selectedCode || !isFullTnvedCode(selectedCode)) {
      setDetail(null); setError(null); setLoading(false); return;
    }
    let cancelled = false;
    setLoading(true); setError(null);
    fetchCommodityByCode(selectedCode)
      .then((d) => { if (!cancelled) setDetail(d); })
      .catch((e: unknown) => {
        if (!cancelled) {
          const msg =
            axios.isAxiosError(e) && e.response?.data && typeof e.response.data === 'object' && 'detail' in e.response.data
              ? String((e.response.data as { detail?: unknown }).detail)
              : 'Не удалось загрузить позицию';
          setError(msg); setDetail(null);
        }
      })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [selectedCode]);

  React.useEffect(() => {
    if (!detail?.code) {
      setReference(null);
      setReferenceLoading(false);
      return;
    }
    let cancelled = false;
    setReferenceLoading(true);
    fetchTnvedImportReference(detail.code)
      .then((ref) => {
        if (!cancelled) setReference(ref);
      })
      .catch(() => {
        if (!cancelled) setReference(null);
      })
      .finally(() => {
        if (!cancelled) setReferenceLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [detail?.code]);

  React.useEffect(() => {
    setChatInput('');
    setChatError(null);
    setChatLoading(false);
    if (!chatStorageKey) {
      setChatMessages([]);
      return;
    }
    try {
      const raw = localStorage.getItem(chatStorageKey);
      if (!raw) {
        setChatMessages([]);
        return;
      }
      const parsed = JSON.parse(raw);
      if (Array.isArray(parsed)) {
        const sanitized = parsed
          .filter((m) => m && (m.role === 'user' || m.role === 'assistant') && typeof m.text === 'string')
          .map((m) => ({ role: m.role as 'user' | 'assistant', text: String(m.text) }));
        setChatMessages(sanitized);
      } else {
        setChatMessages([]);
      }
    } catch {
      setChatMessages([]);
    }
  }, [chatStorageKey]);

  React.useEffect(() => {
    if (!chatStorageKey) return;
    try {
      localStorage.setItem(chatStorageKey, JSON.stringify(chatMessages));
    } catch {
      // ignore quota/storage errors
    }
  }, [chatMessages, chatStorageKey]);

  React.useEffect(() => {
    setActiveTab('payments');
  }, [selectedCode]);

  // Пусто — приглашение
  if (!selectedCode) {
    return (
      <div className="flex min-h-[300px] flex-col items-center justify-center rounded-xl border border-dashed border-gray-300 bg-white px-8 py-16 text-center">
        <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.2" className="mx-auto mb-4 text-gray-300" aria-hidden>
          <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" /><polyline points="14 2 14 8 20 8" />
          <line x1="16" y1="13" x2="8" y2="13" /><line x1="16" y1="17" x2="8" y2="17" /><polyline points="10 9 9 9 8 9" />
        </svg>
        <p className="text-base font-medium text-gray-500">Выберите код товара в дереве слева</p>
        <p className="mt-1 text-sm text-gray-400">Кликните на любой 10-значный код</p>
      </div>
    );
  }

  if (loading) {
    return (
      <div className="flex min-h-[200px] items-center justify-center bg-white text-sm text-gray-500">
        Загрузка позиции…
      </div>
    );
  }

  if (error) {
    return (
      <div className="rounded-lg border border-red-200 bg-red-50 px-5 py-4 text-sm text-red-800">
        {error}
      </div>
    );
  }

  if (!detail) return null;

  const name = formatTnvedCommodityName((detail.name ?? detail.description ?? '').trim());
  const hasName = name.trim().length > 0;
  const duty = (detail.import_duty ?? '').trim();
  const dutyLabel = duty || '0 / См. примечания';
  const notes = (detail.notes ?? detail.notes_combined ?? '').trim();
  const unit = (detail.unit ?? '').trim();
  const nonTariffMeasures = (detail.non_tariff_measures ?? []).filter(hasVisibleNonTariffContent);
  const intellectualProperties = detail.intellectual_properties ?? [];

  const sendQuestion = async () => {
    const q = chatInput.trim();
    if (!q || !detail) return;
    setChatError(null);
    setChatLoading(true);
    setChatMessages((prev) => [...prev, { role: 'user', text: q }]);
    setChatInput('');
    try {
      const { data } = await api.post<{ status: string; answer: string }>('/ai/ask', {
        question: q,
        code: detail.code,
        notes,
      });
      setChatMessages((prev) => [...prev, { role: 'assistant', text: data.answer || 'Нет ответа от ассистента.' }]);
    } catch (e: unknown) {
      setChatError(getUserFacingApiError(e, 'Не удалось получить ответ. Попробуйте позже.'));
    } finally {
      setChatLoading(false);
    }
  };

  const clearChat = () => {
    setChatMessages([]);
    setChatError(null);
    if (!chatStorageKey) return;
    try {
      localStorage.removeItem(chatStorageKey);
    } catch {
      // ignore storage errors
    }
  };

  const getMeasureCardClass = (measureType: string): string => {
    if (measureType === 'ban') {
      return 'border-red-200 bg-red-50';
    }
    if (measureType === 'license' || measureType === 'certificate') {
      return 'border-amber-200 bg-amber-50';
    }
    return 'border-blue-200 bg-blue-50';
  };

  const getMeasureTypeLabel = (measureType: string): string => {
    if (measureType === 'ban') return 'Ограничение';
    if (measureType === 'license') return 'Лицензирование';
    if (measureType === 'certificate') return 'Сертификация';
    if (measureType === 'vet_control') return 'Ветконтроль';
    if (measureType === 'phyto_control') return 'Фитоконтроль';
    return 'Нетарифная мера';
  };

  const getMeasureIcon = (measureType: string) => {
    if (measureType === 'license' || measureType === 'certificate') return <FileCheck2 className="h-4 w-4 text-blue-700" aria-hidden />;
    if (measureType === 'ban') return <ShieldCheck className="h-4 w-4 text-red-700" aria-hidden />;
    return <FolderKanban className="h-4 w-4 text-slate-700" aria-hidden />;
  };

  const renderLinkedParagraphs = (
    text: string,
    keyPrefix: string,
    emptyLabel = 'Описание отсутствует',
  ): React.ReactNode => {
    const paragraphs = splitReadableParagraphs(text);
    if (paragraphs.length === 0) {
      return <p className="text-sm italic text-gray-400">{emptyLabel}</p>;
    }
    return (
      <div className="space-y-1.5">
        {paragraphs.map((line, idx) => (
          <p key={`${keyPrefix}-${idx}`} className="whitespace-pre-wrap break-words text-sm leading-relaxed text-gray-800">
            {formatLinks(line, `${keyPrefix}-${idx}`)}
          </p>
        ))}
      </div>
    );
  };

  const paymentSections = (reference?.sections ?? []).filter((s) => /пошлин|ндс|акциз/i.test(s.title));

  return (
    <div className="space-y-6 bg-white text-gray-900">
      {/* Заголовок */}
      <header className="border-b border-gray-200 pb-6">
        <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-gray-400">Код ТН ВЭД</p>
        <div className="font-mono text-4xl font-bold tracking-tight text-blue-700 leading-none">
          {formatCode(detail.code)}
        </div>
        {hasName ? (
          <h2 className="mt-4 text-lg font-medium leading-snug tracking-normal text-gray-900 antialiased font-sans">
            {name}
          </h2>
        ) : (
          <p className="mt-4 text-sm italic text-gray-400">Описание отсутствует</p>
        )}
        {unit && (
          <p className="mt-2 text-sm text-gray-500">
            Единица измерения: <span className="font-medium text-gray-700">{unit}</span>
          </p>
        )}
        <div className="mt-3 flex flex-wrap gap-2">
          <span className="inline-flex rounded-full bg-blue-100 px-2.5 py-1 text-[11px] font-semibold text-blue-800">
            Пошлина: {dutyLabel}
          </span>
          <span className="inline-flex rounded-full bg-emerald-100 px-2.5 py-1 text-[11px] font-semibold text-emerald-800">
            НДС: 20%
          </span>
          {intellectualProperties.length > 0 ? (
            <span className="inline-flex rounded-full bg-amber-100 px-2.5 py-1 text-[11px] font-semibold text-amber-800">
              ТРОИС: есть совпадения
            </span>
          ) : null}
        </div>
      </header>
      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          className={`rounded-lg border px-3 py-2 text-sm font-medium transition ${
            activeTab === 'payments'
              ? 'border-blue-200 bg-blue-50 text-blue-800'
              : 'border-slate-200 bg-white text-slate-600 hover:bg-slate-50'
          }`}
          onClick={() => setActiveTab('payments')}
        >
          Платежи
        </button>
        <button
          type="button"
          className={`rounded-lg border px-3 py-2 text-sm font-medium transition ${
            activeTab === 'nonTariff'
              ? 'border-blue-200 bg-blue-50 text-blue-800'
              : 'border-slate-200 bg-white text-slate-600 hover:bg-slate-50'
          }`}
          onClick={() => setActiveTab('nonTariff')}
        >
          Нетарифное регулирование
        </button>
        <button
          type="button"
          className={`rounded-lg border px-3 py-2 text-sm font-medium transition ${
            activeTab === 'notes'
              ? 'border-blue-200 bg-blue-50 text-blue-800'
              : 'border-slate-200 bg-white text-slate-600 hover:bg-slate-50'
          }`}
          onClick={() => setActiveTab('notes')}
        >
          Примечания и документы
        </button>
      </div>

      {activeTab === 'payments' ? (
        <div className="space-y-4">
          <section className="rounded-xl border-2 border-blue-100 bg-blue-50 px-5 py-4">
            <p className="mb-1 text-xs font-bold uppercase tracking-wide text-blue-700">Ставка ввозной пошлины</p>
            <p className="font-mono text-2xl font-bold text-blue-900">{dutyLabel}</p>
          </section>

          <section className="rounded-xl border border-gray-200 bg-gray-50 px-4 py-4">
            <h3 className="mb-2 text-xs font-bold uppercase tracking-wide text-gray-600">НДС и акциз</h3>
            {referenceLoading ? (
              <p className="text-sm text-gray-500">Подготовка данных по платежам…</p>
            ) : paymentSections.length > 0 ? (
              <div className="space-y-3">
                {paymentSections.map((s, idx) => (
                  <article key={`${s.title}-${idx}`} className="rounded-lg border border-gray-200 bg-white px-3 py-2">
                    <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-gray-600">{s.title}</p>
                    {(s.items ?? []).length > 0 ? (
                      <div className="space-y-1.5">
                        {(s.items ?? []).map((line, lineIdx) => (
                          <p key={`${s.title}-${lineIdx}`} className="whitespace-pre-wrap break-words text-sm leading-[1.5] text-gray-800">
                            {formatLinks(line, `pay-${s.title}-${lineIdx}`)}
                          </p>
                        ))}
                      </div>
                    ) : (
                      <p className="text-sm italic text-gray-400">Описание отсутствует</p>
                    )}
                  </article>
                ))}
              </div>
            ) : (
              <p className="text-sm italic text-gray-400">Данные по НДС и акцизу отсутствуют в справке для этого кода.</p>
            )}
          </section>
        </div>
      ) : null}

      {activeTab === 'nonTariff' ? (
        <div className="space-y-4">
          <section>
            <h3 className="mb-3 text-xs font-bold uppercase tracking-wide text-gray-600 border-b border-gray-200 pb-2">
              Меры нетарифного регулирования
            </h3>
            {nonTariffMeasures.length === 0 ? (
              <div className="rounded-xl border border-gray-200 bg-gray-50 px-4 py-3 text-sm text-gray-600">
                Документы не требуются.
              </div>
            ) : (
              <div className="space-y-3">
                {nonTariffMeasures.map((m) => {
                  const v = pickNonTariffVisibleFields(m);
                  return (
                    <article
                      key={`${m.id}-${m.measure_type}-${m.commodity_code}`}
                      className={`rounded-xl border px-4 py-3 ${getMeasureCardClass(m.measure_type)}`}
                    >
                      <div className="mb-1.5 flex items-center gap-2">
                        {getMeasureIcon(m.measure_type)}
                        <p className="text-[11px] font-bold uppercase tracking-wide text-gray-600">
                          {getMeasureTypeLabel(m.measure_type)}
                        </p>
                      </div>
                      <p className="text-base font-semibold text-gray-900">
                        {v.document_required ? formatLinks(v.document_required, `${m.id}-doc`) : 'Документы не требуются'}
                      </p>
                      {v.description ? (
                        <div className="mt-1">{renderLinkedParagraphs(v.description, `${m.id}-desc`)}</div>
                      ) : (
                        <p className="mt-1 text-sm italic text-gray-400">Описание отсутствует</p>
                      )}
                      {v.regulatory_act ? (
                        <p className="mt-2 whitespace-pre-wrap break-words text-xs leading-[1.5] text-gray-500">
                          {formatLinks(v.regulatory_act, `${m.id}-act`)}
                        </p>
                      ) : null}
                    </article>
                  );
                })}
              </div>
            )}
          </section>

          <section>
            <h3 className="mb-3 text-xs font-bold uppercase tracking-wide text-gray-600 border-b border-gray-200 pb-2">
              Защита бренда (ТРОИС)
            </h3>
            {intellectualProperties.length === 0 ? (
              <div className="rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800">
                Совпадений с ТРОИС по этому коду не найдено.
              </div>
            ) : (
              <div className="space-y-3">
                <div className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
                  ⚠️ Внимание! Данный код содержит бренды под защитой ТРОИС. Проверьте наличие вашего бренда в списке:{' '}
                  {Array.from(new Set(intellectualProperties.map((x) => x.brand_name).filter(Boolean))).join(', ')}.
                </div>
                <div className="space-y-2">
                  {intellectualProperties.map((ip) => (
                    <article
                      key={`${ip.id}-${ip.brand_name}-${ip.hs_code_prefix}`}
                      className="rounded-xl border border-amber-200 bg-amber-50/50 px-4 py-3"
                    >
                      <p className="text-base font-semibold text-gray-900">{ip.brand_name}</p>
                      <p className="mt-1 text-sm text-gray-700">
                        Префикс ТН ВЭД: <span className="font-mono">{ip.hs_code_prefix}</span>
                      </p>
                      {ip.reg_number && <p className="mt-1 text-sm text-gray-700">Рег. номер: {ip.reg_number}</p>}
                      {ip.right_holder && <p className="mt-1 text-xs text-gray-500">Правообладатель: {ip.right_holder}</p>}
                    </article>
                  ))}
                </div>
              </div>
            )}
          </section>
        </div>
      ) : null}

      {activeTab === 'notes' ? (
        <div className="space-y-4">
          <section>
            <h3 className="mb-3 text-xs font-bold uppercase tracking-wide text-gray-600 border-b border-gray-200 pb-2">
              Справка о товаре (импорт)
            </h3>
            {referenceLoading ? (
              <div className="rounded-xl border border-gray-200 bg-gray-50 px-4 py-3 text-sm text-gray-500">Формирование справки…</div>
            ) : reference ? (
              <div className="rounded-xl border border-gray-200 bg-gray-50">
                <div className="grid grid-cols-[240px_1fr] gap-x-4 gap-y-0 px-4 py-3 text-sm">
                  {reference.fields.map((f) => (
                    <React.Fragment key={f.label}>
                      <div className="border-b border-gray-200 py-2 text-gray-500">{f.label}</div>
                      <div className="border-b border-gray-200 py-2 text-gray-900">
                        {renderLinkedParagraphs(String(f.value || ''), `field-${f.label}`)}
                      </div>
                    </React.Fragment>
                  ))}
                </div>
                <div className="space-y-3 border-t border-gray-200 px-4 py-3">
                  {reference.sections.map((s) => {
                    const rawItems = s.items ?? [];
                    const cleaned = rawItems.map(sanitizeNonTariffLine).filter(Boolean);
                    const isNt = REFERENCE_NT_SECTION_TITLES.has(s.title);
                    const placeholder = 'Документы не требуются.';
                    const items =
                      isNt && cleaned.length === 0
                        ? [placeholder]
                        : isNt
                          ? cleaned
                          : cleaned.length > 0
                            ? cleaned
                            : rawItems;
                    return (
                      <article key={s.title} className="rounded-lg border border-gray-200 bg-white px-3 py-2">
                        <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-gray-600">{s.title}</p>
                        <div className="space-y-1.5">
                          {items.length === 0 ? (
                            <p className="text-sm italic text-gray-400">Описание отсутствует</p>
                          ) : (
                            items.map((line, idx) => (
                              <p
                                key={`${s.title}-${idx}`}
                                className={`whitespace-pre-wrap break-words text-sm leading-[1.5] ${
                                  line === placeholder ? 'italic text-gray-500' : 'text-gray-800'
                                }`}
                              >
                                {formatLinks(line, `${s.title}-${idx}`)}
                              </p>
                            ))
                          )}
                        </div>
                      </article>
                    );
                  })}
                </div>
              </div>
            ) : (
              <div className="rounded-xl border border-gray-200 bg-gray-50 px-4 py-3 text-sm text-gray-500">
                Справка по коду недоступна.
              </div>
            )}
          </section>

          <section>
            <h3 className="mb-3 text-xs font-bold uppercase tracking-wide text-gray-600 border-b border-gray-200 pb-2">
              Примечания к ТН ВЭД
            </h3>
            <div className="max-h-[min(420px,52vh)] overflow-y-auto rounded-xl border border-gray-200 bg-gray-50 px-4 py-4">
              {renderLinkedParagraphs(notes, 'notes', 'Примечания для этой позиции отсутствуют.')}
            </div>
          </section>

          {assistantVisible ? (
            <section className="rounded-xl border border-gray-200 bg-white p-4">
              <div className="mb-3 flex items-center justify-between">
                <h3 className="text-xs font-bold uppercase tracking-wide text-gray-700">
                  Консультант по классификации
                </h3>
                <button
                  type="button"
                  onClick={clearChat}
                  className="text-xs text-gray-400 hover:text-red-500 cursor-pointer"
                  title="Очистить диалог"
                >
                  Очистить
                </button>
              </div>

              <div className="mb-3 max-h-[220px] overflow-y-auto rounded-lg border border-gray-200 bg-gray-50 p-3 space-y-2">
                {chatMessages.length === 0 && (
                  <p className="text-sm text-gray-400">Спросите про классификацию, исключения, сертификаты…</p>
                )}
                {chatMessages.map((m, idx) => (
                  <div
                    key={`${m.role}-${idx}`}
                    className={
                      m.role === 'user'
                        ? 'ml-auto max-w-[85%] rounded-lg bg-blue-600 px-3 py-2 text-sm text-white'
                        : 'mr-auto max-w-[85%] rounded-lg bg-white border border-gray-200 px-3 py-2 text-sm text-gray-800'
                    }
                  >
                    {m.text}
                  </div>
                ))}
                {chatLoading && (
                  <div className="mr-auto max-w-[85%] rounded-lg bg-white border border-gray-200 px-3 py-2 text-sm text-gray-500">
                    Анализирую примечания...
                  </div>
                )}
              </div>

              {chatError && <p className="mb-2 text-xs text-red-600">{chatError}</p>}

              <div className="flex gap-2">
                <input
                  value={chatInput}
                  onChange={(e) => setChatInput(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' && !e.shiftKey) {
                      e.preventDefault();
                      void sendQuestion();
                    }
                  }}
                  placeholder="Спросить про классификацию, исключения, сертификаты..."
                  className="flex-1 rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
                />
                <button
                  type="button"
                  onClick={() => void sendQuestion()}
                  disabled={chatLoading || !chatInput.trim()}
                  className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
                >
                  Отправить
                </button>
              </div>
            </section>
          ) : null}
        </div>
      ) : null}
    </div>
  );
};
