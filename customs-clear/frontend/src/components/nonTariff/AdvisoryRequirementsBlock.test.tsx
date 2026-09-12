import { render, screen } from '@testing-library/react';
import React from 'react';
import { describe, expect, it } from 'vitest';
import { AdvisoryRequirementsBlock } from './AdvisoryRequirementsBlock';

describe('AdvisoryRequirementsBlock', () => {
  it('shows every matched export-control source and the identification route', () => {
    render(
      <AdvisoryRequirementsBlock
        items={[{
          permit_type: 'ЛЗ/разрешение ФСТЭК',
          applicability: 'needs_clarification',
          source: 'official_export_control',
          source_label: 'Экспортный контроль РФ (ФСТЭК)',
          source_url: 'https://example.test/1284',
          direction: 'export',
          used_for_missing_check: false,
          requires_manual_review: true,
          reason: 'Нужна идентификация по техническим параметрам.',
          identification_url: 'https://example.test/identification',
          source_documents: [
            { number: 1284, title: 'Ядерный список', official_url: 'https://example.test/1284' },
            { number: 1299, title: 'Двойное назначение', official_url: 'https://example.test/1299' },
          ],
        }]}
      />,
    );

    expect(screen.getByRole('link', { name: 'ПП РФ №1284' })).toHaveAttribute('href', 'https://example.test/1284');
    expect(screen.getByRole('link', { name: 'ПП РФ №1299' })).toHaveAttribute('href', 'https://example.test/1299');
    expect(screen.getByRole('link', { name: 'Идентификация контролируемой продукции (ФСТЭК)' }))
      .toHaveAttribute('href', 'https://example.test/identification');
    expect(screen.getByText('Лицензия или разрешение в сфере экспортного контроля')).toBeInTheDocument();
  });

  it('renders user-facing labels for every official advisory permit type', () => {
    const permitTypes = [
      'РЭВЧУ',
      'НФ/ЛЗ',
      'ВЕТКОНТРОЛЬ',
      'ФИТОКОНТРОЛЬ (без ФСС)',
      'ЛЗ/разрешение ФСТЭК',
    ];

    render(
      <AdvisoryRequirementsBlock
        items={permitTypes.map((permitType) => ({
          permit_type: permitType,
          applicability: 'needs_clarification',
          source: 'official_ntm_exact_devices_shadow',
          used_for_missing_check: false,
          requires_manual_review: true,
          reason: 'Нужно уточнить характеристики товара.',
        }))}
      />,
    );

    expect(screen.getByText('Разрешительный документ на ввоз РЭС и ВЧУ')).toBeInTheDocument();
    expect(screen.getByText('Нотификация ФСБ или лицензия на ввоз')).toBeInTheDocument();
    expect(screen.getByText('Ветеринарный контроль (вид документа уточняется)')).toBeInTheDocument();
    expect(screen.getByText('Фитосанитарный контроль без фитосанитарного сертификата')).toBeInTheDocument();
    expect(screen.getByText('Лицензия или разрешение в сфере экспортного контроля')).toBeInTheDocument();
  });

  it('renders the combined import-or-transit direction without leaking an API enum', () => {
    render(
      <AdvisoryRequirementsBlock
        items={[{
          permit_type: 'ВЕТКОНТРОЛЬ',
          applicability: 'needs_clarification',
          source: 'official_ntm_exact_health',
          direction: 'import_or_transit',
          used_for_missing_check: false,
          requires_manual_review: true,
          reason: 'Проверка зависит от партии и направления.',
        }]}
      />,
    );

    expect(screen.getByText('ввоз/транзит')).toBeInTheDocument();
    expect(screen.queryByText('import_or_transit')).not.toBeInTheDocument();
  });

  it('uses the correct КТС issuer for Decision No. 299 fallback', () => {
    render(
      <AdvisoryRequirementsBlock
        items={[{
          permit_type: 'СГР',
          applicability: 'needs_clarification',
          source: 'official_sgr_registry',
          used_for_missing_check: false,
          requires_manual_review: true,
          reason: 'Нужно проверить назначение товара.',
        }]}
      />,
    );

    expect(screen.getByText('Решение КТС №299')).toBeInTheDocument();
    expect(screen.queryByText(/ЕЭК №299/)).not.toBeInTheDocument();
  });

  it('shows exact-match evidence and the facts still needed for a legal conclusion', () => {
    render(
      <AdvisoryRequirementsBlock
        items={[{
          permit_type: 'РЭВЧУ',
          applicability: 'needs_clarification',
          source: 'official_ntm_exact_devices_shadow',
          used_for_missing_check: false,
          requires_manual_review: true,
          reason: 'Радиомодуль выявлен, параметры не подтверждены.',
          matched_rule: 'Раздел 2.16 — встроенные РЭС и ВЧУ',
          matched_hs_scope: 'embedded-component',
          source_revision: 'Decision-30/current',
          missing_facts: ['frequency_mhz', 'transmitter_power_mw'],
          exact_advisory: true,
          evidence_trust: 'caller_supplied_structured_facts',
          trusted_source_verified: false,
        }]}
      />,
    );

    expect(screen.getByText(/Точная строка: Раздел 2\.16/)).toBeInTheDocument();
    expect(screen.getByText(/Для точного вывода: рабочие частоты, мощность передатчика/)).toBeInTheDocument();
    expect(screen.getByText(/Сопоставление: embedded-component/)).toBeInTheDocument();
    expect(screen.getByText(/Редакция: Decision-30\/current/)).toBeInTheDocument();
    expect(screen.getByText('Точные правила РЭС/ВЧУ и криптографии')).toBeInTheDocument();
    expect(screen.getByText(/сервис не проверял реестр или документы самостоятельно/)).toBeInTheDocument();
  });

  it('translates new exact personal-use and transit facts for the user', () => {
    render(
      <AdvisoryRequirementsBlock
        items={[{
          permit_type: 'НФ/ЛЗ',
          applicability: 'needs_clarification',
          source: 'official_ntm_exact_devices_shadow',
          used_for_missing_check: false,
          requires_manual_review: true,
          reason: 'Нужно дополнить факты точного исключения.',
          missing_facts: [
            'crypto_exemption.natural_person',
            'transit_route',
            'crypto_transit_authorization_or_notification',
          ],
        }]}
      />,
    );

    expect(screen.getByText(/получатель является физическим лицом/)).toBeInTheDocument();
    expect(screen.getByText(/маршрут транзита/)).toBeInTheDocument();
    expect(screen.getByText(/разрешение или нотификация для выбранного маршрута транзита/)).toBeInTheDocument();
  });

  it('renders a bounded exact exclusion separately from a missing document', () => {
    render(
      <AdvisoryRequirementsBlock
        items={[{
          permit_type: 'ФСС',
          applicability: 'excluded',
          source: 'official_ntm_exact_health',
          used_for_missing_check: false,
          requires_manual_review: true,
          reason: 'Отрицательный вывод ограничен точной строкой.',
          matched_rule: 'Жареный кофе низкого риска',
          exclusion_reason: 'Фитосанитарный сертификат по этой exact-строке не требуется.',
        }]}
      />,
    );

    expect(screen.getByText('Возможное точное исключение')).toBeInTheDocument();
    expect(screen.getByText(/Фитосанитарный сертификат.*не требуется/)).toBeInTheDocument();
    expect(screen.getByText('Точные санитарные, ветеринарные и фитосанитарные правила')).toBeInTheDocument();
  });
});
