const FORBIDDEN_LITERAL_CHARACTERS = /[\u0000-\u0020\u007f-\u009f\u061c\u200e\u200f\u202a-\u202e\u2066-\u2069\\]/u;
const ENCODED_ASCII_CONTROL = /%(?:0[0-9a-f]|1[0-9a-f]|7f)/i;
const MAX_DECODE_SCAN_ROUNDS = 4;

function hasSafeDecodedText(value: string): boolean {
  let current = value;
  for (let round = 0; round < MAX_DECODE_SCAN_ROUNDS; round += 1) {
    let decoded: string;
    try {
      decoded = decodeURIComponent(current);
    } catch {
      return false;
    }
    if (FORBIDDEN_LITERAL_CHARACTERS.test(decoded)) return false;
    if (decoded === current) return true;
    current = decoded;
  }

  // Reject values that remain encoded beyond the scan bound rather than
  // admitting an arbitrarily nested representation of a forbidden character.
  try {
    return decodeURIComponent(current) === current;
  } catch {
    return false;
  }
}

function hasValidHostnameSyntax(hostname: string): boolean {
  if (hostname.startsWith('[') && hostname.endsWith(']')) {
    // The URL parser has already validated the IPv6 literal.
    return hostname.length > 2;
  }

  const dnsName = hostname.endsWith('.') ? hostname.slice(0, -1) : hostname;
  if (!dnsName || dnsName.length > 253) return false;
  return dnsName.split('.').every(
    (label) =>
      label.length > 0 &&
      label.length <= 63 &&
      /^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$/i.test(label),
  );
}

/**
 * Admit an untrusted URL for an external anchor only when it is an absolute,
 * credential-free HTTP(S) URL with a syntactically valid hostname. The
 * original value is returned so the UI does not silently rewrite imported
 * source evidence.
 */
export function getSafeExternalUrl(value: unknown): string | null {
  if (typeof value !== 'string' || value.length === 0) return null;
  if (
    value !== value.trim() ||
    FORBIDDEN_LITERAL_CHARACTERS.test(value) ||
    ENCODED_ASCII_CONTROL.test(value) ||
    !hasSafeDecodedText(value)
  ) {
    return null;
  }
  const authorityMatch = /^https?:\/\/([^/?#]+)(?:[/?#]|$)/i.exec(value);
  if (!authorityMatch || authorityMatch[1].includes('@')) return null;

  try {
    const parsed = new URL(value);
    if (
      (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') ||
      parsed.username ||
      parsed.password ||
      !hasValidHostnameSyntax(parsed.hostname)
    ) {
      return null;
    }
    return value;
  } catch {
    return null;
  }
}

const EVIDENCE_ESCAPE_CHARACTERS = /[\u0000-\u001f\u007f-\u009f\u061c\u200e\u200f\u202a-\u202e\u2066-\u2069]/u;

/** Render unsafe evidence as bounded plain text without invisible controls. */
export function formatUnsafeExternalUrlEvidence(value: unknown, maxLength = 120): string {
  if (typeof value !== 'string' || maxLength <= 0) return '';
  const escaped = Array.from(value, (character) => {
    if (!EVIDENCE_ESCAPE_CHARACTERS.test(character)) return character;
    const codePoint = character.codePointAt(0) ?? 0;
    return `\\u${codePoint.toString(16).padStart(4, '0').toUpperCase()}`;
  }).join('');
  if (escaped.length <= maxLength) return escaped;
  if (maxLength === 1) return '…';
  return `${escaped.slice(0, maxLength - 1)}…`;
}
