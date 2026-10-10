import React from 'react';
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { PermitDocumentsVerificationLink } from '../components/tnved/PermitDocumentsBlock';
import { CalculatorOfficialEttLink } from './Calculator';
import { DocumentCheckRegistryLink } from './DocumentCheck';
import { NonTariffRegistryLink } from './NonTariff';
import { PermitPickerRegistryLink } from './PermitPicker';

type SurfaceCase = {
  name: string;
  renderLink: (value: string) => React.ReactNode;
  unsafeValue: string;
  expectedEvidence: string;
};

const surfaces: SurfaceCase[] = [
  {
    name: 'calculator official ETT URL',
    renderLink: (value) => <CalculatorOfficialEttLink value={value} />,
    unsafeValue: 'https://trusted.example@evil.example/source',
    expectedEvidence: 'https://trusted.example@evil.example/source',
  },
  {
    name: 'permit picker registry URL',
    renderLink: (value) => <PermitPickerRegistryLink value={value} label="Реестр ФСА" />,
    unsafeValue: 'data:text/html,<img src=x onerror=alert(1)>',
    expectedEvidence: 'data:text/html,<img src=x onerror=alert(1)>',
  },
  {
    name: 'non-tariff registry URL',
    renderLink: (value) => <NonTariffRegistryLink value={value} />,
    unsafeValue: 'https://example.test/source\nnext',
    expectedEvidence: 'https://example.test/source\\u000Anext',
  },
  {
    name: 'document-check registry URL',
    renderLink: (value) => <DocumentCheckRegistryLink value={value} />,
    unsafeValue: 'https://example.test\\source',
    expectedEvidence: 'https://example.test\\source',
  },
  {
    name: 'permit-document verification URL',
    renderLink: (value) => <PermitDocumentsVerificationLink manualCheckUrl={value} registryLink={null} />,
    unsafeValue: 'https://./source',
    expectedEvidence: 'https://./source',
  },
];

describe.each(surfaces)('$name admission', ({ renderLink, unsafeValue, expectedEvidence }) => {
  it('keeps a valid absolute HTTPS value byte-for-byte in the anchor', () => {
    const safeUrl = 'https://registry.example.test/entry/%D0%A2%D0%95%D0%A1%D0%A2?view=full#source';
    render(<>{renderLink(safeUrl)}</>);

    const link = screen.getByRole('link');
    expect(link).toHaveAttribute('href', safeUrl);
    expect(link).toHaveAttribute('target', '_blank');
    expect(link).toHaveAttribute('rel', 'noopener noreferrer');
  });

  it('renders rejected non-HTTP or malformed input as escaped plain-text evidence, never an anchor', () => {
    const { container } = render(<>{renderLink(unsafeValue)}</>);

    expect(screen.queryByRole('link')).not.toBeInTheDocument();
    expect(container).toHaveTextContent('ссылка недоступна');
    expect(container).toHaveTextContent(expectedEvidence);
    expect(container.querySelector('img, script')).toBeNull();
  });
});

describe('permit-document verification URL fallback', () => {
  it('does not let a rejected manual URL hide a valid registry URL', () => {
    const safeRegistryUrl = 'https://pub.fsa.gov.ru/rss/certificate/123?source=api';
    const unsafeManualUrl = 'https://trusted.example@evil.example/source';
    render(
      <PermitDocumentsVerificationLink
        manualCheckUrl={unsafeManualUrl}
        registryLink={safeRegistryUrl}
      />,
    );

    expect(screen.getByRole('link', { name: /Проверить на ФСА/ })).toHaveAttribute('href', safeRegistryUrl);
    expect(screen.getByTestId('unsafe-permit-verification-url-evidence')).toHaveTextContent(unsafeManualUrl);
  });

  it('bounds long rejected evidence', () => {
    render(<PermitDocumentsVerificationLink manualCheckUrl={`data:text/plain,${'x'.repeat(200)}`} registryLink={null} />);

    const evidence = screen.getByTestId('unsafe-permit-verification-url-evidence');
    expect(evidence.textContent?.endsWith('…')).toBe(true);
    expect(evidence.textContent?.length).toBeLessThan(180);
  });
});
