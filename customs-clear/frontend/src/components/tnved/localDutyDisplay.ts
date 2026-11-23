import documentFootnotes from './localDutyFootnotes.json';

// Each entry identifies a frozen PDF whose column header supplies the percent
// unit. Suffixes are transcribed from smaller, raised glyphs in that PDF.
const footnotes: Record<string, Record<string, string>> = documentFootnotes;

export function localDutyDisplay(raw: string, pdfSha256: string) {
  const entries = footnotes[pdfSha256];
  if (!entries) return { text: raw, note: '' };

  const note = Object.hasOwn(entries, raw) ? entries[raw] : '';
  const amount = note ? raw.slice(0, -note.length).trimEnd() : raw;
  if (/^\d+(?:[,.]\d+)?$/.test(amount)) return { text: amount + ' %', note };

  // Only the unqualified leading amount uses the percentage column unit.
  // Keep the connector, minimum, currency, quantity and unit as printed.
  const combined = /^(\d+(?:[,.]\d+)?)(,?\s+(?:плюс|но не менее)\s+\d+(?:[,.]\d+)?\s+(?:евро|доллар(?:а|ов)? США)\s+за\s+.+)$/u.exec(raw);
  return { text: combined ? combined[1] + ' %' + combined[2] : raw, note: '' };
}
