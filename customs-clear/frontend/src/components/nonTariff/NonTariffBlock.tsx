import React from 'react';
import { NormativeRequirementsBlock } from './NormativeRequirementsBlock';
import {
  normativeBlockFromNonTariff,
  type NormativeRequirementsBlockData,
} from './normativeBlockHelpers';
import type { AdvisoryRequirement } from './AdvisoryRequirementsBlock';

/**
 * Универсальный блок нетарифных требований.
 *
 * Принимает результат NTM-проверки (`item.non_tariff` из /compliance/check или
 * ответ /non_tariff/check) и отображает требования, сгруппированные по
 * обязательным / отсутствующим / условным, с человекочитаемыми названиями
 * документов и цветовым кодированием. Работает для ЛЮБОГО кода ТН ВЭД
 * автоматически — без частных правил по главам, без сырого TKS-текста.
 */

export type NonTariffResult = {
  normative_block?: NormativeRequirementsBlockData;
  required_permit_types?: string[];
  missing_permit_types?: string[];
  advisory_requirements?: AdvisoryRequirement[];
  required_permits?: Array<{
    permit_type?: string;
    tr_ts?: string | null;
    tr_ts_full_name?: string | null;
    description?: string;
    legal_ref?: string;
    trigger?: string;
    source?: string;
    applicability?: string;
  }>;
  status?: string;
  hs_code?: string;
  description?: string;
  tr_ts?: string[];
  notes?: string[];
};

type Props = {
  nonTariff: NonTariffResult | null | undefined;
  title?: string;
  className?: string;
};

export const NonTariffBlock: React.FC<Props> = ({
  nonTariff,
  title = 'Нетарифные требования',
  className = '',
}) => {
  const block = normativeBlockFromNonTariff(nonTariff);
  if (!block) return null;
  return <NormativeRequirementsBlock block={block} title={title} className={className} />;
};

export default NonTariffBlock;
