/**
 * Хранилище «последних просмотренных кодов ТН ВЭД» в localStorage.
 * Максимум 8 элементов, дубликаты поднимаются наверх.
 */

const KEY = "tnved.recentCodes.v1";
const MAX = 8;

export type RecentCode = {
  code: string;
  title: string;
  ts: number;
};

function safeLS(): Storage | null {
  try {
    if (typeof window === "undefined") return null;
    return window.localStorage;
  } catch {
    return null;
  }
}

export function readRecentCodes(): RecentCode[] {
  const ls = safeLS();
  if (!ls) return [];
  try {
    const raw = ls.getItem(KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed
      .filter((x) => x && typeof x.code === "string" && typeof x.title === "string")
      .slice(0, MAX);
  } catch {
    return [];
  }
}

export function pushRecentCode(entry: Omit<RecentCode, "ts">): RecentCode[] {
  const ls = safeLS();
  if (!ls) return [];
  const prev = readRecentCodes().filter((x) => x.code !== entry.code);
  const next: RecentCode[] = [{ ...entry, ts: Date.now() }, ...prev].slice(0, MAX);
  try {
    ls.setItem(KEY, JSON.stringify(next));
  } catch {
    /* ignore quota */
  }
  return next;
}

export function clearRecentCodes(): void {
  const ls = safeLS();
  if (!ls) return;
  try {
    ls.removeItem(KEY);
  } catch {
    /* ignore */
  }
}
