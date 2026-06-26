import React from 'react';
import { Info } from 'lucide-react';

type Props = {
  text: string;
  className?: string;
};

export const InfoTooltip: React.FC<Props> = ({ text, className }) => (
  <span
    className={`inline-flex shrink-0 cursor-help align-middle text-cargo-light hover:text-cargo-mid ${className ?? ''}`}
    title={text}
    aria-label={text}
  >
    <Info className="h-3.5 w-3.5" aria-hidden />
  </span>
);
