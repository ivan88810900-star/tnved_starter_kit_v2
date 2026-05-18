const TECH_ERROR_SNIPPETS = [
  /\.env\b/i,
  /\bredis\b/i,
  /\bgemini\b/i,
  /\banthropic\b/i,
  /\bopenai\b/i,
  /api[_-]?key/i,
  /GOOGLE_API_KEY/i,
  /traceback/i,
  /sqlalchemy/i,
  /uvicorn/i,
  /internal server error/i,
];

/** Сообщения об инфраструктуре и конфиге — не показываем конечному пользователю. */
export function isTechnicalErrorMessage(message: string): boolean {
  const m = message.trim();
  if (!m) return false;
  return TECH_ERROR_SNIPPETS.some((re) => re.test(m));
}

/** Текст ошибки API для экранов декларанта (без технических деталей). */
export function getUserFacingApiError(
  error: unknown,
  fallback = 'Не удалось выполнить операцию. Попробуйте позже.',
): string {
  const raw = getApiErrorMessage(error, fallback);
  if (isTechnicalErrorMessage(raw)) return fallback;
  return raw;
}

/** Уже известная строка ошибки с сервера — убрать технические детали для UI. */
export function userFacingMessage(text: string | undefined | null, fallback: string): string {
  const t = (text || '').trim();
  if (!t) return fallback;
  if (isTechnicalErrorMessage(t)) return fallback;
  return t;
}

export function getApiErrorMessage(error: unknown, fallback = 'Ошибка запроса'): string {
  if (typeof error === 'string' && error.trim()) {
    return error;
  }

  if (error instanceof Error && error.message.trim()) {
    return error.message;
  }

  if (error && typeof error === 'object') {
    const e = error as {
      message?: unknown;
      response?: { data?: unknown };
    };
    const data = e.response?.data;

    if (typeof data === 'string' && data.trim()) {
      return data;
    }

    if (data && typeof data === 'object') {
      const obj = data as Record<string, unknown>;
      const detail = obj.detail;
      if (detail && typeof detail === 'object' && !Array.isArray(detail)) {
        const d = detail as Record<string, unknown>;
        const nested = d.message ?? d.error;
        if (typeof nested === 'string' && nested.trim()) {
          return nested.trim();
        }
      }
      const candidates = [obj.detail, obj.message, obj.error];
      for (const v of candidates) {
        if (typeof v === 'string' && v.trim()) {
          return v;
        }
      }
    }

    if (typeof e.message === 'string' && e.message.trim()) {
      return e.message;
    }
  }

  return fallback;
}

const alertShownAt = new Map<string, number>();

export function showUiErrorAlert(
  message: string,
  options?: { dedupeKey?: string; minIntervalMs?: number },
): void {
  if (typeof window === 'undefined') return;
  const text = message.trim();
  if (!text) return;
  const key = options?.dedupeKey?.trim() || text;
  const minIntervalMs = options?.minIntervalMs ?? 5000;
  const now = Date.now();
  const last = alertShownAt.get(key) ?? 0;
  if (now - last < minIntervalMs) return;
  alertShownAt.set(key, now);
  window.alert(text);
}
