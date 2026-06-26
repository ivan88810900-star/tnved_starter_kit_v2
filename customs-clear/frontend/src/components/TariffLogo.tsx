import React from 'react';
import { NavLink } from 'react-router-dom';
import logoFullDark from '../assets/logo/logo-full-dark.svg';
import logoFullLight from '../assets/logo/logo-full-light.svg';
import logoIcon from '../assets/logo/logo-icon.svg';

type Props = {
  className?: string;
  iconOnly?: boolean;
  variant?: 'light' | 'dark';
  onNavigate?: () => void;
};

export const TariffLogo: React.FC<Props> = ({
  className,
  iconOnly = false,
  variant = 'light',
  onNavigate,
}) => {
  const isDark = variant === 'dark';
  const handleClick = () => {
    onNavigate?.();
  };

  if (iconOnly) {
    return (
      <NavLink to="/" className="inline-flex shrink-0 items-center" aria-label="Tariff" onClick={handleClick}>
        <img src={logoIcon} alt="" className={className ?? 'h-8 w-8'} aria-hidden />
        <span className="sr-only">Tariff</span>
      </NavLink>
    );
  }

  return (
    <NavLink
      to="/"
      className={`sidebar-logo block px-4 py-5 ${isDark ? 'border-b border-[var(--sidebar-border)]' : 'border-b border-cargo-border'}`}
      aria-label="Tariff — на главную"
      onClick={handleClick}
    >
      <img
        src={isDark ? logoFullDark : logoFullLight}
        alt="Tariff"
        className={className ?? 'h-7 w-auto max-w-[148px]'}
      />
      <p
        className={`mt-2 text-[11px] ${isDark ? 'text-[var(--sidebar-label)]' : 'text-cargo-light'}`}
      >
        Customs Intelligence
      </p>
    </NavLink>
  );
};
