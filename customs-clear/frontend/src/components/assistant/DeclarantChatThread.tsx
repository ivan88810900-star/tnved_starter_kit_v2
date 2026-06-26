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
import type { AssistantChatRequest, AssistantChatResponse } from '../../types/api.types';

export type ChatMessage = { role: 'user' | 'assistant'; text: string };

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
    const history = messages.map((m) => ({
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
      const answer = (data.answer || 'Нет ответа.').trim();
      setMessages((prev) => [...prev, { role: 'user', text: msg }, { role: 'assistant', text: answer }]);
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
