import React from 'react';
import { NavLink } from 'react-router-dom';
import logoFullLight from '../assets/logo/logo-full-light.svg';
import logoIcon from '../assets/logo/logo-icon.svg';

type Props = {
  className?: string;
  iconOnly?: boolean;
  onNavigate?: () => void;
};

export const TariffLogo: React.FC<Props> = ({ className, iconOnly = false, onNavigate }) => {
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
      className="sidebar-logo block border-b border-cargo-border px-4 py-5"
      aria-label="Tariff — на главную"
      onClick={handleClick}
    >
      <img src={logoFullLight} alt="Tariff" className={className ?? 'h-8 w-auto max-w-[148px]'} />
      <p className="mt-2 text-[11px] text-cargo-light">Customs Intelligence</p>
    </NavLink>
  );
};
