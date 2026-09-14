import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { NonTariff } from './NonTariff';

describe('NonTariff caller-supplied trust labels', () => {
  it('does not imply that the service verified registries or legal exemptions', () => {
    render(<NonTariff />);

    expect(screen.getByText('По вашим данным, исключение найдено в реестре РЭС/ВЧУ')).toBeInTheDocument();
    expect(screen.getByText('Вы вручную сверили нотификацию в реестре')).toBeInTheDocument();
    expect(screen.getByText('Вы вручную сверили точную строку исключения')).toBeInTheDocument();
    expect(screen.queryByText('Исключение подтверждено в реестре РЭС/ВЧУ')).not.toBeInTheDocument();
    expect(screen.queryByText('Нотификация проверена в реестре')).not.toBeInTheDocument();
  });

  it('exposes the exact personal-use and transit facts required by the backend', () => {
    render(<NonTariff />);

    fireEvent.change(screen.getByLabelText('Точное исключение для криптографии'), {
      target: { value: 'personal_use_appendix_5' },
    });
    expect(screen.getByLabelText('Получатель — физическое лицо')).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText('Направление перемещения'), {
      target: { value: 'transit' },
    });
    expect(screen.getByLabelText('Маршрут транзита')).toBeInTheDocument();
  });
});
