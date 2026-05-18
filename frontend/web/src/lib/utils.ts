export function cn(...classes: (string | undefined | false | null)[]): string {
  return classes.filter(Boolean).join(" ");
}

/**
 * Минимальная очистка для отображения номенклатуры: без усечения текста и без удаления хвостовых слов
 * (таможенное наименование должно оставаться полным).
 */
export function cleanTitle(raw: string | null | undefined): string {
  if (!raw) return "";
  let s = raw.trim();
  s = s.replace(/^[\s–\-—]+/, "").trim();
  s = s.replace(/^[,;.]+\s*/, "").trim();
  return s;
}

/**
 * Возвращает метку узла для отображения в дереве:
 * если заголовок пустой — показывает сам код.
 */
export function nodeLabel(code: string, titleRu: string | null | undefined): string {
  const cleaned = cleanTitle(titleRu);
  return cleaned || code;
}

/** Узлы «прочие / иные» — нужен явный родительский контекст в UI. */
export function isGenericOtherTitle(text: string): boolean {
  const t = text.trim().replace(/:+\s*$/u, "").toLowerCase();
  if (!t) return false;
  const exact = new Set([
    "прочие",
    "прочая",
    "прочий",
    "прочее",
    "иные",
    "другие",
    "прочие товары",
    "прочие изделия",
  ]);
  if (exact.has(t)) return true;
  if (/^прочие\s/u.test(text.trim())) return true;
  if (/^иные\s/u.test(text.trim())) return true;
  return false;
}

/** Текст родителя для строки контекста (без висячего двоеточия). */
export function parentContextLine(parentDisplayTitle: string): string {
  return parentDisplayTitle.replace(/:+\s*$/u, "").trim();
}

export function formatHsCode(raw: string): string {
  const digits = raw.replace(/\D/g, "").slice(0, 10).padEnd(10, "0");
  if (digits.length < 10) return raw;
  return `${digits.slice(0, 4)} ${digits.slice(4, 6)} ${digits.slice(6, 9)} ${digits.slice(9)}`;
}

/**
 * Делит строку на куски `{ text, match }`, где match=true — совпадающие с query фрагменты.
 * Подходит для безопасного рендера с подсветкой без `dangerouslySetInnerHTML`.
 */
export type HighlightChunk = { text: string; match: boolean };

export function buildHighlightChunks(text: string, query: string): HighlightChunk[] {
  const src = text ?? "";
  const q = (query || "").trim();
  if (!q) return [{ text: src, match: false }];
  // Экранируем спецсимволы regex
  const escaped = q.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const rx = new RegExp(`(${escaped})`, "gi");
  const parts = src.split(rx);
  return parts
    .filter((p) => p !== "")
    .map((p) => ({ text: p, match: p.toLowerCase() === q.toLowerCase() }));
}

type DocType = "tr_ts" | "fsb" | "marking" | "other";

export function classifyDoc(doc: string): DocType {
  const d = doc.toUpperCase();
  if (d.includes("ФСБ") || d.includes("FSB") || d.includes("НОТИФИКАЦ")) return "fsb";
  if (d.includes("ЧЕСТНЫЙ ЗНАК") || d.includes("МАРКИРОВК")) return "marking";
  if (d.includes("ТР ТС") || d.includes("ТР ЕАЭС") || d.includes("ДЕКЛАРАЦ") || d.includes("СЕРТИФИК") || d.includes("СС ") || d.includes("ДС ")) return "tr_ts";
  return "other";
}
