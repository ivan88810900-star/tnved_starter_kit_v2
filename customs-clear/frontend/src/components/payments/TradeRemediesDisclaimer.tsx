import React from 'react';

const REMEDIES_URL = 'https://remedies.eaeunion.org/dimd/ru';

type Props = {
  className?: string;
};

/** Дисклеймер для trade remedies — данные могут быть неполными. */
export const TradeRemediesDisclaimer: React.FC<Props> = ({ className = '' }) => (
  <p className={`text-xs leading-snug text-amber-900 ${className}`.trim()}>
    ⚠️ Данные по мерам защиты рынка (антидемпинг, спецзащита) могут быть неполными.
    Проверяйте актуальный реестр:{' '}
    <a
      href={REMEDIES_URL}
      target="_blank"
      rel="noopener noreferrer"
      className="font-medium text-blue-700 underline hover:text-blue-900"
    >
      remedies.eaeunion.org
    </a>
  </p>
);
