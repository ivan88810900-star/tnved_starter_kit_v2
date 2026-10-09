import React, { forwardRef, useCallback, useEffect, useImperativeHandle, useRef, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Bot, Sparkles, Trash2 } from 'lucide-react';
import { api } from '../../api/client';
import { getUserFacingApiError } from '../../api/error';
import {
  getAssistantCalculationContext,
  subscribeAssistantCalculationContext,
} from '../../store/calculatorAssistantBridge';
import type {
  AssistantChatCoverage,
  AssistantChatGroundingMode,
  AssistantChatRequest,
  AssistantChatResponse,
} from '../../types/api.types';

type GroundingCitationView = {
  id: string;
  title: string;
  url?: string;
};

type GroundingView = {
  coverage: AssistantChatCoverage | 'unknown';
  mode: AssistantChatGroundingMode | 'unknown';
  citations: GroundingCitationView[];
  limitations: string[];
};

export type ChatMessage = {
  role: 'user' | 'assistant';
  text: string;
  grounding?: GroundingView;
};

function recordOrNull(value: unknown): Record<string, unknown> | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null;
  return value as Record<string, unknown>;
}

function boundedText(value: unknown, limit: number): string {
  return typeof value === 'string' ? value.trim().slice(0, limit) : '';
}

function safeExternalUrl(value: unknown): string | undefined {
  const candidate = boundedText(value, 1200);
  if (!candidate) return undefined;
  try {
    const parsed = new URL(candidate);
    return parsed.protocol === 'http:' || parsed.protocol === 'https:' ? parsed.href : undefined;
  } catch {
    return undefined;
  }
}

function normalizeGrounding(value: unknown): GroundingView | undefined {
  const raw = recordOrNull(value);
  if (!raw) return undefined;

  const citations = Array.isArray(raw.citations)
    ? raw.citations.slice(0, 12).flatMap((value): GroundingCitationView[] => {
        const citation = recordOrNull(value);
        if (!citation) return [];
        const id = boundedText(citation.id, 40);
        const title = boundedText(citation.title, 240);
        if (!id || !title) return [];
        return [{ id, title, url: safeExternalUrl(citation.url) }];
      })
    : [];
  const limitations = Array.isArray(raw.limitations)
    ? raw.limitations
        .slice(0, 12)
        .map((item) => boundedText(item, 800))
        .filter(Boolean)
    : [];
  const hasServerEvidence = raw.generated_from_server_facts === true && citations.length > 0;
  const coverage: GroundingView['coverage'] =
    raw.coverage === 'partial' || raw.coverage === 'needs_context'
      ? raw.coverage
      : raw.coverage === 'grounded' && hasServerEvidence
        ? 'grounded'
        : 'unknown';
  const mode: GroundingView['mode'] =
    raw.mode === 'deterministic'
      ? 'deterministic'
      : raw.mode === 'llm_grounded' && hasServerEvidence
        ? 'llm_grounded'
        : 'unknown';

  return { coverage, mode, citations, limitations };
}

function normalizeAssistantReply(response: AssistantChatResponse): {
  text: string;
  grounding?: GroundingView;
} {
  if (typeof response.answer === 'string') {
    return { text: response.answer.trim() || 'Нет ответа.' };
  }
  const payload = recordOrNull(response.answer);
  return {
    text: boundedText(payload?.answer, 12000) || 'Нет ответа.',
    grounding: normalizeGrounding(payload?.grounding),
  };
}

const coverageLabels: Record<GroundingView['coverage'], string> = {
  grounded: 'Ответ опирается на доступные серверные данные',
  partial: 'Данные для ответа неполные',
  needs_context: 'Для ответа нужен дополнительный контекст',
  unknown: 'Статус покрытия не подтверждён',
};

const modeLabels: Record<GroundingView['mode'], string> = {
  deterministic: 'Серверный ответ',
  llm_grounded: 'Серверный ответ выбран моделью',
  unknown: 'Режим ответа не подтверждён',
};

function GroundingDetails({ grounding }: { grounding: GroundingView }) {
  return (
    <div
      data-testid="assistant-grounding"
      className="mt-2 space-y-2 border-t border-slate-100 pt-2 text-[10px] leading-relaxed text-slate-600"
    >
      <div className="flex flex-wrap gap-1.5">
        <span className="rounded-full border border-slate-200 bg-slate-50 px-2 py-0.5">
          {coverageLabels[grounding.coverage]}
        </span>
        <span className="rounded-full border border-slate-200 bg-slate-50 px-2 py-0.5">
          {modeLabels[grounding.mode]}
        </span>
      </div>

      {grounding.citations.length ? (
        <div>
          <p className="font-semibold text-slate-700">Источники в ответе</p>
          <ul className="mt-0.5 space-y-0.5">
            {grounding.citations.map((citation) => (
              <li key={`${citation.id}-${citation.title}`}>
                {citation.url ? (
                  <a
                    href={citation.url}
                    target="_blank"
                    rel="noreferrer"
                    className="text-blue-700 underline decoration-blue-200 underline-offset-2 hover:text-blue-800"
                  >
                    [{citation.id}] {citation.title}
                  </a>
                ) : (
                  <span>[{citation.id}] {citation.title}</span>
                )}
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {grounding.limitations.length ? (
        <div>
          <p className="font-semibold text-slate-700">Ограничения</p>
          <ul className="mt-0.5 list-disc space-y-0.5 pl-4">
            {grounding.limitations.map((limitation) => (
              <li key={limitation}>{limitation}</li>
            ))}
          </ul>
        </div>
      ) : null}

      <p>Статус покрытия описывает доступные данные и не подтверждает юридическую полноту.</p>
    </div>
  );
}

export type DeclarantChatThreadProps = {
  variant?: 'home' | 'full';
  headerTitle: string;
  /** Подзаголовок / бейджи (контекст калькулятора и т.п.) */
  headerExtra?: React.ReactNode;
  emptyStateHint?: string;
  /** Вызывается перед запросом к API (например, сохранить идентификаторы в sessionStorage). */
  onBeforeSend?: () => void;
};

/** Управление из родителя (открытие из калькулятора, prefill текста). */
export type DeclarantChatThreadHandle = {
  resetWithMessages: (msgs: ChatMessage[]) => void;
  setInput: (value: string) => void;
};

export const DeclarantChatThread = forwardRef<DeclarantChatThreadHandle, DeclarantChatThreadProps>(
  function DeclarantChatThread(
    {
      variant = 'full',
      headerTitle,
      headerExtra,
      emptyStateHint,
      onBeforeSend,
    },
    ref,
  ) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInputValue] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [hasCtx, setHasCtx] = useState(() => !!getAssistantCalculationContext());
  const scrollRef = useRef<HTMLDivElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  const isHome = variant === 'home';
  const maxH = isHome ? 'max-h-44' : 'min-h-[14rem] max-h-[min(28rem,55vh)]';

  useEffect(() => {
    return subscribeAssistantCalculationContext(() => {
      setHasCtx(!!getAssistantCalculationContext());
    });
  }, []);

  const scrollToBottom = useCallback(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
  }, []);

  useEffect(() => {
    scrollToBottom();
  }, [messages, loading, scrollToBottom]);

  const clearHistory = () => {
    setMessages([]);
    setError(null);
  };

  useImperativeHandle(
    ref,
    () => ({
      resetWithMessages(msgs: ChatMessage[]) {
        setMessages(msgs);
        setError(null);
        setInputValue('');
      },
      setInput(value: string) {
        setInputValue(value);
      },
    }),
    [],
  );

  const send = async () => {
    const msg = input.trim();
    if (!msg) return;
    onBeforeSend?.();
    setLoading(true);
    setError(null);
    const history = messages.slice(-40).map((m) => ({
      role: m.role,
      content: m.text,
    }));
    const ctx = getAssistantCalculationContext();
    const body: AssistantChatRequest = {
      message: msg,
      history,
      context: ctx ?? undefined,
    };
    try {
      const { data } = await api.post<AssistantChatResponse>('/v1/assistant/chat', body);
      const answer = normalizeAssistantReply(data);
      setMessages((prev) => [
        ...prev,
        { role: 'user', text: msg },
        { role: 'assistant', text: answer.text, grounding: answer.grounding },
      ]);
      setInputValue('');
    } catch (e) {
      setError(getUserFacingApiError(e, 'Не удалось получить ответ. Попробуйте позже.'));
    } finally {
      setLoading(false);
    }
  };

  const defaultHint =
    emptyStateHint ||
    'Задайте вопрос по ТН ВЭД, платежам или документам. История диалога сохраняется до очистки.';

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0 flex-1 space-y-1">
          <div className="flex flex-wrap items-center gap-2">
            <Sparkles className="h-4 w-4 shrink-0 text-indigo-600" aria-hidden />
            <span className="text-[11px] font-semibold uppercase tracking-[0.14em] text-slate-500">
              {headerTitle}
            </span>
            {headerExtra}
            {!headerExtra && hasCtx ? (
              <span className="rounded-full border border-emerald-200 bg-emerald-50 px-2 py-0.5 text-[10px] text-emerald-700">
                есть контекст расчёта
              </span>
            ) : null}
            {!headerExtra && !hasCtx ? (
              <span className="text-[10px] text-slate-600">контекст калькулятора появится после расчёта</span>
            ) : null}
          </div>
        </div>
        <button
          type="button"
          onClick={clearHistory}
          disabled={messages.length === 0 && !error}
          className="inline-flex shrink-0 items-center gap-1 rounded-lg border border-slate-200 bg-white px-2 py-1 text-[11px] font-medium text-slate-600 transition hover:border-slate-300 hover:bg-slate-50 disabled:pointer-events-none disabled:opacity-40"
          title="Очистить диалог"
        >
          <Trash2 className="h-3.5 w-3.5" aria-hidden />
          Очистить
        </button>
      </div>

      <div
        ref={scrollRef}
        className={`space-y-3 overflow-y-auto rounded-xl border border-slate-200/90 bg-slate-50/80 p-3 text-[13px] ${maxH}`}
      >
        {messages.length === 0 && !loading ? (
          <p className="px-1 py-2 text-[12px] leading-relaxed text-slate-500">{defaultHint}</p>
        ) : (
          messages.map((m, i) => (
            <div
              key={`${m.role}-${i}`}
              className={`flex w-full ${m.role === 'user' ? 'justify-end' : 'justify-start'}`}
            >
              {m.role === 'assistant' ? (
                <div className="flex max-w-[min(100%,36rem)] gap-2">
                  <div
                    className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full border border-slate-200 bg-white shadow-sm"
                    aria-hidden
                  >
                    <Bot className="h-4 w-4 text-indigo-600" />
                  </div>
                  <div className="rounded-2xl rounded-tl-md border border-slate-200 bg-white px-3 py-2 shadow-sm">
                    <div className="cc-chat-markdown">
                      <ReactMarkdown remarkPlugins={[remarkGfm]}>{m.text}</ReactMarkdown>
                    </div>
                    {m.grounding ? <GroundingDetails grounding={m.grounding} /> : null}
                  </div>
                </div>
              ) : (
                <div className="max-w-[min(100%,28rem)] rounded-2xl rounded-tr-md bg-indigo-600 px-3 py-2 text-white shadow-md">
                  <p className="whitespace-pre-wrap text-[13px] leading-relaxed">{m.text}</p>
                </div>
              )}
            </div>
          ))
        )}

        {loading ? (
          <div className="flex justify-start">
            <div className="flex items-center gap-2">
              <div
                className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full border border-slate-200 bg-white shadow-sm"
                aria-hidden
              >
                <Bot className="h-4 w-4 animate-pulse text-indigo-600" />
              </div>
              <div
                className="cc-chat-typing flex items-center gap-1.5 rounded-2xl rounded-tl-md border border-slate-200 bg-white px-4 py-2.5 shadow-sm"
                aria-label="Ассистент печатает"
              >
                <span />
                <span />
                <span />
              </div>
            </div>
          </div>
        ) : null}

        <div ref={bottomRef} className="h-px w-full shrink-0" aria-hidden />
      </div>

      {error ? (
        <div className="rounded-lg border border-red-200 bg-red-50 px-2 py-1.5 text-[11px] text-red-700">
          {error}
        </div>
      ) : null}

      <div className="flex flex-col gap-2 sm:flex-row sm:items-end">
        <label className="min-w-0 flex-1 space-y-1">
          <span className="cc-label">Сообщение</span>
          <textarea
            value={input}
            onChange={(e) => setInputValue(e.target.value)}
            rows={isHome ? 2 : 3}
            className="cc-input min-h-[3rem] resize-y font-sans text-[12px] leading-snug sm:min-h-[4.5rem]"
            placeholder="Например: какие документы нужны для выпуска?"
            disabled={loading}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
                e.preventDefault();
                void send();
              }
            }}
          />
        </label>
        <button
          type="button"
          className="cc-btn-primary shrink-0"
          disabled={loading || !input.trim()}
          onClick={() => void send()}
        >
          Отправить
        </button>
      </div>
      <p className="text-[10px] text-slate-500">
        <kbd className="rounded border border-slate-200 bg-slate-100 px-1 py-0.5 font-mono text-[9px]">⌘</kbd>
        +
        <kbd className="rounded border border-slate-200 bg-slate-100 px-1 py-0.5 font-mono text-[9px]">Enter</kbd>
        — отправить
      </p>
    </div>
  );
  },
);
