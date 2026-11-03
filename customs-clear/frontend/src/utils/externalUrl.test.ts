import { describe, expect, it } from 'vitest';

import { formatUnsafeExternalUrlEvidence, getSafeExternalUrl } from './externalUrl';

const encodeRepeatedly = (value: string, rounds: number): string => {
  let encoded = value;
  for (let round = 0; round < rounds; round += 1) encoded = encodeURIComponent(encoded);
  return encoded;
};

describe('getSafeExternalUrl', () => {
  it.each([
    'https://eec.eaeunion.org/comission/department/catr/ett/',
    'http://customs.gov.example/rulings?id=12#source',
  ])('admits an absolute HTTP(S) URL with a hostname: %s', (url) => {
    expect(getSafeExternalUrl(url)).toBe(url);
  });

  it.each([
    '',
    '/relative/source',
    '//example.test/protocol-relative',
    'javascript:alert(1)',
    'data:text/html,unsafe',
    'ftp://example.test/source',
    'https:///missing-host',
    'https://',
    ' https://example.test/source',
    'https://example.test/source\n',
    'https://example.test/a b',
    'https://example.test\\@attacker.test/source',
    'https://trusted.example@evil.example/source',
    'https://user:password@example.test/source',
    'https://example.test/source%0d%0AInjected',
    'https://example.test/source%09tab',
    'https://example.test/source%1fcontrol',
    'https://example.test/source%7Fcontrol',
    'https://example.test/%C2%85',
    'https://example.test/%E2%80%AEevil',
    'https://example.test/%25C2%2585',
    'https://example.test/%25E2%2580%25AEevil',
    `https://example.test/${encodeRepeatedly(String.fromCharCode(0x202e), 6)}evil`,
    'https://example.test/%5Cevil',
    'https://example.test/a%20b',
    'https://example.test/%ZZ',
    'https://example.test/%E2%80',
    `https://example.test/source${String.fromCharCode(0x85)}`,
    `https://example.test/${String.fromCharCode(0x202e)}evil`,
    `https://example.test/${String.fromCharCode(0x2066)}evil`,
    'https://./source',
    'https://../source',
    'https://bad..example/source',
    'https://-bad.example/source',
    'https://bad-.example/source',
    'https://bad_host.example/source',
  ])('rejects a URL that is not a strict external HTTP(S) source: %s', (url) => {
    expect(getSafeExternalUrl(url)).toBeNull();
  });

  it('rejects non-string values', () => {
    expect(getSafeExternalUrl(null)).toBeNull();
    expect(getSafeExternalUrl({ href: 'https://example.test' })).toBeNull();
  });
});

describe('formatUnsafeExternalUrlEvidence', () => {
  it('escapes invisible controls while leaving markup visible as plain evidence', () => {
    const value = `<img src=x onerror=alert(1)>${String.fromCharCode(0x202e)}\nend`;
    expect(formatUnsafeExternalUrlEvidence(value)).toBe('<img src=x onerror=alert(1)>\\u202E\\u000Aend');
  });

  it('bounds long evidence with an explicit ellipsis', () => {
    expect(formatUnsafeExternalUrlEvidence('x'.repeat(200), 20)).toBe(`${'x'.repeat(19)}…`);
  });
});
