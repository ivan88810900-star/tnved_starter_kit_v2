import { render, screen } from '@testing-library/react';
import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import { RouteLoadBoundary } from './RouteLoadBoundary';

describe('RouteLoadBoundary', () => {
  it('announces that a route is loading while its bundle is pending', () => {
    const PendingRoute = React.lazy(
      () => new Promise<{ default: React.ComponentType }>(() => undefined),
    );

    render(
      <RouteLoadBoundary>
        <PendingRoute />
      </RouteLoadBoundary>,
    );

    expect(screen.getByRole('status', { name: 'Загрузка раздела' })).toBeInTheDocument();
    expect(screen.getByText('Загрузка раздела…')).toBeInTheDocument();
  });

  it('offers a safe reload instead of leaving a blank page after a route failure', () => {
    const consoleError = vi.spyOn(console, 'error').mockImplementation(() => undefined);
    const preventExpectedError = (event: ErrorEvent) => event.preventDefault();
    window.addEventListener('error', preventExpectedError);
    const BrokenRoute: React.FC = () => {
      throw new Error('chunk failed');
    };

    try {
      render(
        <RouteLoadBoundary>
          <BrokenRoute />
        </RouteLoadBoundary>,
      );

      expect(screen.getByRole('alert')).toHaveTextContent('Не удалось загрузить раздел');
      expect(screen.getByRole('button', { name: 'Обновить страницу' })).toBeInTheDocument();
    } finally {
      window.removeEventListener('error', preventExpectedError);
      consoleError.mockRestore();
    }
  });
});
