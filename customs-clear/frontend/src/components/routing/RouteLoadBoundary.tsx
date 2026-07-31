import React from 'react';

type RouteErrorBoundaryState = {
  failed: boolean;
};

class RouteErrorBoundary extends React.Component<React.PropsWithChildren, RouteErrorBoundaryState> {
  state: RouteErrorBoundaryState = { failed: false };

  static getDerivedStateFromError(): RouteErrorBoundaryState {
    return { failed: true };
  }

  private reloadApplication = () => {
    if (typeof window !== 'undefined') {
      window.location.reload();
    }
  };

  render() {
    if (this.state.failed) {
      return (
        <section
          className="cc-card flex min-h-64 flex-col items-center justify-center gap-3 px-6 py-10 text-center"
          role="alert"
        >
          <div
            className="flex h-10 w-10 items-center justify-center rounded-full bg-red-50 text-xl text-red-700"
            aria-hidden="true"
          >
            !
          </div>
          <div>
            <h1 className="text-base font-semibold text-cargo-deep">Не удалось загрузить раздел</h1>
            <p className="mt-1 max-w-md text-sm text-cargo-mid">
              Возможно, приложение было обновлено или соединение прервалось. Обновите страницу и
              повторите попытку.
            </p>
          </div>
          <button type="button" className="cc-btn-primary" onClick={this.reloadApplication}>
            Обновить страницу
          </button>
        </section>
      );
    }

    return this.props.children;
  }
}

export function RouteLoading() {
  return (
    <section
      className="cc-card flex min-h-64 flex-col items-center justify-center gap-3 px-6 py-10 text-center"
      role="status"
      aria-live="polite"
      aria-label="Загрузка раздела"
    >
      <span
        className="h-8 w-8 animate-spin rounded-full border-2 border-cargo-border border-t-cargo-trust"
        aria-hidden="true"
      />
      <p className="text-sm font-medium text-cargo-mid">Загрузка раздела…</p>
    </section>
  );
}

export function RouteLoadBoundary({ children }: React.PropsWithChildren) {
  return (
    <RouteErrorBoundary>
      <React.Suspense fallback={<RouteLoading />}>{children}</React.Suspense>
    </RouteErrorBoundary>
  );
}
