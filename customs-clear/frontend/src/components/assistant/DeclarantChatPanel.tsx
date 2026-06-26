import React, { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  getAssistantCalculationContext,
  subscribeAssistantCalculationContext,
} from '../../store/calculatorAssistantBridge';
import { DeclarantChatThread } from './DeclarantChatThread';

type Props = {
  variant?: 'home' | 'full';
};

export const DeclarantChatPanel: React.FC<Props> = ({ variant = 'full' }) => {
  const [hasCtx, setHasCtx] = useState(() => !!getAssistantCalculationContext());

  useEffect(() => {
    return subscribeAssistantCalculationContext(() => {
      setHasCtx(!!getAssistantCalculationContext());
    });
  }, []);

  const isHome = variant === 'home';
  const headerExtra = hasCtx ? (
    <span className="rounded-full border border-emerald-200 bg-emerald-50 px-2 py-0.5 text-[10px] text-emerald-700">
      есть контекст расчёта
    </span>
  ) : (
    <span className="text-[10px] text-slate-600">
      после расчёта в{' '}
      <Link to="/calculator" className="text-blue-700 hover:underline">
        Платежах
      </Link>{' '}
      контекст подставится автоматически
    </span>
  );

  return (
    <div
      className={
        isHome
          ? 'rounded-2xl border border-slate-200 bg-white p-4 shadow-sm'
          : 'cc-card-soft space-y-3 p-4'
      }
    >
      <DeclarantChatThread
        variant={variant}
        headerTitle="Консультация"
        headerExtra={headerExtra}
        emptyStateHint="Спросите о рисках, документах или структуре платежей по вашему расчёту."
      />
      {isHome ? (
        <p className="text-[10px] text-slate-600">
          Полный режим ассистента — в меню{' '}
          <Link to="/assistant" className="text-blue-700 hover:underline">
            Ассистент
          </Link>
          .
        </p>
      ) : null}
    </div>
  );
};
