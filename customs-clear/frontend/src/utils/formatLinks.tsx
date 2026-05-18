import React from 'react';

const ACT_REGEX =
  /(Решение\s+(?:Коллегии|Совета)\s+ЕЭК\s*№\s*\d+|Решение\s+КТС\s*№\s*\d+|ТР\s*ТС\s*\d{3}\/\d{4}|ФЗ\s*№\s*\d+|ПП\s*РФ\s*№\s*\d+)/gi;

/** Разбивает длинные строки на читаемые абзацы. */
export function splitReadableParagraphs(raw: string): string[] {
  const text = (raw || '').replace(/\r/g, '\n').trim();
  if (!text) return [];
  const lines = text
    .split(/\n+/)
    .map((line) => line.trim())
    .filter(Boolean);

  const out: string[] = [];
  for (const line of lines) {
    const chunks = line
      .split(/\s+\|\s+/)
      .map((chunk) => chunk.trim())
      .filter(Boolean);
    const source = chunks.length > 0 ? chunks : [line];
    for (const chunk of source) {
      if (chunk.length > 220 && chunk.includes('; ')) {
        const bySemicolon = chunk
          .split('; ')
          .map((part) => part.trim())
          .filter(Boolean);
        out.push(...bySemicolon);
      } else {
        out.push(chunk);
      }
    }
  }
  return out;
}

/** Добавляет кликабельные ссылки на упоминания нормативных актов. */
export function formatLinks(text: string, keyPrefix = 'act'): React.ReactNode[] {
  const input = (text || '').trim();
  if (!input) return [input];

  const nodes: React.ReactNode[] = [];
  let lastIndex = 0;
  let matchIndex = 0;
  ACT_REGEX.lastIndex = 0;

  let m: RegExpExecArray | null;
  while ((m = ACT_REGEX.exec(input)) !== null) {
    if (m.index > lastIndex) {
      nodes.push(input.slice(lastIndex, m.index));
    }
    const label = m[0];
    const href = `https://yandex.ru/search/?text=${encodeURIComponent(label)}`;
    nodes.push(
      <a
        key={`${keyPrefix}-${matchIndex}`}
        href={href}
        target="_blank"
        rel="noreferrer"
        className="text-blue-600 hover:underline"
      >
        {label}
      </a>,
    );
    matchIndex += 1;
    lastIndex = m.index + label.length;
  }

  if (lastIndex < input.length) {
    nodes.push(input.slice(lastIndex));
  }
  return nodes;
}
